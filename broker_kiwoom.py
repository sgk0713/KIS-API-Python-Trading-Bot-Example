# ==========================================================
# [broker_kiwoom.py] 키움 REST API 기반 국내주식 브로커
# ----------------------------------------------------------
# - KoreaInvestmentBroker(broker.py)와 동일한 공개 메소드 시그니처 유지
#   (scheduler_trade / scheduler_core / telegram_bot 호출부 변경 최소화)
# - LOC/MOC 주문은 15:25 KST 지연 LIMIT 발송 패턴 (조건부지정가 사용 안 함)
# - 시세 계열은 yfinance(ticker.KS) 우선, 키움 시세 TR은 추후 매핑
# ==========================================================

import requests
import json
import time
import datetime
import os
import math
import threading
import yfinance as yf
import pytz
import tempfile
import shutil
import pandas as pd

# ==========================================================
# 지연 주문 디스크 큐 (LOC/MOC 의 15:25 KST 지연 발송용)
# ==========================================================
_PENDING_FILE = "data/pending_orders_kiwoom.json"
_pending_lock = threading.Lock()


def _append_pending_order(ticker, side, qty, price, original_type, desc=""):
    """지연 발송 대기열에 주문 1건 추가 (atomic)."""
    with _pending_lock:
        today = datetime.datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d')
        data = {"date": today, "orders": []}
        if os.path.exists(_PENDING_FILE):
            try:
                with open(_PENDING_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                if saved.get('date') == today:
                    data = saved
            except Exception:
                pass
        data['orders'].append({
            "ticker": str(ticker),
            "side": side,
            "qty": int(qty),
            "price": float(price or 0),
            "original_type": original_type,
            "desc": desc,
            "submitted_at": datetime.datetime.now(pytz.timezone('Asia/Seoul')).isoformat(),
        })
        dir_name = os.path.dirname(_PENDING_FILE) or "."
        if not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dir_name, text=True)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(fd)
        os.replace(tmp, _PENDING_FILE)
        print(f"⏰ [Kiwoom 마감{original_type} 큐] {ticker} {side} {qty}주 @ {int(price):,}원 저장 (총 {len(data['orders'])}건)")


