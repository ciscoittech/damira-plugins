#!/usr/bin/env python3
"""`damira stats` — how the generate-validate loop is doing, from the local log (#475).

Reads ~/.damira/logs/workflows.jsonl only. Nothing is sent anywhere.

A workflow is one loop: saves of one file in one host session until it validates green.
  by skill / framework / vendor  loops, first-pass rate, mean retries-to-green, median
                                 time-to-green, top failing rule IDs
  by model / tier                loops, tokens, estimated cost, cost per validated artifact
                                 (the numbers #498's premium-vs-cheap view builds on)

Costs are estimates at list price from a small local table (events.py), and tokens are
only as good as what the host reports: Claude Code yes, Cursor no.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import events  # noqa: E402

GREEN = ("pass", "warn")


def _since_ts(since: str) -> "str | None":
    """'7d', '24h', or an ISO date → an ISO timestamp to compare event `ts` against."""
    if not since:
        return None
    m = re.fullmatch(r"(\d+)([dh])", since.strip())
    if m:
        secs = int(m.group(1)) * (86400 if m.group(2) == "d" else 3600)
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - secs))
    if re.fullmatch(r"\d{4}-\d\d-\d\d(T\d\d:\d\d:\d\dZ)?", since.strip()):
        return since.strip() if "T" in since else since.strip() + "T00:00:00Z"
    raise ValueError(f"--since: expected 7d, 24h or YYYY-MM-DD, got {since!r}")


def _loops(evs: "list[dict]") -> "list[dict]":
    """Group validate events into loops. v1 events (no loop_id) are one-attempt loops."""
    grouped: "dict[str, list[dict]]" = defaultdict(list)
    for ev in evs:
        grouped[ev.get("loop_id") or ev.get("run_id") or str(id(ev))].append(ev)
    loops = []
    for runs in grouped.values():
        runs.sort(key=lambda e: (e.get("attempt") or 1, e.get("ts") or ""))
        green = next((e for e in runs if e.get("status") in GREEN), None)
        tokens_in = [e["input_tokens"] for e in runs if isinstance(e.get("input_tokens"), int)]
        tokens_out = [e["output_tokens"] for e in runs if isinstance(e.get("output_tokens"), int)]
        costs = [e["est_cost_usd"] for e in runs if isinstance(e.get("est_cost_usd"), (int, float))]
        first = runs[0]
        loops.append({
            "skill": first.get("skill") or "(none)",
            "framework": first.get("framework") or "(none)",
            "vendor": first.get("vendor") or "(none)",
            "model": next((e["model"] for e in runs if e.get("model")), None) or "(unknown)",
            "model_tier": next((e["model_tier"] for e in runs if e.get("model_tier")), None) or "unknown",
            "first_pass": first.get("status") in GREEN,
            "green": green is not None,
            "retries": (green.get("retries") if green and green.get("retries") is not None
                        else runs.index(green) if green else None),
            "time_to_green_ms": green.get("time_to_green_ms") if green else None,
            "failed_rules": [r for e in runs for c in e.get("checks") or [] if c.get("status") == "fail"
                             for r in c.get("rule_ids") or []],
            "input_tokens": sum(tokens_in) if tokens_in else None,
            "output_tokens": sum(tokens_out) if tokens_out else None,
            "est_cost_usd": sum(costs) if costs else None,
        })
    return loops


def _quality(loops: "list[dict]") -> dict:
    retries = [lp["retries"] for lp in loops if lp["retries"] is not None]
    ttg = [lp["time_to_green_ms"] for lp in loops if lp["time_to_green_ms"] is not None]
    return {
        "workflows": len(loops),
        "first_pass_rate": round(sum(lp["first_pass"] for lp in loops) / len(loops), 3) if loops else None,
        "green_rate": round(sum(lp["green"] for lp in loops) / len(loops), 3) if loops else None,
        "mean_retries_to_green": round(statistics.mean(retries), 2) if retries else None,
        "median_time_to_green_ms": int(statistics.median(ttg)) if ttg else None,
        "top_failing_rules": Counter(r for lp in loops for r in lp["failed_rules"]).most_common(5),
    }


def _cost(loops: "list[dict]") -> dict:
    def total(key):
        vals = [lp[key] for lp in loops if lp[key] is not None]
        return sum(vals) if vals else None

    validated = sum(lp["green"] for lp in loops)
    cost = total("est_cost_usd")
    return {
        "workflows": len(loops),
        "validated": validated,
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "est_cost_usd": round(cost, 4) if cost is not None else None,
        "est_cost_per_validated_usd": round(cost / validated, 4) if cost is not None and validated else None,
    }


def compute(since: str = "") -> dict:
    cutoff = _since_ts(since)
    evs = [e for e in events.recent_events(max_bytes=50_000_000)
           if e.get("event") == "validate" and (not cutoff or (e.get("ts") or "") >= cutoff)]
    loops = _loops(evs)
    out = {"since": cutoff, "events": len(evs), "overall": _quality(loops)}
    for dim in ("skill", "framework", "vendor"):
        groups = defaultdict(list)
        for lp in loops:
            groups[lp[dim]].append(lp)
        out[f"by_{dim}"] = {k: _quality(v) for k, v in sorted(groups.items())}
    for dim in ("model", "model_tier"):
        groups = defaultdict(list)
        for lp in loops:
            groups[lp[dim]].append(lp)
        out[f"by_{dim}"] = {k: _cost(v) for k, v in sorted(groups.items())}
    return out


def _pct(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def _n(x, fmt="{}") -> str:
    return "-" if x is None else fmt.format(x)


def format_human(s: dict) -> str:
    lines = [f"damira stats — {s['events']} validate runs"
             + (f" since {s['since']}" if s["since"] else "") + " (local log only)"]
    if not s["events"]:
        lines.append("No validate runs logged yet. They are recorded each time `damira validate` "
                     "or the post-write hook runs.")
        return "\n".join(lines)
    o = s["overall"]
    lines.append(f"workflows {o['workflows']}  first-pass {_pct(o['first_pass_rate'])}  "
                 f"validated {_pct(o['green_rate'])}  retries-to-green {_n(o['mean_retries_to_green'])}  "
                 f"median time-to-green {_n(o['median_time_to_green_ms'], '{}ms')}")
    for dim in ("skill", "framework", "vendor"):
        lines.append(f"\nby {dim}:")
        lines.append(f"  {'':24} {'loops':>6} {'1st-pass':>9} {'retries':>8}  top failing rules")
        for name, q in s[f"by_{dim}"].items():
            rules = ", ".join(f"{r} ({n})" for r, n in q["top_failing_rules"][:3]) or "-"
            lines.append(f"  {name[:24]:24} {q['workflows']:>6} {_pct(q['first_pass_rate']):>9} "
                         f"{_n(q['mean_retries_to_green']):>8}  {rules}")
    lines.append("\nby model (tokens as reported by the host; cost is an estimate at list price):")
    lines.append(f"  {'':28} {'tier':>8} {'loops':>6} {'valid':>6} {'tokens in/out':>18} "
                 f"{'est $':>9} {'$/validated':>12}")
    for name, c in s["by_model"].items():
        tier = events.model_tier(name) if name != "(unknown)" else "unknown"
        tok = (f"{_n(c['input_tokens'])}/{_n(c['output_tokens'])}"
               if c["input_tokens"] is not None else "-")
        lines.append(f"  {name[:28]:28} {tier:>8} {c['workflows']:>6} {c['validated']:>6} {tok:>18} "
                     f"{_n(c['est_cost_usd'], '{:.4f}'):>9} {_n(c['est_cost_per_validated_usd'], '{:.4f}'):>12}")
    lines.append("\nby tier:")
    for name, c in s["by_model_tier"].items():
        lines.append(f"  {name:10} loops {c['workflows']:>5}  validated {c['validated']:>5}  est ${_n(c['est_cost_usd'], '{:.4f}')}"
                     f"  $/validated {_n(c['est_cost_per_validated_usd'], '{:.4f}')}")
    return "\n".join(lines)


def build_parser(p: "argparse.ArgumentParser | None" = None) -> argparse.ArgumentParser:
    p = p or argparse.ArgumentParser(prog="damira stats", description=__doc__.splitlines()[0])
    p.add_argument("--since", default="", help="7d, 24h, or YYYY-MM-DD")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main_with_args(a) -> int:
    try:
        s = compute(a.since)
    except ValueError as exc:
        print(f"damira stats: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(s, indent=2) if a.json else format_human(s))
    return 0


def main() -> None:
    sys.exit(main_with_args(build_parser().parse_args()))


if __name__ == "__main__":
    main()
