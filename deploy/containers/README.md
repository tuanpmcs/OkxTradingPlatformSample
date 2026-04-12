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

## Notes

- `inference-python` expects model at `/app/models/pulse_tree_v1.joblib` by default.
- If you use another model file, update `MODEL_PATH` in `docker-compose.yml`.
- `backend-cpp` image build is heavier because it compiles C++ + vcpkg dependencies.
- `backend-cpp` now selects the matching CMake preset automatically for Docker `amd64` and `arm64` builds, then starts the gRPC server on port `50051`.
