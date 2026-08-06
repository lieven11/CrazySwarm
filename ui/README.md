# Aerium Control UI

Local, simulation-first operator dashboard for the CrazySwarm control service.
It combines a safety-focused application shell with a truthful Three.js indoor
observer. The browser is an operator client; flight policy and command validation
remain in the Python backend.

## Start the UI

```bash
cd ui
npm install
npm run dev
```

The development server normally uses `http://localhost:3000`; it selects the next
available local port when 3000 is occupied.

Start the backend from the repository root in another terminal:

```bash
.venv/bin/crazyswarm-control serve
```

Press **Connect** and enter the token printed by the backend. Credentials remain
in browser session storage. Mission review, start, status polling, and controlled
cancel are wired to the local API.

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
