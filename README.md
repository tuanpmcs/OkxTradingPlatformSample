# OKX Pulse: Real-Time HFT Signal Inference Platform

OKX Pulse is a course-project trading signal platform built around OKX market data. It keeps the latency-sensitive path in C++, serves ML predictions from Python, provides an Electron operator UI, and includes Docker/AWS deployment assets for comparison between local containers, ECS on EC2, and ECS on Fargate.

The project goal is not just to classify price direction. The ML pipeline builds labels from executable bid/ask PnL so model results are evaluated against whether crossing the spread would have produced a profitable trade.

## Project Map

| Path | Purpose |
| --- | --- |
| `backend/` | C++ market-data ingestion, feature generation, gRPC streaming, inference client, strategy runtime, and paper trader |
| `ml_pipeline/` | Python data preparation, feature parity, executable-PnL labels, model training/evaluation, and inference serving |
| `frontend/electron/` | Desktop operator UI |
| `deploy/` | Docker Compose, ECS task/service templates, EC2 scripts, and Terraform notes |
| `docs/` | Architecture, data-contract, feature, and deployment documentation |
| `reports/` | Final report, presentation files, diagrams, and result images |
| `tests/` | C++ and Python test notes/placeholders |

## Review Guide

Start with the final report, then use the docs as implementation support:

| Resource | Location |
| --- | --- |
| IEEE-style paper PDF | `reports/tex/paper_report.pdf` |
| IEEE-style paper source | `reports/tex/paper_report.tex` |
| Final project report | `reports/report.md` |
| Report index and assets | `reports/README.md` |
| Documentation index | `docs/README.md` |
| Runtime architecture | `docs/architecture.md` |
| HFT feature engineering | `docs/feature_engineering_hft.md` |
| Feature definitions | `docs/feature_definitions.md` |
| Data contracts | `docs/data_contracts.md` |
| Deployment notes | `docs/deployment.md` |
| EC2 vs Fargate appendix | `docs/aws_ec2_vs_fargate_comparison.md` |

## Runtime Architecture

```text
OKX WebSocket
  -> backend-cpp
      -> parse market data
      -> build rolling order-book/trade-flow features
      -> optionally export feature CSV
      -> publish MarketData gRPC stream on :50051
  -> inference-python
      -> serve PredictionService gRPC on :50061
  -> strategy / paper trader / operator UI
```

Primary contract: `backend/proto/market_data.proto`

Default local ports:

| Service | Port |
| --- | --- |
| `backend-cpp` | `127.0.0.1:50051` |
| `inference-python` | `127.0.0.1:50061` |
| `web-gateway` | `127.0.0.1:8080` |

## Quick Start

Run the containerized runtime:

```bash
docker compose -f deploy/containers/docker-compose.yml --profile runtime up --build
```

Run the Electron UI:

```bash
cd frontend
npm run install:desktop
npm run start:desktop
```

## Local Development

Build and run the C++ market-data runtime. The executable is currently named `hello_world` in CMake, but it is the main OKX market-data service.

```bash
export VCPKG_ROOT=$HOME/vcpkg
cmake --workflow --preset ci-arm64-osx-dynamic-rel
./build/arm64-osx-dynamic/release/bin/hello_world \
  --grpc-port 50051 \
  --config backend/configs/okx_public.yaml
```

Run the Python inference service:

```bash
python3 -m venv ml_pipeline/.venv
source ml_pipeline/.venv/bin/activate
pip install -r ml_pipeline/requirements.inference.txt
python -m ml_pipeline.serving.app \
  --model models/pulse_lstm_v1.pt \
  --host 127.0.0.1 \
  --port 50061
```

Enable streaming predictions from the C++ runtime:

```bash
./build/arm64-osx-dynamic/release/bin/hello_world \
  --grpc-port 50051 \
  --config backend/configs/okx_public.yaml \
  --inference-mode grpc \
  --inference-grpc-target 127.0.0.1:50061 \
  --inference-model-type xgboost \
  --inference-horizon-sec 30 \
  --inference-min-points 32 \
  --enable-stream-predictions
```

Build and run helper tools:

```bash
cmake --build --preset arm64-osx-dynamic-rel --target paper_trader inference_client feature_export

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

Detailed usage lives in `ml_pipeline/README.md`.

Main stages:

- Data ingestion and labeling: `ml_pipeline/data/`
- Feature building and parity checks: `ml_pipeline/features/`
- Model training and evaluation: `ml_pipeline/models/`
- Online inference serving: `ml_pipeline/serving/`

Typical serving-only setup:

```bash
python3 -m venv ml_pipeline/.venv
source ml_pipeline/.venv/bin/activate
pip install -r ml_pipeline/requirements.inference.txt
python -m ml_pipeline.serving.app --host 127.0.0.1 --port 50061
```

## Deployment

Local Docker and AWS deployment notes are in `docs/deployment.md`.

Key deployment assets:

- `deploy/containers/docker-compose.yml`
- `deploy/containers/Dockerfile.backend-cpp`
- `deploy/containers/Dockerfile.inference-python`
- `deploy/containers/Dockerfile.web-gateway`
- `deploy/ecs/`
- `deploy/ec2/`
- `deploy/terraform/`

Recommended conclusion for the project report:

- Use `ECS on EC2` for lower always-on cost and more host control.
- Use `ECS on Fargate` when operational simplicity matters more than steady-state cost.
- Keep the live trading decision loop on the internal C++/Python gRPC path.

## Submission Package

Create a clean zip from the repository root:

```bash
scripts/prepare_submission.sh
```

The package is written to `submission/` and excludes build outputs, virtual environments, local datasets, model artifacts, `node_modules/`, generated docs, caches, and macOS metadata.
