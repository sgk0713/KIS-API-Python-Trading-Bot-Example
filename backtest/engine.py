"""
백테스트 엔진 — 거래일마다 09:05 / 15:25 / 17:00 세 단계를 순서대로 실행.

이벤트는 events deque 에 축적. 리포터가 이후 소비.
"""
import datetime
from collections import deque
import market_context
from strategy_v14 import V14Strategy


def _merge_star_sell_to_target(orders):
    """scheduler_trade_kr._merge_star_sell_to_target 의 순수 복사 (import 회피용)."""
    star_sell_qty = 0
    filtered = []
    target_sell_idx = None
    for o in orders:
        side = o.get("side")
        desc = o.get("desc", "")
        if side == "SELL" and desc.startswith("🌟"):
            star_sell_qty += int(o.get("qty", 0))
            continue
        if side == "SELL" and desc.startswith("🎯"):
            target_sell_idx = len(filtered)
        filtered.append(o)
    if star_sell_qty > 0 and target_sell_idx is not None:
        filtered[target_sell_idx]["qty"] = int(filtered[target_sell_idx]["qty"]) + star_sell_qty
        filtered[target_sell_idx]["desc"] = (
            f"{filtered[target_sell_idx]['desc']}(+별값{star_sell_qty}통합)"
        )
    return filtered


