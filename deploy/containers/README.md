# Containerized Services (Trading Stack)

This setup containerizes the current system into 3 cloud-ready services:

- `backend-cpp`: C++ market stream backend (gRPC on `50051`)
- `inference-python`: Python inference server (gRPC on `50061`)
- `web-gateway`: REST gateway (HTTP on `8080`) that forwards `/predict` to inference gRPC

## Files

- `Dockerfile.backend-cpp`
- `Dockerfile.inference-python`
- `Dockerfile.web-gateway`
- `docker-compose.yml`
- `gateway/server.js`

## Prerequisites

- Docker Desktop / Docker Engine
- Optional model artifact at `../../models/pulse_tree_v1.joblib`

## Run all 3 services

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample/deploy/containers
docker compose up --build
```

Ports:

- C++ backend: `127.0.0.1:50051`
- Python inference: `127.0.0.1:50061`
- Web gateway: `127.0.0.1:8080`

## Health check (gateway)

```bash
curl http://127.0.0.1:8080/health
```

## Predict via gateway

```bash
curl -X POST http://127.0.0.1:8080/predict \
  -H "Content-Type: application/json" \
  -d '{
    "symbol":"BTC-USDT",
    "channel":"books5",
    "horizonSec":30,
    "strategyMode":"short_term_alpha",
    "holdMs":200,
    "points":[
      {"ts":1712501000000,"price":65000.0,"bidPx":64999.5,"askPx":65000.5,"bidSz":1.4,"askSz":1.0},
      {"ts":1712501000200,"price":65000.2,"bidPx":64999.7,"askPx":65000.7,"bidSz":1.5,"askSz":1.0}
    ]
  }'
```

## Stop

```bash
docker compose down
```

## Training Data Flow (Docker)

Use the `training` profile when you want C++ to export CSV for Python training.

### 1) Start collector mode (C++ -> CSV)

`backend-cpp-collector` runs:

`hello_world --disable-grpc --csv-out /data/market_stream_btcusdt.csv --duration-sec ${COLLECT_DURATION_SEC:-3600}`

and writes to host path:

`../../data/market_stream_btcusdt.csv`

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample/deploy/containers
docker compose --profile training up --build backend-cpp-collector
```

Override duration (example: 15 minutes):

```bash
COLLECT_DURATION_SEC=900 docker compose --profile training up --build backend-cpp-collector
```

Stop it after you have enough rows with `Ctrl+C` (or `docker compose --profile training stop backend-cpp-collector`).

### 2) Start trainer container

```bash
docker compose --profile training up -d ml-trainer
```

### 3) Build features

```bash
docker compose --profile training exec ml-trainer \
  python ml_pipeline/build_realtime_features.py \
  --csv /app/data/market_stream_btcusdt.csv \
  --symbol BTC-USDT \
  --channels trades,books5 \
  --out-csv /app/data/features_btcusdt.csv
```

### 4) Create labels (`up/down/neutral`)

```bash
docker compose --profile training exec ml-trainer \
  python ml_pipeline/create_future_labels.py \
  --features-csv /app/data/features_btcusdt.csv \
  --horizon-sec 30 \
  --eps 0.0001 \
  --out-csv /app/data/train_dataset_btcusdt_h30.csv
```

### 5) Train model artifact

```bash
docker compose --profile training exec ml-trainer \
  python ml_pipeline/train_better_model.py \
  --dataset-csv /app/data/train_dataset_btcusdt_h30.csv \
  --model-out /app/models/pulse_tree_v1.joblib
```

### 6) Stop training profile services

```bash
docker compose --profile training down
```

## Notes

- `inference-python` expects model at `/app/models/pulse_tree_v1.joblib` by default.
- If you use another model file, update `MODEL_PATH` in `docker-compose.yml`.
- `backend-cpp` image build is heavier because it compiles C++ + vcpkg dependencies.
- `backend-cpp` now selects the matching CMake preset automatically for Docker `amd64` and `arm64` builds, then starts the gRPC server on port `50051`.
