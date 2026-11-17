#!/usr/bin/env python3
"""Entry timer for SET stocks (set-entry). Standard library only.

    python3 entry.py check PTT                      # waiting / triggered / expired
    python3 entry.py check PTT --write              # also save trader-set/entry.json
    python3 entry.py check DELTA --level 180        # breakout over your own level
    python3 entry.py watch PTT --every 60           # re-check until it triggers
    python3 entry.py watchlist                      # every symbol in trader-set/watchlist.json

The setup: an opening-range breakout, long only.
  - Opening range = the first --or-minutes of the morning session
    (default 15: the 10:00, 10:05 and 10:10 five-minute bars; the 10:00 bar
    carries the opening auction).
  - Entry = the first COMPLETED 5-minute bar after the range that CLOSES above
    the range high (or above --level). A wick through the high is not enough.
  - No entries before --from (default 10:15) or after --until (default
    15:30), and none in the lunch break: a trigger bar must close inside a
    session.
  - Optional --vol 1.5: the trigger bar's volume must be at least 1.5x the
    average volume of the range bars (the auction bar left out).

Status: closed-day, pre-open, forming (range not finished), waiting (with how
far the last close is from the trigger), triggered (time and price),
expired (past --until with no trigger).

Data: Yahoo Finance 5-minute bars, PTT -> PTT.BK. Free and unofficial;
quotes can be delayed. The tool prints how old the last bar is.
--offline FILE reads a saved chart JSON; --now "2026-11-17 10:20" pins the clock.
"""

import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setmarket as sm  # noqa: E402


def opening_range(day_bars, n):
    rng = [b for b in day_bars if sm.slot_of(b) is not None and sm.slot_of(b) < n]
    if len(rng) < n:
        return None
    return {
        "high": max(b["h"] for b in rng),
        "low": min(b["l"] for b in rng),
        "bars": rng,
        "end": rng[-1]["t"] + sm.BAR,
    }


