import os
import json
import tempfile
import datetime
import pytest
from backtest.sandbox_config import BacktestConfig


@pytest.fixture
def sandbox(tmp_path):
    """각 테스트용 격리된 샌드박스 디렉토리."""
    return str(tmp_path)


def test_files_all_point_to_sandbox(sandbox):
    cfg = BacktestConfig(
        sandbox_dir=sandbox,
        ticker="418660",
        seed=10_000_000,
        split=40,
        target_pct=7.0,
        compound_rate=70,
    )
    for key, path in cfg.FILES.items():
        assert path.startswith(sandbox), f"{key} 경로 {path} 가 샌드박스 밖"


def test_ledger_writes_go_to_sandbox(sandbox):
    cfg = BacktestConfig(
        sandbox_dir=sandbox,
        ticker="418660",
        seed=10_000_000,
        split=40,
        target_pct=7.0,
        compound_rate=70,
    )
    cfg._save_json(cfg.FILES["LEDGER"], [{"test": "row"}])
    expected = os.path.join(sandbox, "ledger.json")
    assert os.path.exists(expected)
    with open(expected) as f:
        assert json.load(f) == [{"test": "row"}]


def test_seed_split_target_compound_come_from_sandbox_params(sandbox):
    cfg = BacktestConfig(
        sandbox_dir=sandbox,
        ticker="418660",
        seed=10_000_000,
        split=40,
        target_pct=7.0,
        compound_rate=70,
    )
    assert cfg.get_seed("418660") == 10_000_000
    assert cfg.get_split_count("418660") == 40
    assert cfg.get_target_profit("418660") == 7.0
    assert cfg.get_compound_rate("418660") == 70


def test_seed_updates_after_graduation(sandbox):
    cfg = BacktestConfig(
        sandbox_dir=sandbox,
        ticker="418660",
        seed=10_000_000,
        split=40,
        target_pct=7.0,
        compound_rate=70,
    )
    cfg.set_seed("418660", 10_500_000)
    assert cfg.get_seed("418660") == 10_500_000


def test_set_lock_uses_sim_date(sandbox):
    cfg = BacktestConfig(
        sandbox_dir=sandbox, ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    cfg._sim_date = datetime.date(2025, 3, 14)
    cfg.set_lock("418660", "REG")
    assert cfg.check_lock("418660", "REG") is True

    cfg._sim_date = datetime.date(2025, 3, 15)
    assert cfg.check_lock("418660", "REG") is False  # 다음날은 락 없음


def test_set_reverse_state_uses_sim_date(sandbox):
    cfg = BacktestConfig(
        sandbox_dir=sandbox, ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    cfg._sim_date = datetime.date(2025, 5, 1)
    cfg.set_reverse_state("418660", is_active=True, day_count=1, exit_target=-20.0)
    state = cfg.get_reverse_state("418660")
    assert state["is_active"] is True
    assert state["day_count"] == 1
    assert state["last_update_date"] == "2025-05-01"
