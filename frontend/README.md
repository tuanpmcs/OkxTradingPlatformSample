# Frontend Split

This repository keeps two separate operator UIs:

- `frontend/web`: browser-first UI (docker-friendly, independent).
- `frontend/electron`: desktop UI (Electron app with richer workstation flow).

## Quick Run

From `frontend/`:

```bash
npm run start:web
```

```bash
npm run start:desktop
```

## Install

```bash
npm run install:web
npm run install:desktop
```

## Runtime Endpoints

- Web app default: `http://127.0.0.1:5173`
- Gateway default: `http://127.0.0.1:8080`
- Backend gRPC: `127.0.0.1:50051`
