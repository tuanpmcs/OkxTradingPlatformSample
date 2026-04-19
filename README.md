# OKX Trading Platform Sample

Refactored multi-stage trading stack with clear separation of concerns:

- `backend/` for low-latency C++ ingest/feature/strategy runtime
- `ml_pipeline/` for Python data prep, labeling, training, and serving
- `frontend/` for operator UIs (`electron` and standalone `web`)
- `deploy/` for container and infra deployment assets

## Runtime Architecture

```text
OKX WS
  -> backend/apps/market_data_main.cpp
      -> marketdata parse + rolling features
      -> optional CSV mirror
      -> gRPC MarketData stream (:50051)
  -> ml_pipeline/serving/app.py (PredictionService, :50061)
  -> frontend/electron (operator UI)
```

Proto contract: `backend/proto/market_data.proto`

## Level 2 (Semi-Production)

- Online feature path stays in C++ runtime.
- Local inference is selected at runtime: `grpc` or `onnx`.
- Cloud is reserved for logs, model artifacts, and deployment automation.

Example (local gRPC inference):

```bash
./build/arm64-osx-dynamic/release/bin/hello_world \
  --grpc-port 50051 \
  --inference-mode grpc \
  --inference-grpc-target 127.0.0.1:50061 \
  --inference-model-type xgboost \
  --inference-horizon-sec 30 \
  --inference-min-points 32
```

`pred_model`, `pred_signal`, `pred_ret`, `pred_price`, and `pred_detail` are attached to outbound stream fields.

Note: `--inference-mode onnx` is wired in the C++ runtime, but this repository does not yet bundle ONNX Runtime linkage by default.

## Recommended Repository Layout

```text
trading-platform/
├── backend/
│   ├── src/{common,marketdata,features,inference,risk,strategy,simulator}/
│   ├── apps/
│   │   └── market_data_main.cpp
│   ├── proto/
│   ├── configs/
│   └── CMakeLists.txt
├── ml_pipeline/
│   ├── data/
│   ├── features/
│   ├── models/
│   ├── serving/
│   └── requirements.txt
├── deploy/
├── frontend/
│   ├── web/
│   └── electron/
├── docs/
└── tests/
```

## Quick Start (Docker)

```bash
docker compose -f deploy/containers/docker-compose.yml --profile runtime up --build
```

Ports:

- `backend-cpp`: `127.0.0.1:50051`
- `inference-python`: `127.0.0.1:50061`
- `web-gateway`: `127.0.0.1:8080`

Run runtime + standalone web UI:

```bash
docker compose -f deploy/containers/docker-compose.yml --profile runtime --profile ui up --build
```

- `frontend-web`: `127.0.0.1:5173`

Run Electron UI:

```bash
cd frontend
npm run install:desktop
npm run start:desktop
```

Run standalone Web UI:

```bash
cd frontend
npm run install:web
npm run start:web
```

Open `http://127.0.0.1:5173`.

Frontend split details: `frontend/README.md`.

## Local Run

1. C++ runtime

```bash
export VCPKG_ROOT=$HOME/vcpkg
cmake --workflow --preset ci-arm64-osx-dynamic-rel
./build/arm64-osx-dynamic/release/bin/hello_world --grpc-port 50051 --config backend/configs/okx_public.yaml
```

2. Python inference

```bash
python3 -m venv ml_pipeline/.venv
source ml_pipeline/.venv/bin/activate
pip install -r ml_pipeline/requirements.inference.txt
python -m ml_pipeline.serving.app --model models/pulse_lstm_v1.pt --host 127.0.0.1 --port 50061
```

3. UI

```bash
cd frontend/electron
npm install
npm start
```

4. C++ simulator / inference tools

```bash
cmake --build --preset arm64-osx-dynamic-rel --target paper_trader inference_client

./build/arm64-osx-dynamic/release/bin/inference_client \
  --stream-target 127.0.0.1:50051 \
  --predict-target 127.0.0.1:50061 \
  --symbol BTC-USDT \
  --channel books5

./build/arm64-osx-dynamic/release/bin/paper_trader \
  --stream-target 127.0.0.1:50051 \
  --predict-target 127.0.0.1:50061 \
  --symbol BTC-USDT \
  --channel books5 \
  --runtime-sec 60
```

## ML Pipeline

Detailed usage: `ml_pipeline/README.md`

Primary stage scripts:

- data capture/label: `ml_pipeline/data/*`
- feature parity/checks: `ml_pipeline/features/*`
- training/eval/export: `ml_pipeline/models/*`
- serving: `ml_pipeline/serving/*`

Compatibility wrappers are still available at legacy `ml_pipeline/*.py` script paths.

## C++ Style

Code is colocated by module for readability:

```text
backend/src/module/foo.hpp
backend/src/module/foo.cpp
```
