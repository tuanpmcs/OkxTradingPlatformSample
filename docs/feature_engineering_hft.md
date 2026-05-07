# Feature Engineering for HFT Signals

## 1. Bid and Ask

- **Bid**: the highest price a buyer is willing to pay.
- **Ask**: the lowest price a seller is willing to sell.

- **Best bid**: highest visible bid.
- **Best ask**: lowest visible ask.

### Spread

$$
\text{spread} = \text{ask} - \text{bid}
$$

---

## 2. Order Book (Books)

The order book is the set of visible resting buy and sell orders.

```text
Ask (sell side)
Price   Qty
101     5
102     10

Bid (buy side)
Price   Qty
100     4
99      8
```

### Interpretation

- Bid side: buying interest and demand.
- Ask side: selling interest and supply.
- Depth: liquidity available at each price level.

## 3. Trades

A trade happens when an aggressive order matches against resting liquidity in the order book.

- **Buy trade**: consumes ask-side liquidity.
- **Sell trade**: consumes bid-side liquidity.

Example:

```text
trade_price = 101
trade_qty = 3
side = buy
```

### Key idea

- Books are passive liquidity.
- Trades are aggressive execution.

## 4. Relationship between Books and Trades

- Trades consume visible or hidden liquidity.
- Buy trades remove ask liquidity and can push price upward.
- Sell trades remove bid liquidity and can push price downward.

## 5. Profit and Loss (PnL)

PnL measures whether a trade would have made money after crossing the spread.

### Buy Strategy

- Buy at ask now.
- Sell at bid in the future.

$$
\text{buy\_pnl}_H = \text{bid}_{\text{future}, H} - \text{ask}_{\text{now}}
$$

### Sell Strategy

- Sell at bid now.
- Buy back at ask in the future.

$$
\text{sell\_pnl}_H = \text{bid}_{\text{now}} - \text{ask}_{\text{future}, H}
$$

### Important Insight

- A buyer crosses the spread and pays the ask.
- A seller crosses the spread and receives the bid.
- The spread is an inherent trading cost.

## 6. Label from PnL (for ML)

$$
\text{label}_H =
\begin{cases}
1 & \text{if } \text{buy\_pnl}_H > \epsilon \ \text{and} \ \text{buy\_pnl}_H > \text{sell\_pnl}_H \\
-1 & \text{if } \text{sell\_pnl}_H > \epsilon \ \text{and} \ \text{sell\_pnl}_H > \text{buy\_pnl}_H \\
0 & \text{otherwise}
\end{cases}
$$

Label meaning:

- `1`: executable long edge.
- `-1`: executable short edge.
- `0`: no clear executable edge.

## 7. Intuition

- Books show market intention through liquidity.
- Trades show actual aggressive order flow.
- PnL evaluates whether crossing the spread would have been profitable.

## 8. Summary

| Concept | Meaning          |
| ------- | ---------------- |
| Bid     | Buyer price      |
| Ask     | Seller price     |
| Book    | Market liquidity |
| Trade   | Executed orders  |
| PnL     | Profit / Loss    |

## 9. Code References

- Online feature builder: `backend/src/features/feature_builder.hpp`
- Offline feature helpers: `ml_pipeline/features/common.py`
- Label builder: `ml_pipeline/data/build_labels.py`
