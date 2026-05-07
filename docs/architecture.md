# Architecture

OKX Pulse separates the online trading path from the offline training path.

![Runtime architecture](diagrams/runtime_architecture.drawio.png)

## Main components

- `backend/`: low-latency C++ runtime for market ingest, feature building, strategy logic, and simulation
- `ml_pipeline/`: Python pipeline for labels, training, evaluation, and model serving
- `frontend/electron/`: desktop operator UI
- `deploy/`: local container, ECS, EC2, and Terraform deployment assets

## Runtime flow

```text
OKX WebSocket
  -> backend-cpp
  -> feature builder
  -> inference-python (gRPC)
  -> strategy / risk
  -> stream output or simulator
```

## Training flow

```text
OKX historical data or captured market snapshots
  -> feature export
  -> executable labels
  -> model training
  -> evaluation
  -> saved model artifact
```

## Design rule

Keep the trading decision loop local. Use AWS for deployment, monitoring, and service management, not for the latency-critical decision path.

## Code map

| Area | Primary files |
| --- | --- |
| C++ runtime entrypoint | `backend/apps/market_data_main.cpp` |
| Market stream | `backend/src/market_data/market_stream.cpp` |
| Feature builder | `backend/src/features/feature_builder.hpp` |
| Prediction client | `backend/src/inference/prediction_client.cpp` |
| Strategy runtime | `backend/src/strategy/runtime_stream_handler.cpp` |
| Python model server | `ml_pipeline/serving/app.py` |
| gRPC contract | `backend/proto/market_data.proto` |
