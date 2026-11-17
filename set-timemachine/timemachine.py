#!/usr/bin/env python3
"""Time Machine for SET stocks (set-timemachine). Standard library only.

    python3 timemachine.py run                         # trader-set/plan.json, 10,000 replays, seed 19
    python3 timemachine.py run --write                 # also save trader-set/timemachine.json
    python3 timemachine.py run --until 16:20 --seed 7 --replays 20000
    python3 timemachine.py run --symbol PTT --date 2026-11-16 --entry 38.60 \\
        --stop 38.35 --target 39.10 --entry-time 11:25

How it works:
  1. Fetch 60 days of Yahoo 5-minute bars (one request). Keep the FULL SET
     sessions before the plan's date: the 10:00 bar to the 16:20/16:25 bar
     and at least 90 % of the 61 slots (10:00-12:25 and 13:55-16:25).
  2. The pool: for every slot 1..60 of the day, each past session's bar as
     ratios to the previous bar's close (open, high, low, close / prev close).
     The 13:55 slot's ratio carries the lunch-break gap, so replays gap over
     lunch the way the stock really does.
  3. One replay starts at the entry price, at the first bar after the entry,
     and walks to --until (default: the plan's flat-by, 16:20). Each bar i
     draws a slot j = i + randint(-2, 2) (kept inside 1..60) and one past bar
     from pool[j], scaled to the current price. The stop is checked before
     the target in each bar: a bar that touches both counts as the stop.
  4. Outcomes: target first, stop first, or neither (still open at --until).
     R = the plan's R at the target, -1 at the stop, otherwise
     (price at --until - entry) / risk. A gap through the stop still counts
     -1R; a real fill can be worse. Fees are NOT in R.
  5. History: the plan's own rule (an opening-range breakout with the same
     range length, stop rule and target R) re-run on each past full session.

Verdict: of the replays that hit a side, the target's share,
target / (target + stop), against the break-even share 1 / (1 + R):
  < 5 points apart     close to a coin flip (1R) / close to break-even
  5 to 15 points       leans toward the target / the stop
  15 points or more    strongly toward the target / the stop
Same plan, same data and same --seed give the same numbers on any machine.
It is a simulation from the stock's own last 60 days, not a prediction.
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setmarket as sm  # noqa: E402

LAST = len(sm.SLOTS) - 1  # 60


class TMError(Exception):
    pass


def slot_at(hhmm):
    """The last slot whose bar ENDS at or before HH:MM."""
    t = sm.parse_hhmm(hhmm)
    best = None
    for i, s in enumerate(sm.SLOTS):
        end = (sm.at(sm.datetime.date(2000, 1, 1), s) + sm.BAR).time()
        if end <= t:
            best = i
    if best is None:
        raise TMError("%s is before the first bar ends (10:05)" % hhmm)
    return best


def sessions_before(bars, day):
    days = sm.by_day(bars)
    out = []
    for d in sorted(days):
        if d < day and sm.full_session(days[d]):
            out.append((d, {sm.slot_of(b): b for b in days[d] if sm.slot_of(b) is not None}))
    return out


def build_pool(sessions):
    pool = [[] for _ in sm.SLOTS]
    for _, by in sessions:
        for j in range(1, len(sm.SLOTS)):
            b, p = by.get(j), by.get(j - 1)
            if b is None or p is None or p["c"] <= 0:
                continue
            pc = p["c"]
            pool[j].append((b["o"] / pc, b["h"] / pc, b["l"] / pc, b["c"] / pc))
    return pool


def pct(a, q):
    s = sorted(a)
    return s[min(len(s) - 1, int(q * len(s)))]


def simulate(pool, entry, stop, target, k, last, replays=10000, seed=19, window=2):
    rng = random.Random(seed)
    risk = entry - stop
    r_target = (target - entry) / risk
    hits = {"target": 0, "stop": 0, "neither": 0}
    rs, closes = [], []
    for _ in range(replays):
        p = entry
        out = None
        for i in range(k, last + 1):
            j = min(LAST, max(1, i + rng.randint(-window, window)))
            if not pool[j]:
                continue
            o, h, l, c = rng.choice(pool[j])
            if p * l <= stop:
                out = "stop"
                break
            if p * h >= target:
                out = "target"
                break
            p = p * c
        if out is None:
            out = "neither"
            rs.append((p - entry) / risk)
            closes.append(p)
        elif out == "stop":
            rs.append(-1.0)
        else:
            rs.append(r_target)
        hits[out] += 1
    n = float(replays)
    return {
        "replays": replays, "seed": seed, "window": window,
        "target": hits["target"] / n, "stop": hits["stop"] / n, "neither": hits["neither"] / n,
        "avg_r": sum(rs) / n, "r_target": r_target,
        "neither_close": {"p5": pct(closes, 0.05), "median": pct(closes, 0.5), "p95": pct(closes, 0.95)}
        if closes else None,
    }


def rule_stop(rule, oh, ol, entry, step):
    rule = (rule or "or-mid").lower()
    if rule == "or-mid":
        return float(sm.tick_down((sm.D(round(oh, 4)) + sm.D(round(ol, 4))) / 2, step))
    if rule == "or-low":
        low = sm.snap(ol, step)
        return float(sm.tick_down(low - sm.tick(low, step), step))
    if rule.startswith("pct:"):
        return float(sm.tick_down(sm.D(entry) * (1 - sm.D(rule[4:]) / 100), step))
    return None


def history(sessions, plan, last, step):
    n = max(1, int(plan.get("or_minutes") or 15) // 5)
    r_t = float(plan["target_r"])
    rule = plan.get("stop_rule") or "or-mid"
    res = {"sessions": len(sessions), "fired": 0, "target": 0, "stop": 0, "neither": 0, "rule": rule,
           "skipped_rule": None, "days": []}
    if rule_stop(rule, 1.0, 0.9, 1.0, None) is None:
        res["skipped_rule"] = "the stop rule %r cannot be replayed on past days" % rule
        return res
    for d, by in sessions:
        rngb = [by[i] for i in range(n) if i in by]
        if len(rngb) < n:
            continue
        oh, ol = max(b["h"] for b in rngb), min(b["l"] for b in rngb)
        entry = None
        for i in range(n, last + 1):
            b = by.get(i)
            if b and b["c"] > oh and i <= slot_at("15:25"):
                entry, k = b["c"], i + 1
                break
        if entry is None:
            continue
        stop = rule_stop(rule, oh, ol, entry, step)
        if stop is None or stop >= entry:
            continue
        target = entry + r_t * (entry - stop)
        res["fired"] += 1
        out = "neither"
        for i in range(k, last + 1):
            b = by.get(i)
            if not b:
                continue
            if b["l"] <= stop:
                out = "stop"
                break
            if b["h"] >= target:
                out = "target"
                break
        res[out] += 1
        res["days"].append({"date": d.isoformat(), "entry": entry, "stop": stop, "target": round(target, 4),
                            "outcome": out})
    return res


def verdict(mc):
    hit = mc["target"] + mc["stop"]
    if hit <= 0:
        return "No replay reached the stop or the target: the close decides this trade."
    share = mc["target"] / hit
    even = 1.0 / (1.0 + mc["r_target"])
    gap = 100.0 * (share - even)
    one_r = abs(mc["r_target"] - 1.0) < 0.05
    if abs(gap) < 5:
        v = "Close to a coin flip." if one_r else "Close to break-even."
    elif abs(gap) < 15:
        v = "Leans toward the target." if gap > 0 else "Leans toward the stop."
    else:
        v = "Strongly toward the target." if gap > 0 else "Strongly toward the stop."
    return "%s Target share %.1f %% of the replays that hit a side; break-even at %.1fR is %.1f %%." % (
        v, 100 * share, mc["r_target"], 100 * even)


def run(text, plan, replays, seed, until):
    bars = sm.parse_bars(sm.chart_result(text, plan["symbol"]))
    day = sm.parse_now(plan["date"]).date()
    sessions = sessions_before(bars, day)
    if len(sessions) < 20:
        raise TMError("only %d full sessions before %s in the data (need 20)" % (len(sessions), day))
    pool = build_pool(sessions)
    et = plan.get("entry_time")
    if not et:
        raise TMError("the plan has no entry_time: pass --entry-time HH:MM (when the entry bar closed)")
    k = slot_at(et) + 1
    last = slot_at(until)
    if k > last:
        raise TMError("the entry at %s is at or after --until %s: nothing to replay" % (et, until))
    entry, stop, target = float(plan["entry"]), float(plan["stop"]), float(plan["target"])
    mc = simulate(pool, entry, stop, target, k, last, replays, seed)
    step = sm.D(plan["tick"]) if plan.get("tick") else None
    hist = history(sessions, plan, last, step)
    return {"symbol": plan["symbol"], "date": plan["date"], "entry": entry, "stop": stop, "target": target,
            "entry_time": et, "until": until, "sessions": len(sessions),
            "first_session": sessions[0][0].isoformat(), "last_session": sessions[-1][0].isoformat(),
            "replay": mc, "history": hist, "verdict": verdict(mc)}


def report(doc):
    mc, h = doc["replay"], doc["history"]
    L = [
        "Time Machine: %s, %s, long from %s at %s, stop %s, target %s (%.2fR), until %s" % (
            doc["symbol"], doc["date"], sm.px(doc["entry"]), doc["entry_time"], sm.px(doc["stop"]),
            sm.px(doc["target"]), mc["r_target"], doc["until"]),
        "  pool: %d full sessions, %s to %s" % (doc["sessions"], doc["first_session"], doc["last_session"]),
        "  %d replays (seed %d):" % (mc["replays"], mc["seed"]),
        "    target first   %5.1f %%" % (100 * mc["target"]),
        "    stop first     %5.1f %%" % (100 * mc["stop"]),
        "    neither        %5.1f %%" % (100 * mc["neither"]),
        "    average R      %+.2f   (before fees)" % mc["avg_r"],
    ]
    if mc.get("neither_close"):
        nc = mc["neither_close"]
        L.append("    still open at %s: median %s, 5-95 %% range %s to %s" % (
            doc["until"], sm.px(nc["median"]), sm.px(nc["p5"]), sm.px(nc["p95"])))
    if h.get("skipped_rule"):
        L.append("  history: skipped (%s)" % h["skipped_rule"])
    else:
        L.append("  history: the same rule fired on %d of %d past sessions: %d target, %d stop, %d neither" % (
            h["fired"], h["sessions"], h["target"], h["stop"], h["neither"]))
    L.append("  verdict: " + doc["verdict"])
    if mc["neither"] > 0.4:
        L.append("  note: more than 40 % of replays hit neither side; the price at %s decides those" % doc["until"])
    if mc["avg_r"] < 0 < (mc["target"] - mc["stop"]) or mc["avg_r"] > 0 > (mc["target"] - mc["stop"]):
        L.append("  note: the average R (%+.2f) goes against the lean" % mc["avg_r"])
    L.append("  A simulation from the last 60 days, not a prediction. Next: /set-budget to size it.")
    return "\n".join(L)


def load_plan(a):
    plan = dict(sm.read_json(a.plan) or {}) if not a.symbol else {}
    for k in ("symbol", "date", "entry", "stop", "target", "entry_time"):
        v = getattr(a, k)
        if v is not None:
            plan[k] = v
    missing = [k for k in ("symbol", "date", "entry", "stop", "target") if plan.get(k) in (None, "")]
    if missing:
        raise TMError("no plan: run /set-exit with --write first, or pass --%s" % " --".join(missing))
    plan["symbol"] = sm.from_yahoo(plan["symbol"])
    e, s, t = float(plan["entry"]), float(plan["stop"]), float(plan["target"])
    if not s < e < t:
        raise TMError("a long plan needs stop < entry < target (got %s / %s / %s)" % (s, e, t))
    plan.setdefault("target_r", round((t - e) / (e - s), 4))
    if a.symbol:
        plan["target_r"] = round((t - e) / (e - s), 4)
        plan.setdefault("stop_rule", a.stop_rule)
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description="Time Machine for SET stocks.")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--plan", default="trader-set/plan.json")
    r.add_argument("--symbol")
    r.add_argument("--date")
    r.add_argument("--entry", type=float)
    r.add_argument("--stop", type=float)
    r.add_argument("--target", type=float)
    r.add_argument("--entry-time")
    r.add_argument("--stop-rule", default="or-mid")
    r.add_argument("--until")
    r.add_argument("--replays", type=int, default=10000)
    r.add_argument("--seed", type=int, default=19)
    r.add_argument("--offline")
    r.add_argument("--out", default="trader-set/timemachine.json")
    r.add_argument("--write", action="store_true")
    r.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        plan = load_plan(a)
        until = a.until or plan.get("flat_by") or "16:20"
        text = sm.read_offline(a.offline) if a.offline else sm.fetch_chart(plan["symbol"], "60d", "5m")
        doc = run(text, plan, a.replays, a.seed, until)
        if a.json:
            print(json.dumps(doc, indent=2, default=str))
        else:
            print(report(doc))
        if a.write:
            sm.write_json(a.out, doc)
            print("  wrote %s" % a.out)
        return 0
    except (TMError, sm.DataError, ValueError) as e:
        print("set-timemachine: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
