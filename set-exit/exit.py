#!/usr/bin/env python3
"""Exit planner for SET stocks (set-exit). Standard library only.

    python3 exit.py plan                              # from trader-set/entry.json
    python3 exit.py plan --write                      # save trader-set/plan.json
    python3 exit.py plan --stop or-low --target 1R
    python3 exit.py plan --symbol PTT --entry 38.60 --stop price:38.20 --target 2R
    python3 exit.py show                              # print trader-set/plan.json

Stop rules (long only):
  or-mid       midpoint of the opening range (default)
  or-low       one tick below the opening-range low
  pct:1.5      1.5 % below the entry
  price:38.20  your price
  atr:1.5      1.5x the average true range of today's 5-minute bars so far
Target: 1R, 1.5R, 2R (default) ... or price:39.50.

Every price is put on the stock's own tick ladder, read from its recent prices
(SET now uses finer ticks for some stocks than the classic table; config "ticks"
overrides it). The stop rounds DOWN to a valid price, the target rounds UP, so
the reward is never less than the R asked for; the real R is printed.

It refuses, and says why: a stop at or above the entry, a target at or below
it, a stop fewer than 2 ticks away (one tick of slippage would be most of the
risk), a stop under the day's floor or a target over the day's ceiling
(+-30 % of the previous close; set price_limit_pct in trader-set/config.json).
Flat by: 16:20 by default (config flat_by), ahead of the 16:30 closing auction.
"""

import argparse
import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setmarket as sm  # noqa: E402


class PlanError(Exception):
    pass


def parse_stop(text):
    t = (text or "or-mid").strip().lower()
    if t in ("or-mid", "or-low"):
        return t, None
    for k in ("pct", "price", "atr"):
        if t.startswith(k + ":"):
            try:
                return k, Decimal(t.split(":", 1)[1])
            except Exception:
                break
    raise PlanError("--stop wants or-mid, or-low, pct:N, price:N or atr:N, got %r" % text)


def parse_target(text):
    t = (text or "2R").strip()
    if t.upper().endswith("R"):
        try:
            r = Decimal(t[:-1])
        except Exception:
            raise PlanError("--target wants like 2R or price:N, got %r" % text)
        if r <= 0:
            raise PlanError("--target R must be above zero")
        return "r", r
    if t.lower().startswith("price:"):
        return "price", Decimal(t.split(":", 1)[1])
    raise PlanError("--target wants like 2R or price:N, got %r" % text)


def atr(bars, n=14):
    if len(bars) < 2:
        return None
    trs = []
    for i in range(1, len(bars)):
        b, pc = bars[i], bars[i - 1]["c"]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    trs = trs[-n:]
    return sum(trs) / len(trs)


