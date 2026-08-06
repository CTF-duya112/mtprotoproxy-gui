# MTProto Proxy GUI RPM spec
# Build: rpmbuild -bb mtprotoproxy-gui.spec

Name:           mtprotoproxy-gui
Version:        1.0.0
Release:        1%{?dist}
Summary:        MTProto proxy with a graphical configuration GUI (tkinter)
License:        MIT
URL:            https://github.com/CTF-duya112/mtprotoproxy-gui
Source0:        MTProtoProxyGUI-src.tar.gz
BuildArch:      noarch
Requires:       python3 >= 3.10
Requires:       python3-tkinter

%description
MTProto proxy with a GUI to configure the port, users/secrets, working modes
(classic/secure/TLS), TLS domain, ad tag and share links. The core protocol
logic comes from alexbers/mtprotoproxy (MIT).

%prep
mkdir -p %{_builddir}/src
cd %{_builddir}/src
tar xzf %{SOURCE0}

%install
cd %{_builddir}/src
rm -rf %{buildroot}
mkdir -p %{buildroot}/opt/mtprotoproxy-gui
cp -r mtprotoproxy-gui-src/core.py mtprotoproxy-gui-src/gui.py \
      mtprotoproxy-gui-src/pyaes mtprotoproxy-gui-src/LICENSE \
      mtprotoproxy-gui-src/README.md %{buildroot}/opt/mtprotoproxy-gui/
mkdir -p %{buildroot}/usr/bin
cat > %{buildroot}/usr/bin/mtprotoproxy-gui <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /opt/mtprotoproxy-gui/gui.py "$@"
EOF
chmod +x %{buildroot}/usr/bin/mtprotoproxy-gui

%files
/opt/mtprotoproxy-gui/
/usr/bin/mtprotoproxy-gui

%post
echo "MTProto Proxy GUI installed."
echo "Run 'mtprotoproxy-gui' or install python3-cryptography for better AES performance."
