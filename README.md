# MTProto Proxy GUI

MTProto 代理的图形化配置工具：开箱即用的 tkinter 界面，一键配置、启动/停止代理，生成 `tg://` 分享链接。

- 核心协议逻辑来自 [alexbers/mtprotoproxy](https://github.com/alexbers/mtprotoproxy)（MIT），见 `core.py`，逻辑保持一致。
- GUI 使用 Python 标准库 tkinter，无需额外依赖即可运行（推荐安装 `cryptography` 以加速 AES）。
- Wayland 原生版（PySide6/Qt6，含 Nix / AUR 打包）在独立仓库 [mtprotoproxy-gui-wayland](https://github.com/CTF-duya112/mtprotoproxy-gui-wayland)。

## 功能

- 端口 / 监听地址 / 对外 IP（留空自动探测公网 IP）
- 工作模式：classic / secure / TLS 伪装
- TLS 域名与伪装主机设置
- 广告标签 AD_TAG（来自 @MTProxybot）
- 多用户密钥管理（增删改、随机生成 32 位 hex）
- 启动/停止、实时日志、一键复制分享链接
- 配置自动保存到 `gui_config.json`

## 运行

```bash
# 需要 Python 3.10+
pip install cryptography   # 可选，显著提升性能

python3 gui.py
```

Windows 可直接使用打包好的 `dist/MTProtoProxyGUI.exe`（无需 Python）。

## 已发布二进制

见 `dist/` 目录（或 GitHub Release）：

- `MTProtoProxyGUI.exe` — Windows（PyInstaller 单文件，tkinter 界面）
- `mtprotoproxy-gui-1.0.0-1.sga8.noarch.rpm` — RHEL/CentOS/Sugon 系（`rpm -ivh`）
- `mtprotoproxy-gui_1.0.0-1_all.deb` — Debian/Ubuntu（`apt install ./xxx.deb`）

安装后命令行执行 `mtprotoproxy-gui` 即可（需 `python3` 与 tkinter）。

## 打包

见 `packaging/` 目录：

- `packaging/rpm/mtprotoproxy-gui.spec` — rpm 打包脚本（`rpmbuild -bb`）
- `packaging/deb/build_deb.sh` — 手工构造 .deb 的脚本（无需 dpkg-deb）

Wayland 版（PySide6）及其 Nix / AUR 打包见 [mtprotoproxy-gui-wayland](https://github.com/CTF-duya112/mtprotoproxy-gui-wayland)。

## License

MIT。核心代码版权归原项目作者 Alexander Bersenev 所有。
