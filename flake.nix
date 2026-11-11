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
          nestedAlpine = import ./guest/nix-alpine/package.nix { inherit pkgs system; };
          storeProbeDynamic = pkgs.hello;
          storeProbeNix = pkgs.nix;
          runtimePrimitives = import ./runtime { inherit pkgs; };
          runtimePython = pkgs.python3.withPackages (_: [ runtimePrimitives ]);
          projectLauncher = pkgs.writeShellApplication {
            name = "nix-xd-project-launch";
            runtimeInputs = [ runtimePython pkgs.nix ];
            text = ''
              exec python3 -m nix_alpine_runtime.launch "$@"
            '';
          };
          storePocView = pkgs.writeShellApplication {
            name = "nix-xd-store-poc-view";
            runtimeInputs = [ runtimePython pkgs.nix ];
            text = ''
              exec python3 -m nix_alpine_runtime.store_poc "$@"
            '';
          };
          storePocTools = pkgs.writeTextDir "tools.json" (builtins.toJSON {
            bash = "${pkgs.bash}";
            coreutils = "${pkgs.coreutils}";
            view = "${storePocView}";
          });
          chrootStorePoc = pkgs.writeShellApplication {
            name = "nix-xd-chroot-store-poc";
            runtimeInputs = [ runtimePython pkgs.nix pkgs.util-linux ];
            text = ''
              exec python3 -m nix_alpine_runtime.store_poc qualify "$@"
            '';
          };
          chrootStoreDiagnose = pkgs.writeShellApplication {
            name = "nix-xd-chroot-store-diagnose";
            runtimeInputs = [ runtimePython pkgs.util-linux ];
            text = ''
              exec python3 -m nix_alpine_runtime.store_poc diagnose "$@"
            '';
          };
          applicationRedis = pkgs.redis;
          composition-plan = pkgs.writeShellApplication {
            name = "nix-xd-composition-plan";
            runtimeInputs = [ pkgs.python3 ];
            text = ''
              exec python3 ${./lib/compositions.py} --input ${pkgs.writeText "shared-store-matrix.json"
                (builtins.toJSON (import ./compositions/shared-store-matrix.nix { inherit system; }))} "$@"
            '';
          };
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
          nixAlpineRootfs = nestedAlpine.rootfs;
          nixAlpineCheck = nestedAlpine.check;
          nixAlpineRuntime = nestedAlpine.runtime;
          nixAlpineRegistration = nestedAlpine.registration;
          wispGoTools = pkgs.buildEnv {
            name = "nix-xd-wisp-go-tools";
            paths = [ pkgs.go_1_26 pkgs.gcc pkgs.git pkgs.bash pkgs.cacert ];
          };
          inherit chrootStoreDiagnose storePocTools storePocView chrootStorePoc runtimePrimitives runtimePython projectLauncher applicationRedis installer workload-control composition-plan storeProbeRootfs storeProbeOciArchive storeProbeDynamic storeProbeNix;
        });
      fatlinePlans = eachSystem (system: {
        host-link = import ./compositions/fatline-coreos.nix { inherit system; };
        vm1 = import ./compositions/fatline-coreos.nix { inherit system; profile = "vm1"; };
        vm2 = import ./compositions/fatline-coreos.nix { inherit system; profile = "vm2"; };
      });
      compositions = eachSystem (system: {
        shared-store-matrix = import ./compositions/shared-store-matrix.nix { inherit system; };
      });
      workloads = eachSystem (system: {
        shared-host-a = self.workloads.${system}.nix-alpine-env // { name = "shared-host-a"; storeDomain = "common"; placement = "host"; capabilities = [ "store-bind-ro" "user-systemd" "rootless-podman" ]; };
        shared-host-b = self.workloads.${system}.nix-alpine-env // { name = "shared-host-b"; storeDomain = "common"; placement = "host"; capabilities = [ "store-bind-ro" "user-systemd" "rootless-podman" ]; };
        shared-vm1-a = self.workloads.${system}.nix-alpine-env // { name = "shared-vm1-a"; storeDomain = "common"; placement = "guest"; };
        shared-vm1-b = self.workloads.${system}.nix-alpine-env // { name = "shared-vm1-b"; storeDomain = "common"; placement = "guest"; };
        shared-vm2-a = self.workloads.${system}.nix-alpine-env // { name = "shared-vm2-a"; storeDomain = "common"; placement = "guest"; };
        shared-vm2-b = self.workloads.${system}.nix-alpine-env // { name = "shared-vm2-b"; storeDomain = "common"; placement = "guest"; };
        nix-alpine-env = {
          version = 1;
          name = "nix-alpine-env";
          inherit system;
          outputs = {
            rootfs = "nixAlpineRootfs";
            executable = "nixAlpineRuntime";
            nix = "storeProbeNix";
            registration = "nixAlpineRegistration";
          };
          rootfs = "rootfs";
          rootfsFormat = "alpine-archive";
          command = { output = "executable"; path = "bin/nix-alpine-runtime"; args = [ ]; };
          capabilities = [ "store-9p-ro" "user-systemd" "rootless-podman" ];
          qualification = {
            mode = "running";
            stdoutContains = "NIX_ALPINE_READY=passed";
            command = { output = "executable"; path = "bin/nix-alpine-ready"; args = [ ]; };
            timeoutSec = 120;
          };
          runtimeMaxSec = 0;
          network = "none";
        };
        nix-alpine = {
          version = 1;
          name = "nix-alpine";
          inherit system;
          outputs = {
            rootfs = "nixAlpineRootfs";
            executable = "nixAlpineCheck";
            nix = "storeProbeNix";
            registration = "nixAlpineRegistration";
          };
          rootfs = "rootfs";
          rootfsFormat = "alpine-archive";
          command = { output = "executable"; path = "bin/nix-alpine-qualify"; args = [ ]; };
          capabilities = [ "store-9p-ro" "user-systemd" "rootless-podman" ];
          qualification = { mode = "exit-success"; stdoutContains = "NESTED_NIX_ALPINE_RESULT=passed"; };
          runtimeMaxSec = 120;
          network = "none";
        };
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
        chroot-store-diagnose = {
          type = "app";
          program = "${self.packages.${system}.chrootStoreDiagnose}/bin/nix-xd-chroot-store-diagnose";
        };
        chroot-store-poc = {
          type = "app";
          program = "${self.packages.${system}.chrootStorePoc}/bin/nix-xd-chroot-store-poc";
        };
        project-launch = {
          type = "app";
          program = "${self.packages.${system}.projectLauncher}/bin/nix-xd-project-launch";
        };
        composition-plan = {
          type = "app";
          program = "${self.packages.${system}.composition-plan}/bin/nix-xd-composition-plan";
        };
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
