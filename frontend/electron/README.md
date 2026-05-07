# Pulse Desk (Electron)

Desktop app for visualizing live stream price changes with a lovable, high-contrast UI.
It is now wired to consume the local C++ gRPC stream by default (`grpc://127.0.0.1:50051`).

## Run

1. Start your C++ streamer and gRPC server in one terminal:

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample
cmake --workflow --preset ci-arm64-osx-dynamic-rel
./build/arm64-osx-dynamic/release/bin/hello_world --grpc-port 50051
```

2. Start the desktop app in a second terminal:

```bash
cd frontend/electron
npm install
npm start
```

## Build Desktop Installers

This Electron app can now be packaged for both macOS and Windows.

1. Install dependencies:

```bash
cd frontend/electron
npm install
```

2. Build from the operating system you want to target:

```bash
npm run dist:mac
npm run dist:win
```

Artifacts are written to `frontend/electron/dist/`.

Notes:

- `npm start` now works on both macOS and Windows.
- The app bundles its own `proto/market_data.proto`, so installed builds do not depend on files in `backend/`.
- macOS `.dmg` builds are best produced on macOS.
- Windows `nsis` installers are best produced on Windows.

## Lovable workflow

1. Build the UI in Lovable and export static files.
2. Put the exported app under:

```bash
frontend/electron/lovable-export/dist/index.html
```

3. Start Electron:

```bash
cd frontend/electron
npm start
```

If your shell has `ELECTRON_RUN_AS_NODE=1`, `npm start` now clears it automatically before Electron launches.

Electron will automatically load Lovable export first. If it does not exist, it falls back to the built-in UI.

You can also force a specific Lovable file:

```bash
cd frontend/electron
npm run start:lovable
```

For a ready-to-paste Lovable prompt, use:
- [LOVABLE_PROMPT.md](/Volumes/Dev/Workspace/okx_trading_platform_sample/frontend/electron/LOVABLE_PROMPT.md)

## Data modes

- `Connect Stream`: connects to current URL input (default local C++ gRPC stream).
- `Use Simulated`: starts a local random-walk stream for quick UI testing.
- `Stop`: disconnects and halts updates.
- Subscription rows are sent at runtime through `MarketData.Subscribe`; the C++ backend uses YAML subscriptions only as startup defaults.

## Strategy Auto Trade

- Model selector supports:
  - `LightGBM`
  - `XGBoost`
- Config selector supports:
  - `Market Maker`
  - `Alpha Fast`
  - `Ultra Alpha`
- Strategy selector supports:
  - `Market Making`: spread-aware quoting logic with adverse-selection filter.
  - `Short-Term Alpha`: imbalance-driven directional entries (`LONG/SHORT`) and fast exits.
- `Start Auto` now opens and closes positions automatically using strategy conditions and `Hold (ms)`.
- The Account & Execution panel keeps only `Start Auto`, `Stop Auto`, and `Reset Account`.
- Controls:
  - `Imbalance Threshold`
  - `Adverse/Predict Threshold`
  - `Min Spread (bps)`
  - `Hold (ms)`

## Notes

- Renderer chart uses Chart.js.
- Main process handles gRPC stream (or websocket fallback) and forwards points to renderer via IPC.
- Prediction requests are routed through `PredictionService` on the current gRPC stream target (default `127.0.0.1:50051`), so desktop uses C++ backend prediction path by default.
- C++ flags:
  - `--grpc-port <port>` to change gRPC port.
  - `--disable-grpc` to turn gRPC off.
