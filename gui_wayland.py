# -*- coding: utf-8 -*-
"""
MTProto Proxy GUI (Wayland-native, PySide6/Qt6)
================================================
与 gui.py(tkinter) 功能一致，但使用 Qt6 原生 Wayland 后端，无需 XWayland。
在 Hyprland / niri 等 Wayland 合成器下可直接运行。

核心协议逻辑仍来自 core.py（与 alexbers/mtprotoproxy 一致）。
"""

import os
import re
import sys
import json
import queue
import secrets
import asyncio
import threading
import urllib.parse
import traceback

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QFormLayout, QLabel, QLineEdit, QSpinBox,
    QCheckBox, QPushButton, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QMessageBox, QDialog, QDialogButtonBox, QSplitter, QStatusBar,
)
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt, QObject, Signal

import core

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_JSON = os.path.join(APP_DIR, "gui_config.json")
RUNTIME_CONFIG = os.path.join(APP_DIR, "_runtime_config.py")

DEFAULT_TLS_DOMAIN = "www.google.com"

DEFAULT_CONFIG = {
    "port": 443,
    "listen": "0.0.0.0",
    "external_ip": "",
    "classic": False,
    "secure": False,
    "tls": True,
    "tls_domain": DEFAULT_TLS_DOMAIN,
    "mask": True,
    "mask_host": DEFAULT_TLS_DOMAIN,
    "ad_tag": "",
    "fast": True,
    "ipv6": False,
    "users": [("tg", "00000000000000000000000000000001")],
}


def gen_secret():
    return secrets.token_hex(16)


class Signals(QObject):
    log = Signal(str)
    status = Signal(str)
    started = Signal()
    stopped = Signal()


class LogRedirector:
    """把 print()/traceback 输出转发到 Qt 信号(线程安全)。"""

    def __init__(self, sig, original):
        self._sig = sig
        self._orig = original

    def write(self, data):
        if data:
            self._sig.log.emit(data)
        if self._orig is not None:
            try:
                self._orig.write(data)
                self._orig.flush()
            except Exception:
                pass

    def flush(self):
        if self._orig is not None:
            try:
                self._orig.flush()
            except Exception:
                pass

    def isatty(self):
        return False


