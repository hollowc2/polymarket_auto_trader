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
            python313  # Change to python311, python313 as needed
            uv         # Fast Python package manager
          ];
      shellHook = ''
            echo "Python $(python --version) | uv $(uv --version)"

            # Auto-create venv if it doesn't exist
            if [ ! -d .venv ]; then
              echo "Creating virtual environment..."
              uv venv
            fi

            # Activate the venv
            source .venv/bin/activate

            # Create pyrightconfig.json for LSP support (if not exists)
            if [ ! -f pyrightconfig.json ]; then
              echo '{"venvPath": ".", "venv": ".venv"}' > pyrightconfig.json
              echo "Created pyrightconfig.json for LSP support"
            fi
          '';
        };
      });
}
