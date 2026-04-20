"""Plotly + Jinja2 HTML 대시보드."""
import json
import os
from jinja2 import Environment, FileSystemLoader


def _fmt_krw(n):
    try:
        return f"{int(round(n)):,}원"
    except (TypeError, ValueError):
        return "-"


def _build_equity_traces(snapshots):
    dates = [s["date"] for s in snapshots]
    cashes = [s["cash"] for s in snapshots]
    equities = [s["equity"] for s in snapshots]
    closes = [s["close"] for s in snapshots]

    traces = [
        {"x": dates, "y": cashes, "name": "현금", "type": "scatter",
         "mode": "lines", "stackgroup": "total",
         "line": {"color": "#7bb4f1"}},
        {"x": dates, "y": equities, "name": "평가액", "type": "scatter",
         "mode": "lines", "stackgroup": "total",
         "line": {"color": "#2d7dd2"}},
        {"x": dates, "y": closes, "name": "418660 종가", "type": "scatter",
         "mode": "lines", "yaxis": "y2",
         "line": {"color": "#c42a1c", "dash": "dot"}},
    ]
    layout = {
        "yaxis": {"title": "자본 (원)"},
        "yaxis2": {"title": "종가", "overlaying": "y", "side": "right"},
        "hovermode": "x unified",
        "margin": {"l": 60, "r": 60, "t": 20, "b": 50},
        "shapes": [],
    }
    # 리버스 구간 빨간 밴드
    in_rev = False
    rev_start = None
    for s in snapshots:
        if s.get("is_reverse") and not in_rev:
            in_rev = True
            rev_start = s["date"]
        elif not s.get("is_reverse") and in_rev:
            in_rev = False
            layout["shapes"].append({
                "type": "rect", "xref": "x", "yref": "paper",
                "x0": rev_start, "x1": s["date"], "y0": 0, "y1": 1,
                "fillcolor": "rgba(196, 42, 28, 0.08)", "line": {"width": 0},
            })
    if in_rev and rev_start:
        layout["shapes"].append({
            "type": "rect", "xref": "x", "yref": "paper",
            "x0": rev_start, "x1": snapshots[-1]["date"], "y0": 0, "y1": 1,
            "fillcolor": "rgba(196, 42, 28, 0.08)", "line": {"width": 0},
        })
    return {"traces": traces, "layout": layout}


def write_dashboard(events, snapshots, out_path, ticker, start, end,
                    seed, split, target_pct, compound_rate):
    if not snapshots:
        raise ValueError("snapshots 가 비어있음")

    final = snapshots[-1]
    total_ret = (final["total"] - seed) / seed * 100.0 if seed > 0 else 0.0
    grads = [e for e in events if e.get("kind") == "graduated"]

    max_rev = 0
    for s in snapshots:
        if s.get("rev_day", 0) > max_rev:
            max_rev = s["rev_day"]

    cycles = []
    for g in grads:
        d = g.get("day")
        end_date = d.isoformat() if hasattr(d, "isoformat") else str(d)
        cycles.append({
            "end_date": end_date,
            "profit_fmt": _fmt_krw(g.get("profit", 0)),
            "yield_pct": f"{g.get('yield_pct', 0):.2f}",
            "added_seed_fmt": _fmt_krw(g.get("added_seed", 0)),
            "new_seed_fmt": _fmt_krw(g.get("new_seed", 0)),
        })

    equity = _build_equity_traces(snapshots)

    tmpl_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(tmpl_dir))
    tmpl = env.get_template("dashboard.html.j2")
    html = tmpl.render(
        ticker=ticker,
        start=start.isoformat() if hasattr(start, "isoformat") else str(start),
        end=end.isoformat() if hasattr(end, "isoformat") else str(end),
        seed_fmt=_fmt_krw(seed),
        split=split, target_pct=target_pct, compound_rate=compound_rate,
        total_return_pct=f"{total_ret:+.2f}",
        return_cls="pos" if total_ret >= 0 else "neg",
        final_total_fmt=_fmt_krw(final["total"]),
        final_seed_fmt=_fmt_krw(final["seed"]),
        num_graduations=len(grads),
        max_rev_days=max_rev,
        cycles=cycles,
        equity_data_json=json.dumps(equity),
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
