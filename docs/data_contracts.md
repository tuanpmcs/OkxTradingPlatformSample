# Data Contracts

## gRPC contract

- File: `backend/proto/market_data.proto`
- Services:
  - `MarketData.Subscribe(SubscribeRequest) -> stream Tick`
  - `PredictionService.Predict(PredictRequest) -> PredictResponse`

## CSV contracts

- Online feature export columns are emitted by `trading::FeatureCsvWriter`
- Label builder input accepts C++ feature CSV schema and normalizes to:
  - `ts`, `price`, `mid_price`, `spread`, `imbalance`, `trade_volume`, `trade_imbalance`
