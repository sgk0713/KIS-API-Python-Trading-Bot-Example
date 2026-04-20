import csv
import datetime
from backtest.reporter_csv import write_trades_csv, write_daily_csv


def test_write_trades_csv(tmp_path):
    events = [
        {
            "day": datetime.date(2025, 2, 18), "phase": "15:25", "kind": "order_filled",
            "order": {"side": "BUY", "qty": 24, "price": 11839, "type": "LOC", "desc": "🆕새출발"},
            "fill_price": 10310.0, "post_qty": 24, "post_avg": 10310.0, "is_reverse": False,
        },
        {
            "day": datetime.date(2025, 2, 19), "phase": "intraday", "kind": "order_filled",
            "order": {"side": "SELL", "qty": 2, "price": 11032, "type": "LIMIT", "desc": "🎯목표매도"},
            "fill_price": 11032.0, "post_qty": 22, "post_avg": 10310.0, "is_reverse": False,
        },
        # non-fill 이벤트는 제외돼야 함
        {"day": datetime.date(2025, 2, 19), "kind": "order_placed", "order": {"side": "BUY"}},
    ]
    out = str(tmp_path / "trades.csv")
    write_trades_csv(events, out, ticker="418660")

    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["date"] == "2025-02-18"
    assert rows[0]["side"] == "BUY"
    assert rows[0]["qty"] == "24"
    assert rows[0]["desc"] == "🆕새출발"
    assert rows[1]["desc"] == "🎯목표매도"


def test_write_daily_csv(tmp_path):
    snaps = [
        {
            "date": "2025-02-18", "open": 10250, "high": 10380, "low": 10180,
            "close": 10310, "volume": 530000, "ma5": 10150.0, "qty": 24,
            "avg": 10310.0, "cash": 9752560.0, "equity": 247440.0,
            "total": 10000000.0, "seed": 10000000, "t_val": 1.0,
            "is_reverse": False, "rev_day": 0,
        },
    ]
    out = str(tmp_path / "daily.csv")
    write_daily_csv(snaps, out)

    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["date"] == "2025-02-18"
    assert rows[0]["close"] == "10310"
    assert rows[0]["t_val"] == "1.0"
    assert rows[0]["is_reverse"] == "False"
