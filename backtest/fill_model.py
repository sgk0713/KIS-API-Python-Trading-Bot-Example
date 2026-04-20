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
    LOC 주문 체결 판정.

    KRX 종가 동시호가(15:20-15:30)는 단일가 경매로 청산됨. 프로덕션은 15:25 에
    LIMIT 으로 변환해 보내는데, 이 LIMIT 은 동시호가에 참여해 '청산가=Close' 에
    체결됨. 즉 BUY LIMIT @ P 가 Close 위에 있어도 체결은 Close 에 일어남.

    BUY:  Close ≤ P 면 체결 at Close  (지정가보다 싼 단일가 청산 → 유리한 매수)
    SELL: Close ≥ P 면 체결 at Close  (지정가보다 비싼 단일가 청산 → 유리한 매도)
    """
    if side == "BUY":
        if bar["close"] <= price:
            return True, float(bar["close"])
        return False, 0.0
    if side == "SELL":
        if bar["close"] >= price:
            return True, float(bar["close"])
        return False, 0.0
    raise ValueError(f"Unknown side: {side}")


def check_moc_fill(side, bar):
    """MOC 주문은 15:25 에 MARKET 으로 전환, 종가 체결이 확정."""
    if side not in ("BUY", "SELL"):
        raise ValueError(f"Unknown side: {side}")
    return True, float(bar["close"])
