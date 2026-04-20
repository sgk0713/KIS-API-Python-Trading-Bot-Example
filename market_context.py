# ==========================================================
# [market_context.py]
# ----------------------------------------------------------
# BROKER 환경변수에 따른 시장 컨텍스트(타임존/캘린더/통화) 중앙화.
#   BROKER=KIS     → US 시장 (NYSE, US/Eastern, USD)   - 기본값, 기존 동작 보존
#   BROKER=KIWOOM  → KR 시장 (XKRX, Asia/Seoul, KRW)
#
# 사용 예:
#   from market_context import now, today_str, format_money, market_close_time, is_kr
# ==========================================================

import os
import datetime
import pytz
import pandas_market_calendars as mcal


def _broker_choice():
    return os.getenv('BROKER', 'KIS').upper()


def is_kr():
    return _broker_choice() == 'KIWOOM'


def is_us():
    return not is_kr()


# ==========================================================
# Timezone
# ==========================================================
_TZ_KR = pytz.timezone('Asia/Seoul')
_TZ_US = pytz.timezone('US/Eastern')


def get_tz():
    """시장의 네이티브 타임존 객체."""
    return _TZ_KR if is_kr() else _TZ_US


def now():
    """시장 타임존 기준 현재 datetime (aware)."""
    return datetime.datetime.now(get_tz())


def today_str(fmt='%Y-%m-%d'):
    """시장 타임존 기준 오늘 날짜 문자열."""
    return now().strftime(fmt)


# ==========================================================
# Calendar
# ==========================================================
_CAL_CACHE = {}


def get_calendar():
    """시장 캘린더 객체 (KR: XKRX, US: NYSE). 캐싱."""
    key = 'XKRX' if is_kr() else 'NYSE'
    if key not in _CAL_CACHE:
        _CAL_CACHE[key] = mcal.get_calendar(key)
    return _CAL_CACHE[key]


def is_trading_day(date=None):
    """date가 시장 개장일인지. date 미지정 시 오늘 (시장 타임존 기준)."""
    if date is None:
        date = now().date()
    try:
        cal = get_calendar()
        schedule = cal.schedule(start_date=date, end_date=date)
        return not schedule.empty
    except Exception:
        return date.weekday() < 5


# ==========================================================
# Market hours (시장 타임존 기준)
# ==========================================================
def market_open_time():
    """정규장 개장 시각 (KR: 09:00, US: 09:30)."""
    return datetime.time(9, 0) if is_kr() else datetime.time(9, 30)


def market_close_time():
    """정규장 종료 시각 (KR: 15:30, US: 16:00)."""
    return datetime.time(15, 30) if is_kr() else datetime.time(16, 0)


def closing_limit_delay_time():
    """LOC 대체 지연 LIMIT 발송 시각.
    KR: 15:25 (동시호가 진입 직후)
    US: 15:55 (마감 5분 전)"""
    return datetime.time(15, 25) if is_kr() else datetime.time(15, 55)


def after_market_time():
    """애프터마켓 로터리 트리거 시각. KR은 애프터마켓 없음 → None."""
    return None if is_kr() else datetime.time(16, 5)


# ==========================================================
# Currency
# ==========================================================
def currency_code():
    return 'KRW' if is_kr() else 'USD'


def currency_symbol():
    return '₩' if is_kr() else '$'


def format_money(amount, decimals=None):
    """금액 포맷팅.
    KR: "10,000,000원" (정수)
    US: "$9,000.00"   (기본 소수 2자리, decimals로 제어 가능)"""
    try:
        amt = float(amount)
    except Exception:
        amt = 0.0
    if is_kr():
        return f"{int(amt):,}원"
    if decimals is None:
        decimals = 2
    return f"${amt:,.{decimals}f}"
