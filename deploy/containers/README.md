# Containerized Services (Trading Stack)

This setup defines three Docker Compose profiles:

- `runtime`: `OKX WS -> C++ runtime backend -> Python local inference -> gateway`
- `training`: `OKX WS / historical data -> C++ collector backend -> dataset export -> Python training`

The runtime profile includes 3 Level 2 services:

- `backend-cpp`: C++ market stream backend (gRPC on `50051`)
- `inference-python`: Python inference server (gRPC on `50061`)
- `web-gateway`: REST gateway (HTTP on `8080`) that forwards `/predict` to inference gRPC

Runtime flow:

```text
OKX WS
  -> C++ runtime backend
      -> parse trades/books5
      -> maintain rolling state
      -> build feature
      -> call local Python inference (gRPC)
      -> receive prediction
      -> stream/risk output
  -> web-gateway (/predict)
```

## Files

- `Dockerfile.backend-cpp`
- `Dockerfile.inference-python`
- `Dockerfile.web-gateway`
- `docker-compose.yml`
- `gateway/server.js`

## Prerequisites

- Docker Desktop / Docker Engine
- A model artifact such as `../../models/pulse_xgboost_v1.joblib`, `../../models/pulse_lstm_v1.pt`, or `../../models/pulse_best_model.artifact`

For a local connectivity smoke test only, create a deterministic zero-return artifact:

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample
python -m ml_pipeline.models.bootstrap_model --model-out models/pulse_xgboost_v1.joblib
```

Replace that smoke-test artifact with a trained model before production trading.

## Run Runtime Profile

`--profile` must be followed by a profile name. `docker compose --profile up --build` is invalid; use `runtime` or `training`.

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample
docker compose -f deploy/containers/docker-compose.yml --profile runtime up --build
```

Ports:

- C++ backend: `127.0.0.1:50051`
- Python inference (gRPC): `127.0.0.1:50061`
- Web gateway: `127.0.0.1:8080`

## Health check (gateway)

```bash
curl http://127.0.0.1:8080/health
```

Expected local runtime targets:

- `predTarget`: `inference-python:50061`
- `marketTarget`: `backend-cpp:50051`

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
docker compose -f deploy/containers/docker-compose.yml --profile runtime down
```

## Training Data Flow (Docker)

Use the `training` profile when you want C++ to export CSV and run the full Python training pipeline.

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

| Stage | Input | Output | Tool |
| --- | --- | --- | --- |
| Market | Order book / Trades | Raw data | OKX WebSocket |
| Data | Raw stream | Structured dataset | Python / C++ |
| Feature | Raw data | Feature vector | NumPy / Pandas |
| Label | Feature + future price | `y` (`up/down/neutral`) | Python |
| Model | `X`, `y` | Prediction model | XGBoost / PyTorch CNN / LSTM / Transformer |
| System | Model + stream | Trading signal | C++ + gRPC |

### Run the full training pipeline

```bash
cd /Volumes/Dev/Workspace/okx_trading_platform_sample
docker compose -f deploy/containers/docker-compose.yml --profile training up --build model-trainer
```

This starts the training chain in order:

```text
OKX WS / historical data -> C++ collector backend -> feature CSV export -> labeling -> Python training
```

### 1) Collector mode (C++ -> CSV)

`backend-cpp-collector` runs the C++ backend in collector mode:

`hello_world --disable-grpc --csv-out /data/books_trades_btcusdt.csv --duration-sec ${COLLECT_DURATION_SEC:-600}`

and writes to host path:

`../../data/books_trades_btcusdt.csv`

By default, the collector subscribes to OKX order book and trade channels, including `books5` and `trades`, maintains the same rolling feature state used by runtime, and exports structured rows to CSV.

Override duration (example: 15 minutes):

```bash
COLLECT_DURATION_SEC=900 docker compose -f deploy/containers/docker-compose.yml --profile training up --build model-trainer
```

Stop the collector early with `Ctrl+C` only if you are running `backend-cpp-collector` by itself. The full pipeline waits for the collector to complete successfully.

### 2) Label maker

`label-maker` reads features and writes:

`/app/data/train_dataset_btcusdt_h30.csv`

Default feature input:

`/app/data/books_trades_btcusdt.features.csv`

Labels are built from executable PnL:

- long candidate: buy current ask, sell future bid
- short candidate: sell current bid, buy future ask
- neutral: neither side beats `eps`, or the better side is not clearly positive

Override defaults with `LABEL_HORIZON_SEC`, `LABEL_HORIZON_MS`, `LABEL_EPS`, and `TRAIN_DATASET_CSV`.
Set `LABEL_SPREAD_EPS_MULTIPLIER` to control the dynamic neutral band; default is `0.3`, meaning `eps = 0.3 * spread` when spread is available.

### 3) Model trainer

`model-trainer` trains the model set used by runtime inference and offline comparison. By default it trains:

- `/app/models/pulse_xgboost_v1.joblib`
- `/app/models/pulse_lstm_v1.pt`
- `/app/models/pulse_cnn_v1.pt`
- `/app/models/pulse_transformer_v1.pt`

Override the set with `TRAIN_MODEL_TYPES` and the directory with `MODEL_OUT_DIR`.

### Stop training profile services

```bash
docker compose -f deploy/containers/docker-compose.yml --profile training down
```

## Notes

- `inference-python` defaults to `INSTALL_PROFILE=inference` (no torch/cuda stack) for faster build.
- `model-trainer` uses `INSTALL_PROFILE=training` to include torch/lightgbm/catboost.
- `inference-python` expects model at `/app/models/pulse_xgboost_v1.joblib` by default.
- Use `MODEL_PATH=/app/models/pulse_xgboost_v1.joblib`, `MODEL_PATH=/app/models/pulse_cnn_v1.pt`, or `MODEL_PATH=/app/models/pulse_transformer_v1.pt` to run a different trained architecture.
- `backend-cpp` image build is heavier because it compiles C++ + vcpkg dependencies.
- `backend-cpp` now selects the matching CMake preset automatically for Docker `amd64` and `arm64` builds, then starts the gRPC server on port `50051`.
