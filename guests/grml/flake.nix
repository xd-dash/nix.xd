{
  description = "Wisp Grml-derived ARM64 guest qualification tools";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      system = "aarch64-linux";
      pkgs = import nixpkgs { inherit system; };
      manifest = pkgs.writeText "wisp-grml-packages" ''
        systemd
        systemd-sysv
        dbus
        ca-certificates
        iproute2
        linux-image-arm64
        podman
        uidmap
        passt
        crun
        netavark
        aardvark-dns
      '';
      verify = pkgs.writeShellApplication {
        name = "wisp-grml-verify";
        runtimeInputs = [ pkgs.coreutils pkgs.gnugrep ];
        text = ''
          test -s ${manifest}
          for pkg in systemd linux-image-arm64 podman uidmap passt crun netavark aardvark-dns; do
            grep -qx "$pkg" ${manifest}
          done
          printf 'PASS: ARM64 Grml guest package intent validated (not a boot qualification)\\n'
        '';
      };
    in {
      packages.${system} = { inherit manifest verify; default = verify; };
      apps.${system}.qualify = {
        type = "app";
        program = "${verify}/bin/wisp-grml-verify";
      };
      checks.${system}.manifest = verify;
    };
}
