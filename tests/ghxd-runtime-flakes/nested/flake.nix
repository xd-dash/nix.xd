{
  description = "Secret-free nested local GHXD runtime qualification flake";
  inputs.toolbox.url = "path:/workspaces/nix-alpine/nix-alpine/toolbox";
  inputs.nixpkgs.follows = "toolbox/nixpkgs";
  outputs = { self, toolbox, nixpkgs }:
    let
      systems = [ "aarch64-linux" "x86_64-linux" ];
      each = f: nixpkgs.lib.genAttrs systems (system: f system);
    in {
      packages = each (system:
        let
          pkgs = import nixpkgs { inherit system; };
          runner = pkgs.writeShellScriptBin "ghxd-nested" ''
            set -euo pipefail
            depth="${NIX_XD_NESTING_DEPTH:-0}"
[[ "$depth" =~ ^[0-4]$ ]] || { echo 'GHXD_NESTING=FAIL reason=depth-bound' >&2; exit 2; }
export NIX_XD_NESTING_DEPTH="$((depth+1))"
exec nix --offline run --no-write-lock-file /workspaces/tests/ghxd-runtime-flakes/plain#default
          '';
        in { default = runner; });
      apps = each (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/ghxd-nested";
        };
      });
    };
}
