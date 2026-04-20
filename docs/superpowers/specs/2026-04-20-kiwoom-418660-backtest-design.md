# 418660 백테스트 엔진 설계서

**작성일**: 2026-04-20
**브랜치**: feature/kiwoom
**대상**: TIGER 미국나스닥100레버리지 (418660) 단일 티커
**기간**: 2025-02-18 → 2026-04-20 (약 290 거래일)
**시드**: 10,000,000 KRW

---

## 1. 목표

"2025-02-18부터 1000만원으로 봇이 운용됐다면 실제로 어떤 매매들이 일어났을까?" — 전 기간 동안의 모든 V14 사이클, 리버스 진입/탈출, 졸업/복리 반영을 프로덕션 로직 그대로 재현하고 일별 내러티브 + 체결/일별 CSV + 인터랙티브 HTML 대시보드로 산출한다.

성과 수치가 아니라 **"그 날 뭐가 일어났는지"의 시나리오 재현**이 핵심이다.

---

## 2. 설계 원칙

1. **프로덕션 코드 재사용 (드리프트 0%)** — `V14Strategy.get_plan()`, `Config.calculate_v14_state()`, `Config.archive_graduation()` 등 실전 코드를 100% 그대로 호출. 베껴쓰지 않는다.
2. **프로덕션 파일 오염 0** — 샌드박스 디렉토리 `data/backtest/`에만 쓴다. 실전 장부(418660 6주) 무손상.
3. **일봉 OHLCV 만으로 결정론적 체결 판정** — LOC/MOC/LIMIT 세 유형별로 명확한 규칙.
4. **시간 주입**: 프로덕션 `datetime.now()` 호출부를 최소 침습적으로 우회. 실전 파일 수정 없음.

---

## 3. 아키텍처

### 3-1. 파일 구조

```
backtest/
├── __init__.py
├── run.py                # CLI 엔트리포인트
├── fetch_ohlcv.py        # ka10081 호출 + 캐시
├── sandbox_config.py     # BacktestConfig(Config 상속)
├── engine.py             # 일일 루프 (09:05/15:25/17:00)
├── fill_model.py         # 주문 체결 판정 순수함수
├── reporter_md.py        # report.md 생성
├── reporter_csv.py       # trades.csv + daily.csv 생성
└── reporter_html.py      # dashboard.html 생성

data/backtest/            # .gitignore 에 추가
├── ohlcv_418660.json     # ka10081 캐시 (600봉)
├── ledger.json           # 샌드박스 장부
├── reverse_config.json
├── seed.json
├── locks.json
├── history.json          # 졸업 기록
├── trades.csv            # 체결 로그
├── daily.csv             # 일별 상태
├── report.md             # 내러티브 일지
└── dashboard.html
```

### 3-2. 실행 커맨드

```bash
python -m backtest.run \
  --ticker 418660 \
  --start 2025-02-18 \
  --end 2026-04-20 \
  --seed 10000000 \
  --split 40 \
  --target 7.0 \
  --compound 70 \
  --reverse-exit -10.0
```

모든 파라미터 기본값은 현재 프로덕션 설정과 동일.

---

## 4. 데이터 플로우

### 4-1. 1단계: 데이터 수집 (`fetch_ohlcv.py`)

- 키움 `ka10081` 주식일봉차트조회요청 한 번 호출 → 최대 600봉
- `end_date` 를 요청일로 지정하면 과거로 거슬러 올라가며 봉을 받음
- 2025-02-18 로부터 MA5 계산용 5 거래일치 여유 확보하려면 2024-12 부근까지 포함
- 결과 JSON: `{"YYYY-MM-DD": {"open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}}`
- 캐시 파일 존재 시 네트워크 호출 스킵 (수동 삭제 시 재획득)
- **실패 시**: 캐시 있으면 경고 후 캐시 사용. 캐시 없으면 abort.

### 4-2. 2단계: 거래일 산출

- `pandas_market_calendars.XKRX` 로 2025-02-18 ~ 2026-04-20 거래일 리스트 생성
- 봉 데이터에 없는 날짜(임시휴장 등) 제거
- 각 거래일에 대해 `engine.daily_tick(sim_date, bar, cfg)` 호출

### 4-3. 3단계: 일일 루프 (`engine.py`)

각 거래일마다 3개 단계를 순서대로 실행:

