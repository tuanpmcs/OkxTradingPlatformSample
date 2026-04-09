# Pulse Desk (Electron)

Desktop app for visualizing live stream price changes with a lovable, high-contrast UI.
It is now wired to consume the local C++ gRPC stream by default (`grpc://127.0.0.1:50051`).

## Run

1. Start your C++ streamer and gRPC server in one terminal:

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample
cmake --build --preset build-debug-osx -j
./build/osx/debug/bin/hello_world --grpc-port 50051
```

2. Start the desktop app in a second terminal:

```bash
cd desktop
npm install
npm start
```

## Lovable workflow

1. Build the UI in Lovable and export static files.
2. Put the exported app under:

```bash
desktop/lovable-export/dist/index.html
```

3. Start Electron:

```bash
cd desktop
npm start
```

Electron will automatically load Lovable export first. If it does not exist, it falls back to the built-in UI.

You can also force a specific Lovable file:

```bash
cd desktop
npm run start:lovable
```

For a ready-to-paste Lovable prompt, use:
- [LOVABLE_PROMPT.md](/Volumes/Dev/Workspace/okx_trading_platform_sample/desktop/LOVABLE_PROMPT.md)

## Data modes

- `Connect Stream`: connects to current URL input (default local C++ gRPC stream).
- `Use Simulated`: starts a local random-walk stream for quick UI testing.
- `Stop`: disconnects and halts updates.

## Strategy Auto Trade

- Strategy selector supports:
  - `Market Making`: spread-aware quoting logic with adverse-selection filter.
  - `Short-Term Alpha`: imbalance-driven directional entries (`LONG/SHORT`) and fast exits.
- `Start Auto` now opens and closes positions automatically using strategy conditions and `Hold (ms)`.
- Controls:
  - `Imbalance Threshold`
  - `Adverse/Predict Threshold`
  - `Min Spread (bps)`
  - `Hold (ms)`

## Notes

- Renderer chart uses Chart.js.
- Main process handles gRPC stream (or websocket fallback) and forwards points to renderer via IPC.
- C++ flags:
  - `--grpc-port <port>` to change gRPC port.
  - `--disable-grpc` to turn gRPC off.
