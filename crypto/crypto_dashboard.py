#!/usr/bin/env python3
"""
ton_drop_chart.py

- Fetch 1h candles via ccxt
- Compute 24h sliding-window drops using prior 24h HIGH vs current CLOSE
- Mark >=5% (and >=10%) drop events
- Plot price + volume with event markers
- Save PNG and CSV

Install:
  pip install ccxt pandas matplotlib python-dateutil

Run:
  python ton_drop_chart.py --symbol TON/USDT --exchange binance --days 30 --window 24 --threshold 5 --out_prefix ton_1h
"""

import argparse
from datetime import datetime, timedelta, timezone
import time

import ccxt
import pandas as pd
import matplotlib.pyplot as plt


def fetch_ohlcv(exchange_name: str, symbol: str, days: int, timeframe: str = "1h") -> pd.DataFrame:
    ex_cls = getattr(ccxt, exchange_name)
    ex = ex_cls({"enableRateLimit": True})
    ex.load_markets()
    if symbol not in ex.markets:
        raise ValueError(f"Symbol {symbol} not found on {exchange_name}. Try a different quote asset or check spelling.")
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    limit = 1000
    all_rows = []
    fetch_since = since_ms
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=fetch_since, limit=limit)
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < limit:
            break
        last_ts = batch[-1][0]
        fetch_since = last_ts + 1
        if last_ts >= int(datetime.now(timezone.utc).timestamp() * 1000) - 60_000:
            break
        time.sleep(ex.rateLimit / 1000 if hasattr(ex, "rateLimit") else 0.1)

    if not all_rows:
        raise RuntimeError("No data fetched.")

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df.set_index("timestamp")
    return df


def compute_drops(df: pd.DataFrame, window_hours: int) -> pd.DataFrame:
    # Rolling max of high over prior window_hours, excluding current bar
    highs = df["high"]
    roll_max_incl = highs.rolling(window=window_hours, min_periods=window_hours).max()
    ref_peak = roll_max_incl.shift(1)  # exclude current
    drops = (ref_peak - df["close"]) / ref_peak * 100.0
    out = df.copy()
    out["peak_lookback_high"] = ref_peak
    out["drop_pct"] = drops
    return out


def summarize_and_bucket(events: pd.DataFrame, thr: float):
    ev = events[events["drop_pct"] >= thr]
    if ev.empty:
        return {
            "count": 0,
            "avg": None,
            "max": None,
            "count_5_10": 0,
            "count_10_plus": 0,
        }
    count = len(ev)
    avg = float(ev["drop_pct"].mean())
    mx = float(ev["drop_pct"].max())
    count_5_10 = int(((ev["drop_pct"] >= 5.0) & (ev["drop_pct"] < 10.0)).sum())
    count_10_plus = int((ev["drop_pct"] >= 10.0).sum())
    return {
        "count": count,
        "avg": avg,
        "max": mx,
        "count_5_10": count_5_10,
        "count_10_plus": count_10_plus,
    }


def plot_price_volume_with_events(df: pd.DataFrame, symbol: str, timeframe: str, thr: float, out_png: str):
    # Build figure with two axes
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    fig.suptitle(f"{symbol} Price & Volume ({timeframe})  |  {len(df)} bars")

    # Price
    ax1.plot(df.index, df["close"], label="Close")
    # Event markers
    ev5 = df[df["drop_pct"] >= thr]
    ev10 = df[df["drop_pct"] >= 10.0]
    ax1.scatter(ev5.index, ev5["close"], marker="o", s=20, label=f">= {thr:.2f}% drop")
    if not ev10.empty:
        ax1.scatter(ev10.index, ev10["close"], marker="x", s=35, label=">= 10% drop")
    ax1.set_ylabel("Price")
    ax1.grid(True)
    ax1.legend(loc="upper left")

    # Volume
    ax2.bar(df.index, df["volume"], label="Volume", alpha=0.7)
    ax2.set_xlabel("Time (UTC)")
    ax2.set_ylabel("Volume")
    ax2.grid(True)
    ax2.legend(loc="upper left")

    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(out_png, dpi=300, bbox_inches="tight")
    print(f"Saved chart: {out_png}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="TON/USDT")
    parser.add_argument("--exchange", type=str, default="binance")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--window", type=int, default=24)
    parser.add_argument("--threshold", type=float, default=5.0)
    parser.add_argument("--timeframe", type=str, default="1h")
    parser.add_argument("--out_prefix", type=str, default=None)
    args = parser.parse_args()

    df = fetch_ohlcv(args.exchange, args.symbol, args.days, timeframe=args.timeframe)
    df2 = compute_drops(df, window_hours=args.window)

    # Filter valid rows with reference peak present
    valid = df2.dropna(subset=["peak_lookback_high"]).copy()

    # Summary
    summary = summarize_and_bucket(valid, args.threshold)
    print(f"Exchange: {args.exchange}")
    print(f"Symbol:   {args.symbol}")
    print(f"TF:       {args.timeframe}")
    print(f"Days:     {args.days}")
    print(f"Window:   {args.window}h")
    print(f"Thresh:   {args.threshold:.2f}%")
    print("-" * 40)
    print(f"Events >= {args.threshold:.2f}%: {summary['count']}")
    print(f"Avg drop: {summary['avg']:.2f}%") if summary["avg"] is not None else print("Avg drop: N/A")
    print(f"Max drop: {summary['max']:.2f}%") if summary["max"] is not None else print("Max drop: N/A")
    print(f"5%–9.99%: {summary['count_5_10']}")
    print(f">=10%:    {summary['count_10_plus']}")

    # Events table
    events = valid[valid["drop_pct"] >= args.threshold][["peak_lookback_high", "close", "drop_pct"]].copy()
    events = events.rename(columns={"close": "current_close"})
    events.index.name = "datetime_utc"

    prefix = args.out_prefix or f"{args.symbol.replace('/', '_')}_{args.timeframe}"
    out_csv = f"{prefix}_events_ge_{int(args.threshold)}.csv"
    out_png = f"{prefix}_chart.png"

    events.to_csv(out_csv, float_format="%.6f")
    print(f"Saved events CSV: {out_csv}")

    # Plot
    plot_price_volume_with_events(valid, args.symbol, args.timeframe, args.threshold, out_png)


if __name__ == "__main__":
    main()
