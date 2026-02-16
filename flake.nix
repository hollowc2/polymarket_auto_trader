{
  description = "Python development environment with uv";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python313
            uv
            ruff
            ty
            prek
          ];
          shellHook = ''
            echo "Python $(python --version) | uv $(uv --version) | ruff $(ruff version)"

            # Auto-create venv if it doesn't exist
            if [ ! -d .venv ]; then
              echo "Creating virtual environment..."
              uv venv
            fi

            # Activate the venv
            source .venv/bin/activate

            # Install pre-commit hooks via prek
            prek install >/dev/null 2>&1 || true
          '';
        };
      });
}
