# -*- coding: utf-8 -*-
"""
MTProto Proxy GUI
基于 mtprotoproxy 的图形化配置界面：配置代理、一键启动/停止、查看日志与分享链接。
核心协议逻辑见 core.py（与原始 mtprotoproxy.py 一致）。
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

import tkinter as tk
from tkinter import ttk, messagebox

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


class LogRedirector:
    """把 print()/traceback 输出同时转发到队列(供 GUI 显示)和原始控制台。"""

    def __init__(self, q, original):
        self._q = q
        self._orig = original

    def write(self, data):
        if data:
            self._q.put(data)
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


class MTProxyGUI:
    def __init__(self, q, root):
        self.q = q
        self.root = root
        self.config = dict(DEFAULT_CONFIG)
        self._load_config()

        self._stop_event = threading.Event()
        self._proxy_thread = None
        self._server_up = threading.Event()
        self._start_error = None

        self._build_ui()
        self._poll()

    # ---------- 配置持久化 ----------
    def _load_config(self):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.config.update(saved)
        except Exception:
            pass

    def _save_config(self):
        data = {
            "port": self.port_var.get().strip(),
            "listen": self.listen_var.get().strip(),
            "external_ip": self.ext_ip_var.get().strip(),
            "classic": self.classic_var.get(),
            "secure": self.secure_var.get(),
            "tls": self.tls_var.get(),
            "tls_domain": self.tls_domain_var.get().strip(),
            "mask": self.mask_var.get(),
            "mask_host": self.mask_host_var.get().strip(),
            "ad_tag": self.ad_tag_var.get().strip(),
            "fast": self.fast_var.get(),
            "ipv6": self.ipv6_var.get(),
            "users": self._get_users(),
        }
        try:
            with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        self.root.title("MTProto Proxy GUI")
        self.root.geometry("980x640")
        self.root.minsize(820, 520)

        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        paned = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=1)

        self._build_settings(left)
        self._build_log(right)

        bottom = ttk.Frame(main, padding=(0, 8, 0, 0))
        bottom.pack(fill=tk.X)
        self._build_links_panel(bottom)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_settings(self, parent):
        # 基本设置
        basic = ttk.LabelFrame(parent, text="基本设置", padding=8)
        basic.pack(fill=tk.X, pady=(0, 6))

        self.port_var = tk.StringVar(value=self.config["port"])
        self.listen_var = tk.StringVar(value=self.config["listen"])
        self.ext_ip_var = tk.StringVar(value=self.config["external_ip"])

        ttk.Label(basic, text="监听端口").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(basic, textvariable=self.port_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(basic, text="监听地址").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(basic, textvariable=self.listen_var, width=18).grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Label(basic, text="对外IP/域名").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Entry(basic, textvariable=self.ext_ip_var, width=18).grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(basic, text="(留空则自动探测，用于生成分享链接)",
                  foreground="#666").grid(row=2, column=2, sticky=tk.W, padx=4)

        # 工作模式
        mode = ttk.LabelFrame(parent, text="工作模式", padding=8)
        mode.pack(fill=tk.X, pady=(0, 6))
        self.classic_var = tk.BooleanVar(value=self.config["classic"])
        self.secure_var = tk.BooleanVar(value=self.config["secure"])
        self.tls_var = tk.BooleanVar(value=self.config["tls"])
        ttk.Checkbutton(mode, text="经典 classic（易被检测）", variable=self.classic_var).grid(row=0, column=0, sticky=tk.W)
        ttk.Checkbutton(mode, text="安全 secure（较难检测）", variable=self.secure_var).grid(row=0, column=1, sticky=tk.W)
        ttk.Checkbutton(mode, text="TLS 伪装（最难检测，推荐）", variable=self.tls_var).grid(row=0, column=2, sticky=tk.W)

        # TLS / 伪装
        tls = ttk.LabelFrame(parent, text="TLS 伪装", padding=8)
        tls.pack(fill=tk.X, pady=(0, 6))
        self.tls_domain_var = tk.StringVar(value=self.config["tls_domain"])
        self.mask_var = tk.BooleanVar(value=self.config["mask"])
        self.mask_host_var = tk.StringVar(value=self.config["mask_host"])
        ttk.Label(tls, text="TLS域名").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(tls, textvariable=self.tls_domain_var, width=24).grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Checkbutton(tls, text="伪装坏连接", variable=self.mask_var).grid(row=0, column=2, sticky=tk.W, padx=(8, 0))
        ttk.Label(tls, text="伪装主机").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(tls, textvariable=self.mask_host_var, width=24).grid(row=1, column=1, sticky=tk.W, pady=2)

        # 广告 / 性能
        adv = ttk.LabelFrame(parent, text="广告 / 性能", padding=8)
        adv.pack(fill=tk.X, pady=(0, 6))
        self.ad_tag_var = tk.StringVar(value=self.config["ad_tag"])
        self.fast_var = tk.BooleanVar(value=self.config["fast"])
        self.ipv6_var = tk.BooleanVar(value=self.config["ipv6"])
        ttk.Label(adv, text="广告标签 AD_TAG").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(adv, textvariable=self.ad_tag_var, width=24).grid(row=0, column=1, sticky=tk.W, pady=2)
        ttk.Label(adv, text="(从 @MTProxybot 获取，留空关闭)").grid(row=0, column=2, sticky=tk.W, padx=4)
        ttk.Checkbutton(adv, text="快速模式 FAST_MODE", variable=self.fast_var).grid(row=1, column=0, sticky=tk.W)
        ttk.Checkbutton(adv, text="优先 IPv6", variable=self.ipv6_var).grid(row=1, column=1, sticky=tk.W)

        # 用户管理
        users_frame = ttk.LabelFrame(parent, text="用户（密钥）", padding=8)
        users_frame.pack(fill=tk.BOTH, expand=True)

        self.users_tree = ttk.Treeview(users_frame, columns=("name", "secret"), show="headings", height=8)
        self.users_tree.heading("name", text="用户名")
        self.users_tree.heading("secret", text="Secret (32位十六进制)")
        self.users_tree.column("name", width=90)
        self.users_tree.column("secret", width=210)
        self.users_tree.pack(fill=tk.BOTH, expand=True)
        self.users_tree.bind("<Double-1>", lambda e: self._edit_selected_user())
        for name, secret in self.config["users"]:
            self.users_tree.insert("", tk.END, values=(name, secret))

        btns = ttk.Frame(users_frame)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btns, text="添加用户", command=self._add_user).pack(side=tk.LEFT)
        ttk.Button(btns, text="修改", command=self._edit_selected_user).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(btns, text="删除", command=self._delete_selected_user).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(btns, text="随机密钥", command=self._copy_random_secret).pack(side=tk.LEFT, padx=(4, 0))

    def _build_log(self, parent):
        frame = ttk.LabelFrame(parent, text="运行日志", padding=4)
        frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(frame, wrap="none", state=tk.NORMAL, font=("Consolas", 9))
        scroll = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        bar = ttk.Frame(parent, padding=(4, 4, 4, 0))
        bar.pack(fill=tk.X)
        self.status_var = tk.StringVar(value="未启动")
        ttk.Label(bar, textvariable=self.status_var, foreground="#0a0").pack(side=tk.LEFT)
        self.start_btn = ttk.Button(bar, text="启动", command=self._on_start)
        self.start_btn.pack(side=tk.RIGHT)
        self.stop_btn = ttk.Button(bar, text="停止", command=self._on_stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT, padx=(0, 4))

    def _build_links_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="代理分享链接（tg://）", padding=4)
        frame.pack(fill=tk.X)

        self.links_text = tk.Text(frame, height=5, wrap="none", state=tk.NORMAL, font=("Consolas", 9))
        lscroll = ttk.Scrollbar(frame, command=self.links_text.yview)
        self.links_text.configure(yscrollcommand=lscroll.set)
        lscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.links_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        bar = ttk.Frame(parent, padding=(0, 4, 0, 0))
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="刷新链接", command=self._refresh_links).pack(side=tk.LEFT)
        ttk.Button(bar, text="复制全部", command=self._copy_links).pack(side=tk.LEFT, padx=(4, 0))

    # ---------- 用户管理 ----------
    def _get_users(self):
        users = []
        seen = set()
        for iid in self.users_tree.get_children():
            values = self.users_tree.item(iid, "values")
            if not values or len(values) < 2:
                continue
            name, secret = values[0], values[1]
            if not name:
                continue
            if name in seen:
                raise ValueError("用户名重复: %s" % name)
            seen.add(name)
            users.append((name, secret))
        return users

    def _ask_user(self, title, initial=None):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        name_var = tk.StringVar(value=(initial or ("", gen_secret()))[0])
        secret_var = tk.StringVar(value=(initial or ("", gen_secret()))[1])

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="用户名").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(frm, textvariable=name_var, width=20).grid(row=0, column=1, pady=3)
        ttk.Label(frm, text="Secret").grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(frm, textvariable=secret_var, width=36).grid(row=1, column=1, pady=3)
        ttk.Button(frm, text="随机", command=lambda: secret_var.set(gen_secret())).grid(row=1, column=2, padx=4)

        result = {"ok": False}

        def ok():
            name = name_var.get().strip()
            secret = secret_var.get().strip()
            if not name:
                messagebox.showerror("错误", "用户名不能为空", parent=dlg)
                return
            if not re.fullmatch(r"[0-9a-fA-F]{32}", secret):
                messagebox.showerror("错误", "Secret 必须是 32 位十六进制字符", parent=dlg)
                return
            result["ok"] = True
            result["user"] = (name, secret)
            dlg.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=3, pady=(8, 0))
        ttk.Button(btns, text="确定", command=ok).pack(side=tk.LEFT)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=(6, 0))

        self.root.wait_window(dlg)
        return result["user"] if result["ok"] else None

    def _add_user(self):
        user = self._ask_user("添加用户")
        if user:
            self.users_tree.insert("", tk.END, values=user)

    def _edit_selected_user(self):
        sel = self.users_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要修改的用户")
            return
        iid = sel[0]
        current = self.users_tree.item(iid, "values")
        user = self._ask_user("修改用户", initial=(current[0], current[1]))
        if user:
            self.users_tree.item(iid, values=user)

    def _delete_selected_user(self):
        sel = self.users_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要删除的用户")
            return
        for iid in sel:
            self.users_tree.delete(iid)

    def _copy_random_secret(self):
        s = gen_secret()
        self.root.clipboard_clear()
        self.root.clipboard_append(s)
        messagebox.showinfo("随机密钥", "已生成并复制到剪贴板:\n" + s)

    # ---------- 启动 / 停止 ----------
    def _on_start(self):
        if self._proxy_thread and self._proxy_thread.is_alive():
            return
        try:
            config_path = self._write_runtime_config()
        except ValueError as e:
            messagebox.showerror("配置错误", str(e))
            return
        self._save_config()

        self._stop_event = threading.Event()
        self._server_up.clear()
        self._start_error = None
        self._proxy_thread = threading.Thread(target=self._run_proxy, args=(config_path,), daemon=True)
        self._proxy_thread.start()
        self._log(">>> 正在启动代理...\n")

    def _on_stop(self):
        if not (self._proxy_thread and self._proxy_thread.is_alive()):
            return
        self._stop_event.set()
        self._log(">>> 正在停止代理...\n")
        self.status_var.set("正在停止...")
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)

    def _write_runtime_config(self):
        users = self._get_users()
        if not users:
            raise ValueError("请至少添加一个用户")

        for name, secret in users:
            if not re.fullmatch(r"[0-9a-fA-F]{32}", secret):
                raise ValueError("用户 %s 的 Secret 不是 32 位十六进制" % name)

        port_str = self.port_var.get().strip()
        if not port_str.isdigit() or not (1 <= int(port_str) <= 65535):
            raise ValueError("端口必须是 1-65535 之间的数字")
        port = int(port_str)

        ad = self.ad_tag_var.get().strip()
        if ad and not re.fullmatch(r"[0-9a-fA-F]{32}", ad):
            raise ValueError("AD_TAG 应为 32 位十六进制或留空")

        modes = {
            "classic": self.classic_var.get(),
            "secure": self.secure_var.get(),
            "tls": self.tls_var.get(),
        }
        if not any(modes.values()):
            raise ValueError("至少启用一种工作模式")

        domain = self.tls_domain_var.get().strip() or DEFAULT_TLS_DOMAIN
        mask_host = self.mask_host_var.get().strip() or domain

        lines = []
        lines.append("PORT = %d" % port)
        lines.append("USERS = %r" % dict(users))
        lines.append("MODES = %r" % modes)
        lines.append("TLS_DOMAIN = %r" % domain)
        if ad:
            lines.append("AD_TAG = %r" % ad)
        lines.append("MASK = %s" % ("True" if self.mask_var.get() else "False"))
        lines.append("MASK_HOST = %r" % mask_host)
        lines.append("FAST_MODE = %s" % ("True" if self.fast_var.get() else "False"))
        lines.append("PREFER_IPV6 = %s" % ("True" if self.ipv6_var.get() else "False"))
        lines.append("LISTEN_ADDR_IPV4 = %r" % (self.listen_var.get().strip() or "0.0.0.0"))
        ext = self.ext_ip_var.get().strip()
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
            self._log(">>> 代理服务器已启动，正在监听端口 %s\n" % self.port_var.get().strip())

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
            self._log(">>> 代理已停止\n")
        except Exception:
            self._start_error = traceback.format_exc()
            self._log("[错误] " + traceback.format_exc() + "\n")
        finally:
            self._server_up.set()

    # ---------- 分享链接 ----------
    def _build_links(self):
        try:
            users = self._get_users()
            port = int(self.port_var.get().strip())
        except Exception:
            return []

        ip = self.ext_ip_var.get().strip()
        if not ip:
            ip = core.my_ip_info.get("ipv4") or core.my_ip_info.get("ipv6") or "YOUR_IP"
        domain = self.tls_domain_var.get().strip() or DEFAULT_TLS_DOMAIN

        links = []
        for name, secret in users:
            if self.classic_var.get():
                p = {"server": ip, "port": port, "secret": secret}
                links.append((name, "classic", "tg://proxy?" + urllib.parse.urlencode(p, safe=":")))
            if self.secure_var.get():
                p = {"server": ip, "port": port, "secret": "dd" + secret}
                links.append((name, "secure", "tg://proxy?" + urllib.parse.urlencode(p, safe=":")))
            if self.tls_var.get():
                tls_secret = "ee" + secret + domain.encode().hex()
                p = {"server": ip, "port": port, "secret": tls_secret}
                links.append((name, "tls", "tg://proxy?" + urllib.parse.urlencode(p, safe=":")))
        return links

    def _refresh_links(self):
        self.links_text.delete("1.0", tk.END)
        links = self._build_links()
        for name, mode, link in links:
            self.links_text.insert(tk.END, "[%s/%s] %s\n" % (name, mode, link))
        if not links:
            self.links_text.insert(tk.END, "(无可生成链接，请检查用户与模式配置)\n")

    def _copy_links(self):
        content = self.links_text.get("1.0", tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.status_var.set("链接已复制到剪贴板")
        else:
            self._refresh_links()

    # ---------- 日志 / 状态 ----------
    def _log(self, msg):
        self.q.put(msg)

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.log_text.insert(tk.END, msg)
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self._update_status()
        self.root.after(100, self._poll)

    def _update_status(self):
        thread_alive = self._proxy_thread is not None and self._proxy_thread.is_alive()
        if thread_alive:
            if self._server_up.is_set():
                self.status_var.set("运行中（端口 %s）" % self.port_var.get().strip())
                self.start_btn.config(state=tk.DISABLED)
                self.stop_btn.config(state=tk.NORMAL)
            else:
                self.status_var.set("正在启动...")
                self.start_btn.config(state=tk.DISABLED)
                self.stop_btn.config(state=tk.NORMAL)
        else:
            if self._start_error:
                self.status_var.set("启动失败（详见日志）")
                self._start_error = None
            elif self._server_up.is_set():
                self._server_up.clear()
                self.status_var.set("已停止")
            else:
                self.status_var.set("未启动")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def _on_close(self):
        if self._proxy_thread and self._proxy_thread.is_alive():
            self._stop_event.set()
            self._proxy_thread.join(timeout=5)
        try:
            self._save_config()
        except Exception:
            pass
        self.root.destroy()


def main():
    q = queue.Queue()
    sys.stdout = LogRedirector(q, sys.__stdout__)
    sys.stderr = LogRedirector(q, sys.__stderr__)

    root = tk.Tk()
    app = MTProxyGUI(q, root)
    root.mainloop()


if __name__ == "__main__":
    main()
