#!/bin/bash
# Build mtprotoproxy-gui .deb manually (no dpkg-deb needed)
set -e
cd ~/mtpp
rm -rf deb-build deb-out
mkdir -p deb-build/data/opt/mtprotoproxy-gui
mkdir -p deb-build/data/usr/bin
mkdir -p deb-build/control

# data tree
tar xzf MTProtoProxyGUI-src.tar.gz -C /tmp
cp -r /tmp/mtprotoproxy-gui-src/core.py /tmp/mtprotoproxy-gui-src/gui.py \
      /tmp/mtprotoproxy-gui-src/pyaes /tmp/mtprotoproxy-gui-src/LICENSE \
      /tmp/mtprotoproxy-gui-src/README.md deb-build/data/opt/mtprotoproxy-gui/
rm -rf /tmp/mtprotoproxy-gui-src

cat > deb-build/data/usr/bin/mtprotoproxy-gui <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /opt/mtprotoproxy-gui/gui.py "$@"
EOF
chmod +x deb-build/data/usr/bin/mtprotoproxy-gui

# md5sums
cd deb-build/data
find opt usr -type f -exec md5sum {} \; | sed 's|  \./|  |; s|  opt/|  opt/|; s|  usr/|  usr/|' > ../control/md5sums
find opt usr -type f -exec md5sum {} \; | sed 's|  \.||' > ../control/md5sums
cd ..

# control file
cat > control/control <<'EOF'
Package: mtprotoproxy-gui
Version: 1.0.0-1
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-tk
Maintainer: CTF-duya112 <15735369400@qq.com>
Description: MTProto proxy with a graphical configuration GUI (tkinter)
 GUI to configure the MTProto proxy: port, users/secrets, working modes
 (classic/secure/TLS), TLS domain, ad tag and share links.
 Core protocol logic from alexbers/mtprotoproxy (MIT).
EOF

# archives
cd control
tar czf ../control.tar.gz control md5sums
cd ../data
tar czf ../data.tar.gz opt usr
cd ..

mkdir -p deb-out
printf '2.0\n' > debian-binary
ar rD deb-out/mtprotoproxy-gui_1.0.0-1_all.deb debian-binary control.tar.gz data.tar.gz
echo "=== RESULT ==="
ls -la deb-out/
echo "=== control in deb ==="
ar p deb-out/mtprotoproxy-gui_1.0.0-1_all.deb control.tar.gz | tar tz