```
┌─ 09:05 단계 ───────────────────────────────────────
│  입력:
│    curr_p = bar.open
│    prev_c = 전일 bar.close (없으면 이전 봉)
│    ma5    = 전일 포함 직전 5 거래일 close 평균
│    cash   = cfg 에서 get_total_locked_cash 고려한 available
│
│  strategy.v14_plugin.get_plan(...) 호출 → orders
│  _merge_star_sell_to_target(orders) 적용 (KR 후처리)
│
│  각 order 에 대해:
│    - type in {LIMIT}: 즉시 체결 판정 → fill_model.check_limit(bar, order)
│    - type in {LOC, MOC}: 보류 큐에 저장 (15:25 처리용)
│  체결된 LIMIT → overwrite_incremental_ledger 로 장부 기록
└────────────────────────────────────────────────────

┌─ 15:25 단계 ───────────────────────────────────────
│  보류 큐의 LOC/MOC 주문 일괄 발송:
│    LOC → LIMIT: fill_model.check_loc(bar, order)
│    MOC → MARKET: 항상 Close 체결
│  체결된 주문 → overwrite_incremental_ledger
└────────────────────────────────────────────────────

┌─ 17:00 단계 (EOD) ──────────────────────────────────
│  1. cfg.reset_locks()
│  2. 리버스 체크:
│     rev_state = cfg.get_reverse_state(ticker)
│     if rev_state.is_active:
│       curr_p = bar.close
│       actual_avg = calculate_holdings()[1]
│       curr_ret = (curr_p - actual_avg) / actual_avg * 100
│       if curr_ret >= -10.0:  # KR override
│           set_reverse_state(False, 0, 0)
│           clear_escrow_cash()
│           ledger 의 is_reverse=True 전부 False 로 롤백
│           → 탈출 이벤트 기록
│       else:
│           cfg.increment_reverse_day(ticker)
│  3. 졸업 감지:
│     ledger_qty > 0 AND 보유계산 후 qty == 0:
│       → archive_graduation() → 시드 += profit * 0.7
│       → 졸업 이벤트 기록
└────────────────────────────────────────────────────
```

모든 주요 상태 변화는 `events` deque 에 (day, phase, kind, payload) 튜플로 append. 루프 종료 후 reporter 들이 소비.

---

## 5. 샌드박스 Config 설계

### 5-1. `BacktestConfig(Config)`

```python
class BacktestConfig(Config):
    def __init__(self, sandbox_dir, seed, split, target_pct, compound_rate, ticker):
        self.SANDBOX_DIR = sandbox_dir
        self.FILES = {
            "LEDGER":       f"{sandbox_dir}/ledger.json",
            "REVERSE_CFG":  f"{sandbox_dir}/reverse_config.json",
            "LOCKS":        f"{sandbox_dir}/locks.json",
            "HISTORY":      f"{sandbox_dir}/history.json",
            "CACHE":        f"{sandbox_dir}/cache.json",
            # 등등 — 모든 FILES 경로를 sandbox_dir 아래로
        }
        self._sim_date = None
        # 기본 설정 주입 (seed/split/target/compound)
```

### 5-2. 시간 주입 오버라이드

프로덕션 `Config` 에서 `datetime.now()` / `market_context.now()` 사용 지점:

| 메서드 | 현 동작 | 백테스트 오버라이드 |
|-------|--------|-------------------|
| `set_reverse_state(..., last_update_date=None)` | `datetime.now(US/Eastern)` | `self._sim_date` |
| `set_lock(ticker, market_type)` | `datetime.now(US/Eastern)` | `self._sim_date` |
| `check_lock(ticker, market_type)` | `datetime.now(US/Eastern)` | `self._sim_date` |
| `increment_reverse_day(ticker)` | `market_context.now()` | monkeypatch `market_context.now` 를 lambda 로 교체 |

`overwrite_ledger`, `overwrite_incremental_ledger` 등은 호출자(엔진)에서 `date` 인자로 명시적 주입 → 내부 `now()` 없음.

### 5-3. 엔진 루프에서 날짜 갱신

```python
import market_context
os.environ['BROKER'] = 'KIWOOM'  # market_context 가 KST/XKRX 분기 타도록

for sim_date in trading_days:
    cfg._sim_date = sim_date
    market_context.now = lambda d=sim_date: d  # 클로저 주의
    market_context.is_trading_day = lambda d: True  # 이미 필터됨
    engine.daily_tick(sim_date, bar, cfg)
```

---

## 6. 체결 모델 (`fill_model.py`)

### 6-1. 판정 규칙

| 주문 유형 | 체결 조건 | 체결가 | 비고 |
|----------|----------|-------|------|
| LIMIT BUY @ P | `Low ≤ P` | `min(Open, P)` | 갭다운 개선 (Open < P면 Open) |
| LIMIT SELL @ P | `High ≥ P` | `max(Open, P)` | 갭업 개선 (Open > P면 Open) |
| LOC BUY @ P | `Close ≤ P` | `P` | 15:25 LIMIT 변환 후 종가 판정 |
| LOC SELL @ P | `Close ≥ P` | `P` | 동일 |
| MOC BUY | 항상 | `Close` | 15:25 MARKET 변환 |
| MOC SELL | 항상 | `Close` | 동일 |

### 6-2. 동시 체결 우선순위

같은 날 여러 주문이 조건 만족 시 처리 순서:

1. LIMIT SELL (익절)
2. LIMIT BUY
3. LOC (SELL 먼저, 그다음 BUY)
4. MOC (SELL 먼저, 그다음 BUY)

각 체결 후 `calculate_holdings()` 재계산 → 다음 체결은 갱신된 포지션 기준. 자전거래 방호벽(`_apply_wash_trade_shield`)은 프로덕션 코드가 이미 order 생성 단계에서 처리하므로 중복 방어 불필요.

### 6-3. 수량

