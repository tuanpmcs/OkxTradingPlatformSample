# OKX Trading Platform Sample

An end-to-end sample project for real-time market data streaming and local inference:

- `backend-cpp`: a C++ backend that reads OKX WebSocket data and republishes it as a gRPC stream
- `inference-python`: a Python gRPC service for model inference
- `web-gateway`: an HTTP gateway that forwards prediction requests to the inference service
- `desktop/`: an Electron frontend for stream monitoring, charts, predictions, and trading simulation

## Architecture Overview

![Architecture](docs/architecture.drawio.svg)

Diagram file:

- [docs/architecture.drawio.svg](docs/architecture.drawio.svg)

## Main Components

### 1. Backend C++

- Main file: [main.cpp](main.cpp)
- Connects to OKX public and business channels
- Parses payloads with `simdjson`
- Normalizes ticks and publishes them through `MarketData.Subscribe`
- In Docker, the service binds to `0.0.0.0:50051`
- From the host machine or the desktop app, connect with `grpc://127.0.0.1:50051`

### 2. gRPC Contract

- Proto file: [proto/market_data.proto](proto/market_data.proto)
- Main services:
  - `MarketData.Subscribe(SubscribeRequest) returns (stream Tick)`
  - `PredictionService.Predict(PredictRequest) returns (PredictResponse)`

### 3. Python Inference

- Folder: [ml_pipeline](ml_pipeline)
- Server: [prediction_server.py](ml_pipeline/prediction_server.py)
- Default model in Docker Compose:
  - `/app/models/pulse_tree_v1.joblib`
- Default port:
  - `127.0.0.1:50061`

### 4. Web Gateway

- Dockerfile: [deploy/containers/Dockerfile.web-gateway](deploy/containers/Dockerfile.web-gateway)
- Compose service: `web-gateway`
- Port:
  - `http://127.0.0.1:8080`
- Purpose:
  - exposes HTTP endpoints such as `/health` and `/predict`
- Note:
  - this is not the visual frontend

### 5. Electron Frontend

- Folder: [desktop](desktop)
- Main entry points:
  - [desktop/main.js](desktop/main.js)
  - [desktop/renderer.js](desktop/renderer.js)
  - [desktop/index.html](desktop/index.html)
- Default frontend connections:
  - stream backend: `grpc://127.0.0.1:50051`
  - prediction service: `127.0.0.1:50061`

## Data Flow

1. `backend-cpp` connects to OKX WebSocket and receives market events.
2. The backend normalizes the data and publishes it through the `MarketData.Subscribe` gRPC stream.
3. The Electron app subscribes to the stream at `127.0.0.1:50051`.
4. When predictions are needed, Electron calls `PredictionService.Predict` at `127.0.0.1:50061`.
5. `web-gateway` provides an additional HTTP API for testing or external integration.

## Quick Start With Docker Compose

Start the three backend services:

```bash
docker compose -f deploy/containers/docker-compose.yml up --build
```

Once started, the exposed ports are:

- `backend-cpp`: `127.0.0.1:50051`
- `inference-python`: `127.0.0.1:50061`
- `web-gateway`: `127.0.0.1:8080`

Check the gateway:

```bash
curl http://127.0.0.1:8080/health
```

## Launch The Desktop Frontend

The frontend is not part of Docker Compose. After the three services above are running, launch the Electron app in another terminal:

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample/desktop
npm install
npm start
```

In the app, use this stream URL:

```text
grpc://127.0.0.1:50051
```

## Run Locally Without Docker

### Backend C++

```bash
cmake --build --preset build-debug-osx -j
./build/osx/debug/bin/hello_world --grpc-port 50051
```

### Python Inference

```bash
cd ml_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python prediction_server.py --model ../models/pulse_tree_v1.joblib --host 127.0.0.1 --port 50061
```

### Desktop Electron

```bash
cd desktop
npm install
npm start
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

## Notes

- `web-gateway` is only an HTTP API and does not provide the UI.
- The first Docker build for `backend-cpp` can take a while because it compiles C++ dependencies.
- The Docker build for `backend-cpp` is now more cache-friendly, but changing `vcpkg.json`, `Dockerfile.backend-cpp`, or the custom triplets will still invalidate the dependency layer.
- If the desktop app cannot connect to the stream, check the `backend-cpp` container logs and confirm that port `50051` is published.
