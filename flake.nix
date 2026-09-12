{
  description = "conversations dev environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          pkgs.nodejs_22        # frontend; compose.yml also uses node:22
          pkgs.yarn-berry       # yarn 4.14 — src/frontend/yarn.lock is a Yarn 4 lockfile
          pkgs.python314        # backend; pyproject.toml requires-python ~=3.14.6
          pkgs.uv               # backend package manager — src/backend/uv.lock
          pkgs.postgresql_17    # psql client for the postgres:17.5 compose service
        ];

        shellHook = ''
          # uv must use the nix Python above; its own downloaded CPython
          # binaries don't reliably run on NixOS.
          export UV_PYTHON_PREFERENCE=only-system

          export PS1="(conversations) $PS1"
          echo "dev shell: node 22, yarn 4, python 3.14, uv, psql 17"
        '';
      };
    };
}