항상 **주문 수량 전량 체결**. 부분체결 없음. 418660 ETF 일평균 거래량 대비 우리 수량(최대 수십~수백주)은 유동성 문제 없음.

---

## 7. 출력 포맷

### 7-1. `report.md` (일별 내러티브)

매 거래일 1개 블록. V14 일반일 / 리버스일 / 이벤트일(진입/탈출/졸업) 모두 동일 레벨.

```markdown
## 📅 2025-02-18 (화) · T=0.000 · 🌓V14 새출발
OHLC: 10,245 / 10,380 / 10,180 / 10,310 · MA5: 10,150

주문 장전 (09:05):
- 🆕새출발 BUY 11,839원 × 24주 [LOC]

체결 (15:25):
- ✅ 🆕새출발 BUY 11,839원 × 24주 @ 10,310원 → 24주 · 평단 10,310원

상태: 현금 9,752,560원 · 평가액 247,440원 · T=1.0 · 별값 없음
```

이벤트 블록 (진입/탈출/졸업)은 별도 헤더(`## 🚨`, `## 🌤️`, `## 🎓`)로 구분. **리버스 중인 날도 매일 전체 블록 포함** — 주문/체결/상태 전부.

### 7-2. `trades.csv`

체결 한 건당 한 행:

```
date,ticker,side,qty,price,type,desc,is_reverse,cash_after,qty_after,avg_after,t_val_after
```

### 7-3. `daily.csv`

일자별 상태 스냅샷:

```
date,open,high,low,close,volume,ma5,phase,is_reverse,rev_day,t_val,qty,avg,cash,equity,pnl_day,pnl_cum,star_price,target_price
```

### 7-4. `dashboard.html` (Plotly + Jinja2)

- **상단 카드**: 총 수익률 / 졸업 횟수 / 최대 리버스 일수 / 최종 자본 / 최종 시드
- **자본곡선**: 현금 + 평가액 스택 에리어 + 418660 종가 라인 오버레이 (우측 y축)
- **사이클 표**: 시작일/종료일/최대 T/리버스 일수/실현손익/수익률/복리 적립액
- **이벤트 타임라인**: 리버스 진입 🚨 / 탈출 🌤️ / 졸업 🎓 마커
- **리버스 밴드**: 자본곡선 배경에 리버스 구간 연한 빨강 음영
- **일자 클릭**: `report.md#YYYY-MM-DD` 앵커로 점프

---

## 8. 엣지 케이스

- **MA5 부족** (2025-02-18 직전 5일치 덜 받아졌을 때): available 데이터만으로 평균. 600봉 여유분에서 해결될 예정.
- **첫날 prev_close**: 시작일 직전 거래일 close. 없으면 Open 으로 대체.
- **잔고 부족**: 프로덕션의 `is_money_short` 로직 그대로 사용 → 방어모드 + 리버스 트리거 조건 반영.
- **0주 상태에서 기존 LIMIT 미체결**: 09:05 에 새 plan 받기 전 보류 큐 전부 폐기 (프로덕션 `cancel_all_orders_safe` 미러).
- **리버스 1일차 의무매도 수량 > 보유**: `sell_qty = qty` 로 전량 청산 (strategy_v14.py:174 규칙).
- **리버스 탈출 직후 같은 날 졸업**: 탈출 처리(`is_reverse=False`) → 잔고 재평가 → `archive_graduation` 진입. 이벤트 블록 2개 분리.
- **복리 전파 검증**: 졸업 뒤 첫 거래일의 `one_portion_amt` 가 새 시드 기준으로 갱신됐는지 assert.

### 범위 외

- **세금/수수료 미모델링** — 약간 낙관적. 추후 확장 시: 매수 수수료 0.015%, 매도 수수료 0.015% + 증권거래세 + 농특세 합계 약 0.23%.
- **호가단위** — 가격 1원 단위 반올림은 프로덕션 `_round_to_krw_tick` 으로 이미 처리됨. 백테스트도 order 생성 단계에서 그대로 적용.
- **부분체결 없음** — 전량 체결 가정.

---

## 9. 검증 (self-assertion)

실행 중 매 거래일 EOD 에 다음 불변식 체크:

1. **자본 보존**: `cash + (qty × close) + escrow_cash ≈ 이전일 자본 + 당일 체결 기반 P&L` (오차 ≤ 1원)
2. **장부 무결성**: `calculate_holdings()` 결과가 수동 집계와 일치
3. **T 값 유효 범위**: `0 ≤ t_val ≤ split * 1.2` (너무 벗어나면 로직 버그 의심)

위반 시 즉시 assert 실패 + 문제 일자 명시.

---

## 10. 구현 범위 밖

- 다중 티커 동시 백테스트 (현재 418660 단일만)
- 파라미터 스위프/최적화 (시드/분할/목표 등 튜닝은 추후)
- 미국주식 브로커(KoreaInvestmentBroker) 백테스트
- 실시간 병렬 백테스트 (배치 단일 실행만)

---

## 11. 승인 대기 항목

이 설계가 최종 승인되면 `superpowers:writing-plans` 로 넘어가 각 모듈의 구체적 구현 단계 계획을 작성한다.
