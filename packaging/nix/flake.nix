{
  description = "MTProto proxy with a graphical configuration GUI (PySide6, native Wayland)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f:
        builtins.foldl' (acc: s: acc // { ${s} = f s; }) { } systems;
    in
    {
      packages = forAllSystems (system:
        let pkgs = nixpkgs.legacyPackages.${system};
        in {
          default = pkgs.callPackage ./default.nix { };
        });

      # nix run github:CTF-duya112/mtprotoproxy-gui
      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/mtprotoproxy-gui";
        };
      });
    };
}
