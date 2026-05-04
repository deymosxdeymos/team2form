{
  description = "team2form development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      forAllSystems =
        function:
        nixpkgs.lib.genAttrs systems (
          system:
          function nixpkgs.legacyPackages.${system}
        );
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.caddy
            pkgs.curl
            pkgs.docker
            pkgs.erlang_28
            pkgs.gleam
            pkgs.jq
            pkgs.podman
            pkgs.rebar3
          ];

          shellHook = ''
            echo "team2form dev shell"
            echo "try: gleam check && gleam test"
          '';
        };
      });
    };
}
