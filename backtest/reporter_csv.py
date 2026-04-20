"""trades.csv + daily.csv 생성."""
import csv


_TRADES_COLS = [
    "date", "ticker", "side", "qty", "price", "type", "desc",
    "is_reverse", "post_qty", "post_avg",
]


def write_trades_csv(events, out_path, ticker):
    """order_filled 이벤트만 추출해 CSV 로."""
    rows = []
    for e in events:
        if e.get("kind") != "order_filled":
            continue
        o = e["order"]
        rows.append({
            "date": e["day"].isoformat() if hasattr(e["day"], "isoformat") else str(e["day"]),
            "ticker": ticker,
            "side": o["side"],
            "qty": o["qty"],
            "price": e["fill_price"],
            "type": o["type"],
            "desc": o.get("desc", ""),
            "is_reverse": e.get("is_reverse", False),
            "post_qty": e.get("post_qty", ""),
            "post_avg": e.get("post_avg", ""),
        })
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_TRADES_COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


_DAILY_COLS = [
    "date", "open", "high", "low", "close", "volume", "ma5",
    "qty", "avg", "cash", "equity", "total", "seed",
    "t_val", "is_reverse", "rev_day",
]


def write_daily_csv(snapshots, out_path):
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_DAILY_COLS)
        w.writeheader()
        for s in snapshots:
            w.writerow({c: s.get(c, "") for c in _DAILY_COLS})
