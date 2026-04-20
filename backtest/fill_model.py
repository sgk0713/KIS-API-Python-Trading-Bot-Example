"""
일봉 OHLCV 기반 주문 체결 판정 순수함수.

외부 상태에 의존하지 않고, 주문 스펙과 일봉 하나만으로 체결 여부·체결가를 반환.
규칙은 docs/superpowers/specs/2026-04-20-kiwoom-418660-backtest-design.md §6 참조.
"""


def check_limit_fill(side, price, bar):
    """
    LIMIT 주문 체결 판정.

    BUY:  Low ≤ P 면 체결. 체결가 = min(Open, P)   (갭다운이면 Open 으로 개선)
    SELL: High ≥ P 면 체결. 체결가 = max(Open, P)  (갭업이면 Open 으로 개선)

    Returns:
        (filled: bool, fill_price: float)  미체결이면 (False, 0.0)
    """
    if side == "BUY":
        if bar["low"] <= price:
            return True, float(min(bar["open"], price))
        return False, 0.0
    if side == "SELL":
        if bar["high"] >= price:
            return True, float(max(bar["open"], price))
        return False, 0.0
    raise ValueError(f"Unknown side: {side}")


def check_loc_fill(side, price, bar):
    """
    LOC 주문 체결 판정 (15:25 에 LIMIT 으로 변환돼 종가 경매까지 살아있다고 가정).

    BUY:  Close ≤ P 면 체결 at P   (종가가 지정가 이하 → 체결 가능)
    SELL: Close ≥ P 면 체결 at P

    체결가는 항상 지정가 P (보수적: 마지막 5분 구간의 High/Low 부재).
    """
    if side == "BUY":
        if bar["close"] <= price:
            return True, float(price)
        return False, 0.0
    if side == "SELL":
        if bar["close"] >= price:
            return True, float(price)
        return False, 0.0
    raise ValueError(f"Unknown side: {side}")


def check_moc_fill(side, bar):
    """MOC 주문은 15:25 에 MARKET 으로 전환, 종가 체결이 확정."""
    if side not in ("BUY", "SELL"):
        raise ValueError(f"Unknown side: {side}")
    return True, float(bar["close"])
