{ pkgs, system }:
let
  platform = {
    aarch64-linux = {
      arch = "aarch64";
      sha256 = "5552106ac866be0c46fdff7a2991a1ed85c0464301a1ac87454c41739d5b6431";
    };
    x86_64-linux = {
      arch = "x86_64";
      sha256 = "ce8f782f1628d046fb6360eff880b898e5205ed91106d9d14ff4fcb97431bbde";
    };
  }.${system};
  alpine = pkgs.fetchurl {
    url = "https://dl-cdn.alpinelinux.org/alpine/v3.23/releases/${platform.arch}/alpine-minirootfs-3.23.0-${platform.arch}.tar.gz";
    inherit (platform) sha256;
  };
  registration = pkgs.closureInfo { rootPaths = [ pkgs.nix pkgs.hello ]; };
  check = pkgs.writeScriptBin "nix-alpine-qualify" ("#!/bin/sh\n" +
    builtins.replaceStrings [ "@registration@" "@hello@" "@system@" ]
      [ "${registration}" "${pkgs.hello}" system ]
      (builtins.readFile ./qualify.sh));
  runtime = pkgs.symlinkJoin {
    name = "nix-alpine-runtime";
    paths = [
      (pkgs.writeScriptBin "nix-alpine-runtime" ("#!/bin/sh\n" +
        builtins.replaceStrings [ "@check@" ] [ "${check}" ] (builtins.readFile ./runtime.sh)))
      (pkgs.writeScriptBin "nix-alpine-ready" ("#!/bin/sh\n" +
        builtins.replaceStrings [ "@hello@" ] [ "${pkgs.hello}" ] (builtins.readFile ./ready.sh)))
    ];
  };
  rootfs = pkgs.runCommand "nix-xd-guest-nix-alpine-${platform.arch}.tar.gz" {
    nativeBuildInputs = [ pkgs.gnutar pkgs.gzip pkgs.coreutils ];
  } ''
    mkdir rootfs
    tar --extract --gzip --file ${alpine} --directory rootfs --no-same-owner --no-same-permissions
    mkdir -p rootfs/nix/store rootfs/nix/var rootfs/home/nixuser rootfs/usr/local/bin rootfs/etc/nix
    test -z "$(ls -A rootfs/nix/store)"
    printf 'nixuser:x:1000:1000:Nix runtime:/home/nixuser:/bin/sh\n' >> rootfs/etc/passwd
    printf 'nixuser:x:1000:\n' >> rootfs/etc/group
    cp ${./entrypoint.sh} rootfs/usr/local/bin/nix-alpine-init
    chmod +x rootfs/usr/local/bin/nix-alpine-init
    for tool in nix nix-store nix-instantiate; do
      ln -s ${pkgs.nix}/bin/$tool rootfs/usr/local/bin/$tool
    done
    ln -s ${pkgs.hello}/bin/hello rootfs/usr/local/bin/hello
    cat > rootfs/etc/nix/nix.conf <<'CONFIG'
    experimental-features = nix-command flakes
    build-users-group =
    substituters =
    flake-registry =
    sandbox = false
    CONFIG
    tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner -C rootfs -cf - . | gzip -n > "$out"
  '';
in { inherit rootfs check registration runtime; }
