"""
키움 ka10081 주식일봉차트조회 래퍼 + 로컬 캐시.

한 번 호출로 최대 600봉을 받아 JSON 캐시에 저장. 재실행 시 캐시 활용.
필드명은 실 API 프로빙으로 확정 (2026-04-21, 418660 기준).
"""
import json
import os
from broker_kiwoom import _API_IDS, _CHART_PATH


_ARRAY_KEY = "stk_dt_pole_chart_qry"
_FIELD_DATE = "dt"
_FIELD_OPEN = "open_pric"
_FIELD_HIGH = "high_pric"
_FIELD_LOW = "low_pric"
_FIELD_CLOSE = "cur_prc"
_FIELD_VOLUME = "trde_qty"


def _parse_signed(raw):
    """키움 가격 필드 '+12000' / '-11800' / '12000' → 절대값 float."""
    if raw is None or raw == "":
        return 0.0
    return float(str(raw).lstrip('+-'))


def _to_iso_date(yyyymmdd):
    """'20260420' → '2026-04-20'."""
    s = str(yyyymmdd)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def load_cached_ohlcv(cache_path):
    """캐시 파일을 읽어 dict 반환, 없으면 None."""
    if not os.path.exists(cache_path):
        return None
    with open(cache_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def fetch_daily_ohlcv(broker, ticker, base_date, cache_path):
    """
    ka10081 한 번 호출 — 최대 600봉. base_date (YYYYMMDD) 부터 과거로.

    캐시가 있으면 그걸 반환 (네트워크 생략).

    Returns:
        dict: {"YYYY-MM-DD": {"open", "high", "low", "close", "volume"}}
    """
    cached = load_cached_ohlcv(cache_path)
    if cached is not None:
        return cached

    body = {"stk_cd": str(ticker), "base_dt": str(base_date), "upd_stkpc_tp": "1"}
    res = broker._call_api(_API_IDS["DAILY_CANDLE"], _CHART_PATH, "POST", body=body)

    if res.get("return_code") != 0:
        raise RuntimeError(f"ka10081 실패: {res.get('return_msg', res)}")

    bars = res.get(_ARRAY_KEY, [])
    if not bars:
        raise RuntimeError(f"ka10081 응답에 {_ARRAY_KEY} 비어있음: {res}")

    result = {}
    for bar in bars:
        iso = _to_iso_date(bar[_FIELD_DATE])
        result[iso] = {
            "open":   _parse_signed(bar[_FIELD_OPEN]),
            "high":   _parse_signed(bar[_FIELD_HIGH]),
            "low":    _parse_signed(bar[_FIELD_LOW]),
            "close":  _parse_signed(bar[_FIELD_CLOSE]),
            "volume": int(_parse_signed(bar[_FIELD_VOLUME])),
        }

    parent = os.path.dirname(cache_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result
