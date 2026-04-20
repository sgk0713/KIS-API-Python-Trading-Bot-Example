"""
CLI: python -m backtest.run --start 2025-02-18 --end 2026-04-20

- ka10081 로 일봉 수집 (캐시 활용)
- BacktestConfig 샌드박스 초기화
- BacktestEngine 으로 거래일 루프
- report.md / trades.csv / daily.csv / dashboard.html 생성
"""
import argparse
import datetime
import os

import pandas_market_calendars as mcal
from dotenv import load_dotenv


def parse_args():
    ap = argparse.ArgumentParser(description="418660 V14 백테스트")
    ap.add_argument("--ticker", default="418660")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--seed", type=int, default=10_000_000)
    ap.add_argument("--split", type=int, default=40)
    ap.add_argument("--target", type=float, default=7.0)
    ap.add_argument("--compound", type=int, default=70)
    ap.add_argument("--reverse-exit", type=float, default=-10.0)
    ap.add_argument("--sandbox-dir", default="data/backtest")
    ap.add_argument("--env-file", default=".env.kiwoom")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="캐시만 사용, 키움 API 호출 생략")
    return ap.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.sandbox_dir, exist_ok=True)

    if not args.skip_fetch:
        load_dotenv(args.env_file)

    os.environ["BROKER"] = "KIWOOM"

    # 1) 일봉 수집
    from backtest.fetch_ohlcv import fetch_daily_ohlcv, load_cached_ohlcv
    cache_path = os.path.join(args.sandbox_dir, f"ohlcv_{args.ticker}.json")

    if args.skip_fetch:
        ohlcv = load_cached_ohlcv(cache_path)
        if ohlcv is None:
            raise RuntimeError(f"--skip-fetch 지정했지만 캐시 없음: {cache_path}")
    else:
        from broker_kiwoom import KiwoomBroker
        broker = KiwoomBroker(
            app_key=os.getenv("KIWOOM_APPKEY"),
            app_secret=os.getenv("KIWOOM_SECRETKEY"),
            account_no=os.getenv("KIWOOM_ACCOUNT_NO"),
            is_mock=False,
        )
        end_yyyymmdd = args.end.replace("-", "")
        ohlcv = fetch_daily_ohlcv(broker, args.ticker, end_yyyymmdd, cache_path)

    print(f"✔ OHLCV 수집 완료: {len(ohlcv)}봉")

    # 2) 거래일 계산
    cal = mcal.get_calendar("XKRX")
    sch = cal.schedule(start_date=args.start, end_date=args.end)
    trading_days = [d.date() for d in sch.index]
    trading_days = [d for d in trading_days if d.isoformat() in ohlcv]
    if not trading_days:
        raise RuntimeError("거래일이 없습니다. 범위와 캐시를 확인하세요.")
    print(f"✔ 거래일: {len(trading_days)}일 ({trading_days[0]} ~ {trading_days[-1]})")

    # 3) BacktestConfig + Engine
    from backtest.sandbox_config import BacktestConfig
    from backtest.engine import BacktestEngine

    cfg = BacktestConfig(
        sandbox_dir=args.sandbox_dir, ticker=args.ticker,
        seed=args.seed, split=args.split,
        target_pct=args.target, compound_rate=args.compound,
    )
    engine = BacktestEngine(
        cfg=cfg, ticker=args.ticker,
        ohlcv=ohlcv, reverse_exit_threshold=args.reverse_exit,
    )

    # 4) 루프
    snapshots = []
    for d in trading_days:
        engine.run_day(d)
        snap = engine.daily_snapshot(d)
        if snap is not None:
            snapshots.append(snap)

    print(f"✔ 시뮬 완료: {len(engine.events)}개 이벤트 · {len(snapshots)}일 스냅샷")

    # 5) 리포트 생성
    from backtest.reporter_md import write_report
    from backtest.reporter_csv import write_trades_csv, write_daily_csv
    from backtest.reporter_html import write_dashboard

    start_d = datetime.date.fromisoformat(args.start)
    end_d = datetime.date.fromisoformat(args.end)
    events_list = list(engine.events)

    md_path = os.path.join(args.sandbox_dir, "report.md")
    write_report(events_list, snapshots, md_path, ticker=args.ticker,
                 start=start_d, end=end_d,
                 seed=args.seed, split=args.split,
                 target_pct=args.target, compound_rate=args.compound)
    print(f"✔ report.md 생성: {md_path}")

    trades_path = os.path.join(args.sandbox_dir, "trades.csv")
    write_trades_csv(events_list, trades_path, ticker=args.ticker)
    print(f"✔ trades.csv 생성: {trades_path}")

    daily_path = os.path.join(args.sandbox_dir, "daily.csv")
    write_daily_csv(snapshots, daily_path)
    print(f"✔ daily.csv 생성: {daily_path}")

    html_path = os.path.join(args.sandbox_dir, "dashboard.html")
    write_dashboard(events_list, snapshots, html_path, ticker=args.ticker,
                    start=start_d, end=end_d,
                    seed=args.seed, split=args.split,
                    target_pct=args.target, compound_rate=args.compound)
    print(f"✔ dashboard.html 생성: {html_path}")

    # 6) 요약
    grads = [e for e in events_list if e.get("kind") == "graduated"]
    final_snap = snapshots[-1]
    initial_seed = args.seed
    ret_pct = (final_snap["total"] - initial_seed) / initial_seed * 100.0
    print()
    print("=" * 60)
    print(f"최종 자본: {final_snap['total']:,.0f}원 (수익률 {ret_pct:+.2f}%)")
    print(f"최종 시드: {final_snap['seed']:,}원")
    print(f"졸업 횟수: {len(grads)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
