{
  description = "Rootless Podman host installation for nix-alpine";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.nix-alpine = {
    url = "github:dash-xd/nix-alpine/80a2821b7571edd09507f9b4349e2f1ed3daf900";
    flake = false;
  };
  outputs = { self, nixpkgs, nix-alpine }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      eachSystem = nixpkgs.lib.genAttrs systems;
    in {
      packages = eachSystem (system:
        let
          pkgs = import nixpkgs { inherit system; };
          context = if system == "x86_64-linux" then nix-alpine else ./arm;
          storeProbeRootfs = pkgs.runCommand "nix-xd-store-probe-rootfs" {
            nativeBuildInputs = [ pkgs.coreutils ];
          } ''
            mkdir -p "$out/bin" "$out/nix/store" "$out/dev" "$out/proc" "$out/sys" "$out/run" "$out/tmp" "$out/etc"
            ln -s "${pkgs.pkgsStatic.busybox}/bin/busybox" "$out/bin/sh"
            ln -s /proc/self/mounts "$out/etc/mtab"
          '';
          storeProbeOciArchive = pkgs.dockerTools.buildLayeredImage {
            name = "localhost/nix-xd-store-probe";
            tag = "shared-store";
            created = "1970-01-01T00:00:01Z";
            contents = [ storeProbeRootfs ];
            config = {
              Cmd = [ "/bin/sh" ];
            };
          };
          storeProbeDynamic = pkgs.hello;
          storeProbeNix = pkgs.nix;
          workload-control = pkgs.writeShellApplication {
            name = "nix-xd-workload-control";
            runtimeInputs = [ pkgs.python3 pkgs.nix ];
            text = ''
              exec python3 ${./lib/workloads.py} --executor ${./bin/nix-xd-guest-store-exec} "$@"
            '';
          };
          installer = pkgs.writeShellApplication {
            name = "nix-xd";
            runtimeInputs = [ pkgs.coreutils pkgs.gnused ];
            text = ''
              export NIX_XD_CONTEXT=${context}
              export NIX_XD_SYSTEM=${system}
              ${builtins.readFile ./bin/nix-xd}
            '';
          };
        in {
          default = installer;
          inherit installer workload-control storeProbeRootfs storeProbeOciArchive storeProbeDynamic storeProbeNix;
        });
      workloads = eachSystem (system: {
        starwisp-probe = {
          version = 1;
          name = "starwisp-probe";
          inherit system;
          outputs = {
            rootfs = "storeProbeRootfs";
            executable = "storeProbeDynamic";
            nix = "storeProbeNix";
            oci-archive = "storeProbeOciArchive";
          };
          rootfs = "rootfs";
          command = { output = "executable"; path = "bin/hello"; args = [ ]; };
          capabilities = [ "store-9p-ro" "user-systemd" "rootless-podman" ];
          qualification = { mode = "exit-success"; stdoutContains = "Hello, world!"; };
          runtimeMaxSec = 30;
          network = "none";
        };
      });
      apps = eachSystem (system: {
        workload-control = {
          type = "app";
          program = "${self.packages.${system}.workload-control}/bin/nix-xd-workload-control";
        };
        default = {
          type = "app";
          program = "${self.packages.${system}.installer}/bin/nix-xd";
        };
      });
      checks = eachSystem (system: {
        installer = self.packages.${system}.installer;
      });
    };
}
