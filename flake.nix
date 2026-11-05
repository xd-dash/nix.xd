{
  description = "Architecture-neutral Nix-Alpine host orchestration";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.nix-alpine = {
    url = "github:dash-xd/nix-alpine/037290d6713cb5efc548982c42b26f77f467e58a";
    flake = false;
  };

  outputs = { self, nixpkgs, nix-alpine }:
    let
      hostSystems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" ];
      eachHostSystem = nixpkgs.lib.genAttrs hostSystems;
    in {
      packages = eachHostSystem (hostSystem:
        let
          linuxSystem =
            if hostSystem == "x86_64-linux"
            then "x86_64-linux"
            else "aarch64-linux";
          pkgs = import nixpkgs { system = hostSystem; };
          operator = pkgs.writeShellApplication {
            name = "nix-xd";
            runtimeInputs = [ pkgs.bash pkgs.coreutils pkgs.git pkgs.gnumake ];
            text = ''
              export NIX_XD_SOURCE=${self}
              export NIX_XD_HOST_SYSTEM=${hostSystem}
              export NIX_XD_LINUX_SYSTEM=${linuxSystem}
              export NIX_XD_NIX_ALPINE_REV=037290d6713cb5efc548982c42b26f77f467e58a
              exec ${pkgs.bash}/bin/bash ${./bin/nix-xd-entry} "$@"
            '';
          };
          context = if linuxSystem == "x86_64-linux" then nix-alpine else ./arm;
          installer = pkgs.writeShellApplication {
            name = "nix-xd-install";
            runtimeInputs = [ pkgs.bash pkgs.coreutils pkgs.gnused ];
            text = ''
              export NIX_XD_CONTEXT=${context}
              export NIX_XD_SYSTEM=${linuxSystem}
              ${builtins.readFile ./bin/nix-xd}
            '';
          };
        in {
          default = operator;
          inherit operator installer;
        });

      apps = eachHostSystem (hostSystem: {
        default = {
          type = "app";
          program = "${self.packages.${hostSystem}.operator}/bin/nix-xd";
        };
        install = {
          type = "app";
          program = "${self.packages.${hostSystem}.installer}/bin/nix-xd-install";
        };
      });

      checks = eachHostSystem (hostSystem: {
        operator = self.packages.${hostSystem}.operator;
      });
    };
}
