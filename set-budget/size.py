#!/usr/bin/env python3
"""Budget and risk check for SET day trades (set-budget). Standard library only.

    python3 size.py check                     # size trader-set/plan.json, PASS or BLOCK
    python3 size.py check --write             # also save trader-set/order.json
    python3 size.py check --account 200000 --max-loss 1500 --price 38.65
    python3 size.py log                       # you placed order.json: add it to the journal
    python3 size.py close --price 39.10       # you got out: record the exit price
    python3 size.py today                     # today's trades, risk used, limits left

Sizing (long only, whole board lots of 100 shares unless config board_lot):
  loss a share at the stop = (entry - stop) + fees on both sides
  fees = fee_rate_pct (default 0.17 %: about 0.157 % commission + 7 % VAT on
         it + exchange fees; set yours from your broker) x price, each side
  shares = the most whole lots inside ALL of:
    max loss per trade      max_loss_per_trade_thb / loss a share
    position cap            max_position_pct of the account / entry
    cash                    account x (1 - cash_buffer_pct) / (entry + fees)
  The limit that decided it is named. A stop too far for the max loss is a
  plain refusal, never a smaller stop.

Checks (each PASS or BLOCK, with the reason):
  plan        stop below entry below target, prices on the stock's tick
  max loss    loss at the stop, fees in, within max_loss_per_trade_thb
  reward:risk net of fees at least min_reward_risk
  day limit   trades today below max_trades_per_day; today's open risk plus
              realised losses plus this trade within daily_loss_limit_thb
  window      for today's plan: between entry_from and entry_until, inside a
              session (not the 12:30-14:00 break), and SET open today
  limits      stop and target inside today's floor and ceiling
  blocked     the symbol is not on your blocked list
  board lot   at least one lot fits
Nothing here places an order. The ticket is for you to type into your
broker's app yourself.
"""

import argparse
import datetime
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setmarket as sm  # noqa: E402


class SizeError(Exception):
    pass


def size(plan, cfg, account=None, max_loss=None, price=None):
    entry = float(plan["entry"])
    if price is not None and float(price) > entry:
        entry_used = float(price)
        entry_note = "the fresh price %s is above the plan's entry %s: sized from %s" % (
            sm.px(price), sm.px(plan["entry"]), sm.px(price))
    else:
        entry_used, entry_note = entry, None
    stop, target = float(plan["stop"]), float(plan["target"])
    fee = float(cfg.get("fee_rate_pct", 0.17)) / 100.0
    lot = int(cfg.get("board_lot") or 100)
    acct = float(account if account is not None else cfg["account_thb"])
    ml = float(max_loss if max_loss is not None else cfg["max_loss_per_trade_thb"])
    loss_ps = (entry_used - stop) + fee * (entry_used + stop)
    gain_ps = (target - entry_used) - fee * (entry_used + target)
    if loss_ps <= 0:
        raise SizeError("the stop %s is not below the entry %s" % (sm.px(stop), sm.px(entry_used)))
    caps = {
        "max loss per trade": ml / loss_ps,
        "position cap (%s %% of the account)" % cfg.get("max_position_pct", 50):
            acct * float(cfg.get("max_position_pct", 50)) / 100.0 / entry_used,
        "cash (after a %s %% buffer)" % cfg.get("cash_buffer_pct", 5):
            acct * (1 - float(cfg.get("cash_buffer_pct", 5)) / 100.0) / (entry_used * (1 + fee)),
    }
    lots = {k: int(math.floor(v / lot + 1e-9)) for k, v in caps.items()}
    decided = min(lots, key=lambda k: lots[k])
    shares = lots[decided] * lot
    return {
        "entry_used": entry_used, "entry_note": entry_note, "stop": stop, "target": target,
        "fee_rate": fee, "board_lot": lot, "account": acct, "max_loss": ml,
        "loss_per_share": loss_ps, "gain_per_share": gain_ps,
        "shares": shares, "decided_by": decided, "caps_shares": {k: v * lot for k, v in lots.items()},
        "cost": shares * entry_used, "fees_in": shares * entry_used * fee,
        "loss_at_stop": shares * loss_ps, "gain_at_target": shares * gain_ps,
        "net_r": gain_ps / loss_ps if loss_ps else None,
    }


