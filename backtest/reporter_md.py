"""
일별 내러티브 마크다운 리포트.

events: engine.events deque 내용
snapshots: [engine.daily_snapshot(d) for d in trading_days]
"""
import datetime
from collections import defaultdict


def _fmt(n):
    try:
        return f"{int(round(n)):,}"
    except (TypeError, ValueError):
        return "-"


def _group_by_day(events):
    g = defaultdict(list)
    for e in events:
        g[e["day"]].append(e)
    return g


def _render_day_block(date_str, snap, day_events):
    lines = []
    rev = snap.get("is_reverse")
    if rev:
        phase_label = f"🔄리버스({snap.get('rev_day')}일차)"
    else:
        phase_label = "🌓V14"
    lines.append(f"## 📅 {date_str} · T={snap.get('t_val', 0.0):.3f} · {phase_label}")

    lines.append(
        f"OHLC: {_fmt(snap['open'])} / {_fmt(snap['high'])} / "
        f"{_fmt(snap['low'])} / {_fmt(snap['close'])} · MA5: {_fmt(snap.get('ma5', 0))}"
    )
    lines.append("")

    placed = [e for e in day_events if e["kind"] == "order_placed"]
    if placed:
        lines.append("주문 장전 (09:05):")
        for e in placed:
            o = e["order"]
            if o["type"] == "MOC":
                price_str = "시장가"
            else:
                price_str = f"{_fmt(o['price'])}원"
            lines.append(
                f"- {o.get('desc', '')} {o['side']} {price_str} × {o['qty']}주 [{o['type']}]"
            )
        lines.append("")

    fills = [e for e in day_events if e["kind"] == "order_filled"]
    unfilled = [e for e in day_events if e["kind"] == "order_unfilled"]
    if fills or unfilled:
        lines.append("체결:")
        for e in fills:
            o = e["order"]
            lines.append(
                f"- ✅ {o.get('desc', '')} {o['side']} {o['qty']}주 "
                f"@ {_fmt(e['fill_price'])}원 → {e['post_qty']}주 · 평단 {_fmt(e['post_avg'])}원"
            )
        if not fills and unfilled:
            lines.append("- (체결 없음)")
        for e in unfilled:
            o = e["order"]
            lines.append(
                f"- ❌ {o.get('desc', '')} {o['side']} {_fmt(o['price'])}원 × {o['qty']}주 "
                f"미체결 (종가 {_fmt(e['close'])}원)"
            )
        lines.append("")

    lines.append(
        f"상태: 현금 {_fmt(snap['cash'])}원 · 평가액 {_fmt(snap['equity'])}원 · "
        f"총 {_fmt(snap['total'])}원"
    )

    # 특수 이벤트 (진입/탈출/졸업) 블록
    for e in day_events:
        k = e["kind"]
        if k == "reverse_entered":
            lines.append("")
            lines.append(f"### 🚨 리버스 진입 · {date_str}")
            lines.append(
                f"수익률 {e.get('curr_return', 0):.2f}% · T={e.get('t_val', 0):.2f} · "
                f"exit_target 저장 {e.get('exit_target', 0):.1f}%"
            )
        elif k == "reverse_exited":
            lines.append("")
            lines.append(f"### 🌤️ 리버스 확정 탈출 · {date_str}")
            lines.append(
                f"수익률 {e.get('curr_return', 0):.2f}% ≥ 기준 {e.get('threshold', 0):.1f}% · "
                f"is_reverse 플래그 전부 False 롤백"
            )
        elif k == "graduated":
            lines.append("")
            lines.append(f"### 🎓 사이클 졸업 · {date_str}")
            lines.append(
                f"실현손익 {_fmt(e.get('profit', 0))}원 · 수익률 {e.get('yield_pct', 0):.2f}% · "
                f"복리 +{_fmt(e.get('added_seed', 0))}원 → 시드 "
                f"{_fmt(e.get('old_seed', 0))}원 → {_fmt(e.get('new_seed', 0))}원"
            )

    return "\n".join(lines)


def write_report(events, snapshots, out_path, ticker, start, end,
                 seed, split, target_pct, compound_rate):
    lines = []
    lines.append(f"# {ticker} 백테스트 일지 · {start} → {end}")
    lines.append("")
    lines.append(
        f"시드 {_fmt(seed)}원 · {split}분할 · 목표 {target_pct}% · 복리 {compound_rate}%"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    grouped = _group_by_day(events)

    for snap in snapshots:
        date_str = snap["date"]
        d = datetime.date.fromisoformat(date_str)
        day_events = grouped.get(d, [])
        lines.append(_render_day_block(date_str, snap, day_events))
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
