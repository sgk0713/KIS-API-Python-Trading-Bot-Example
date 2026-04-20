import datetime
import json
import os
import pytest
from backtest.sandbox_config import BacktestConfig
from backtest.engine import BacktestEngine


@pytest.fixture
def tiny_ohlcv():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "ohlcv_tiny.json")
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def fresh_engine(tmp_path, tiny_ohlcv):
    cfg = BacktestConfig(
        sandbox_dir=str(tmp_path),
        ticker="418660",
        seed=10_000_000,
        split=40,
        target_pct=7.0,
        compound_rate=70,
    )
    return BacktestEngine(
        cfg=cfg,
        ticker="418660",
        ohlcv=tiny_ohlcv,
        reverse_exit_threshold=-10.0,
    )


def test_day1_new_start_places_loc_buy(fresh_engine):
    """2025-02-18 은 0주 보유 → '🆕새출발' LOC BUY 발행."""
    events = fresh_engine.run_day(datetime.date(2025, 2, 18))
    order_events = [e for e in events if e["kind"] == "order_placed"]
    assert len(order_events) >= 1
    new_start = [e for e in order_events if "🆕" in e["order"]["desc"]]
    assert len(new_start) == 1
    assert new_start[0]["order"]["side"] == "BUY"
    assert new_start[0]["order"]["type"] == "LOC"


def test_new_start_loc_fills_at_close(fresh_engine):
    """🆕새출발 LOC BUY 는 Open×1.15 쯤 가격이라 Close 이하 → 체결."""
    fresh_engine.run_day(datetime.date(2025, 2, 18))
    fills = [e for e in fresh_engine.events if e["kind"] == "order_filled"]
    assert len(fills) >= 1
    new_start_fills = [f for f in fills if "🆕" in f["order"]["desc"]]
    assert len(new_start_fills) == 1


def test_day2_after_position_has_sell_orders(fresh_engine):
    """첫날 체결 후 2025-02-19 09:05 주문에 목표매도(LIMIT) 가 있어야."""
    fresh_engine.run_day(datetime.date(2025, 2, 18))
    fresh_engine.run_day(datetime.date(2025, 2, 19))

    day2_orders = [
        e for e in fresh_engine.events
        if e["kind"] == "order_placed" and e["day"] == datetime.date(2025, 2, 19)
    ]
    sell_orders = [e for e in day2_orders if e["order"]["side"] == "SELL"]
    assert len(sell_orders) >= 1


def test_fill_updates_holdings(fresh_engine):
    """체결 후 calculate_holdings 결과가 갱신됐는지."""
    fresh_engine.run_day(datetime.date(2025, 2, 18))
    qty, avg, _, _ = fresh_engine.cfg.calculate_holdings("418660")
    assert qty > 0
    assert avg > 0
