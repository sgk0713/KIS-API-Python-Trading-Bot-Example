import os
import datetime
from backtest.reporter_md import write_report


def test_report_contains_daily_block(tmp_path):
    events = [
        {"day": datetime.date(2025, 2, 18), "phase": "09:05", "kind": "order_placed",
         "order": {"side": "BUY", "qty": 24, "price": 11839, "type": "LOC", "desc": "🆕새출발"},
         "plan_status": "✨새출발", "t_val": 0.0, "star_price": 0.0},
        {"day": datetime.date(2025, 2, 18), "phase": "15:25", "kind": "order_filled",
         "order": {"side": "BUY", "qty": 24, "price": 11839, "type": "LOC", "desc": "🆕새출발"},
         "fill_price": 10310.0, "post_qty": 24, "post_avg": 10310.0, "is_reverse": False},
    ]
    snaps = [
        {"date": "2025-02-18", "open": 10250, "high": 10380, "low": 10180,
         "close": 10310, "volume": 530000, "ma5": 10150.0, "qty": 24,
         "avg": 10310.0, "cash": 9752560.0, "equity": 247440.0,
         "total": 10000000.0, "seed": 10000000, "t_val": 1.0,
         "is_reverse": False, "rev_day": 0},
    ]
    out = str(tmp_path / "report.md")
    write_report(events, snaps, out, ticker="418660",
                 start=datetime.date(2025, 2, 18), end=datetime.date(2025, 2, 18),
                 seed=10_000_000, split=40, target_pct=7.0, compound_rate=70)

    assert os.path.exists(out)
    content = open(out, encoding="utf-8").read()
    assert "2025-02-18" in content
    assert "🆕새출발" in content
    assert "OHLC: 10,250 / 10,380 / 10,180 / 10,310" in content
    assert "24주 @ 10,310원" in content
    assert "시드 10,000,000원" in content


def test_report_renders_graduation_block(tmp_path):
    events = [
        {"day": datetime.date(2025, 3, 10), "phase": "17:00", "kind": "graduated",
         "profit": 500000, "yield_pct": 5.0, "added_seed": 350000,
         "old_seed": 10_000_000, "new_seed": 10_350_000},
    ]
    snaps = [
        {"date": "2025-03-10", "open": 11000, "high": 11050, "low": 10950,
         "close": 11000, "volume": 500000, "ma5": 10900.0, "qty": 0,
         "avg": 0.0, "cash": 10_350_000.0, "equity": 0.0,
         "total": 10_350_000.0, "seed": 10_350_000, "t_val": 0.0,
         "is_reverse": False, "rev_day": 0},
    ]
    out = str(tmp_path / "report.md")
    write_report(events, snaps, out, ticker="418660",
                 start=datetime.date(2025, 3, 10), end=datetime.date(2025, 3, 10),
                 seed=10_000_000, split=40, target_pct=7.0, compound_rate=70)
    content = open(out, encoding="utf-8").read()
    assert "🎓 사이클 졸업" in content
    assert "복리 +350,000원" in content
    assert "10,350,000원" in content
