# OKX Trading Platform Sample

An end-to-end sample trading stack for:

- streaming real-time market data from OKX
- serving normalized ticks over gRPC from C++
- running local ML inference over gRPC from Python
- exposing an optional HTTP bridge for external integrations
- visualizing and simulating strategy behavior in an Electron desktop app

## What You Get

- `backend-cpp` (`hello_world`): C++ market stream service
- `inference-python`: Python `PredictionService` gRPC server
- `web-gateway`: Node/Express HTTP gateway (`/health`, `/predict`)
- `desktop/`: Electron UI for stream + prediction workflows

## Architecture

![Architecture](docs/architecture.drawio.svg)

- Diagram source: [docs/architecture.drawio](docs/architecture.drawio)
- Rendered diagram: [docs/architecture.drawio.svg](docs/architecture.drawio.svg)
- Proto contract: [proto/market_data.proto](proto/market_data.proto)

## Kiến Trúc Ngắn Gọn

Runtime:

```text
OKX WS
  -> C++ runtime backend
      -> parse trades/books5
      -> maintain rolling state
      -> build feature
      -> call Python/SageMaker inference
      -> receive prediction
      -> simulator / frontend
```

Training:

```text
OKX WS / historical data
  -> C++ collector backend
      -> parse trades/books5
      -> maintain rolling state
      -> build feature
      -> future label
      -> dataset export
  -> Python training
```

YAML is only the default subscription/config source. The frontend can request symbol/channel subscriptions at runtime through the stream API.

Role split:

- `backend-cpp` runs the C++ runtime path and publishes ticks/features over gRPC.
- `backend-cpp-collector` runs the same parser and rolling feature path in collector mode, writes CSV, then exits after `COLLECT_DURATION_SEC`.
- `inference-python` serves trained artifacts for runtime prediction.
- Python training scripts build labels, train XGBoost/CNN/LSTM/Transformer models, and compare metrics.

## Prerequisites

- Docker (recommended path)
- Node.js + npm (for `desktop` app)
- Python 3.9+ (for local ML path)
- CMake 3.25+, Ninja, and `vcpkg` (for local C++ path)

## Quick Start (Recommended): Docker + Desktop

### 1) Start backend services

```bash
docker compose -f deploy/containers/docker-compose.yml --profile runtime up --build
```

Runtime profile:

```text
OKX WS -> C++ runtime backend -> Python/SageMaker inference -> simulator / frontend
```

Exposed ports:

- `backend-cpp`: `127.0.0.1:50051`
- `inference-python`: `127.0.0.1:50061`
- `web-gateway`: `127.0.0.1:8080`

Optional health check:

```bash
curl http://127.0.0.1:8080/health
```

### 2) Start desktop app (separate terminal)

```bash
cd desktop
npm install
npm start
```

Default targets used by the app:

- stream: `grpc://127.0.0.1:50051`
- prediction gRPC: `127.0.0.1:50061`

## Run Locally (Without Docker)

### 1) C++ backend

```bash
export VCPKG_ROOT=$HOME/vcpkg
cmake --workflow --preset ci-arm64-osx-dynamic-rel
./build/arm64-osx-dynamic/release/bin/hello_world --grpc-port 50051
```

Notes:

- For Linux presets, see [CMakePresets.json](CMakePresets.json).
- Binary name is `hello_world`.

### 2) Python inference server

```bash
cd ml_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python prediction_server.py --model ../models/pulse_lstm_v1.pt --host 127.0.0.1 --port 50061
```

### 3) Desktop

```bash
cd desktop
npm install
npm start
```

## Service Endpoints

### gRPC

- `MarketData.Subscribe(SubscribeRequest) returns (stream Tick)`
- `PredictionService.Predict(PredictRequest) returns (PredictResponse)`

Defined in: [proto/market_data.proto](proto/market_data.proto)

### HTTP (web-gateway)

- `GET /health`
- `POST /predict`

Gateway implementation: [deploy/containers/gateway/server.js](deploy/containers/gateway/server.js)

## ML Pipeline (Training / Model Build)

Detailed steps are documented in:

- [ml_pipeline/README.md](ml_pipeline/README.md)

Containerized training profile is documented in:

- [deploy/containers/README.md](deploy/containers/README.md)

Training profile:

```text
OKX WS / historical data -> C++ collector backend -> dataset export -> Python training
```

## Repository Layout

```text
.
├── main.cpp
├── proto/
├── ml_pipeline/
├── desktop/
├── deploy/
│   └── containers/
├── docs/
└── models/
```

## Troubleshooting

- If `desktop` cannot connect to stream:
  - verify `backend-cpp` is listening on `127.0.0.1:50051`
  - check container logs: `docker logs backend-cpp`
- If `/predict` fails from gateway:
  - verify `inference-python` is up on `127.0.0.1:50061`
  - verify model file exists at `models/pulse_xgboost_v1.joblib`, `models/pulse_lstm_v1.pt`, `models/pulse_cnn_v1.pt`, or `models/pulse_transformer_v1.pt`
- First C++ Docker build can take longer due to dependency compilation.

## Notes

- `web-gateway` is an API bridge, not a visual frontend.
- `desktop/README.md` has additional UI-specific usage details.
