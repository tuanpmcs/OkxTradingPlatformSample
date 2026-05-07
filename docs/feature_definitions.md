# Feature Definitions

These are the main features shared across the runtime and training pipeline.

Feature logic is split between the online C++ path and the offline Python path. The implementation should keep names and meanings aligned so training results match live serving behavior.

## Price state

| Feature | Meaning |
| --- | --- |
| `mid_price` | average of best bid and best ask |
| `spread` | best ask minus best bid |
| `rel_spread` | spread normalized by mid price |
| `microprice` | top-of-book price adjusted by bid/ask size pressure |

## Order-book pressure

| Feature | Meaning |
| --- | --- |
| `imbalance_l1` | level-1 bid/ask size imbalance |
| `imbalance_l5` | aggregate imbalance across the first five book levels |
| `weighted_bid_depth` | distance-weighted bid-side depth |
| `weighted_ask_depth` | distance-weighted ask-side depth |

## Trade flow

| Feature | Meaning |
| --- | --- |
| `trade_volume` | recent executed trade quantity |
| `trade_imbalance` | buy-vs-sell aggressive flow imbalance |
| `trade_vwap` | recent volume-weighted average trade price |
| `trade_vwap_dev_from_mid` | trade VWAP deviation from current mid price |

## Short-horizon changes

| Feature | Meaning |
| --- | --- |
| `delta_mid_price` | recent change in mid price |
| `delta_spread` | recent change in spread |
| `delta_imbalance_l5` | recent change in five-level book imbalance |

## Source files

- Online C++: `backend/src/features/feature_builder.hpp`
- Offline Python helpers: `ml_pipeline/features/common.py`
- Feature export: `backend/src/features/feature_csv_writer.cpp`
- Label generation: `ml_pipeline/data/build_labels.py`
