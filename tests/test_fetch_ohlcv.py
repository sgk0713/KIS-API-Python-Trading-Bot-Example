import json
import os
from unittest.mock import MagicMock
import pytest
from backtest.fetch_ohlcv import fetch_daily_ohlcv, load_cached_ohlcv


def _mock_kiwoom_response():
    """ka10081 응답 형태 모사 — 실 프로빙으로 확정된 필드명."""
    return {
        "return_code": 0,
        "return_msg": "정상적으로 처리되었습니다",
        "stk_cd": "418660",
        "stk_dt_pole_chart_qry": [
            {"dt": "20260420", "open_pric": "38190", "high_pric": "38245",
             "low_pric": "37870", "cur_prc": "38175", "trde_qty": "204187"},
            {"dt": "20260417", "open_pric": "37800", "high_pric": "38000",
             "low_pric": "37750", "cur_prc": "37905", "trde_qty": "180000"},
        ],
    }


def test_fetch_parses_bars_into_dict(tmp_path):
    cache_path = str(tmp_path / "ohlcv_418660.json")
    mock_broker = MagicMock()
    mock_broker._call_api.return_value = _mock_kiwoom_response()

    result = fetch_daily_ohlcv(
        broker=mock_broker, ticker="418660",
        base_date="20260420", cache_path=cache_path,
    )

    assert "2026-04-20" in result
    assert result["2026-04-20"]["open"] == 38190.0
    assert result["2026-04-20"]["high"] == 38245.0
    assert result["2026-04-20"]["low"] == 37870.0
    assert result["2026-04-20"]["close"] == 38175.0
    assert result["2026-04-20"]["volume"] == 204187


def test_fetch_writes_cache(tmp_path):
    cache_path = str(tmp_path / "ohlcv_418660.json")
    mock_broker = MagicMock()
    mock_broker._call_api.return_value = _mock_kiwoom_response()

    fetch_daily_ohlcv(
        broker=mock_broker, ticker="418660",
        base_date="20260420", cache_path=cache_path,
    )

    assert os.path.exists(cache_path)
    with open(cache_path) as f:
        cached = json.load(f)
    assert "2026-04-20" in cached


def test_load_cached_ohlcv_returns_none_if_missing(tmp_path):
    result = load_cached_ohlcv(str(tmp_path / "missing.json"))
    assert result is None


def test_fetch_uses_cache_when_present(tmp_path):
    cache_path = str(tmp_path / "ohlcv_418660.json")
    existing = {"2026-01-01": {"open": 10000.0, "high": 10100.0,
                                "low": 9900.0, "close": 10050.0, "volume": 100000}}
    with open(cache_path, 'w') as f:
        json.dump(existing, f)

    mock_broker = MagicMock()
    result = fetch_daily_ohlcv(
        broker=mock_broker, ticker="418660",
        base_date="20260420", cache_path=cache_path,
    )

    mock_broker._call_api.assert_not_called()
    assert result == existing


def test_fetch_raises_on_api_error(tmp_path):
    cache_path = str(tmp_path / "ohlcv_418660.json")
    mock_broker = MagicMock()
    mock_broker._call_api.return_value = {
        "return_code": 9001, "return_msg": "TR 호출 실패",
    }

    with pytest.raises(RuntimeError, match="ka10081"):
        fetch_daily_ohlcv(
            broker=mock_broker, ticker="418660",
            base_date="20260420", cache_path=cache_path,
        )
