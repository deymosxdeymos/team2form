# Gleam Runtime Plan

## Current Decision

`team2form` is now Gleam/JavaScript only. Legacy runtime code, package API,
tests, parity scripts, and rollback hooks were removed.

## Runtime Commands

Build before deploy:

```bash
gleam build
```

Production command:

```bash
node scripts/server.mjs
```

CLI commands:

```bash
node scripts/cli.mjs quality examples/team-quality.json --mode compat --preset
live_compat
node scripts/cli.mjs form examples/team-formation.json --mode compat --preset
live_compat
```

## Verification

```bash
gleam check
gleam test
node scripts/http_smoke_gleam.mjs
```

The HTTP smoke test starts the Node server, checks `/v1/help`,
`/v1/teamQuality`, `/v1/teamFormation`, startup env validation, error JSON, and
the request body limit.

## Accepted Risks

- **Validation messages may differ from older releases.** Accept this unless
  clients rely on exact error text.
- **JSON field ordering differs.** Accept this; clients should parse JSON.
- **Node server has no framework middleware.** Add only what production actually
  uses: CORS, health checks, logging, or more limits.
