# MTProto Proxy GUI (Wayland-native, PySide6) - Nix package
{ lib, python3Packages, makeWrapper }:

python3Packages.buildPythonApplication {
  pname = "mtprotoproxy-gui";
  version = "1.0.0";

  src = lib.cleanSource ../..;

  dontUnpack = true;

  format = "other";

  nativeBuildInputs = [ makeWrapper ];

  propagatedBuildInputs = with python3Packages; [
    pyside6
    cryptography
  ];

  installPhase = ''
    runHook preInstall
    mkdir -p $out/lib/mtprotoproxy-gui $out/bin
    cp gui_wayland.py core.py $out/lib/mtprotoproxy-gui/
    cp -r pyaes $out/lib/mtprotoproxy-gui/
    mkdir -p $out/share/applications
    cat > $out/share/applications/mtprotoproxy-gui.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=MTProto Proxy GUI
Comment=MTProto proxy configuration GUI
Exec=mtprotoproxy-gui
Categories=Network;Utility;
DESKTOP
    makeWrapper ${python3Packages.python.interpreter} $out/bin/mtprotoproxy-gui \
      --set PYTHONPATH "$out/lib/mtprotoproxy-gui:${python3Packages.pyside6}/${python3Packages.python.sitePackages}:${python3Packages.cryptography}/${python3Packages.python.sitePackages}" \
      --add-flags "$out/lib/mtprotoproxy-gui/gui_wayland.py"
    runHook postInstall
  '';

  meta = with lib; {
    description = "MTProto proxy with a graphical configuration GUI (PySide6, native Wayland)";
    homepage = "https://github.com/CTF-duya112/mtprotoproxy-gui";
    license = licenses.mit;
    platforms = platforms.linux;
    maintainers = [ ];
  };
}
