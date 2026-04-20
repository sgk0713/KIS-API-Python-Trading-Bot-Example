from backtest.fill_model import check_limit_fill, check_loc_fill, check_moc_fill


def _bar(o, h, l, c, v=100000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def test_limit_buy_fills_at_open_when_gap_down():
    # P=1000, Open=950 → Low 950 ≤ P → 갭다운 Open 체결 (price improvement)
    bar = _bar(o=950, h=1020, l=940, c=1000)
    filled, fill_price = check_limit_fill(side="BUY", price=1000.0, bar=bar)
    assert filled is True
    assert fill_price == 950.0


def test_limit_buy_fills_at_limit_when_low_touches():
    # P=1000, Open=1050, Low=990 → Low ≤ P, Open > P → P 체결
    bar = _bar(o=1050, h=1080, l=990, c=1020)
    filled, fill_price = check_limit_fill(side="BUY", price=1000.0, bar=bar)
    assert filled is True
    assert fill_price == 1000.0


def test_limit_buy_no_fill_when_low_above():
    # P=1000, Low=1020 > P → 미체결
    bar = _bar(o=1030, h=1080, l=1020, c=1050)
    filled, fill_price = check_limit_fill(side="BUY", price=1000.0, bar=bar)
    assert filled is False
    assert fill_price == 0.0


def test_limit_sell_fills_at_open_when_gap_up():
    # P=1000, Open=1050 → High=1080 ≥ P, Open > P → Open 체결
    bar = _bar(o=1050, h=1080, l=1020, c=1060)
    filled, fill_price = check_limit_fill(side="SELL", price=1000.0, bar=bar)
    assert filled is True
    assert fill_price == 1050.0


def test_limit_sell_fills_at_limit_when_high_touches():
    # P=1000, Open=950, High=1010 → High ≥ P, Open < P → P 체결
    bar = _bar(o=950, h=1010, l=940, c=980)
    filled, fill_price = check_limit_fill(side="SELL", price=1000.0, bar=bar)
    assert filled is True
    assert fill_price == 1000.0


def test_limit_sell_no_fill_when_high_below():
    # P=1000, High=980 < P → 미체결
    bar = _bar(o=950, h=980, l=940, c=960)
    filled, fill_price = check_limit_fill(side="SELL", price=1000.0, bar=bar)
    assert filled is False
    assert fill_price == 0.0


def test_loc_buy_fills_when_close_at_or_below():
    # P=1000, Close=990 ≤ P → 체결 at P
    bar = _bar(o=1010, h=1020, l=980, c=990)
    filled, fill_price = check_loc_fill(side="BUY", price=1000.0, bar=bar)
    assert filled is True
    assert fill_price == 1000.0


def test_loc_buy_no_fill_when_close_above():
    bar = _bar(o=1010, h=1030, l=1000, c=1020)
    filled, fill_price = check_loc_fill(side="BUY", price=1000.0, bar=bar)
    assert filled is False
    assert fill_price == 0.0


def test_loc_sell_fills_when_close_at_or_above():
    bar = _bar(o=990, h=1020, l=980, c=1010)
    filled, fill_price = check_loc_fill(side="SELL", price=1000.0, bar=bar)
    assert filled is True
    assert fill_price == 1000.0


def test_loc_sell_no_fill_when_close_below():
    bar = _bar(o=990, h=1010, l=970, c=980)
    filled, fill_price = check_loc_fill(side="SELL", price=1000.0, bar=bar)
    assert filled is False
    assert fill_price == 0.0


def test_moc_buy_always_fills_at_close():
    bar = _bar(o=1010, h=1050, l=990, c=1025)
    filled, fill_price = check_moc_fill(side="BUY", bar=bar)
    assert filled is True
    assert fill_price == 1025.0


def test_moc_sell_always_fills_at_close():
    bar = _bar(o=1010, h=1050, l=990, c=1025)
    filled, fill_price = check_moc_fill(side="SELL", bar=bar)
    assert filled is True
    assert fill_price == 1025.0