class BacktestEngine:
    def __init__(self, cfg, ticker, ohlcv, reverse_exit_threshold=-10.0):
        self.cfg = cfg
        self.ticker = ticker
        self.ohlcv = ohlcv
        self.reverse_exit_threshold = reverse_exit_threshold
        self.strategy = V14Strategy(cfg)
        self.events = deque()
        self._pending_orders = []
        self._today_limit_orders = []

    def _iso(self, d):
        return d.strftime('%Y-%m-%d')

    def _bar(self, d):
        return self.ohlcv.get(self._iso(d))

    def _sorted_dates(self):
        return sorted(datetime.date.fromisoformat(k) for k in self.ohlcv.keys())

    def _prev_bar(self, d):
        prior = [x for x in self._sorted_dates() if x < d]
        return self._bar(prior[-1]) if prior else None

    def _ma5(self, d):
        """d 이전(미포함) 5 거래일 close 평균. 데이터 부족 시 가용분 평균."""
        prior_dates = [x for x in self._sorted_dates() if x < d][-5:]
        closes = [self._bar(x)["close"] for x in prior_dates]
        return sum(closes) / len(closes) if closes else 0.0

    def _current_cash(self):
        """현금 = seed - 총 BUY 금액 + 총 SELL 금액."""
        ledger = self.cfg.get_ledger()
        target = [r for r in ledger if r["ticker"] == self.ticker]
        cash = self.cfg.get_seed(self.ticker)
        for r in target:
            amt = r["qty"] * r["price"]
            if r["side"] == "BUY":
                cash -= amt
            elif r["side"] == "SELL":
                cash += amt
        return max(0.0, cash)

    def _phase_0905(self, d, bar):
        self.cfg._sim_date = d
        market_context.now = lambda d=d: datetime.datetime.combine(d, datetime.time(9, 5))
        market_context.is_trading_day = lambda _d: True

        qty, avg_price, _, _ = self.cfg.calculate_holdings(self.ticker)
        prev = self._prev_bar(d)
        prev_close = prev["close"] if prev else bar["open"]
        ma5 = self._ma5(d)
        available_cash = self._current_cash()

        plan = self.strategy.get_plan(
            ticker=self.ticker,
            current_price=bar["open"],
            avg_price=avg_price,
            qty=qty,
            prev_close=prev_close,
            ma_5day=ma5,
            market_type="REG",
            available_cash=available_cash,
        )

        # 리버스 진입 감지 — strategy_v14 가 plan.is_reverse 만 계산하고 cfg 는 갱신하지 않음.
        # 프로덕션은 텔레그램/스케줄러가 대신 set_reverse_state 를 호출 → 백테스트는 여기서.
        rev_state = self.cfg.get_reverse_state(self.ticker)
        if plan.get("is_reverse") and not rev_state.get("is_active"):
            curr_ret = ((bar["open"] - avg_price) / avg_price * 100.0) if avg_price > 0 else 0.0
            default_exit = -20.0
            exit_target = 0.0 if curr_ret >= default_exit else default_exit
            self.cfg.set_reverse_state(self.ticker, True, 1, exit_target)
            self.events.append({
                "day": d, "phase": "09:05", "kind": "reverse_entered",
                "curr_return": curr_ret, "exit_target": exit_target,
                "t_val": plan.get("t_val", 0.0),
            })

        orders = plan.get("core_orders", []) + plan.get("bonus_orders", [])
        orders = _merge_star_sell_to_target(orders)

        for o in orders:
            self.events.append({
                "day": d, "phase": "09:05", "kind": "order_placed",
                "order": dict(o), "plan_status": plan.get("process_status", ""),
                "t_val": plan.get("t_val", 0.0), "star_price": plan.get("star_price", 0.0),
            })

        self._pending_orders = [o for o in orders if o["type"] in ("LOC", "MOC")]
        self._today_limit_orders = [o for o in orders if o["type"] == "LIMIT"]

    def _phase_limit_intraday(self, d, bar):
        """LIMIT 주문 일중 판정. 우선순위: SELL → BUY."""
        from backtest.fill_model import check_limit_fill
        ordered = sorted(self._today_limit_orders,
                         key=lambda o: 0 if o["side"] == "SELL" else 1)
        for o in ordered:
            filled, price = check_limit_fill(o["side"], o["price"], bar)
            if filled:
                self._record_fill(d, "intraday", o, price)

    def _phase_1525(self, d, bar):
        """보류된 LOC/MOC 발송 판정. 우선순위: SELL → BUY."""
        from backtest.fill_model import check_loc_fill, check_moc_fill
        ordered = sorted(self._pending_orders,
                         key=lambda o: 0 if o["side"] == "SELL" else 1)
        for o in ordered:
            if o["type"] == "LOC":
                filled, price = check_loc_fill(o["side"], o["price"], bar)
            else:  # MOC
                filled, price = check_moc_fill(o["side"], bar)
            if filled:
                self._record_fill(d, "15:25", o, price)
            else:
                self.events.append({
                    "day": d, "phase": "15:25", "kind": "order_unfilled",
                    "order": dict(o), "close": bar["close"],
                })
        self._pending_orders = []

    def _record_fill(self, d, phase, order, fill_price):
        """체결을 장부에 기록하고 event 추가."""
        qty = int(order["qty"])
        side = order["side"]
        desc = order.get("desc", "")
        pre_qty, pre_avg, _, _ = self.cfg.calculate_holdings(self.ticker)

        if side == "BUY":
            new_total_qty = pre_qty + qty
            new_total_cost = pre_qty * pre_avg + qty * fill_price
            new_avg = new_total_cost / new_total_qty if new_total_qty > 0 else fill_price
            post_qty = new_total_qty
        else:  # SELL
            new_avg = pre_avg
            post_qty = pre_qty - qty

        rev_state = self.cfg.get_reverse_state(self.ticker)
        is_rev = rev_state.get("is_active", False)

        new_rec = {
            "date": self._iso(d),
            "side": side,
            "price": float(fill_price),
            "qty": qty,
            "avg_price": float(new_avg),
            "exec_id": f"BT_{self._iso(d)}_{phase}_{side}_{qty}_{desc}",
            "desc": desc,
            "is_reverse": is_rev,
        }

        ledger = self.cfg.get_ledger()
        target = [r for r in ledger if r["ticker"] == self.ticker]
        self.cfg.overwrite_incremental_ledger(self.ticker, target, [new_rec])

        self.events.append({
            "day": d, "phase": phase, "kind": "order_filled",
            "order": dict(order), "fill_price": float(fill_price),
            "post_qty": post_qty, "post_avg": float(new_avg),
            "is_reverse": is_rev,
        })

    def _phase_1700(self, d, bar):
        """17:00 EOD — 매매 잠금 해제, 리버스 탈출/day++, 졸업 감지."""
        self.cfg._sim_date = d
        self.cfg.reset_locks()

        # 1) 리버스 중이면 수익률 체크
        rev_state = self.cfg.get_reverse_state(self.ticker)
        if rev_state.get("is_active"):
            qty, avg, _, _ = self.cfg.calculate_holdings(self.ticker)
            close = bar["close"]
            if avg > 0 and qty > 0:
                curr_ret = (close - avg) / avg * 100.0
                if curr_ret >= self.reverse_exit_threshold:
                    # 🌤️ 리버스 확정 탈출
                    self.cfg.set_reverse_state(self.ticker, False, 0, 0.0)
                    try:
                        self.cfg.clear_escrow_cash(self.ticker)
                    except Exception:
                        pass

                    # ledger 의 is_reverse 플래그 일괄 False
                    ledger = self.cfg.get_ledger()
                    changed = False
                    for r in ledger:
                        if r.get("ticker") == self.ticker and r.get("is_reverse"):
                            r["is_reverse"] = False
                            changed = True
                    if changed:
                        self.cfg._save_json(self.cfg.FILES["LEDGER"], ledger)

                    self.events.append({
                        "day": d, "phase": "17:00", "kind": "reverse_exited",
                        "curr_return": curr_ret, "threshold": self.reverse_exit_threshold,
                    })
                else:
                    self.cfg.increment_reverse_day(self.ticker)
                    new_state = self.cfg.get_reverse_state(self.ticker)
                    self.events.append({
                        "day": d, "phase": "17:00", "kind": "reverse_day_incremented",
                        "new_day": new_state.get("day_count", 0),
                        "curr_return": curr_ret,
                    })

        # 2) 졸업 감지 — 잔고 0 && 장부 양수
        qty_after, _, _, _ = self.cfg.calculate_holdings(self.ticker)
        ledger_after = self.cfg.get_ledger()
        has_records = any(r["ticker"] == self.ticker for r in ledger_after)
        if qty_after == 0 and has_records:
            end_date = self._iso(d)
            old_seed = self.cfg.get_seed(self.ticker)
            new_hist, added_seed = self.cfg.archive_graduation(
                self.ticker, end_date, bar["close"],
            )
            new_seed = self.cfg.get_seed(self.ticker)
            if new_hist is not None:
                self.events.append({
                    "day": d, "phase": "17:00", "kind": "graduated",
                    "profit": new_hist.get("profit", 0.0),
                    "yield_pct": new_hist.get("yield", 0.0),
                    "added_seed": added_seed,
                    "old_seed": old_seed, "new_seed": new_seed,
                })

    def run_day(self, d):
        bar = self._bar(d)
        if bar is None:
            return []
        events_before = len(self.events)
        self._phase_0905(d, bar)
        self._phase_limit_intraday(d, bar)
        self._phase_1525(d, bar)
        self._phase_1700(d, bar)
        return list(self.events)[events_before:]