def compute(entry, stop_rule, stop_param, target_rule, target_param, or_high=None, or_low=None,
            atr_value=None, prev_close=None, limit_pct=30, step=None):
    st = step
    e = sm.snap(entry, st)
    if stop_rule == "or-mid":
        if or_high is None or or_low is None:
            raise PlanError("or-mid needs the opening range: run /set-entry first, or use pct:/price:")
        raw = (sm.D(round(or_high, 4)) + sm.D(round(or_low, 4))) / 2
        stop = sm.tick_down(raw, st)
        why = "opening-range midpoint %s" % sm.px(raw)
    elif stop_rule == "or-low":
        if or_low is None:
            raise PlanError("or-low needs the opening range: run /set-entry first, or use pct:/price:")
        low = sm.snap(or_low, st)
        stop = sm.tick_down(low - sm.tick(low - Decimal("0.0001"), st), st)
        why = "one tick under the range low %s" % sm.px(low)
    elif stop_rule == "pct":
        stop = sm.tick_down(e * (1 - stop_param / 100), st)
        why = "%s %% under the entry" % stop_param
    elif stop_rule == "price":
        stop = sm.tick_down(stop_param, st)
        why = "your price"
    elif stop_rule == "atr":
        if not atr_value:
            raise PlanError("atr: needs today's 5-minute bars")
        stop = sm.tick_down(e - stop_param * sm.D(round(atr_value, 4)), st)
        why = "%sx ATR (%s)" % (stop_param, sm.px(atr_value))
    else:
        raise PlanError("unknown stop rule %r" % stop_rule)
    if stop >= e:
        raise PlanError("the stop %s is not below the entry %s" % (sm.px(stop), sm.px(e)))
    risk = e - stop
    n_stop = sm.ticks_between(stop, e, st)
    if n_stop < 2:
        raise PlanError("the stop %s is only 1 tick under the entry %s: one tick of slippage is the "
                        "whole risk. Use a wider stop." % (sm.px(stop), sm.px(e)))
    if target_rule == "r":
        target = sm.tick_up(e + target_param * risk, st)
    else:
        target = sm.tick_up(target_param, st)
    if target <= e:
        raise PlanError("the target %s is not above the entry %s" % (sm.px(target), sm.px(e)))
    real_r = (target - e) / risk
    notes = []
    ceiling = floor = None
    if prev_close:
        ceiling, floor = sm.price_limits(prev_close, limit_pct)
        if stop < floor:
            raise PlanError("the stop %s is under today's floor %s (-%s %% of the previous close %s)" % (
                sm.px(stop), sm.px(floor), limit_pct, sm.px(prev_close)))
        if target > ceiling:
            raise PlanError("the target %s is over today's ceiling %s (+%s %% of the previous close %s)" % (
                sm.px(target), sm.px(ceiling), limit_pct, sm.px(prev_close)))
    if n_stop < 4:
        notes.append("the stop is only %d ticks away: a fast market can skip it" % n_stop)
    for edge in (Decimal(x) for x in ("2", "5", "10", "25", "50", "100", "200", "400")):
        if stop < edge <= target:
            notes.append("the plan crosses %s baht, where the tick size can change: check the "
                         "stop and target are valid prices in your broker's app" % edge)
            break
    return {
        "entry": float(e), "stop": float(stop), "target": float(target),
        "risk_per_share": float(risk), "reward_per_share": float(target - e),
        "target_r": float(round(real_r, 2)), "stop_why": why,
        "tick": float(sm.tick(e, st)),
        "stop_ticks": n_stop, "target_ticks": sm.ticks_between(e, target, st),
        "ceiling": float(ceiling) if ceiling is not None else None,
        "floor": float(floor) if floor is not None else None,
        "notes": notes,
    }


