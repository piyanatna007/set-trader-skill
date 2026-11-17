#!/usr/bin/env python3
"""Chart scanner for SET stocks (set-scanner). Standard library only.

    python3 scan.py daily                       # setups on daily closes, whole list
    python3 scan.py daily --write               # also save trader-set/watchlist.json
    python3 scan.py orb --at 10:15              # opening-range breakouts so far today
    python3 scan.py orb --at 10:30 --write
    python3 scan.py daily --symbols PTT,AOT,DELTA

The list: trader-set/universe.txt if you made one, else universe.txt in this
folder (89 liquid SET names, not an official index). One symbol per line or
space-separated; '#' starts a comment.

Daily setups (on completed daily bars, today's unfinished bar left out):
  breakout20   close above the highest close of the 20 sessions before it
  reclaim20    close back above the 20-day average after closing below it
  oversold     RSI(14) under 30
  bounce       RSI(14) was under 30 yesterday and today closed higher
Filters: --min-price (default 1 baht) and --min-value (average daily value
traded over 20 days, default 50 million baht).

ORB scan: the opening range is the first --or-minutes (default 15: the
10:00-10:10 bars). A hit is a completed 5-minute bar after the range, ending
by --at, that CLOSED above the range high. Sorted by how far over it is.

Data: Yahoo Finance (PTT -> PTT.BK), one request per symbol with a short
pause. Free, unofficial, can be delayed. --offline-dir DIR reads saved
SYM.json(.gz) files instead; --now "2026-11-16 10:30" pins the clock.
"""

import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setmarket as sm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def read_universe(path=None, symbols=None):
    if symbols:
        return [sm.from_yahoo(s) for s in symbols.replace(",", " ").split() if s.strip()]
    for p in (path, "trader-set/universe.txt", os.path.join(HERE, "universe.txt")):
        if p and os.path.exists(p):
            out = []
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.split("#", 1)[0]
                    out.extend(sm.from_yahoo(x) for x in line.split() if x.strip())
            seen = set()
            return [s for s in out if not (s in seen or seen.add(s))]
    raise ValueError("no universe list found")


def get(sym, rng, interval, a):
    if a.offline_dir:
        for pat in ("%s-%s%s.json.gz" % (sym, rng, interval), "%s.json.gz" % sym, "%s.json" % sym, "%s-*.json.gz" % sym):
            hits = glob.glob(os.path.join(a.offline_dir, pat))
            if hits:
                return sm.chart_result(sm.read_offline(hits[0]), sym)
        raise sm.DataError("no offline file for %s" % sym)
    text = sm.fetch_chart(sym, rng, interval)
    time.sleep(a.pause)
    return sm.chart_result(text, sym)


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1 + ag / al)


def daily_setups(bars, now):
    done = [b for b in bars if b["t"].date() < now.date() or now.time() >= sm.ATC_END]
    if len(done) < 22:
        return None, None
    c = [b["c"] for b in done]
    last, prev = c[-1], c[-2]
    out = []
    if last > max(c[-21:-1]):
        out.append("breakout20")
    sma = sum(c[-20:]) / 20
    sma_prev = sum(c[-21:-1]) / 20
    if last > sma and prev <= sma_prev:
        out.append("reclaim20")
    r_now, r_prev = rsi(c), rsi(c[:-1])
    if r_now is not None and r_now < 30:
        out.append("oversold")
    if r_prev is not None and r_prev < 30 and last > prev:
        out.append("bounce")
    value = sum(b["c"] * b["v"] for b in done[-20:]) / 20
    info = {"date": done[-1]["t"].date().isoformat(), "close": last, "change_pct": 100 * (last / prev - 1),
            "rsi": r_now, "sma20": sma, "value_thb": value}
    return out, info


def cmd_daily(a):
    now = sm.parse_now(a.now)
    syms = read_universe(a.universe, a.symbols)
    rows, errors = [], []
    for i, s in enumerate(syms):
        if a.progress:
            print("  %d/%d %s" % (i + 1, len(syms), s), file=sys.stderr)
        try:
            setups, info = daily_setups(sm.parse_bars(get(s, "6mo", "1d", a)), now)
        except sm.DataError as e:
            errors.append("%s: %s" % (s, e))
            continue
        if info is None:
            errors.append("%s: under 22 daily bars" % s)
            continue
        if info["close"] < a.min_price or info["value_thb"] < a.min_value * 1e6:
            continue
        if setups:
            rows.append(dict(info, symbol=s, setups=setups))
    rows.sort(key=lambda r: -r["value_thb"])
    print("SET daily scan, %d symbols, closes to %s (filters: price >= %s, value >= %s M baht/day)" % (
        len(syms), rows[0]["date"] if rows else "-", a.min_price, a.min_value))
    for k in ("breakout20", "reclaim20", "oversold", "bounce"):
        hit = [r for r in rows if k in r["setups"]]
        print("\n  %s: %d" % (k, len(hit)))
        for r in hit:
            print("    %-8s %9s  %+6.2f %%  RSI %5.1f  value %6.0f M" % (
                r["symbol"], sm.px(r["close"]), r["change_pct"], r["rsi"] or 0, r["value_thb"] / 1e6))
    if errors:
        print("\n  skipped %d: %s" % (len(errors), "; ".join(errors[:5]) + (" ..." if len(errors) > 5 else "")))
    if a.write:
        sm.write_json(a.out, {"kind": "daily", "made": now.strftime("%Y-%m-%d %H:%M"),
                              "symbols": [r["symbol"] for r in rows], "hits": rows})
        print("\n  wrote %s (%d symbols): next /set-entry watchlist" % (a.out, len(rows)))
    return 0


