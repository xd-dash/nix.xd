{
  description = "Nix-Alpine protocol-v1 synthetic qualification fixture";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "aarch64-linux" "x86_64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems f;
    in {
      apps = forAll (system:
        let
          pkgs = import nixpkgs { inherit system; };
          app = pkgs.writeShellScriptBin "nix-xd-protocol-fixture" ''
            exec ${pkgs.python3}/bin/python3 ${./runner.py} "$@"
          '';
        in {
          qualify-plan = {
            type = "app";
            program = "${app}/bin/nix-xd-protocol-fixture";
          };
        });
    };
}