def journal_today(journal, day):
    return [t for t in (journal or {}).get("trades", []) if t.get("date") == day.isoformat()]


def day_usage(trades):
    open_risk = sum(t["loss_at_stop"] for t in trades if t.get("exit") is None)
    realised = sum(t.get("result_thb", 0) for t in trades if t.get("exit") is not None)
    losses = -min(0.0, realised)
    return {"count": len(trades), "open_risk": open_risk, "realised": realised, "used": open_risk + losses}


def check(plan, cfg, s, now, journal=None, holidays=None):
    res = []

    def add(name, ok, why):
        res.append({"check": name, "ok": bool(ok), "why": why})

    sym = plan["symbol"]
    add("plan", s["stop"] < s["entry_used"] < s["target"],
        "stop %s < entry %s < target %s" % (sm.px(s["stop"]), sm.px(s["entry_used"]), sm.px(s["target"])))
    step = plan.get("tick")
    if step:
        bad = [n for n, v in (("entry", plan["entry"]), ("stop", s["stop"]), ("target", s["target"]))
               if sm.D(round(v, 4)) % sm.D(step) != 0]
        add("tick", not bad, "all on the %s tick" % sm.px(step) if not bad else
            "%s not on the %s tick: re-run /set-exit" % (", ".join(bad), sm.px(step)))
    add("board lot", s["shares"] >= s["board_lot"],
        "%s shares (%d x %d-share lots)" % ("{:,}".format(s["shares"]), s["shares"] // s["board_lot"], s["board_lot"])
        if s["shares"] >= s["board_lot"] else
        "not even one lot of %d fits: %s decides it. %s" % (
            s["board_lot"], s["decided_by"],
            "The stop is too far for your max loss: one lot would lose %s baht at the stop, over your %s." % (
                sm.baht(s["board_lot"] * s["loss_per_share"]), sm.baht(s["max_loss"]))
            if s["decided_by"] == "max loss per trade" else "The account is too small for one lot."))
    add("max loss", s["loss_at_stop"] <= s["max_loss"] + 1e-6,
        "%s baht at the stop, fees in (limit %s)" % (sm.baht(s["loss_at_stop"]), sm.baht(s["max_loss"])))
    mrr = float(cfg.get("min_reward_risk", 1.0))
    add("reward:risk", s["net_r"] is not None and s["net_r"] >= mrr - 1e-9,
        "%.2f after fees (minimum %.2f)" % (s["net_r"] or 0, mrr))
    today = now.date()
    trades = journal_today(journal, today)
    u = day_usage(trades)
    mt = int(cfg.get("max_trades_per_day", 3))
    add("trades today", u["count"] < mt, "%d placed today (limit %d)" % (u["count"], mt))
    dl = float(cfg.get("daily_loss_limit_thb", 3000))
    total = u["used"] + s["loss_at_stop"]
    add("daily loss limit", total <= dl + 1e-6,
        "open risk %s + losses %s + this %s = %s (limit %s)" % (
            sm.baht(u["open_risk"]), sm.baht(-min(0, u["realised"])), sm.baht(s["loss_at_stop"]),
            sm.baht(total), sm.baht(dl)))
    if plan.get("date") == today.isoformat():
        ph = sm.phase(now, holidays)
        t = now.timetz().replace(tzinfo=None)
        t0, t1 = sm.parse_hhmm(cfg.get("entry_from", "10:15")), sm.parse_hhmm(cfg.get("entry_until", "15:30"))
        ok = ph in ("morning", "afternoon") and t0 <= t <= t1
        add("window", ok, "%s, %s (entries %s-%s, not in the lunch break)" % (
            now.strftime("%H:%M"), sm.PHASE_TEXT.get(ph, ph), cfg.get("entry_from"), cfg.get("entry_until")))
    else:
        add("window", False, "the plan is for %s, today is %s: make a fresh plan" % (plan.get("date"), today))
    if plan.get("floor") and plan.get("ceiling"):
        ok = plan["floor"] <= s["stop"] and s["target"] <= plan["ceiling"]
        add("price limits", ok, "floor %s, ceiling %s" % (sm.px(plan["floor"]), sm.px(plan["ceiling"])))
    blocked = [sm.from_yahoo(x) for x in cfg.get("blocked") or []]
    add("blocked", sym not in blocked, "%s is %son your blocked list" % (sym, "" if sym in blocked else "not "))
    return res


def ticket(plan, s):
    q = "{:,}".format(s["shares"])
    return "\n".join([
        "  ORDER TICKET (type it into your broker's app yourself)",
        "    1. BUY  %s  %s shares  limit %s   (about %s baht + fees %s)" % (
            plan["symbol"], q, sm.px(s["entry_used"]), sm.baht(s["cost"]), sm.baht(s["fees_in"])),
        "    2. once filled: STOP sell %s shares at %s   (loss about %s baht, fees in)" % (
            q, sm.px(s["stop"]), sm.baht(s["loss_at_stop"])),
        "       This is the order that matters. If your app has no stop order, set a price",
        "       alert at %s and sell by hand the moment it rings." % sm.px(s["stop"]),
        "    3. target %s (gain about %s baht, fees in): most Thai apps will not hold a" % (
            sm.px(s["target"]), sm.baht(s["gain_at_target"])),
        "       stop and a limit sell on the same shares at once, so keep the stop working",
        "       and sell by hand at the target (an alert at %s helps)." % sm.px(s["target"]),
        "    4. whatever is still open: sell by %s, before the 16:30 closing auction" % plan.get("flat_by", "16:20"),
    ])


def report(plan, s, res):
    passed = all(r["ok"] for r in res)
    L = ["%s %s  %s" % ("PASS" if passed else "BLOCK", plan["symbol"], plan["date"]),
         "  size: %s shares, decided by %s" % ("{:,}".format(s["shares"]), s["decided_by"])]
    for k, v in s["caps_shares"].items():
        L.append("    %-34s %s shares" % (k, "{:,}".format(v)))
    if s["entry_note"]:
        L.append("  note: " + s["entry_note"])
    L.append("  fees: %.3f %% a side (fee_rate_pct); loss a share at the stop %s, gain a share at the target %s" % (
        100 * s["fee_rate"], sm.px(s["loss_per_share"]), sm.px(s["gain_per_share"])))
    for r in res:
        L.append("  [%s] %-16s %s" % ("ok" if r["ok"] else "XX", r["check"], r["why"]))
    if passed and s["shares"] > 0:
        L.append(ticket(plan, s))
        L.append("  After you place it: `size.py log`. When you are out: `size.py close --price X`.")
    else:
        L.append("  BLOCKED: no ticket. Fix what is marked XX, or skip this trade.")
    return "\n".join(L), passed


def load_plan(path):
    plan = sm.read_json(path)
    if not plan:
        raise SizeError("no %s: run /set-exit with --write first" % path)
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description="Budget and risk check for SET day trades.")
    ap.add_argument("--dir", default="trader-set")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check")
    c.add_argument("--account", type=float)
    c.add_argument("--max-loss", type=float)
    c.add_argument("--price", type=float, help="a fresh price; if above the entry, size from it")
    c.add_argument("--now")
    c.add_argument("--write", action="store_true")
    c.add_argument("--json", action="store_true")
    lg = sub.add_parser("log")
    lg.add_argument("--now")
    cl = sub.add_parser("close")
    cl.add_argument("--price", type=float, required=True)
    cl.add_argument("--symbol")
    cl.add_argument("--now")
    td = sub.add_parser("today")
    td.add_argument("--now")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    P = lambda f: os.path.join(a.dir, f)  # noqa: E731
    try:
        cfg = sm.load_config(P("config.json"))
        now = sm.parse_now(a.now)
        journal = sm.read_json(P("journal.json"), {"trades": []})
        if a.cmd == "check":
            plan = load_plan(P("plan.json"))
            s = size(plan, cfg, a.account, a.max_loss, a.price)
            res = check(plan, cfg, s, now, journal, sm.load_holidays(P("holidays.json")))
            text, passed = report(plan, s, res)
            if a.json:
                print(json.dumps({"pass": passed, "size": s, "checks": res}, indent=2))
            else:
                print(text)
            if a.write:
                order = {"status": "PASS" if passed else "BLOCK", "checked_at": now.strftime("%Y-%m-%d %H:%M"),
                         "symbol": plan["symbol"], "date": plan["date"], "side": "buy", "shares": s["shares"],
                         "entry": s["entry_used"], "stop": s["stop"], "target": s["target"],
                         "flat_by": plan.get("flat_by"), "loss_at_stop": round(s["loss_at_stop"], 2),
                         "gain_at_target": round(s["gain_at_target"], 2), "fee_rate": s["fee_rate"],
                         "checks": res}
                sm.write_json(P("order.json"), order)
                print("  wrote %s" % P("order.json"))
            return 0 if passed else 3
        if a.cmd == "log":
            order = sm.read_json(P("order.json"))
            if not order or order.get("status") != "PASS":
                raise SizeError("no passed order in %s: run `size.py check --write` first" % P("order.json"))
            if order.get("date") != now.date().isoformat():
                raise SizeError("order.json is for %s, not today" % order.get("date"))
            journal.setdefault("trades", []).append({
                "date": order["date"], "symbol": order["symbol"], "shares": order["shares"],
                "entry": order["entry"], "stop": order["stop"], "target": order["target"],
                "loss_at_stop": order["loss_at_stop"], "fee_rate": order["fee_rate"],
                "logged_at": now.strftime("%H:%M"), "exit": None})
            sm.write_json(P("journal.json"), journal)
            print("logged: buy %s %s at %s (stop %s, target %s)" % (
                "{:,}".format(order["shares"]), order["symbol"], sm.px(order["entry"]),
                sm.px(order["stop"]), sm.px(order["target"])))
            return 0
        if a.cmd == "close":
            opens = [t for t in journal_today(journal, now.date()) if t.get("exit") is None and
                     (not a.symbol or t["symbol"] == sm.from_yahoo(a.symbol))]
            if not opens:
                raise SizeError("no open trade today in the journal")
            t = opens[-1]
            f = t["fee_rate"]
            t["exit"] = a.price
            t["closed_at"] = now.strftime("%H:%M")
            t["result_thb"] = round(t["shares"] * ((a.price - t["entry"]) - f * (a.price + t["entry"])), 2)
            sm.write_json(P("journal.json"), journal)
            print("closed: %s %s shares, in %s out %s: %s baht after fees" % (
                t["symbol"], "{:,}".format(t["shares"]), sm.px(t["entry"]), sm.px(a.price), sm.baht(t["result_thb"])))
            return 0
        if a.cmd == "today":
            trades = journal_today(journal, now.date())
            u = day_usage(trades)
            print("today %s: %d trades (limit %s), open risk %s, realised %s, daily limit %s" % (
                now.date(), u["count"], cfg.get("max_trades_per_day"), sm.baht(u["open_risk"]),
                sm.baht(u["realised"]), sm.baht(cfg.get("daily_loss_limit_thb"))))
            for t in trades:
                print("  %s %s %s in %s %s" % (t["logged_at"], t["symbol"], "{:,}".format(t["shares"]),
                                               sm.px(t["entry"]),
                                               "out %s: %s" % (sm.px(t["exit"]), sm.baht(t["result_thb"]))
                                               if t.get("exit") is not None else "open, stop %s" % sm.px(t["stop"])))
            return 0
    except (SizeError, sm.DataError, ValueError, KeyError) as e:
        print("set-budget: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
