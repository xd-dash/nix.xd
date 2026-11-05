{
  description = "Rootless Podman host installation for nix-alpine";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.nix-alpine = {
    url = "github:dash-xd/nix-alpine/80a2821b7571edd09507f9b4349e2f1ed3daf900";
    flake = false;
  };
  outputs = { self, nixpkgs, nix-alpine }:
    let
      hostSystems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" ];
      eachHostSystem = nixpkgs.lib.genAttrs hostSystems;
    in {
      packages = eachHostSystem (hostSystem:
        let
          linuxSystem = if hostSystem == "x86_64-linux" then "x86_64-linux" else "aarch64-linux";
          pkgs = import nixpkgs { system = hostSystem; };
          context = if linuxSystem == "x86_64-linux" then nix-alpine else ./arm;
          installer = pkgs.writeShellApplication {
            name = "nix-xd";
            runtimeInputs = [ pkgs.coreutils pkgs.gnused ];
            text = ''
              export NIX_XD_CONTEXT=${context}
              export NIX_XD_SYSTEM=${linuxSystem}
              ${builtins.readFile ./bin/nix-xd}
            '';
          };
        in { default = installer; inherit installer; });
      apps = eachHostSystem (hostSystem: {
        default = {
          type = "app";
          program = "${self.packages.${hostSystem}.installer}/bin/nix-xd";
        };
      });
      checks = eachHostSystem (hostSystem: {
        installer = self.packages.${hostSystem}.installer;
      });
    };
}
