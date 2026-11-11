{ pkgs }:
pkgs.python3Packages.buildPythonPackage {
  pname = "nix-alpine-runtime";
  version = "0.1.0";
  pyproject = true;
  src = ../lib/nix_alpine_runtime;
  build-system = [ pkgs.python3Packages.setuptools ];
  pythonImportsCheck = [ "nix_alpine_runtime" "nix_alpine_runtime.launch" ];
}
