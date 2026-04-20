# ==========================================================
# [scheduler_trade_kr.py]
# ----------------------------------------------------------
# KRX 국내주식 전용 매매 스케줄러 (BROKER=KIWOOM 모드에서만 등록됨).
#
# MVP 범위:
#   - 일일 1회 (09:05 KST) 정규장 주문 장전
#   - V14 전략 그대로 재활용 (strategy.get_plan 호출)
#   - LOC/MOC 주문은 broker_kiwoom가 15:25 KST 지연 LIMIT으로 자동 처리
#
# 이후 확장 여지:
#   - sniper_monitor / vwap / after-market 등 고급 로직
#   - KR 전용 변동성 지표 (VKOSPI 등)
# ==========================================================

import asyncio
import datetime
import logging
import random
import pytz
import pandas_market_calendars as mcal


_KST = pytz.timezone('Asia/Seoul')
_CAL_XKRX = None


def _get_calendar():
    global _CAL_XKRX
    if _CAL_XKRX is None:
        _CAL_XKRX = mcal.get_calendar('XKRX')
    return _CAL_XKRX


def is_kr_market_open():
    """현재 KRX 정규장(09:00~15:30 KST) 개장 여부. 휴장일 고려."""
    now = datetime.datetime.now(_KST)
    if now.weekday() >= 5:
        return False
    try:
        sch = _get_calendar().schedule(start_date=now.date(), end_date=now.date())
        if sch.empty:
            return False
        open_t = sch.iloc[0]['market_open'].tz_convert(_KST).time()
        close_t = sch.iloc[0]['market_close'].tz_convert(_KST).time()
        return open_t <= now.time() <= close_t
    except Exception:
        return datetime.time(9, 0) <= now.time() <= datetime.time(15, 30)


def is_kr_trading_day():
    """오늘이 KRX 개장일인지."""
    now = datetime.datetime.now(_KST)
    if now.weekday() >= 5:
        return False
    try:
        sch = _get_calendar().schedule(start_date=now.date(), end_date=now.date())
        return not sch.empty
    except Exception:
        return True


def _is_kr_ticker(t):
    """6자리 숫자 = KR 국내주식 코드."""
    return isinstance(t, str) and t.isdigit() and len(t) == 6


async def scheduled_kr_regular_trade(context):
    """
    KRX 정규장 개시 직후 (09:05 KST 등록 가정) V14 일일 주문을 장전.

    동작:
      1) 개장일·개장시간 체크
      2) 잔고 조회 (주문가능금액 + 보유종목)
      3) KR 티커에 한해 V14 plan 생성
      4) 기존 미체결 주문 취소 → plan의 모든 주문 송신
      5) 텔레그램으로 결과 리포트
    """
    now = datetime.datetime.now(_KST)
    chat_id = context.job.chat_id

    if not is_kr_trading_day():
        await context.bot.send_message(chat_id=chat_id, text="🗓️ 오늘은 KRX 휴장일입니다. 주문 장전을 스킵합니다.")
        return

    if not is_kr_market_open():
        # 등록 시각(09:05)과 실 시각의 오차를 흡수 — 너무 동떨어지면 스킵
        logging.warning(f"[KR scheduler] 장외 시간 호출됨 (now={now.time()}). 스킵.")
        return

    app_data = context.job.data
    cfg = app_data['cfg']
    broker = app_data['broker']
    strategy = app_data['strategy']
    tx_lock = app_data['tx_lock']

    # 서버 부하 완화용 지터 (0~60초)
    jitter = random.randint(0, 60)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🌅 <b>[{now.strftime('%H:%M')}] KRX 일일 주문 장전 준비</b>\n"
             f"▫️ 서버 부하 방지를 위해 <b>{jitter}초</b> 지터 후 진행합니다.",
        parse_mode='HTML',
    )
    await asyncio.sleep(jitter)

    async with tx_lock:
        cash, holdings = broker.get_account_balance()
        if holdings is None:
            await context.bot.send_message(chat_id=chat_id, text="❌ 계좌 조회 실패 — 잠시 후 다시 시도하세요.")
            return

        active = [t for t in cfg.get_active_tickers() if _is_kr_ticker(t)]
        if not active:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ 활성 KR 종목이 없습니다. /ticker 커맨드로 6자리 코드를 설정하세요 (예: 418660)."
            )
            return

        report = [
            f"🌅 <b>[{now.strftime('%Y-%m-%d %H:%M')} KST] KRX 일일 주문 장전</b>",
            f"💰 주문가능금액: <b>{int(cash):,}원</b>",
            f"📦 보유종목: {len(holdings)}건 (KR 운용 대상: {len(active)}종목)",
        ]

        for t in active:
            if cfg.check_lock(t, "REG"):
                report.append(f"\n🔒 <b>{t}</b>: 오늘 이미 장전됨 — 스킵")
                continue

            h = holdings.get(t, {}) or {}
            qty = int(h.get('qty') or 0)
            avg = float(h.get('avg') or 0.0)

            # 시세 조회
            curr_p = float(await asyncio.to_thread(broker.get_current_price, t) or 0.0)
            prev_c = float(await asyncio.to_thread(broker.get_previous_close, t) or 0.0)
            ma5 = float(await asyncio.to_thread(broker.get_5day_ma, t) or 0.0)

            if curr_p <= 0:
                report.append(f"\n⚠️ <b>{t}</b>: 현재가 조회 실패 — 스킵")
                continue

            # 기존 미체결 전량 취소 (Wash-trade 방지 + 깨끗한 재발송)
            try:
                await asyncio.to_thread(broker.cancel_all_orders_safe, t)
            except Exception as e:
                logging.warning(f"[{t}] 취소 실패 (계속 진행): {e}")

            # 할당 현금 (단순 균등분배)
            allocated = cash / max(len(active), 1)

            plan = strategy.get_plan(
                t, curr_p, avg, qty, prev_c,
                ma_5day=ma5, market_type="REG",
                available_cash=allocated,
            )
            orders = plan.get('core_orders', []) + plan.get('bonus_orders', [])

            status = plan.get('process_status', '')
            t_val = plan.get('t_val', 0.0)
            star_price = plan.get('star_price', 0.0)

            report.append(
                f"\n📊 <b>{t}</b>  보유 {qty}주 · 평단 {int(avg):,}원 · 현재 {int(curr_p):,}원"
            )
            report.append(f"   상태: {status}  T={t_val:.2f}  별값: {int(star_price):,}원")

            if not orders:
                report.append("   (주문 없음)")
                continue

            for o in orders:
                try:
                    res = broker.send_order(t, o['side'], o['qty'], o['price'], o['type'])
                    ok = res.get('rt_cd') == '0'
                    mark = '✅' if ok else '❌'
                    report.append(
                        f"   {mark} {o['desc']}: {o['side']} {o['qty']}주 @ {int(o['price']):,}원 [{o['type']}]"
                    )
                    if not ok:
                        report.append(f"      └ {res.get('msg1', '')[:80]}")
                except Exception as e:
                    report.append(f"   💥 {o['desc']} 예외: {e}")
                await asyncio.sleep(0.3)

            cfg.set_lock(t, "REG")

        await context.bot.send_message(chat_id=chat_id, text='\n'.join(report), parse_mode='HTML')
