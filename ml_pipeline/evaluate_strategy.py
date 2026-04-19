from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate trading profitability from predictions/signals.")
    p.add_argument("--csv", required=True, help="Input CSV with ts, price and either pred_return or signal")
    p.add_argument("--out-csv", help="Optional output CSV path for per-trade details")
    p.add_argument("--price-col", default="price", help="Price column name")
    p.add_argument("--ts-col", default="ts", help="Timestamp column name (ms)")
    p.add_argument("--pred-col", default="pred_return", help="Predicted return column (if available)")
    p.add_argument("--signal-col", default="signal", help="Signal column (LONG/SHORT/HOLD or 1/-1/0)")
    p.add_argument("--target-price-col", default="target_price", help="Future/exit price column")
    p.add_argument("--hold-rows", type=int, default=1, help="Fallback holding rows if target_price is missing")
    p.add_argument("--qty", type=float, default=1.0, help="Position size in base units")
    p.add_argument("--entry-threshold", type=float, default=0.0, help="Absolute pred_return threshold to enter")
    p.add_argument("--fee-bps-per-side", type=float, default=1.0, help="Fee bps per side (entry/exit)")
    p.add_argument("--slippage-bps-per-side", type=float, default=0.5, help="Slippage bps per side (entry/exit)")
    return p.parse_args()


def _to_signal(value: object) -> int:
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"long", "buy", "1", "+1"}:
            return 1
        if v in {"short", "sell", "-1"}:
            return -1
        return 0
    try:
        f = float(value)
    except Exception:
        return 0
    if f > 0:
        return 1
    if f < 0:
        return -1
    return 0


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(equity)
    dd = equity - peaks
    return float(dd.min())


def build_signals(df: pd.DataFrame, args: argparse.Namespace) -> pd.Series:
    if args.signal_col in df.columns:
        return df[args.signal_col].map(_to_signal).astype(int)

    if args.pred_col not in df.columns:
        raise ValueError(f"CSV must have either '{args.signal_col}' or '{args.pred_col}'")

    pred = pd.to_numeric(df[args.pred_col], errors="coerce").fillna(0.0)
    th = max(0.0, float(args.entry_threshold))
    sig = np.where(pred > th, 1, np.where(pred < -th, -1, 0))
    return pd.Series(sig, index=df.index, dtype=int)


def run(args: argparse.Namespace) -> None:
    df = pd.read_csv(args.csv)
    if args.ts_col not in df.columns or args.price_col not in df.columns:
        raise ValueError(f"CSV must contain '{args.ts_col}' and '{args.price_col}'")

    out = df.copy()
    out[args.ts_col] = pd.to_numeric(out[args.ts_col], errors="coerce")
    out[args.price_col] = pd.to_numeric(out[args.price_col], errors="coerce")
    out = out.dropna(subset=[args.ts_col, args.price_col]).sort_values(args.ts_col).reset_index(drop=True)
    if out.empty:
        raise ValueError("No valid rows after cleaning")

    signals = build_signals(out, args)
    out["signal"] = signals

    if args.target_price_col in out.columns:
        exit_px = pd.to_numeric(out[args.target_price_col], errors="coerce")
    else:
        exit_px = out[args.price_col].shift(-max(1, int(args.hold_rows)))
    out["entry_price"] = out[args.price_col]
    out["exit_price"] = exit_px
    out = out.dropna(subset=["exit_price"]).reset_index(drop=True)
    out["signal"] = out["signal"].astype(int)

    qty = float(args.qty)
    fee_bps = float(args.fee_bps_per_side)
    slippage_bps = float(args.slippage_bps_per_side)
    bps_to_frac = 1e-4

    notional_entry = np.abs(qty) * out["entry_price"].to_numpy(dtype=float)
    notional_exit = np.abs(qty) * out["exit_price"].to_numpy(dtype=float)
    total_notional = notional_entry + notional_exit
    side_cost_frac = (fee_bps + slippage_bps) * bps_to_frac
    total_cost = total_notional * side_cost_frac

    pos = out["signal"].to_numpy(dtype=int) * qty
    gross = pos * (out["exit_price"].to_numpy(dtype=float) - out["entry_price"].to_numpy(dtype=float))
    net = np.where(out["signal"].to_numpy(dtype=int) == 0, 0.0, gross - total_cost)

    out["gross_pnl"] = gross
    out["cost"] = np.where(out["signal"] == 0, 0.0, total_cost)
    out["net_pnl"] = net
    out["equity_curve"] = out["net_pnl"].cumsum()

    active = out[out["signal"] != 0]
    gross_total = float(active["gross_pnl"].sum()) if not active.empty else 0.0
    net_total = float(active["net_pnl"].sum()) if not active.empty else 0.0
    wins = int((active["net_pnl"] > 0).sum()) if not active.empty else 0
    losses = int((active["net_pnl"] < 0).sum()) if not active.empty else 0
    trades = int(len(active))
    win_rate = float(wins / trades) if trades > 0 else 0.0
    avg_trade = float(active["net_pnl"].mean()) if trades > 0 else 0.0
    profit_sum = float(active.loc[active["net_pnl"] > 0, "net_pnl"].sum()) if trades > 0 else 0.0
    loss_sum = float(-active.loc[active["net_pnl"] < 0, "net_pnl"].sum()) if trades > 0 else 0.0
    profit_factor = float(profit_sum / loss_sum) if loss_sum > 0 else float("inf")
    max_dd = _max_drawdown(out["equity_curve"].to_numpy(dtype=float))

    print(f"Rows:           {len(out)}")
    print(f"Active trades:  {trades}")
    print(f"Gross PnL:      {gross_total:.6f}")
    print(f"Net PnL:        {net_total:.6f}")
    print(f"Win rate:       {win_rate:.4f}")
    print(f"Avg trade PnL:  {avg_trade:.6f}")
    print(f"Profit factor:  {profit_factor:.4f}")
    print(f"Max drawdown:   {max_dd:.6f}")
    print(f"Wins/Losses:    {wins}/{losses}")

    if args.out_csv:
        out_path = Path(args.out_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(out_path, index=False)
        print(f"Saved trade detail: {out_path}")


def main() -> int:
    args = parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
