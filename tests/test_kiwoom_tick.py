"""KRX ETF 호가단위(5원) 특례 반영 테스트.

KRX 일반주 호가단위 표와 달리 ETF/ETN은 가격대 무관 5원 고정.
- 418660 (TIGER 미국나스닥100레버리지) 같은 ETF에서 38605원이 유효 호가.
- 일반주 호가표(38605 → 50원 tick)로 반올림하면 조용한 슬리피지 발생.

자동판별: ka10001 응답의 stk_nm 에 "ETF"/"ETN" 포함 여부.
오버라이드: env KIWOOM_ETF_TICKERS (CSV, 기본 "418660").
"""
import os
import pytest
from unittest.mock import patch

from broker_kiwoom import KiwoomBroker


@pytest.fixture
def broker():
    """네트워크 없이 bare 인스턴스 생성 (__init__ 우회)."""
    b = KiwoomBroker.__new__(KiwoomBroker)
    # 캐시/토큰 등 최소 속성만 초기화
    b.token = "FAKE_TOKEN"
    b.base_url = "https://api.kiwoom.com"
    b.app_key = "K"
    b.app_secret = "S"
    return b


@pytest.fixture
def clean_env(monkeypatch):
    """KIWOOM_ETF_TICKERS env 격리 — 각 테스트가 명시적으로 세팅."""
    monkeypatch.delenv("KIWOOM_ETF_TICKERS", raising=False)


# ----------------------------------------------------------
# _round_to_krw_tick: ETF 5원 / 일반주 표
# ----------------------------------------------------------

def test_etf_exact_5won_price_untouched_both_sides(broker, clean_env, monkeypatch):
    """38605 (5의 배수) 는 BUY/SELL 모두 그대로 유지."""
    monkeypatch.setenv("KIWOOM_ETF_TICKERS", "418660")
    assert broker._round_to_krw_tick(38605, side="BUY", ticker="418660") == 38605
    assert broker._round_to_krw_tick(38605, side="SELL", ticker="418660") == 38605


def test_etf_mid_tick_floors_buy_ceils_sell(broker, clean_env, monkeypatch):
    """38607 → BUY floor 38605, SELL ceil 38610."""
    monkeypatch.setenv("KIWOOM_ETF_TICKERS", "418660")
    assert broker._round_to_krw_tick(38607, side="BUY", ticker="418660") == 38605
    assert broker._round_to_krw_tick(38607, side="SELL", ticker="418660") == 38610


def test_non_etf_keeps_regular_stock_table(broker, clean_env):
    """일반주 38605 → 구간 20000~50000 의 50원 tick 기존 동작 유지."""
    with patch.object(broker, "_kiwoom_stock_basic", return_value={"stk_nm": "삼성전자"}):
        assert broker._round_to_krw_tick(38605, side="BUY", ticker="005930") == 38600
        assert broker._round_to_krw_tick(38605, side="SELL", ticker="005930") == 38650


def test_no_ticker_falls_back_to_regular_table(broker, clean_env):
    """ticker 미지정 시 기존 동작(일반주 표) 유지 — 하위호환."""
    assert broker._round_to_krw_tick(38605, side="BUY") == 38600
    assert broker._round_to_krw_tick(38605, side="SELL") == 38650


def test_zero_or_negative_price_returns_zero(broker, clean_env):
    assert broker._round_to_krw_tick(0, ticker="418660") == 0
    assert broker._round_to_krw_tick(-100, ticker="418660") == 0
    assert broker._round_to_krw_tick(None, ticker="418660") == 0


# ----------------------------------------------------------
# _is_etf: env 오버라이드 + ka10001 자동판별 + 캐시
# ----------------------------------------------------------

def test_is_etf_via_env_override_even_if_api_says_otherwise(broker, clean_env, monkeypatch):
    """env 리스트에 있으면 API 무시하고 True."""
    monkeypatch.setenv("KIWOOM_ETF_TICKERS", "418660, 091160")
    with patch.object(broker, "_kiwoom_stock_basic", return_value={"stk_nm": "삼성전자"}):
        assert broker._is_etf("418660") is True
        assert broker._is_etf("091160") is True


def test_is_etf_autodetect_via_stk_nm_contains_etf(broker, clean_env):
    """ka10001 응답의 stk_nm 에 'ETF' 포함 시 True."""
    with patch.object(broker, "_kiwoom_stock_basic",
                      return_value={"stk_nm": "KODEX 코스닥150 ETF"}):
        assert broker._is_etf("229200") is True


def test_is_etf_autodetect_via_stk_nm_contains_etn(broker, clean_env):
    """ETN 도 동일하게 5원 tick → True."""
    with patch.object(broker, "_kiwoom_stock_basic",
                      return_value={"stk_nm": "신한 WTI원유선물 ETN"}):
        assert broker._is_etf("500001") is True


def test_is_etf_false_for_regular_stock(broker, clean_env):
    with patch.object(broker, "_kiwoom_stock_basic",
                      return_value={"stk_nm": "삼성전자"}):
        assert broker._is_etf("005930") is False


def test_is_etf_api_failure_defaults_to_false(broker, clean_env):
    """API 실패 시 일반주 표로 안전 폴백."""
    with patch.object(broker, "_kiwoom_stock_basic", return_value=None):
        assert broker._is_etf("999999") is False


def test_is_etf_caches_result(broker, clean_env):
    """두 번째 호출에서 ka10001 재호출 없이 캐시 히트."""
    with patch.object(broker, "_kiwoom_stock_basic",
                      return_value={"stk_nm": "TIGER 200 ETF"}) as m:
        broker._is_etf("102110")
        broker._is_etf("102110")
        assert m.call_count == 1


def test_default_env_includes_418660(broker, clean_env):
    """env 미설정 시 기본값으로 418660 은 ETF 로 인식."""
    # env 없음 (clean_env 가 delenv 처리)
    with patch.object(broker, "_kiwoom_stock_basic", return_value=None):
        assert broker._is_etf("418660") is True
