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
    expected = os.path.join(sandbox, "manual_ledger.json")
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


def test_increment_reverse_day_uses_sim_date(sandbox):
    """increment_reverse_day 가 _sim_date 를 사용하는지 검증 (실시간 아님)."""
    cfg = BacktestConfig(
        sandbox_dir=sandbox, ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    cfg._sim_date = datetime.date(2025, 5, 1)
    cfg.set_reverse_state("418660", is_active=True, day_count=1, exit_target=-5.0,
                          last_update_date="2025-04-30")

    # 2025-05-01: 전날과 다른 날짜 → increment 되어야 함
    result = cfg.increment_reverse_day("418660")
    assert result is True
    state = cfg.get_reverse_state("418660")
    assert state["day_count"] == 2
    assert state["last_update_date"] == "2025-05-01"

    # 같은 날 재호출 → 이미 오늘로 갱신됐으므로 False
    result2 = cfg.increment_reverse_day("418660")
    assert result2 is False
    assert cfg.get_reverse_state("418660")["day_count"] == 2


def test_get_sniper_multiplier_returns_one(sandbox):
    """get_sniper_multiplier 는 DEFAULT_SNIPER_MULTIPLIER 없이 항상 1.0 반환."""
    cfg = BacktestConfig(
        sandbox_dir=sandbox, ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    assert cfg.get_sniper_multiplier("418660") == 1.0
    # 부모 __init__ 미호출로 속성 없어도 AttributeError 없이 동작해야 함
    assert not hasattr(cfg, "DEFAULT_SNIPER_MULTIPLIER")


def test_production_files_keys_match_sandbox():
    """
    방어막: config.py ConfigManager.__init__ 이 새 FILES 키를 추가하면 sandbox 가
    자동으로 동기화되지 않아 런타임 KeyError. 주기적으로 둘을 비교해 드리프트 감지.
    """
    from config import ConfigManager
    prod = ConfigManager()
    sandbox_keys = set(BacktestConfig._PRODUCTION_FILES.keys())
    prod_keys = set(prod.FILES.keys())
    assert sandbox_keys == prod_keys, (
        f"Drift detected. Only in sandbox: {sandbox_keys - prod_keys}. "
        f"Only in prod: {prod_keys - sandbox_keys}"
    )


def test_set_lock_without_sim_date_raises(sandbox):
    """_sim_date 가 None 인 상태에서 set_lock 호출 → RuntimeError."""
    cfg = BacktestConfig(
        sandbox_dir=sandbox, ticker="418660",
        seed=10_000_000, split=40, target_pct=7.0, compound_rate=70,
    )
    # _sim_date 가 None 인 상태에서 set_lock 호출 → RuntimeError
    with pytest.raises(RuntimeError):
        cfg.set_lock("418660", "REG")