def orb_hit(day_bars, cutoff, n):
    bars = sm.complete(day_bars, cutoff)
    rng = [b for b in bars if sm.slot_of(b) is not None and sm.slot_of(b) < n]
    if len(rng) < n:
        return None
    hi, lo = max(b["h"] for b in rng), min(b["l"] for b in rng)
    first = None
    for b in bars:
        s = sm.slot_of(b)
        if s is not None and s >= n and b["c"] > hi:
            first = b
            break
    last = bars[-1]
    value = sum(b["c"] * b["v"] for b in bars)
    return {"or_high": hi, "or_low": lo, "first_close_above": sm.hm(first["t"] + sm.BAR) if first else None,
            "first_price": first["c"] if first else None, "last": last["c"], "last_bar": sm.hm(last["t"]),
            "over_pct": 100 * (last["c"] / hi - 1), "value_thb": value, "hit": first is not None}


def cmd_orb(a):
    now = sm.parse_now(a.now)
    hol = sm.load_holidays()
    day = now.date()
    if not sm.trading_day(day, hol):
        print("SET is closed on %s (%s). Next trading day: %s" % (
            day, sm.holiday_name(day, hol) or "weekend", sm.next_trading_day(day, hol)))
        return 0
    cutoff = sm.at(day, sm.parse_hhmm(a.at, "--at")) if a.at else now
    n = max(1, a.or_minutes // 5)
    syms = read_universe(a.universe, a.symbols)
    rows, errors, checked = [], [], 0
    for i, s in enumerate(syms):
        if a.progress:
            print("  %d/%d %s" % (i + 1, len(syms), s), file=sys.stderr)
        try:
            bars = sm.by_day(sm.parse_bars(get(s, "5d", "5m", a))).get(day, [])
        except sm.DataError as e:
            errors.append("%s: %s" % (s, e))
            continue
        h = orb_hit(bars, cutoff, n)
        if h is None:
            continue
        checked += 1
        if h["hit"] and h["last"] >= a.min_price:
            rows.append(dict(h, symbol=s))
    rows.sort(key=lambda r: -r["over_pct"])
    print("SET opening-range breakouts, %s at %s: %d of %d charts closed above their %d-minute range" % (
        day, cutoff.strftime("%H:%M"), len(rows), checked, a.or_minutes))
    for r in rows:
        print("  %-8s range %s-%s  broke out %s (close %s)  last %s at %s (%+.2f %% vs the high)  value %.0f M" % (
            r["symbol"], sm.px(r["or_low"]), sm.px(r["or_high"]), r["first_close_above"],
            sm.px(r["first_price"]), sm.px(r["last"]), r["last_bar"], r["over_pct"], r["value_thb"] / 1e6))
    if checked == 0:
        print("  no chart has a finished opening range yet (it ends at %s)" % sm.hm(
            sm.at(day, sm.SLOTS[n - 1]) + sm.BAR))
    if errors:
        print("  skipped %d: %s" % (len(errors), "; ".join(errors[:5])))
    if rows and not a.offline_dir:
        age = int((now - sm.at(day, sm.parse_hhmm(max(r["last_bar"] for r in rows))) - sm.BAR).total_seconds() // 60)
        if not a.at and age > 10:
            print("  note: the newest bar ended %d min ago: Yahoo's SET bars are delayed. Check the live "
                  "price in your broker's app before acting." % age)
    if a.write:
        sm.write_json(a.out, {"kind": "orb", "date": day.isoformat(), "at": cutoff.strftime("%H:%M"),
                              "or_minutes": a.or_minutes, "symbols": [r["symbol"] for r in rows], "hits": rows})
        print("  wrote %s: next /set-entry check SYMBOL" % a.out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chart scanner for SET stocks.")
    sub = ap.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--universe")
        sp.add_argument("--symbols")
        sp.add_argument("--min-price", type=float, default=1.0)
        sp.add_argument("--pause", type=float, default=0.25)
        sp.add_argument("--offline-dir")
        sp.add_argument("--now")
        sp.add_argument("--out", default="trader-set/watchlist.json")
        sp.add_argument("--write", action="store_true")
        sp.add_argument("--progress", action="store_true")

    d = sub.add_parser("daily")
    d.add_argument("--min-value", type=float, default=50.0, help="million baht a day, 20-day average")
    common(d)
    o = sub.add_parser("orb")
    o.add_argument("--at")
    o.add_argument("--or-minutes", type=int, default=15)
    common(o)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        return {"daily": cmd_daily, "orb": cmd_orb}[a.cmd](a)
    except (sm.DataError, ValueError) as e:
        print("set-scanner: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
