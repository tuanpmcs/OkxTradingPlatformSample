# Feature Definitions

Core features used across online/offline:

- `mid_price`
- `spread`
- `rel_spread`
- `microprice`
- `imbalance_l1`, `imbalance_l5`
- `trade_volume`, `trade_imbalance`
- `trade_vwap`, `trade_vwap_dev_from_mid`
- `delta_mid_price`, `delta_spread`, `delta_imbalance_l5`

Primary implementation:

- Online C++: `backend/src/features/feature_builder.hpp`
- Offline Python parity helpers: `ml_pipeline/features/common.py`
