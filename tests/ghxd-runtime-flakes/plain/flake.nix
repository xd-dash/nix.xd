{
  description = "Secret-free plain local GHXD runtime qualification flake";
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
          runner = pkgs.writeShellScriptBin "ghxd-plain" ''
            set -euo pipefail
            exec /workspaces/.smoke-ghxd-state/bin/smoke ghxd-secrets probe
          '';
        in { default = runner; });
      apps = each (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/ghxd-plain";
        };
      });
    };
}
