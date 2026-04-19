# Web Frontend

Browser-first operator UI that runs independently from the backend.
It now includes a desktop-style realtime market chart (price + volume), and tolerates partial book snapshots where `price=0`.

## Run

```bash
cd frontend/web
npm start
```

Then open `http://127.0.0.1:5173`.

## Modes

- `Gateway` (default): pulls latest tick from backend via `GET /market/latest`, then sends rolling points to `POST /predict`.
- `Simulated`: fallback mode without backend; generates local ticks in browser.

You can use this UI standalone for demo/dev, then switch to gateway mode when runtime services are up.