def gather(a, cfg):
    ent = sm.read_json(a.entry_file) or {}
    sym = sm.from_yahoo(a.symbol or ent.get("symbol") or "")
    if not sym:
        raise PlanError("no symbol: run /set-entry first, or pass --symbol and --entry")
    entry = a.entry if a.entry is not None else ent.get("entry")
    if entry is None:
        raise PlanError("no entry price: run /set-entry (it must say TRIGGERED), or pass --entry")
    now = sm.parse_now(a.now)
    day = sm.parse_now(a.date).date() if a.date else (
        sm.parse_now(ent["date"]).date() if ent.get("date") and a.entry is None else now.date())
    or_high = ent.get("or_high") if ent.get("symbol") == sym else None
    or_low = ent.get("or_low") if ent.get("symbol") == sym else None
    prev_close = atr_value = step = None
    step_why = "classic SET table"
    if not a.no_data:
        text = sm.read_offline(a.offline) if a.offline else sm.fetch_chart(sym, "5d", "5m")
        bars = sm.parse_bars(sm.chart_result(text, sym))
        days = sm.by_day(bars)
        before = [d for d in sorted(days) if d < day]
        if before:
            prev_close = days[before[-1]][-1]["c"]
        step, step_why = sm.stock_tick(sym, bars, entry, cfg)
        today = days.get(day, [])
        if a.entry_time or ent.get("entry_time"):
            et = sm.parse_hhmm(a.entry_time or ent.get("entry_time"), "--entry-time")
            today = [b for b in today if (b["t"] + sm.BAR).timetz().replace(tzinfo=None) <= et]
        atr_value = atr(today)
        if or_high is None and today:
            n = max(1, a.or_minutes // 5)
            rng = [b for b in today if sm.slot_of(b) is not None and sm.slot_of(b) < n]
            if len(rng) == n:
                or_high, or_low = max(b["h"] for b in rng), min(b["l"] for b in rng)
    return {"symbol": sym, "date": day.isoformat(), "entry": entry,
            "entry_time": a.entry_time or ent.get("entry_time"),
            "or_high": or_high, "or_low": or_low, "or_minutes": ent.get("or_minutes", a.or_minutes),
            "prev_close": prev_close, "atr": atr_value, "step": step, "step_why": step_why}


def build(a):
    cfg = sm.load_config(a.config)
    g = gather(a, cfg)
    sr, sp = parse_stop(a.stop)
    tr, tp = parse_target(a.target)
    c = compute(g["entry"], sr, sp, tr, tp, g["or_high"], g["or_low"], g["atr"], g["prev_close"],
                cfg.get("price_limit_pct", 30), g["step"])
    plan = {
        "symbol": g["symbol"], "date": g["date"], "side": "buy", "entry_time": g["entry_time"],
        "stop_rule": a.stop, "target_rule": a.target, "or_minutes": g["or_minutes"],
        "or_high": g["or_high"], "or_low": g["or_low"], "prev_close": g["prev_close"],
        "flat_by": a.flat_by or cfg.get("flat_by", "16:20"), "tick_source": g["step_why"],
    }
    plan.update(c)
    return plan


def describe(p):
    lines = [
        "%s exit plan for %s (long)" % (p["symbol"], p["date"]),
        "  entry   %s%s" % (sm.px(p["entry"]), "  at %s" % p["entry_time"] if p.get("entry_time") else ""),
        "  stop    %s  (%s; %s a share at risk, %d ticks)" % (
            sm.px(p["stop"]), p["stop_why"], sm.px(p["risk_per_share"]), p["stop_ticks"]),
        "  target  %s  (%sR; %s a share, %d ticks)" % (
            sm.px(p["target"]), p["target_r"], sm.px(p["reward_per_share"]), p["target_ticks"]),
        "  tick    %s  (%s)" % (sm.px(p["tick"]), p.get("tick_source", "")),
        "  flat by %s either way (the closing auction runs 16:30-16:40)" % p["flat_by"],
    ]
    if p.get("ceiling"):
        lines.append("  today's limits: floor %s, ceiling %s" % (sm.px(p["floor"]), sm.px(p["ceiling"])))
    for n in p.get("notes") or []:
        lines.append("  note: " + n)
    lines.append("  next: /set-timemachine to see the odds, then /set-budget to size it")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Exit planner for SET stocks (long only).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan")
    p.add_argument("--symbol")
    p.add_argument("--entry", type=float)
    p.add_argument("--entry-time")
    p.add_argument("--date")
    p.add_argument("--stop", default="or-mid")
    p.add_argument("--target", default="2R")
    p.add_argument("--flat-by")
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--entry-file", default="trader-set/entry.json")
    p.add_argument("--config", default="trader-set/config.json")
    p.add_argument("--out", default="trader-set/plan.json")
    p.add_argument("--offline")
    p.add_argument("--no-data", action="store_true", help="skip Yahoo (no price limits, no ATR)")
    p.add_argument("--now")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("--out", default="trader-set/plan.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        if a.cmd == "show":
            plan = sm.read_json(a.out)
            if not plan:
                print("no %s yet: run `exit.py plan --write`" % a.out)
                return 1
            print(describe(plan))
            return 0
        plan = build(a)
        print(json.dumps(plan, indent=2) if a.json else describe(plan))
        if a.write:
            sm.write_json(a.out, plan)
            print("  wrote %s" % a.out)
        return 0
    except (PlanError, sm.DataError, ValueError) as e:
        print("set-exit: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
