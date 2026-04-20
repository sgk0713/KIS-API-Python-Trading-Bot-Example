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


# ==========================================================
# Task 6: 17:00 EOD — 리버스 진입/탈출/졸업
# ==========================================================
@pytest.fixture
def reverse_cycle_ohlcv():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "ohlcv_reverse_cycle.json")
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def graduation_ohlcv():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "ohlcv_graduation.json")
    with open(path) as f:
        return json.load(f)


def _run_all(engine, ohlcv, start_date):
    dates = sorted([datetime.date.fromisoformat(k) for k in ohlcv.keys()])
    for d in [x for x in dates if x >= start_date]:
        engine.run_day(d)


def test_reverse_exit_mechanism_when_recovered(tmp_path, tiny_ohlcv):
    """
    메커니즘 테스트: 리버스 상태로 프리시드 + 가격이 avg 대비 -10% 이상 회복하면 탈출.
    합성 fixture 의 가격 다이내믹이 리버스 진입 조건을 불안정하게 만들 수 있어,
    탈출 로직만 독립 검증.
    """
    cfg = BacktestConfig(
        sandbox_dir=str(tmp_path), ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    # 가상 보유: 100주 @ 11000원 (tiny_ohlcv 의 close 10000~10600 범위 → 수익률 -5% 정도)
    cfg._sim_date = datetime.date(2025, 2, 17)
    cfg.overwrite_incremental_ledger("418660", [], [{
        "date": "2025-02-14", "side": "BUY", "price": 11000.0, "qty": 100,
        "avg_price": 11000.0, "exec_id": "SEED", "desc": "테스트시드", "is_reverse": True,
    }])
    cfg.set_reverse_state("418660", is_active=True, day_count=3, exit_target=-20.0)

    engine = BacktestEngine(
        cfg=cfg, ticker="418660",
        ohlcv=tiny_ohlcv, reverse_exit_threshold=-10.0,
    )
    # 2025-02-21 close=10550, avg=11000 → 수익률 = -4.09% ≥ -10% → 탈출해야 함
    engine.run_day(datetime.date(2025, 2, 21))

    exits = [e for e in engine.events if e["kind"] == "reverse_exited"]
    assert len(exits) == 1, f"탈출 이벤트 정확히 1건 기대 — 실제 {len(exits)}건"
    assert cfg.get_reverse_state("418660").get("is_active") is False


def test_reverse_exit_skipped_when_return_below_threshold(tmp_path):
    """수익률이 -10% 미만이면 탈출 안 하고 day 증가."""
    ohlcv = {
        "2025-02-17": {"open": 8000, "high": 8050, "low": 7900, "close": 7950, "volume": 100000},
        "2025-02-18": {"open": 7950, "high": 8000, "low": 7800, "close": 7850, "volume": 100000},
    }
    cfg = BacktestConfig(
        sandbox_dir=str(tmp_path), ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    cfg._sim_date = datetime.date(2025, 2, 17)
    cfg.overwrite_incremental_ledger("418660", [], [{
        "date": "2025-02-14", "side": "BUY", "price": 10000.0, "qty": 100,
        "avg_price": 10000.0, "exec_id": "SEED", "desc": "테스트시드", "is_reverse": True,
    }])
    cfg.set_reverse_state("418660", is_active=True, day_count=1, exit_target=-20.0,
                          last_update_date="2025-02-17")

    engine = BacktestEngine(
        cfg=cfg, ticker="418660",
        ohlcv=ohlcv, reverse_exit_threshold=-10.0,
    )
    # 2025-02-18 close=7850, avg=10000 → 수익률 -21.5% < -10% → day++
    engine.run_day(datetime.date(2025, 2, 18))

    exits = [e for e in engine.events if e["kind"] == "reverse_exited"]
    day_incs = [e for e in engine.events if e["kind"] == "reverse_day_incremented"]
    assert len(exits) == 0
    assert len(day_incs) == 1
    assert cfg.get_reverse_state("418660").get("day_count") == 2


def test_daily_snapshot_shape(fresh_engine):
    """daily_snapshot 은 OHLC + 잔고 + reverse 상태 전부 포함."""
    fresh_engine.run_day(datetime.date(2025, 2, 18))
    snap = fresh_engine.daily_snapshot(datetime.date(2025, 2, 18))
    assert snap is not None
    expected_keys = {"date", "open", "high", "low", "close", "volume", "ma5",
                     "qty", "avg", "cash", "equity", "total", "seed",
                     "t_val", "is_reverse", "rev_day"}
    assert set(snap.keys()) == expected_keys
    assert snap["date"] == "2025-02-18"
    assert snap["total"] == round(snap["cash"] + snap["equity"], 2)


def test_capital_conservation_invariant(tmp_path, graduation_ohlcv):
    """매일 cash + equity ≥ 0, 체결로 인한 자본 유지 확인."""
    cfg = BacktestConfig(
        sandbox_dir=str(tmp_path), ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    engine = BacktestEngine(
        cfg=cfg, ticker="418660",
        ohlcv=graduation_ohlcv, reverse_exit_threshold=-10.0,
    )
    dates = sorted([datetime.date.fromisoformat(k) for k in graduation_ohlcv.keys()])
    for d in [x for x in dates if x >= datetime.date(2025, 2, 18)]:
        engine.run_day(d)
        snap = engine.daily_snapshot(d)
        assert snap["total"] >= 0, f"{d}: total 음수 {snap['total']}"
        assert snap["cash"] >= 0, f"{d}: cash 음수 {snap['cash']}"


def test_graduation_compounds_seed(tmp_path, graduation_ohlcv):
    cfg = BacktestConfig(
        sandbox_dir=str(tmp_path), ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    engine = BacktestEngine(
        cfg=cfg, ticker="418660",
        ohlcv=graduation_ohlcv, reverse_exit_threshold=-10.0,
    )
    _run_all(engine, graduation_ohlcv, datetime.date(2025, 2, 18))

    grads = [e for e in engine.events if e["kind"] == "graduated"]
    assert len(grads) >= 1, "졸업 이벤트 없음"
    first = grads[0]
    assert first["profit"] > 0
    assert first["added_seed"] > 0
    assert first["new_seed"] > first["old_seed"]
