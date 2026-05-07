# Data Contracts

The runtime, model server, training pipeline, and UI share two contracts: gRPC for live service communication and CSV for offline feature export.

## gRPC

Proto file: `backend/proto/market_data.proto`

| Service | Purpose |
| --- | --- |
| `MarketData.Subscribe(...) -> stream Tick` | stream live market data |
| `PredictionService.Predict(...) -> PredictResponse` | request a model prediction |

Runtime endpoints:

- `backend-cpp`: `127.0.0.1:50051`
- `inference-python`: `127.0.0.1:50061`
- `web-gateway`: `127.0.0.1:8080`

## CSV

The runtime can export feature rows through `trading::FeatureCsvWriter`.

The training pipeline expects the normalized fields below:

- `ts`
- `price`
- `mid_price`
- `spread`
- `imbalance`
- `trade_volume`
- `trade_imbalance`

Additional engineered columns are documented in `feature_definitions.md`.

## Key rule

Online feature names and offline training columns must stay aligned, otherwise model behavior at runtime will drift from training results.
