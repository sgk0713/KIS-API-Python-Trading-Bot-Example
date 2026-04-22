"""pick_target_trade_date 헬퍼 단위 테스트.

호출 시각이 장 마감 전이면 전 거래일, 마감 후면 당일 거래일을 반환.
오늘이 비거래일(주말/휴장)이면 schedule 마지막 = 마지막 거래일을 그대로 사용.
"""
import datetime
import pandas as pd
import pytz

from market_context import pick_target_trade_date


KST = pytz.timezone('Asia/Seoul')


def _sched(*date_strs):
    """dates 리스트로 pandas schedule-like 객체 생성."""
    return pd.DataFrame(index=pd.DatetimeIndex([pd.Timestamp(d) for d in date_strs]))


def test_trading_day_before_close_returns_prev_trading_day():
    """오늘(거래일) 09:30 KST 호출 → 전 거래일 선택."""
    sched = _sched("2026-04-21", "2026-04-22", "2026-04-23")
    now_market = datetime.datetime(2026, 4, 23, 9, 30, tzinfo=KST)
    close_t = datetime.time(15, 30)
    assert pick_target_trade_date(sched, now_market, close_t).date() == datetime.date(2026, 4, 22)


def test_trading_day_after_close_returns_today():
    """오늘(거래일) 16:00 KST 호출 → 오늘 선택."""
    sched = _sched("2026-04-21", "2026-04-22", "2026-04-23")
    now_market = datetime.datetime(2026, 4, 23, 16, 0, tzinfo=KST)
    close_t = datetime.time(15, 30)
    assert pick_target_trade_date(sched, now_market, close_t).date() == datetime.date(2026, 4, 23)


def test_weekend_falls_back_to_last_trading_day():
    """토요일에 호출 → schedule 마지막(=금요일) 그대로."""
    sched = _sched("2026-04-22", "2026-04-23", "2026-04-24")  # …~금
    now_market = datetime.datetime(2026, 4, 25, 9, 30, tzinfo=KST)  # 토
    close_t = datetime.time(15, 30)
    # 토요일은 schedule 에 없음 → index[-1] = 금요일
    assert pick_target_trade_date(sched, now_market, close_t).date() == datetime.date(2026, 4, 24)


def test_exact_close_time_is_treated_as_closed():
    """정확히 15:30:00 KST 은 '마감됨' 쪽으로 분류 → 오늘."""
    sched = _sched("2026-04-22", "2026-04-23")
    now_market = datetime.datetime(2026, 4, 23, 15, 30, 0, tzinfo=KST)
    close_t = datetime.time(15, 30)
    assert pick_target_trade_date(sched, now_market, close_t).date() == datetime.date(2026, 4, 23)


def test_single_entry_before_close_falls_back_to_that_entry():
    """거래일 1개뿐 + 마감 전 → 전 거래일 없음 → 그 1개 반환."""
    sched = _sched("2026-04-23")
    now_market = datetime.datetime(2026, 4, 23, 9, 30, tzinfo=KST)
    close_t = datetime.time(15, 30)
    assert pick_target_trade_date(sched, now_market, close_t).date() == datetime.date(2026, 4, 23)


def test_empty_schedule_returns_none():
    sched = _sched()
    now_market = datetime.datetime(2026, 4, 23, 9, 30, tzinfo=KST)
    close_t = datetime.time(15, 30)
    assert pick_target_trade_date(sched, now_market, close_t) is None


def test_us_after_close_behavior_unchanged():
    """US: KST 08:30 = EST 18:30 같은 EST 거래일 저녁. 마감(16:00) 후 → 오늘."""
    est = pytz.timezone('US/Eastern')
    sched = _sched("2026-04-21", "2026-04-22")
    # EST 18:30 on 2026-04-22 (장마감 후 같은 날)
    now_market = datetime.datetime(2026, 4, 22, 18, 30, tzinfo=est)
    close_t = datetime.time(16, 0)
    assert pick_target_trade_date(sched, now_market, close_t).date() == datetime.date(2026, 4, 22)
