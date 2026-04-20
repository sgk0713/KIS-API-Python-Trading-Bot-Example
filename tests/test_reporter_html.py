import os
import datetime
from backtest.reporter_html import write_dashboard


def test_dashboard_renders(tmp_path):
    events = [
        {"day": datetime.date(2025, 2, 18), "phase": "09:05", "kind": "order_placed",
         "order": {"side": "BUY", "qty": 24, "price": 11839, "type": "LOC", "desc": "🆕새출발"}},
        {"day": datetime.date(2025, 3, 10), "phase": "17:00", "kind": "graduated",
         "profit": 500000, "yield_pct": 5.0, "added_seed": 350000,
         "old_seed": 10_000_000, "new_seed": 10_350_000},
    ]
    snaps = [
        {"date": "2025-02-18", "open": 10250, "high": 10380, "low": 10180,
         "close": 10310, "volume": 530000, "ma5": 10150.0, "qty": 24,
         "avg": 10310.0, "cash": 9752560.0, "equity": 247440.0,
         "total": 10000000.0, "seed": 10000000, "t_val": 1.0,
         "is_reverse": False, "rev_day": 0},
        {"date": "2025-03-10", "open": 11000, "high": 11050, "low": 10950,
         "close": 11000, "volume": 500000, "ma5": 10900.0, "qty": 0,
         "avg": 0.0, "cash": 10_350_000.0, "equity": 0.0,
         "total": 10_350_000.0, "seed": 10_350_000, "t_val": 0.0,
         "is_reverse": False, "rev_day": 0},
    ]
    out = str(tmp_path / "dashboard.html")
    write_dashboard(events, snaps, out, ticker="418660",
                    start=datetime.date(2025, 2, 18),
                    end=datetime.date(2025, 3, 10),
                    seed=10_000_000, split=40, target_pct=7.0, compound_rate=70)
    assert os.path.exists(out)
    content = open(out, encoding="utf-8").read()
    assert "418660" in content
    assert "equity-chart" in content
    assert "Plotly" in content
    assert "+3.50%" in content  # total_ret = (10,350,000 - 10,000,000) / 10,000,000
    assert "350,000원" in content  # 복리 가산


def test_dashboard_reverse_band(tmp_path):
    """리버스 구간이 있으면 shapes 에 사각형이 들어감."""
    snaps = [
        {"date": "2025-03-01", "open": 10000, "high": 10100, "low": 9900,
         "close": 9950, "volume": 500000, "ma5": 10000, "qty": 100, "avg": 10000,
         "cash": 9_000_000, "equity": 995_000, "total": 9_995_000,
         "seed": 10_000_000, "t_val": 10, "is_reverse": False, "rev_day": 0},
        {"date": "2025-03-02", "open": 9950, "high": 10000, "low": 9800,
         "close": 9850, "volume": 500000, "ma5": 9950, "qty": 100, "avg": 10000,
         "cash": 9_000_000, "equity": 985_000, "total": 9_985_000,
         "seed": 10_000_000, "t_val": 10, "is_reverse": True, "rev_day": 1},
        {"date": "2025-03-03", "open": 9850, "high": 9900, "low": 9700,
         "close": 9750, "volume": 500000, "ma5": 9900, "qty": 100, "avg": 10000,
         "cash": 9_000_000, "equity": 975_000, "total": 9_975_000,
         "seed": 10_000_000, "t_val": 10, "is_reverse": False, "rev_day": 0},
    ]
    out = str(tmp_path / "dashboard.html")
    write_dashboard([], snaps, out, ticker="418660",
                    start=datetime.date(2025, 3, 1),
                    end=datetime.date(2025, 3, 3),
                    seed=10_000_000, split=40, target_pct=7.0, compound_rate=70)
    content = open(out, encoding="utf-8").read()
    assert "rgba(196, 42, 28" in content  # 리버스 밴드 색상
