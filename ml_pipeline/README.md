# ML Pipeline

The pipeline is now grouped by stage:

- `ml_pipeline/data`: data ingestion, label build, splits, schema checks
- `ml_pipeline/features`: feature builders and parity checks
- `ml_pipeline/models`: training, evaluation, export
- `ml_pipeline/serving`: online inference service/client

Legacy top-level scripts are still present as wrappers for compatibility.

## Setup

```bash
python3 -m venv ml_pipeline/.venv
source ml_pipeline/.venv/bin/activate
# For serving/inference only:
pip install -r ml_pipeline/requirements.inference.txt
# For full training stack (torch/lightgbm/catboost included):
# pip install -r ml_pipeline/requirements.training.txt
```

## 1) Collect ticks from gRPC

```bash
python -m ml_pipeline.data.collect_ticks_from_grpc \
  --target 127.0.0.1:50051 \
  --symbol BTC-USDT \
  --trade-channel trades \
  --book-channel books5 \
  --duration-sec 300 \
  --out-csv data/books_trades_btcusdt.csv
```

## 2) Build realtime features

```bash
python -m ml_pipeline.features.build_realtime_features \
  --csv data/books_trades_btcusdt.csv \
  --symbol BTC-USDT \
  --channels trades,books5 \
  --out-csv data/features_btcusdt.csv
```

## 3) Build labels

```bash
python -m ml_pipeline.data.build_labels \
  --features-csv data/features_btcusdt.csv \
  --horizon-sec 30 \
  --eps 0.0001 \
  --out-csv data/train_dataset_btcusdt_h30.csv
```

Labels use executable bid/ask PnL when book columns are present:
`buy_pnl = future_bid - current_ask`, `sell_pnl = current_bid - future_ask`.
The label is `up`, `down`, or `neutral` based on which side clears the neutral band.

## Build HFT Archive Dataset

Use this path for the OKX L2 order book archive plus trade archive workflow. The book stream is reconstructed from
`snapshot` and `update` messages before sampling features.

```bash
python -m ml_pipeline.data.build_hft_dataset_from_archives \
  --books-archive ml_pipeline/train_data/BTC-USDT-L2orderbook-400lv-2026-04-12.tar.gz \
  --trades-zip ml_pipeline/train_data/BTC-USDT-trades-2026-04-13.zip \
  --books-start-day 2026-04-06 \
  --books-end-day 2026-04-11 \
  --trades-start-day 2026-04-05 \
  --trades-end-day 2026-04-12 \
  --sample-ms 1000 \
  --horizon-ms 1000 \
  --trade-lookback-ms 1000 \
  --eps 0.01 \
  --spread-eps-multiplier 0.3 \
  --out-csv data/train_dataset_btcusdt_books_2026-04-06_2026-04-11_trades_2026-04-05_2026-04-12_h1000ms.csv
```

If an archive filename and embedded timestamps disagree, the builder filters by embedded UTC timestamps.

## 4) Train models

```bash
python -m ml_pipeline.models.train_xgb \
  --dataset-csv data/train_dataset_btcusdt_h30.csv \
  --model-out-dir models \
  --model-types xgboost,cnn,lstm
```

CPU model zoo:

```bash
python -m ml_pipeline.models.train_cpu_model_zoo \
  --dataset-csv data/train_dataset_btcusdt_h30.csv \
  --out-dir models/cpu_zoo \
  --metrics-out-csv data/cpu_zoo_metrics.csv \
  --task regression
```

## 5) Evaluate strategy

```bash
python -m ml_pipeline.models.evaluate \
  --csv data/cpu_zoo_predictions.csv \
  --pred-col pred_xgboost \
  --price-col price \
  --target-price-col target_price
```

## 6) Run serving

```bash
python -m ml_pipeline.serving.app \
  --model models/pulse_lstm_v1.pt \
  --host 127.0.0.1 \
  --port 50061
```

## 7) Test serving

```bash
python -m ml_pipeline.serving.predictor \
  --target 127.0.0.1:50061 \
  --csv data/books_trades_btcusdt.csv \
  --symbol BTC-USDT \
  --channel books5 \
  --horizon-sec 30
```