class UserDialog(QDialog):
    def __init__(self, parent, name="", secret=""):
        super().__init__(parent)
        self.setWindowTitle("用户")
        self._result = None
        form = QFormLayout(self)
        self.name_edit = QLineEdit(name)
        self.secret_edit = QLineEdit(secret)
        self.secret_edit.setMinimumWidth(340)
        form.addRow("用户名", self.name_edit)
        form.addRow("Secret", self.secret_edit)
        rand_btn = QPushButton("随机")
        rand_btn.clicked.connect(lambda: self.secret_edit.setText(gen_secret()))
        form.addRow(QLabel(""), rand_btn)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _accept(self):
        name = self.name_edit.text().strip()
        secret = self.secret_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "错误", "用户名不能为空")
            return
        if not re.fullmatch(r"[0-9a-fA-F]{32}", secret):
            QMessageBox.warning(self, "错误", "Secret 必须是 32 位十六进制字符")
            return
        self._result = (name, secret)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, sig):
        super().__init__()
        self.sig = sig
        self.config = dict(DEFAULT_CONFIG)
        self._load_config()

        self._stop_event = threading.Event()
        self._proxy_thread = None
        self._server_up = threading.Event()
        self._start_error = None

        self.setWindowTitle("MTProto Proxy GUI")
        self.resize(1020, 680)

        sig.log.connect(self._append_log)
        sig.status.connect(self.statusBar().showMessage)
        sig.started.connect(self._on_server_started)
        sig.stopped.connect(self._on_server_stopped)

        self._build_ui()

    # ---------- 配置持久化 ----------
    def _load_config(self):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                self.config.update(json.load(f))
        except Exception:
            pass

    def _save_config(self):
        data = {
            "port": self.port_edit.value(),
            "listen": self.listen_edit.text().strip(),
            "external_ip": self.ext_ip_edit.text().strip(),
            "classic": self.classic_cb.isChecked(),
            "secure": self.secure_cb.isChecked(),
            "tls": self.tls_cb.isChecked(),
            "tls_domain": self.tls_domain_edit.text().strip(),
            "mask": self.mask_cb.isChecked(),
            "mask_host": self.mask_host_edit.text().strip(),
            "ad_tag": self.ad_tag_edit.text().strip(),
            "fast": self.fast_cb.isChecked(),
            "ipv6": self.ipv6_cb.isChecked(),
            "users": self._get_users(),
        }
        try:
            with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(left)

        # 基本设置
        basic = QGroupBox("基本设置")
        bf = QFormLayout(basic)
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setValue(int(self.config["port"]))
        self.listen_edit = QLineEdit(self.config["listen"])
        self.ext_ip_edit = QLineEdit(self.config["external_ip"])
        self.ext_ip_edit.setPlaceholderText("留空则自动探测公网IP")
        bf.addRow("监听端口", self.port_edit)
        bf.addRow("监听地址", self.listen_edit)
        bf.addRow("对外IP/域名", self.ext_ip_edit)
        left_layout.addWidget(basic)

        # 模式
        mode = QGroupBox("工作模式")
        ml = QVBoxLayout(mode)
        self.classic_cb = QCheckBox("经典 classic（易被检测）")
        self.secure_cb = QCheckBox("安全 secure（较难检测）")
        self.tls_cb = QCheckBox("TLS 伪装（最难检测，推荐）")
        self.classic_cb.setChecked(self.config["classic"])
        self.secure_cb.setChecked(self.config["secure"])
        self.tls_cb.setChecked(self.config["tls"])
        ml.addWidget(self.classic_cb)
        ml.addWidget(self.secure_cb)
        ml.addWidget(self.tls_cb)
        left_layout.addWidget(mode)

        # TLS / 伪装
        tls = QGroupBox("TLS 伪装")
        tf = QFormLayout(tls)
        self.tls_domain_edit = QLineEdit(self.config["tls_domain"])
        self.mask_cb = QCheckBox("伪装坏连接")
        self.mask_cb.setChecked(self.config["mask"])
        self.mask_host_edit = QLineEdit(self.config["mask_host"])
        tf.addRow("TLS域名", self.tls_domain_edit)
        tf.addRow(self.mask_cb, self.mask_host_edit)
        left_layout.addWidget(tls)

        # 广告 / 性能
        adv = QGroupBox("广告 / 性能")
        af = QFormLayout(adv)
        self.ad_tag_edit = QLineEdit(self.config["ad_tag"])
        self.ad_tag_edit.setPlaceholderText("从 @MTProxybot 获取，留空关闭")
        self.fast_cb = QCheckBox("快速模式 FAST_MODE")
        self.fast_cb.setChecked(self.config["fast"])
        self.ipv6_cb = QCheckBox("优先 IPv6")
        self.ipv6_cb.setChecked(self.config["ipv6"])
        af.addRow("广告标签 AD_TAG", self.ad_tag_edit)
        af.addRow(self.fast_cb, self.ipv6_cb)
        left_layout.addWidget(adv)

        # 用户管理
        users = QGroupBox("用户（密钥）")
        ul = QVBoxLayout(users)
        self.users_tree = QTreeWidget()
        self.users_tree.setHeaderLabels(["用户名", "Secret (32位十六进制)"])
        self.users_tree.setColumnWidth(0, 110)
        for name, secret in self.config["users"]:
            QTreeWidgetItem(self.users_tree, [name, secret])
        ul.addWidget(self.users_tree)
        btns = QHBoxLayout()
        add_btn = QPushButton("添加用户")
        edit_btn = QPushButton("修改")
        del_btn = QPushButton("删除")
        rand_btn = QPushButton("随机密钥")
        add_btn.clicked.connect(self._add_user)
        edit_btn.clicked.connect(self._edit_selected_user)
        del_btn.clicked.connect(self._delete_selected_user)
        rand_btn.clicked.connect(self._copy_random_secret)
        for b in (add_btn, edit_btn, del_btn, rand_btn):
            btns.addWidget(b)
        ul.addLayout(btns)
        left_layout.addWidget(users, 1)

        # 右侧日志
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(right)
        log_group = QGroupBox("运行日志")
        lg = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(self.log_text.font().family())
        lg.addWidget(self.log_text)
        rl.addWidget(log_group, 1)

        links_group = QGroupBox("代理分享链接（tg://）")
        ll = QVBoxLayout(links_group)
        self.links_text = QTextEdit()
        self.links_text.setReadOnly(True)
        ll.addWidget(self.links_text)
        link_btns = QHBoxLayout()
        refresh_btn = QPushButton("刷新链接")
        copy_btn = QPushButton("复制全部")
        refresh_btn.clicked.connect(self._refresh_links)
        copy_btn.clicked.connect(self._copy_links)
        link_btns.addWidget(refresh_btn)
        link_btns.addWidget(copy_btn)
        ll.addLayout(link_btns)
        rl.addWidget(links_group)

        splitter.setSizes([480, 540])

        # 底部控制
        control = QHBoxLayout()
        self.start_btn = QPushButton("启动")
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        control.addWidget(self.start_btn)
        control.addWidget(self.stop_btn)
        control.addStretch(1)
        root.addLayout(control)

        self.statusBar().showMessage("未启动")

    # ---------- 用户管理 ----------
    def _get_users(self):
        users = []
        seen = set()
        for i in range(self.users_tree.topLevelItemCount()):
            item = self.users_tree.topLevelItem(i)
            name = item.text(0).strip()
            secret = item.text(1).strip()
            if not name:
                continue
            if name in seen:
                raise ValueError("用户名重复: %s" % name)
            seen.add(name)
            users.append((name, secret))
        return users

    def _add_user(self):
        dlg = UserDialog(self)
        if dlg.exec():
            name, secret = dlg._result
            QTreeWidgetItem(self.users_tree, [name, secret])

    def _edit_selected_user(self):
        items = self.users_tree.selectedItems()
        if not items:
            QMessageBox.information(self, "提示", "请先选择要修改的用户")
            return
        item = items[0]
        dlg = UserDialog(self, item.text(0), item.text(1))
        if dlg.exec():
            name, secret = dlg._result
            item.setText(0, name)
            item.setText(1, secret)

    def _delete_selected_user(self):
        for item in self.users_tree.selectedItems():
            idx = self.users_tree.indexOfTopLevelItem(item)
            self.users_tree.takeTopLevelItem(idx)

    def _copy_random_secret(self):
        s = gen_secret()
        QApplication.clipboard().setText(s)
        QMessageBox.information(self, "随机密钥", "已生成并复制到剪贴板:\n" + s)

    # ---------- 启动 / 停止 ----------
    def _on_start(self):
        if self._proxy_thread and self._proxy_thread.is_alive():
            return
        try:
            config_path = self._write_runtime_config()
        except ValueError as e:
            QMessageBox.critical(self, "配置错误", str(e))
            return
        self._save_config()

        self._stop_event = threading.Event()
        self._server_up.clear()
        self._start_error = None
        self._proxy_thread = threading.Thread(target=self._run_proxy, args=(config_path,), daemon=True)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar().showMessage("正在启动...")
        self._proxy_thread.start()
        self.sig.log.emit(">>> 正在启动代理...\n")

    def _on_stop(self):
        if not (self._proxy_thread and self._proxy_thread.is_alive()):
            return
        self._stop_event.set()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("正在停止...")
        self.sig.log.emit(">>> 正在停止代理...\n")

    def _on_server_started(self):
        self.statusBar().showMessage("运行中（端口 %d）" % self.port_edit.value())
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _on_server_stopped(self):
        if self._start_error:
            self.statusBar().showMessage("启动失败（详见日志）")
            self._start_error = None
        else:
            self.statusBar().showMessage("已停止")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _write_runtime_config(self):
        users = self._get_users()
        if not users:
            raise ValueError("请至少添加一个用户")
        for name, secret in users:
            if not re.fullmatch(r"[0-9a-fA-F]{32}", secret):
                raise ValueError("用户 %s 的 Secret 不是 32 位十六进制" % name)
        port = self.port_edit.value()
        ad = self.ad_tag_edit.text().strip()
        if ad and not re.fullmatch(r"[0-9a-fA-F]{32}", ad):
            raise ValueError("AD_TAG 应为 32 位十六进制或留空")
        modes = {
            "classic": self.classic_cb.isChecked(),
            "secure": self.secure_cb.isChecked(),
            "tls": self.tls_cb.isChecked(),
        }
        if not any(modes.values()):
            raise ValueError("至少启用一种工作模式")
        domain = self.tls_domain_edit.text().strip() or DEFAULT_TLS_DOMAIN
        mask_host = self.mask_host_edit.text().strip() or domain

        lines = []
        lines.append("PORT = %d" % port)
        lines.append("USERS = %r" % dict(users))
        lines.append("MODES = %r" % modes)
        lines.append("TLS_DOMAIN = %r" % domain)
        if ad:
            lines.append("AD_TAG = %r" % ad)
        lines.append("MASK = %s" % ("True" if self.mask_cb.isChecked() else "False"))
        lines.append("MASK_HOST = %r" % mask_host)
        lines.append("FAST_MODE = %s" % ("True" if self.fast_cb.isChecked() else "False"))
        lines.append("PREFER_IPV6 = %s" % ("True" if self.ipv6_cb.isChecked() else "False"))
        lines.append("LISTEN_ADDR_IPV4 = %r" % (self.listen_edit.text().strip() or "0.0.0.0"))
        ext = self.ext_ip_edit.text().strip()
        if ext:
            lines.append("MY_DOMAIN = %r" % ext)

        with open(RUNTIME_CONFIG, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return RUNTIME_CONFIG

    def _run_proxy(self, config_path):
        try:
            sys.argv = [sys.argv[0], config_path]

            core.init_config()
            core.ensure_users_in_user_stats()
            core.apply_upstream_proxy_settings()
            core.init_ip_info()
            core.print_tg_info()

            core.setup_asyncio()
            core.setup_files_limit()
            if threading.current_thread() is threading.main_thread():
                core.setup_signals()
            core.try_setup_uvloop()
            core.init_proxy_start_time()

            if self._stop_event.is_set():
                return

            if sys.platform == "win32":
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.set_exception_handler(core.loop_exception_handler)

            tasks = core.create_utilitary_tasks(loop)
            for t in tasks:
                asyncio.ensure_future(t)

            servers = core.create_servers(loop)
            self._server_up.set()
            self.sig.started.emit()
            self.sig.log.emit(">>> 代理服务器已启动，正在监听端口 %d\n" % self.port_edit.value())

            while not self._stop_event.is_set():
                loop.run_until_complete(asyncio.sleep(0.1))

            if hasattr(asyncio, "all_tasks"):
                all_tasks = asyncio.all_tasks(loop)
            else:
                all_tasks = asyncio.Task.all_tasks(loop)
            for t in all_tasks:
                t.cancel()
            for s in servers:
                s.close()
                loop.run_until_complete(s.wait_closed())
            loop.close()
            self.sig.log.emit(">>> 代理已停止\n")
        except Exception:
            self._start_error = traceback.format_exc()
            self.sig.log.emit("[错误] " + traceback.format_exc() + "\n")
        finally:
            self._server_up.set()
            self.sig.stopped.emit()

    # ---------- 分享链接 ----------
    def _build_links(self):
        try:
            users = self._get_users()
            port = self.port_edit.value()
        except Exception:
            return []
        ip = self.ext_ip_edit.text().strip()
        if not ip:
            ip = core.my_ip_info.get("ipv4") or core.my_ip_info.get("ipv6") or "YOUR_IP"
        domain = self.tls_domain_edit.text().strip() or DEFAULT_TLS_DOMAIN

        links = []
        for name, secret in users:
            if self.classic_cb.isChecked():
                p = {"server": ip, "port": port, "secret": secret}
                links.append((name, "classic", "tg://proxy?" + urllib.parse.urlencode(p, safe=":")))
            if self.secure_cb.isChecked():
                p = {"server": ip, "port": port, "secret": "dd" + secret}
                links.append((name, "secure", "tg://proxy?" + urllib.parse.urlencode(p, safe=":")))
            if self.tls_cb.isChecked():
                tls_secret = "ee" + secret + domain.encode().hex()
                p = {"server": ip, "port": port, "secret": tls_secret}
                links.append((name, "tls", "tg://proxy?" + urllib.parse.urlencode(p, safe=":")))
        return links

    def _refresh_links(self):
        self.links_text.clear()
        links = self._build_links()
        for name, mode, link in links:
            self.links_text.append("[%s/%s] %s" % (name, mode, link))
        if not links:
            self.links_text.append("(无可生成链接，请检查用户与模式配置)")

    def _copy_links(self):
        text = self.links_text.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("链接已复制到剪贴板", 3000)
        else:
            self._refresh_links()

    def _append_log(self, msg):
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
        self.log_text.insertPlainText(msg)

    def closeEvent(self, event):
        if self._proxy_thread and self._proxy_thread.is_alive():
            self._stop_event.set()
            self._proxy_thread.join(timeout=5)
        try:
            self._save_config()
        except Exception:
            pass
        super().closeEvent(event)


def main():
    sig = Signals()
    sys.stdout = LogRedirector(sig, sys.__stdout__)
    sys.stderr = LogRedirector(sig, sys.__stderr__)

    app = QApplication(sys.argv)
    win = MainWindow(sig)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
