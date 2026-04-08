# Gleam port todo

Goal: keep the port simple and minimal. Start with a usable Gleam core on the JavaScript target, then add thin JS wrappers for CLI/API runtime glue.

## Plan

- [x] Create a separate `gleam/` project so the Python code stays intact as the reference implementation.
- [x] Install the Gleam toolchain locally and verify `gleam check` works.
- [x] Port the domain model, enums, weight presets, and request validation.
- [x] Port the core scoring pipeline with a simple exact skill-assignment solver.
- [x] Port team formation with a simple exact search over task/team allocations.
- [x] Add JSON decoders/encoders and a small public API surface.
- [x] Add thin JS wrappers for the CLI and HTTP API.
- [x] Add a small Gleam test suite that locks down the shipped examples.
- [x] Document the current scope and known gaps vs the Python implementation.

## Non-goals for the first pass

- Reproducing every Python optimization and cache.
- Reproducing the capped-search heuristics.
- Premature FFI for core logic.

## Notes

- Target: JavaScript for now, because the environment already has Node but not Erlang.
- Keep all core scoring/formation logic in Gleam.
- If a feature would add a lot of complexity for little value, ship the simple exact version first and note the gap.
- Known gaps are documented in `gleam/README.md`.