def evaluate(bars, now, or_minutes=15, level=None, start="10:15", until="15:30", vol=None, holidays=None):
    day = now.date()
    res = {"date": day.isoformat(), "now": now.strftime("%Y-%m-%d %H:%M"), "phase": sm.phase(now, holidays),
           "or_minutes": or_minutes, "level": level, "until": until}
    if not sm.trading_day(day, holidays):
        res.update(status="closed-day", reason=sm.holiday_name(day, holidays) or "weekend",
                   next_open=sm.next_trading_day(day, holidays).isoformat())
        return res
    n = max(1, or_minutes // 5)
    today = sm.complete(sm.by_day(bars).get(day, []), now)
    if res["phase"] == "pre-open" or not today:
        res.update(status="pre-open", reason="no completed bar yet today (the morning session opens at 10:00)")
        return res
    last = today[-1]
    res["last_bar"] = sm.hm(last["t"])
    res["last_close"] = last["c"]
    res["data_age_min"] = int((now - (last["t"] + sm.BAR)).total_seconds() // 60)
    rng = opening_range(today, n)
    if rng is None:
        res.update(status="forming", reason="the opening range ends at %s" % sm.hm(
            sm.at(day, sm.SLOTS[n - 1]) + sm.BAR))
        return res
    res["or_high"], res["or_low"] = rng["high"], rng["low"]
    trigger = float(level) if level is not None else rng["high"]
    res["trigger"] = trigger
    t_from = sm.parse_hhmm(start, "--from")
    t_until = sm.parse_hhmm(until, "--until")
    avg_vol = None
    vb = [b["v"] for b in rng["bars"] if sm.slot_of(b) != 0]
    if vb:
        avg_vol = sum(vb) / len(vb)
    for b in today:
        s = sm.slot_of(b)
        if s is None or s < n:
            continue
        end = (b["t"] + sm.BAR).timetz().replace(tzinfo=None)
        if end < t_from or end > t_until:
            continue
        if b["c"] > trigger:
            if vol and avg_vol and b["v"] < vol * avg_vol:
                continue
            res.update(status="triggered", entry=b["c"], entry_time=sm.hm(b["t"] + sm.BAR),
                       bar=sm.hm(b["t"]), bar_volume=b["v"])
            return res
    nowt = now.timetz().replace(tzinfo=None)
    if nowt >= t_until:
        res.update(status="expired", reason="no 5-minute close above %s by %s" % (sm.px(trigger), until))
        return res
    gap = trigger - last["c"]
    res.update(status="waiting", away=gap, away_pct=100.0 * gap / trigger if trigger else None)
    return res


def describe(sym, r):
    head = "%s  %s  (%s)" % (sym, r["now"], sm.PHASE_TEXT.get(r["phase"], r["phase"]))
    st = r["status"]
    lines = [head]
    if "or_high" in r:
        lines.append("  opening range (%d min): %s - %s" % (r["or_minutes"], sm.px(r["or_low"]), sm.px(r["or_high"])))
    if r.get("level") is not None:
        lines.append("  trigger level: %s (yours)" % sm.px(r["level"]))
    if st == "triggered":
        lines.append("  TRIGGERED at %s: the %s bar closed at %s, above %s" % (
            r["entry_time"], r["bar"], sm.px(r["entry"]), sm.px(r["trigger"])))
        lines.append("  next: /set-exit to set the stop and target before you buy")
    elif st == "waiting":
        lines.append("  WAITING: last close %s (%s bar), %s (%.2f %%) below the trigger %s" % (
            sm.px(r["last_close"]), r["last_bar"], sm.px(r["away"]), r["away_pct"], sm.px(r["trigger"])))
    elif st == "expired":
        lines.append("  EXPIRED: %s" % r["reason"])
    elif st == "closed-day":
        lines.append("  SET is closed (%s). Next trading day: %s" % (r["reason"], r["next_open"]))
    else:
        lines.append("  %s: %s" % (st.upper(), r.get("reason", "")))
    if r.get("data_age_min") is not None and r["data_age_min"] > 10 and st not in ("expired",):
        lines.append("  note: the newest bar ended %d min ago; Yahoo's SET data can be delayed" % r["data_age_min"])
    return "\n".join(lines)


def load(sym, a):
    text = sm.read_offline(a.offline) if a.offline else sm.fetch_chart(sym, "5d", "5m")
    return sm.parse_bars(sm.chart_result(text, sym))


def entry_doc(sym, r):
    keep = {k: r.get(k) for k in ("date", "status", "entry", "entry_time", "bar", "or_high", "or_low",
                                    "or_minutes", "trigger", "level", "now")}
    keep["symbol"] = sm.from_yahoo(sym)
    keep["setup"] = "orb" if r.get("level") is None else "level"
    return keep


def cmd_check(a):
    now = sm.parse_now(a.now)
    hol = sm.load_holidays()
    sym = sm.from_yahoo(a.symbol)
    r = evaluate(load(sym, a), now, a.or_minutes, a.level, a.start, a.until, a.vol, hol)
    note = sm.calendar_note(now.date(), hol)
    if a.json:
        print(json.dumps(dict(r, symbol=sym), indent=2, default=str))
    else:
        print(describe(sym, r))
        if note:
            print("  calendar: " + note)
    if a.write and r["status"] == "triggered":
        sm.write_json(a.out, entry_doc(sym, r))
        print("  wrote %s" % a.out)
    return 0


def cmd_watch(a):
    sym = sm.from_yahoo(a.symbol)
    hol = sm.load_holidays()
    while True:
        now = sm.parse_now(None)
        try:
            r = evaluate(load(sym, a), now, a.or_minutes, a.level, a.start, a.until, a.vol, hol)
        except sm.DataError as e:
            print("  data error: %s (retrying)" % e)
            time.sleep(a.every)
            continue
        print(describe(sym, r))
        sys.stdout.flush()
        if r["status"] in ("triggered", "expired", "closed-day") or r["phase"] == "closed":
            if r["status"] == "triggered" and a.write:
                sm.write_json(a.out, entry_doc(sym, r))
                print("  wrote %s" % a.out)
            return 0
        time.sleep(a.every)


def cmd_watchlist(a):
    wl = sm.read_json(a.watchlist)
    if not wl:
        print("no %s yet: run /set-scanner first, or pass symbols to `check`" % a.watchlist)
        return 1
    syms = [x["symbol"] if isinstance(x, dict) else x for x in (wl.get("symbols") or wl.get("hits") or [])]
    now = sm.parse_now(a.now)
    hol = sm.load_holidays()
    for s in syms:
        try:
            text = sm.fetch_chart(s, "5d", "5m")
            r = evaluate(sm.parse_bars(sm.chart_result(text, s)), now, a.or_minutes, None, a.start, a.until, a.vol, hol)
            print(describe(s, r))
        except sm.DataError as e:
            print("%s  data error: %s" % (s, e))
        time.sleep(0.3)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Entry timer for SET stocks (opening-range breakout, long only).")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--or-minutes", type=int, default=15)
        sp.add_argument("--from", dest="start", default="10:15")
        sp.add_argument("--until", default="15:30")
        sp.add_argument("--vol", type=float, default=None)
        sp.add_argument("--now", default=None)
        sp.add_argument("--offline", default=None)
        sp.add_argument("--out", default="trader-set/entry.json")
        sp.add_argument("--write", action="store_true")
        sp.add_argument("--json", action="store_true")

    c = sub.add_parser("check")
    c.add_argument("symbol")
    c.add_argument("--level", type=float, default=None)
    common(c)
    w = sub.add_parser("watch")
    w.add_argument("symbol")
    w.add_argument("--level", type=float, default=None)
    w.add_argument("--every", type=int, default=60)
    common(w)
    l = sub.add_parser("watchlist")
    l.add_argument("--watchlist", default="trader-set/watchlist.json")
    common(l)
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    try:
        return {"check": cmd_check, "watch": cmd_watch, "watchlist": cmd_watchlist}[a.cmd](a)
    except (sm.DataError, ValueError) as e:
        print("set-entry: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
