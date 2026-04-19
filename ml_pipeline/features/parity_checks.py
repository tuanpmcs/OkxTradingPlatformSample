from __future__ import annotations

import argparse

import pandas as pd


def main() -> int:
    p = argparse.ArgumentParser(description="Compare offline feature file against online-exported feature file")
    p.add_argument("--offline-csv", required=True)
    p.add_argument("--online-csv", required=True)
    args = p.parse_args()

    offline = pd.read_csv(args.offline_csv)
    online = pd.read_csv(args.online_csv)
    common = sorted(set(offline.columns).intersection(online.columns))
    if not common:
        raise ValueError("no overlapping feature columns")
    print({"offline_rows": len(offline), "online_rows": len(online), "shared_columns": len(common)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
