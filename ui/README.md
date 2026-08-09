# Aerium Control UI

Local, simulation-first operator dashboard for the CrazySwarm control service.
It combines a safety-focused application shell with a truthful Three.js indoor
observer. The browser is an operator client; flight policy and command validation
remain in the Python backend.

## Start the complete local application

The normal operator setup is the persistent macOS user service, installed from
the repository root:

```bash
.venv/bin/crazyswarm-control dashboard-service install
```

Open `http://localhost:3001`. This runs a production build with API/UI health
supervision and persistent logs. For live-reloading foreground development use:

```bash
.venv/bin/crazyswarm-control dashboard --dev
```

Service builds are created outside the live asset tree and published as an
immutable release. The running UI remains pinned to that release until the
service restarts, so an overlapping test or production build cannot remove the
hashed JavaScript and CSS files required by browser reloads. A failed build
leaves the previously published release active.

The API and its local credential are wired automatically. The API can still be
started separately when developing only that layer:

```bash
.venv/bin/crazyswarm-control serve
```

## Development routes

- `/` — control-center shell and 3D room observer
- `/fixtures` — explicit test-only component states; the operator route has no
  fixture import or fallback

## Checks

```bash
npm run generate:api
npm run check
```

`generate:api` exports the FastAPI schema and refreshes the generated TypeScript
contract. `check` runs lint, TypeScript, unit/accessibility tests, the production
build, and server-rendered HTML tests.

The application is intentionally local-only while it can connect to a loopback
drone-control service. Do not expose or deploy it as a public flight-control URL.