def _drain_pending_orders():
    """대기 중인 주문 전부 꺼내고 파일 초기화. 당일 항목만 반환 (stale 자동 제거)."""
    with _pending_lock:
        if not os.path.exists(_PENDING_FILE):
            return []
        today = datetime.datetime.now(pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d')
        try:
            with open(_PENDING_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return []
        orders = data.get('orders', []) if data.get('date') == today else []
        # 파일 클리어 (다음 사이클을 위해)
        try:
            os.remove(_PENDING_FILE)
        except Exception:
            pass
        return orders

# ==========================================================
# 키움 REST API 엔드포인트 / api-id 상수
# ----------------------------------------------------------
# ✅ 확정 (공식 가이드)
#   - POST /oauth2/token  api-id: au10001
#   - 도메인: 운영 https://api.kiwoom.com / 모의 https://mockapi.kiwoom.com
# ✅ 확정 (주문 계열, 공개 래퍼 문서 기준)
#   - kt10000 주식매수 / kt10001 주식매도 / kt10002 정정 / kt10003 취소
# ⚠️ 공식 상세 페이지 비공개 — api-id 미매핑 항목은 None으로 두고
#    호출 시 안전 디폴트 반환(리스트/0) 또는 경고만 출력, 프로세스는 계속 동작
# ==========================================================

_TOKEN_PATH = "/oauth2/token"
_ORDER_PATH = "/api/dostk/ordr"     # ✅ 확정 (2026-04-20 실 API 프로빙 검증)
_INQUIRY_PATH = "/api/dostk/acnt"   # ✅ 확정 (계좌 카테고리, kt00009 체결내역 등)
_CHART_PATH = "/api/dostk/chart"    # ✅ 확정 (ka10079/80/81 틱/분/일봉)
_STKINFO_PATH = "/api/dostk/stkinfo" # ✅ 확정 (ka10099 종목목록 등)

_API_IDS = {
    # ✅ 주문 계열 (URI: /api/dostk/ordr)
    "ORDER_BUY":        "kt10000",
    "ORDER_SELL":       "kt10001",
    "ORDER_AMEND":      "kt10002",
    "ORDER_CANCEL":     "kt10003",
    # ✅ 계좌 계열 (URI: /api/dostk/acnt)
    "BALANCE_CASH":     "kt00001",  # 예수금상세 → ord_alow_amt
    "BALANCE_HOLDINGS": "kt00018",  # 계좌평가잔고 → acnt_evlt_remn_indv_tot[]
    "UNFILLED_ORDERS":  "ka10075",  # 미체결 주문 조회 → oso[]
    "EXEC_HISTORY":     "kt00009",  # 체결내역 → acnt_ord_cntr_prst_array[]
    # ✅ 시세 계열 (URI: /api/dostk/stkinfo)
    "STOCK_INFO":       "ka10001",  # 주식기본정보 → cur_prc, base_pric, upl_pric, lst_pric
    # 추후 확장 여지
    "ORDER_BOOK":       None,  # 호가 (ka10005 추정)
    "DAILY_CANDLE":     "ka10081",  # 주식 일봉 차트 (/api/dostk/chart)
}

# KRX 주문 종류(trde_tp) — 지정가/시장가. LOC/MOC는 15:25 지연 LIMIT로 귀결.
_KRX_ORD_LIMIT = "00"
_KRX_ORD_MARKET = "03"


class KiwoomBroker:
    """키움 REST API 국내주식 브로커. 공개 메소드는 KoreaInvestmentBroker와 호환."""

    def __init__(self, app_key, app_secret, account_no, is_mock=True):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.is_mock = is_mock
        # 기존 KIS 호출부 호환 속성
        self.cano = account_no
        self.acnt_prdt_cd = "22" if is_mock else "01"
        self.base_url = "https://mockapi.kiwoom.com" if is_mock else "https://api.kiwoom.com"
        # 토큰 파일은 브로커별 네임스페이스 분리
        self.token_file = f"data/token_kiwoom_{account_no}.dat"
        self.token = None

        self._get_access_token()

    # ==========================================================
    # 인증
    # ==========================================================
    def _get_access_token(self, force=False):
        if not force and os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    saved = json.load(f)
                expire_time = datetime.datetime.strptime(saved['expire'], '%Y-%m-%d %H:%M:%S')
                kst = pytz.timezone('Asia/Seoul')
                now_kst_naive = datetime.datetime.now(kst).replace(tzinfo=None)
                if expire_time > now_kst_naive + datetime.timedelta(hours=1):
                    self.token = saved['token']
                    return
            except Exception:
                pass

        if force and os.path.exists(self.token_file):
            try:
                os.remove(self.token_file)
            except Exception:
                pass

        url = f"{self.base_url}{_TOKEN_PATH}"
        headers = {"content-type": "application/json;charset=UTF-8"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret,
        }
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
            data = res.json()
            if data.get('return_code') == 0 and data.get('token'):
                self.token = data['token']
                # 키움 토큰 유효기간은 약 24시간 — 보수적으로 23시간 캐싱
                expire_str = (datetime.datetime.now() + datetime.timedelta(hours=23)).strftime('%Y-%m-%d %H:%M:%S')
                dir_name = os.path.dirname(self.token_file)
                if dir_name and not os.path.exists(dir_name):
                    os.makedirs(dir_name, exist_ok=True)
                fd, temp_path = tempfile.mkstemp(dir=dir_name, text=True)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump({'token': self.token, 'expire': expire_str}, f)
                    f.flush()
                    os.fsync(fd)
                shutil.move(temp_path, self.token_file)
            else:
                print(f"❌ [KiwoomBroker] 토큰 발급 실패: {data.get('return_msg', '알 수 없는 오류')}")
        except Exception as e:
            print(f"❌ [KiwoomBroker] 토큰 통신 에러: {e}")

    def _get_header(self, api_id):
        return {
            "content-type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.token}",
            "api-id": api_id,
            "appkey": self.app_key,
            "secretkey": self.app_secret,
        }

    def _api_request(self, method, url, headers, params=None, data=None):
        for attempt in range(2):
            try:
                if method.upper() == "GET":
                    res = requests.get(url, headers=headers, params=params, timeout=10)
                else:
                    res = requests.post(url, headers=headers, data=json.dumps(data) if data else None, timeout=10)
                resp_json = res.json()
                rcode = resp_json.get('return_code')
                if rcode is not None and rcode != 0:
                    rmsg = str(resp_json.get('return_msg', ''))
                    if any(x in rmsg.lower() for x in ['토큰', 'token', '인증', 'expired']):
                        if attempt == 0:
                            print(f"\n🚨 [KiwoomBroker] 토큰 만료 감지: {rmsg}")
                            self._get_access_token(force=True)
                            headers["authorization"] = f"Bearer {self.token}"
                            time.sleep(1.0)
                            continue
                return res, resp_json
            except Exception as e:
                print(f"⚠️ [KiwoomBroker] API 통신 예외: {e}")
                if attempt == 1:
                    return None, {}
                time.sleep(1.0)
        return None, {}

    def _call_api(self, api_id, url_path, method="POST", params=None, body=None):
        if not api_id:
            print(f"⚠️ [KiwoomBroker] api-id 미매핑 — 호출 생략 ({url_path})")
            return {'return_code': 999, 'return_msg': 'api-id not mapped'}
        headers = self._get_header(api_id)
        url = f"{self.base_url}{url_path}"
        _, resp_json = self._api_request(method, url, headers, params=params, data=body)
        if not resp_json:
            return {'return_code': 999, 'return_msg': '통신 오류 또는 최대 재시도 초과'}
        return resp_json

    # ==========================================================
    # 유틸리티
    # ==========================================================
    def _safe_float(self, value):
        try:
            return float(str(value).replace(',', ''))
        except Exception:
            return 0.0

    def _safe_int(self, value):
        try:
            return int(float(str(value).replace(',', '')))
        except Exception:
            return 0

    def _yf_symbol(self, ticker):
        """국내 종목코드를 yfinance 심볼로 변환.
        .KS(코스피)/.KQ(코스닥) 둘 다 프로브해서 최근 일자가 더 최신인 쪽 선택.
        결과는 인스턴스 dict에 캐시해 동일 티커 재조회를 방지."""
        t = str(ticker).strip()
        if '.' in t:
            return t

        if not hasattr(self, '_yf_sym_cache'):
            self._yf_sym_cache = {}
        cached = self._yf_sym_cache.get(t)
        if cached:
            return cached

        def _latest_date(sym):
            try:
                h = yf.Ticker(sym).history(period="5d", timeout=5)
                if h.empty:
                    return None
                last_idx = h.index[-1]
                return last_idx.date() if hasattr(last_idx, 'date') else None
            except Exception:
                return None

        ks = f"{t}.KS"
        kq = f"{t}.KQ"
        ks_date = _latest_date(ks)
        kq_date = _latest_date(kq)

        if ks_date and kq_date:
            chosen = ks if ks_date >= kq_date else kq
        elif kq_date:
            chosen = kq
        else:
            chosen = ks  # .KS가 유일하거나 둘 다 실패 시 기본
        self._yf_sym_cache[t] = chosen
        return chosen

    def _round_to_krw_tick(self, price, side=None):
        """KRX 가격대별 호가단위로 반올림.
        side='SELL' → 올림 (ceil)    매도자 유리, 목표가 상승 방향
        side='BUY' / None → 내림 (floor) 매수자 유리, 지정가 하락 방향"""
        if price is None or price <= 0:
            return 0
        p = float(price)
        pi = int(p)
        if pi < 2000:      tick = 1
        elif pi < 5000:    tick = 5
        elif pi < 20000:   tick = 10
        elif pi < 50000:   tick = 50
        elif pi < 200000:  tick = 100
        elif pi < 500000:  tick = 500
        else:              tick = 1000
        if side == "SELL":
            return int(math.ceil(p / tick)) * tick
        return int(p // tick) * tick

    # ==========================================================
    # 잔고 / 보유종목
    # ==========================================================
    def get_account_balance(self):
        """반환: (cash_krw, holdings_dict) 또는 실패 시 (0.0, None).
        holdings_dict: {stk_cd_6digit: {'qty': int, 'ord_psbl_qty': int, 'avg': float}}
        (kt00018 응답의 stk_cd 앞 'A' 접두사는 제거해서 6자리 코드로 통일)"""
        api_success = False
        cash = 0.0
        holdings = {}

        # 1) 예수금상세 (kt00001) — 주문가능금액
        res_cash = self._call_api(_API_IDS["BALANCE_CASH"], _INQUIRY_PATH, "POST", body={"qry_tp": "1"})
        if res_cash.get('return_code') == 0:
            api_success = True
            cash = self._safe_float(res_cash.get('ord_alow_amt', 0))

        # 2) 계좌평가잔고 (kt00018) — 보유종목 리스트
        res_hold = self._call_api(_API_IDS["BALANCE_HOLDINGS"], _INQUIRY_PATH, "POST", body={"qry_tp": "1", "dmst_stex_tp": "KRX"})
        if res_hold.get('return_code') == 0:
            api_success = True
            for item in res_hold.get('acnt_evlt_remn_indv_tot', []):
                raw_cd = str(item.get('stk_cd', '')).strip()
                # 키움은 응답에 'A' 접두사를 붙여 반환 (요청엔 6자리만)
                ticker = raw_cd[1:] if raw_cd and raw_cd[0].isalpha() else raw_cd
                qty = self._safe_int(item.get('rmnd_qty', 0))
                ord_qty = self._safe_int(item.get('trde_able_qty', qty))
                avg = self._safe_float(item.get('pur_pric', 0))
                if qty > 0 and ticker:
                    holdings[ticker] = {'qty': qty, 'ord_psbl_qty': ord_qty, 'avg': avg}

        if api_success:
            return cash, holdings
        return 0.0, None

    # ==========================================================
    # 시세 (키움 ka10001 주력, yfinance 백업)
    # ==========================================================
    def _kiwoom_stock_basic(self, ticker):
        """ka10001 주식기본정보 — cur_prc(현재가), base_pric(전일종가),
        upl_pric(상한가), lst_pric(하한가). 응답값은 '+15000' / '-28100'
        식으로 부호 prefix 있음 (전일대비 방향)."""
        res = self._call_api(_API_IDS["STOCK_INFO"], _STKINFO_PATH, "POST",
                             body={"stk_cd": str(ticker)})
        if res.get('return_code') != 0:
            return None
        return res

    def _parse_signed_price(self, raw):
        """'+15000' 또는 '-28100' 형태를 절대값 float로."""
        if raw is None:
            return 0.0
        return self._safe_float(str(raw).lstrip('+-'))

    def get_current_price(self, ticker, is_market_closed=False):
        # 1순위: 키움 ka10001 (국장 실시간 공식 시세)
        try:
            info = self._kiwoom_stock_basic(ticker)
            if info:
                price = self._parse_signed_price(info.get('cur_prc'))
                if price > 0:
                    return price
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] 키움 현재가 실패 ({ticker}): {e} — yfinance 폴백")

        # 2순위: yfinance (백업)
        try:
            stock = yf.Ticker(self._yf_symbol(ticker))
            if is_market_closed:
                return float(stock.fast_info['last_price'])
            hist = stock.history(period="1d", interval="1m", timeout=5)
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
            return float(stock.fast_info['last_price'])
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] 현재가 조회 실패 ({ticker}): {e}")
            return 0.0

    def get_previous_close(self, ticker):
        # 1순위: 키움 ka10001.base_pric (전일 종가)
        try:
            info = self._kiwoom_stock_basic(ticker)
            if info:
                price = self._parse_signed_price(info.get('base_pric'))
                if price > 0:
                    return price
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] 키움 전일종가 실패 ({ticker}): {e} — yfinance 폴백")

        # 2순위: yfinance
        try:
            stock = yf.Ticker(self._yf_symbol(ticker))
            hist = stock.history(period="5d", timeout=5)
            if not hist.empty:
                kst = pytz.timezone('Asia/Seoul')
                now_kst = datetime.datetime.now(kst)
                cutoff_date = now_kst.date()
                if now_kst.time() < datetime.time(15, 30):
                    cutoff_date -= datetime.timedelta(days=1)
                if hist.index.tzinfo is None:
                    hist.index = hist.index.tz_localize('UTC').tz_convert(kst)
                else:
                    hist.index = hist.index.tz_convert(kst)
                past = hist[hist.index.date <= cutoff_date]
                if not past.empty:
                    return float(past['Close'].iloc[-1])
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] 전일 종가 조회 실패 ({ticker}): {e}")
        return 0.0

    def get_5day_ma(self, ticker):
        try:
            stock = yf.Ticker(self._yf_symbol(ticker))
            hist = stock.history(period="10d", timeout=5)
            if len(hist) >= 5:
                return float(hist['Close'][-5:].mean())
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] MA5 조회 실패 ({ticker}): {e}")
        return 0.0

    def get_day_high_low(self, ticker):
        try:
            stock = yf.Ticker(self._yf_symbol(ticker))
            hist = stock.history(period="1d", interval="1m", timeout=5)
            if not hist.empty:
                return float(hist['High'].max()), float(hist['Low'].min())
            info = stock.fast_info
            return float(info.get('dayHigh', 0.0)), float(info.get('dayLow', 0.0))
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] 고가/저가 조회 실패 ({ticker}): {e}")
        return 0.0, 0.0

    def get_ask_price(self, ticker):
        """매도 1호가. 키움 호가 TR 미매핑 상태에선 현재가 근처로 추정."""
        p = self.get_current_price(ticker)
        return float(self._round_to_krw_tick(p)) if p > 0 else 0.0

    def get_bid_price(self, ticker):
        p = self.get_current_price(ticker)
        return float(self._round_to_krw_tick(p)) if p > 0 else 0.0

    def get_current_5min_candle(self, ticker):
        try:
            stock = yf.Ticker(self._yf_symbol(ticker))
            df = stock.history(period="5d", interval="1m", timeout=5)
            if df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            kst = pytz.timezone('Asia/Seoul')
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert(kst)
            else:
                df.index = df.index.tz_convert(kst)
            regular = df.between_time('09:00', '15:30')
            if regular.empty:
                return None
            typical = (regular['High'] + regular['Low'] + regular['Close']) / 3.0
            vp = typical * regular['Volume']
            vwap_series = vp.cumsum() / regular['Volume'].cumsum().replace(0, 1)
            current_vwap = float(vwap_series.iloc[-1]) if not vwap_series.empty else 0.0
            resampled = regular.resample('5min', label='left', closed='left').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()
            if resampled.empty:
                return None
            resampled['Vol_MA10'] = resampled['Volume'].rolling(10, min_periods=1).mean()
            resampled['Vol_MA20'] = resampled['Volume'].rolling(20, min_periods=1).mean()
            last = resampled.iloc[-1]
            latest_1m = df.iloc[-1]
            return {
                'open': float(last['Open']),
                'high': float(latest_1m['High']),
                'low': float(latest_1m['Low']),
                'close': float(latest_1m['Close']),
                'volume': float(last['Volume']),
                'vol_ma10': float(last['Vol_MA10']) if not pd.isna(last['Vol_MA10']) else float(last['Volume']),
                'vol_ma20': float(last['Vol_MA20']) if not pd.isna(last['Vol_MA20']) else float(last['Volume']),
                'vwap': current_vwap,
            }
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] 5분봉 조회 실패 ({ticker}): {e}")
            return None

    def get_1min_candles_df(self, ticker):
        try:
            stock = yf.Ticker(self._yf_symbol(ticker))
            df = stock.history(period="1d", interval="1m", timeout=5)
            if df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            kst = pytz.timezone('Asia/Seoul')
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert(kst)
            else:
                df.index = df.index.tz_convert(kst)
            df = df.rename(columns={'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
            df['time_est'] = df.index.strftime('%H%M00')  # 키명은 호환 유지(값은 KST)
            return df[['high', 'low', 'close', 'volume', 'time_est']]
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] 1분봉 조회 실패 ({ticker}): {e}")
            return None

    # ==========================================================
    # 주문
    # ==========================================================
    def send_order(self, ticker, side, qty, price, order_type="LIMIT"):
        # LOC/MOC → 15:25 KST 지연 발송 (각자 의도 유지)
        if order_type in ("LOC", "MOC"):
            print(f"⚠️ [KiwoomBroker] {order_type} → 15:25 KST 지연 예약 ({ticker} {side} {qty})")
            self._schedule_closing_order(ticker, side, qty, price, original_type=order_type)
            return {'rt_cd': '0', 'msg1': f'[Kiwoom] {order_type} → 마감 직전 예약', 'odno': 'KW_SCHEDULED'}
        if order_type in ("LOO", "MOO"):
            order_type = "LIMIT"

        api_id = _API_IDS["ORDER_BUY"] if side == "BUY" else _API_IDS["ORDER_SELL"]

        # 시장가/지정가 분기
        if order_type == "MARKET":
            ord_dvsn = _KRX_ORD_MARKET  # "03"
            final_price = 0  # 시장가는 가격 없음
        else:  # LIMIT 및 그 외 모든 케이스
            ord_dvsn = _KRX_ORD_LIMIT  # "00"
            final_price = self._round_to_krw_tick(price, side=side)

        body = {
            "dmst_stex_tp": "KRX",
            "stk_cd": str(ticker),
            "ord_qty": str(int(qty)),
            "ord_uv": str(int(final_price)),
            "trde_tp": ord_dvsn,
            "cond_uv": "",
        }
        res = self._call_api(api_id, _ORDER_PATH, "POST", body=body)
        rt_cd = '0' if res.get('return_code') == 0 else str(res.get('return_code', '999'))
        msg1 = res.get('return_msg', '')
        odno = res.get('ord_no', '') or res.get('odno', '')
        return {'rt_cd': rt_cd, 'msg1': msg1, 'odno': odno}

    def _schedule_closing_order(self, ticker, side, qty, price, original_type="LOC"):
        """LOC/MOC 주문을 디스크 큐(data/pending_orders_kiwoom.json) 에 기록.
          실제 발송은 scheduler_trade_kr.scheduled_kr_closing_dispatch 가 15:25 KST 에 처리.
          봇이 09:05 ~ 15:25 사이에 재시작돼도 지연 주문 유실 방지."""
        _append_pending_order(ticker, side, qty, price, original_type)

    # 하위 호환성 — 예전 이름으로도 호출 가능
    _schedule_closing_limit_order = _schedule_closing_order

    def cancel_order(self, ticker, order_id):
        body = {
            "dmst_stex_tp": "KRX",
            "orig_ord_no": str(order_id),
            "stk_cd": str(ticker),
            "cncl_qty": "0",  # 0 = 전량취소 (실 API 검증 완료 2026-04-20)
        }
        self._call_api(_API_IDS["ORDER_CANCEL"], _ORDER_PATH, "POST", body=body)

    def cancel_all_orders_safe(self, ticker, side=None):
        for _ in range(3):
            orders = self.get_unfilled_orders_detail(ticker)
            if not orders:
                return True
            targets = orders
            if side == "BUY":
                targets = [o for o in orders if o.get('sll_buy_dvsn_cd') == '02']
            elif side == "SELL":
                targets = [o for o in orders if o.get('sll_buy_dvsn_cd') == '01']
            if not targets:
                return True
            for o in targets:
                self.cancel_order(ticker, o.get('odno'))
            time.sleep(5)
        final = self.get_unfilled_orders_detail(ticker)
        if side == "BUY":
            failed = [o for o in final if o.get('sll_buy_dvsn_cd') == '02']
        elif side == "SELL":
            failed = [o for o in final if o.get('sll_buy_dvsn_cd') == '01']
        else:
            failed = final
        if failed:
            raise Exception(f"[FATAL] {ticker} 미체결 취소 실패: {[o.get('odno') for o in failed]}")
        return True

    def cancel_targeted_orders(self, ticker, side, target_ord_dvsn):
        sll_buy_cd = '02' if side == "BUY" else '01'
        orders = self.get_unfilled_orders_detail(ticker)
        if not orders:
            return 0
        targets = [
            o for o in orders
            if o.get('sll_buy_dvsn_cd') == sll_buy_cd
            and (o.get('ord_dvsn_cd') or o.get('ord_dvsn') or '') == target_ord_dvsn
        ]
        for o in targets:
            self.cancel_order(ticker, o.get('odno'))
            time.sleep(0.3)
        return len(targets)

    def cancel_orders_by_price(self, ticker, side, target_prices):
        sll_buy_cd = '02' if side == "BUY" else '01'
        orders = self.get_unfilled_orders_detail(ticker)
        if not orders:
            return 0
        targets = []
        for o in orders:
            if o.get('sll_buy_dvsn_cd') != sll_buy_cd:
                continue
            op = 0.0
            for key in ('ord_uv', 'ord_unpr', 'ovrs_ord_unpr'):
                v = self._safe_float(o.get(key, 0))
                if v > 0:
                    op = v
                    break
            for tp in target_prices:
                if op > 0 and abs(op - tp) < 1.0:  # KRW 1원 오차 이내
                    targets.append(o)
                    break
        for o in targets:
            self.cancel_order(ticker, o.get('odno'))
            time.sleep(0.3)
        return len(targets)

    # ==========================================================
    # 미체결 / 체결내역
    # ----------------------------------------------------------
    # 호출부(scheduler_trade, telegram_bot)가 KIS 응답 포맷(sll_buy_dvsn_cd,
    # odno, ft_ccld_qty, ft_ccld_unpr3, ord_tmd, ord_dvsn_cd, ord_unpr 등)을
    # 참조하므로 키움 응답을 KIS-호환 dict 로 매핑해서 반환.
    #
    # ⚠️ kt00009 응답에서 매수/매도는 `io_tp_nm` ("현금매수"/"현금매도" 등 한국어)
    #    에 들어있고, `trde_tp` 는 주문종류("시장가"/"지정가") 라는 별개 필드다.
    #    과거 `trde_tp` 를 side 로 오인해 읽은 탓에 BUY 체결이 SELL 로 기록되는
    #    장부 오염이 발생했다. side 해석은 반드시 `_kiwoom_side_to_kis` 로.
    # ==========================================================
    @staticmethod
    def _kiwoom_side_to_kis(v):
        """Kiwoom 매수/매도 값 → KIS sll_buy_dvsn_cd ('01'=매도, '02'=매수).
        인식 불가 값은 빈 문자열 반환 (호출부가 SELL 로 미끄러지지 않도록)."""
        s = str(v or '').strip()
        if not s:
            return ''
        if s in ('1', '01'):
            return '01'
        if s in ('2', '02'):
            return '02'
        # 부호 프리픽스 제거 후 한국어 판정 ("현금매수", "신용매도", "+매수" 등)
        stripped = s.lstrip('+-').strip()
        if '매도' in stripped or stripped in ('S', 'SELL', 'sell'):
            return '01'
        if '매수' in stripped or stripped in ('B', 'BUY', 'buy'):
            return '02'
        return ''

    def get_unfilled_orders(self, ticker):
        details = self.get_unfilled_orders_detail(ticker)
        return [d.get('odno') for d in details if d.get('odno')]

    def get_unfilled_orders_detail(self, ticker):
        """미체결 주문 리스트 반환. KIS-호환 포맷으로 매핑."""
        body = {
            "all_stk_tp": "1" if ticker else "0",
            "trde_tp": "0",      # 0=전체
            "stex_tp": "0",      # 0=KRX
            "stk_cd": str(ticker) if ticker else "",
        }
        res = self._call_api(_API_IDS["UNFILLED_ORDERS"], _INQUIRY_PATH, "POST", body=body)
        if res.get('return_code') != 0:
            return []
        raw_list = res.get('oso', []) or []
        mapped = []
        for item in raw_list:
            stk_cd = str(item.get('stk_cd', '')).strip()
            # 응답엔 종종 "A" 접두사가 붙어옴 — 요청 티커와 비교 시 정규화
            norm_cd = stk_cd[1:] if stk_cd and stk_cd[0].isalpha() else stk_cd
            if ticker and norm_cd != str(ticker):
                continue
            # 미체결 응답(oso)의 side 후보. 미확인 엔드포인트이므로 한국어 우선.
            side_cd = ''
            for key in ('io_tp_nm', 'io_tp', 'sll_buy_dvsn_cd_nm',
                        'sll_buy_dvsn_cd', 'sll_buy_tp', 'sell_tp'):
                raw_side = item.get(key)
                if raw_side in (None, ''):
                    continue
                side_cd = self._kiwoom_side_to_kis(raw_side)
                if side_cd:
                    break
            mapped.append({
                'odno': str(item.get('ord_no', '')),
                'pdno': norm_cd,
                'sll_buy_dvsn_cd': side_cd,
                'ord_dvsn_cd': item.get('ord_stat', '') or item.get('ord_dvsn', ''),
                'ord_dvsn': item.get('ord_stat', ''),
                'ord_unpr': item.get('ord_uv', '0'),
                'ovrs_ord_unpr': item.get('ord_uv', '0'),
                'ft_ord_unpr3': item.get('ord_uv', '0'),
                'ord_qty': item.get('ord_qty', '0'),
                'rmnd_qty': item.get('rmnd_qty', item.get('oso_qty', '0')),
                'stk_nm': item.get('stk_nm', ''),
                '_raw': item,  # 디버그용 원본
            })
        return mapped

    def get_execution_history(self, ticker, start_date, end_date):
        """체결내역 리스트 반환 (지정 기간 중 특정 ticker). KIS-호환 포맷으로 매핑.
          start_date/end_date: 'YYYYMMDD'. 키움 kt00009는 단일 일자 기반이라 start만 사용.
          (여러 날이 필요하면 호출부가 loop — 원본 broker.get_genesis_ledger 패턴)"""
        body = {
            "stk_bond_tp": "0",            # 0=전체 (주식/채권)
            "mrkt_tp": "0",                # 0=전체 시장
            "sell_tp": "0",                # 0=전체 (매수/매도)
            "qry_tp": "0",                 # 0=전체
            "stk_cd": str(ticker) if ticker else "",
            "ord_dt": str(start_date) if start_date else "",
            "dmst_stex_tp": "KRX",
        }
        res = self._call_api(_API_IDS["EXEC_HISTORY"], _INQUIRY_PATH, "POST", body=body)
        if res.get('return_code') != 0:
            return []
        raw_list = res.get('acnt_ord_cntr_prst_array', []) or []
        mapped = []
        for item in raw_list:
            stk_cd = str(item.get('stk_cd', '')).strip()
            norm_cd = stk_cd[1:] if stk_cd and stk_cd[0].isalpha() else stk_cd
            if ticker and norm_cd != str(ticker):
                continue
            cntr_qty = self._safe_float(item.get('cntr_qty', 0))
            if cntr_qty <= 0:
                continue  # 미체결 건(cnfm_qty만 있고 cntr_qty=0)은 제외

            # kt00009 spec: side 는 `io_tp_nm` 의 한국어("현금매수"/"현금매도" 등).
            # `trde_tp` 는 "시장가"/"지정가" 주문종류이므로 side 로 쓰면 안 됨.
            # 다른 유사 엔드포인트 호환을 위해 몇 개 후보를 추가로 둠.
            side_cd = ''
            for key in ('io_tp_nm', 'io_tp', 'sll_buy_dvsn_cd_nm',
                        'sll_buy_dvsn_cd', 'sll_buy_tp', 'sell_tp'):
                raw_side = item.get(key)
                if raw_side in (None, ''):
                    continue
                side_cd = self._kiwoom_side_to_kis(raw_side)
                if side_cd:
                    break
            if not side_cd:
                import logging as _lg
                _lg.warning(
                    "[kt00009] 매수/매도 구분 판정 실패 — 해당 체결 제외. raw=%s",
                    item,
                )
                continue
            mapped.append({
                'odno': str(item.get('ord_no', '')),
                'pdno': norm_cd,
                'sll_buy_dvsn_cd': side_cd,
                'ft_ccld_qty': item.get('cntr_qty', '0'),
                'ft_ccld_unpr3': item.get('cntr_uv', '0'),
                'ord_tmd': item.get('cntr_tm', ''),
                'stk_nm': item.get('stk_nm', ''),
                '_raw': item,
            })
        return mapped

    def get_genesis_ledger(self, ticker, limit_date_str=None):
        _, holdings = self.get_account_balance()
        if holdings is None:
            return None, 0, 0.0
        info = holdings.get(ticker, {'qty': 0, 'avg': 0.0})
        curr_qty = int(info.get('qty', 0))
        final_qty = curr_qty
        final_avg = float(info.get('avg', 0.0))
        if curr_qty == 0:
            return [], 0, 0.0
        records = []
        kst = pytz.timezone('Asia/Seoul')
        target_date = datetime.datetime.now(kst)
        genesis = False
        for _ in range(365):
            if curr_qty <= 0 or genesis:
                break
            date_str = target_date.strftime('%Y%m%d')
            if limit_date_str and date_str < limit_date_str:
                break
            execs = self.get_execution_history(ticker, date_str, date_str)
            if execs:
                execs.sort(key=lambda x: x.get('ord_tmd', '000000'), reverse=True)
                for ex in execs:
                    side_cd = ex.get('sll_buy_dvsn_cd')
                    q = int(self._safe_float(ex.get('ft_ccld_qty', 0)))
                    p = self._safe_float(ex.get('ft_ccld_unpr3', 0))
                    rec_q = q
                    if side_cd == "02":
                        if curr_qty <= q:
                            rec_q = curr_qty
                            curr_qty = 0
                            genesis = True
                        else:
                            curr_qty -= q
                    else:
                        curr_qty += q
                    records.append({
                        'date': f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
                        'side': "BUY" if side_cd == "02" else "SELL",
                        'qty': rec_q,
                        'price': p,
                    })
                    if genesis:
                        break
            target_date -= datetime.timedelta(days=1)
            time.sleep(0.1)
        records.reverse()
        return records, final_qty, final_avg

    # ==========================================================
    # 액면분할 / 변동성 / ATR
    # ==========================================================
    def get_recent_stock_split(self, ticker, last_date_str):
        try:
            stock = yf.Ticker(self._yf_symbol(ticker))
            splits = stock.splits
            if splits is not None and not splits.empty:
                kst = pytz.timezone('Asia/Seoul')
                if last_date_str == "":
                    seven_ago = datetime.datetime.now(kst) - datetime.timedelta(days=7)
                    safe_last = seven_ago.strftime('%Y-%m-%d')
                else:
                    safe_last = last_date_str
                for dt, ratio in splits.items():
                    ds = dt.strftime('%Y-%m-%d')
                    if ds > safe_last:
                        return float(ratio), ds
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] 액면분할 조회 실패: {e}")
        return 0.0, ""

    def get_dynamic_sniper_target(self, index_ticker):
        """KR 기준 변동성 엔진 미구현 — 안전 폴백 반환 (호출부 호환 유지)."""
        class TargetFloat(float):
            pass
        target_drop = -4.0  # 2x 레버리지 가정 보수적 기본 타깃
        ret = TargetFloat(target_drop)
        ret.metric_val = 0.0
        ret.weight = 1.0
        ret.base_amp = target_drop
        ret.metric_name = "KR 기본값(변동성엔진 미구현)"
        ret.metric_base = 20.0
        ret.is_panic = False
        ret.gap_pct = 0.0
        return ret

    def get_atr_data(self, ticker):
        try:
            stock = yf.Ticker(self._yf_symbol(ticker))
            hist = stock.history(period="30d", timeout=5)
            if hist.empty or len(hist) < 15:
                return 0.0, 0.0
            hist['Prev_Close'] = hist['Close'].shift(1)
            hist['TR'] = hist.apply(lambda r: max(
                r['High'] - r['Low'],
                abs(r['High'] - r['Prev_Close']) if not pd.isna(r['Prev_Close']) else 0,
                abs(r['Low'] - r['Prev_Close']) if not pd.isna(r['Prev_Close']) else 0,
            ), axis=1)
            hist['ATR5'] = hist['TR'].rolling(5).mean()
            hist['ATR14'] = hist['TR'].rolling(14).mean()
            last = hist.iloc[-1]
            lc = float(last['Close'])
            if lc > 0:
                a5 = float(last['ATR5']) / lc * 100
                a14 = float(last['ATR14']) / lc * 100
                return round(a5, 1), round(a14, 1)
        except Exception as e:
            print(f"⚠️ [KiwoomBroker] ATR 연산 실패 ({ticker}): {e}")
        return 0.0, 0.0
