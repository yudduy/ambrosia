# Ambrosia

Ambrosia is a private, single-user health dashboard for Fitbit data available through Google Health. It turns the latest seven days into plain comparisons against the preceding 28 valid personal days, keeps the deterministic analysis on your Mac, and offers an optional ChatGPT-backed consultation through the official Codex app-server.

The product has four tabs: Home, Fitness, Sleep, and Nutrition. It does not produce a proprietary health score, diagnose conditions, or silently save AI output.

## Run locally

Ambrosia requires Python 3.13, `uv`, Node.js, Bun, and the Codex CLI.

```sh
uv sync --extra dev
npm --prefix web install
npm --prefix web run build
uv run ambrosia import /absolute/path/to/google-health-export
uv run ambrosia serve
```

Open `http://127.0.0.1:8787`. Runtime data defaults to `~/Library/Application Support/Ambrosia`; set `AMBROSIA_HOME` to use another private directory.

For development, run the API with `uv run ambrosia serve` and the Vite frontend with `npm --prefix web run dev`. Vite proxies `/api` to port 8787.

## Google Health sync

Configure the collector with absolute paths before starting the service:

```sh
export AMBROSIA_GOOGLE_CREDENTIALS=/private/path/credentials.json
export AMBROSIA_GOOGLE_TOKEN=/private/path/token.json
```

The OAuth grant must include the read-only activity, measurement, sleep, ECG, irregular-rhythm, location, and nutrition scopes. Ambrosia uses list mode for named sessions and nutrition logs, reconciliation mode for wearable aggregates, a 48-hour overlap, and independent watermarks per data type. A failed type does not advance its watermark.

Authorize or expand the grant, then verify nutrition and hydration directly:

```sh
uv run ambrosia google-auth --credentials "$AMBROSIA_GOOGLE_CREDENTIALS" --token "$AMBROSIA_GOOGLE_TOKEN"
uv run ambrosia sync --type nutrition-log --type hydration-log
```

The original responses are retained as immutable compressed files with hashes and counts. Normalized DuckDB tables and portable Parquet snapshots live under `AMBROSIA_HOME`, never in this repository.

## AI and meal photos

The first AI action starts `codex app-server` over stdio with an isolated `CODEX_HOME`. Sign-in is managed by ChatGPT. Ambrosia discovers an image-capable model instead of hardcoding one and exposes only five bounded aggregate-health MCP tools. If the full target-machine compatibility gate fails, Ambrosia records the result and switches future conversations to the bundled OMP sidecar. OMP exposes the same five bounded tools and accepts images only from Ambrosia's sanitized upload directory; it exposes no shell or general filesystem tool.

Meal uploads are EXIF-stripped, resized locally, and deleted after 24 hours if abandoned. AI returns editable nutrition ranges; the meal is not saved until the user confirms it. Routine sync, comparisons, and weekly reports do not invoke AI.

Run the non-destructive compatibility checks with:

```sh
uv run ambrosia assistant-gate --provider codex-app-server --activate-fallback
uv run ambrosia assistant-gate --provider omp
```

## Verification

```sh
uv run pytest
npm --prefix web test
npm --prefix web run build
npm --prefix web run e2e
```

The browser service binds to `127.0.0.1`. The deployment script installs a per-user launchd service and configures private HTTPS through Tailscale Serve; it does not open a public port.

On the target Mac mini, after the import and both sign-ins are complete:

```sh
uv run ambrosia install-macos \
  --credentials "$AMBROSIA_GOOGLE_CREDENTIALS" \
  --token "$AMBROSIA_GOOGLE_TOKEN"
```
