"""Offline tests for the SET trader pack. Run: python3 -m unittest discover -s tests -v"""
import datetime
import filecmp
import glob
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
PTT = os.path.join(FIX, "PTT-60d5m.json.gz")
DELTA = os.path.join(FIX, "DELTA-60d5m.json.gz")


def load(folder, name):
    path = os.path.join(ROOT, folder, name + ".py")
    sys.path.insert(0, os.path.join(ROOT, folder))
    spec = importlib.util.spec_from_file_location("%s_%s" % (folder.replace("-", "_"), name), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.path.pop(0)
    return mod


sm = load(".", "setmarket")
entry = load("set-entry", "entry")
exitp = load("set-exit", "exit")
tm = load("set-timemachine", "timemachine")
size = load("set-budget", "size")
scan = load("set-scanner", "scan")


def bars(path):
    return sm.parse_bars(sm.chart_result(sm.read_offline(path), "X"))


class Market(unittest.TestCase):
    def test_slots(self):
        self.assertEqual(len(sm.SLOTS), 61)
        self.assertEqual(sm.hm(sm.SLOTS[0]), "10:00")
        self.assertEqual(sm.hm(sm.SLOTS[29]), "12:25")
        self.assertEqual(sm.hm(sm.SLOTS[30]), "13:55")
        self.assertEqual(sm.hm(sm.SLOTS[-1]), "16:25")

    def test_holidays(self):
        h = sm.load_holidays(None)
        self.assertFalse(sm.trading_day(datetime.date(2026, 4, 13), h))   # Songkran
        self.assertFalse(sm.trading_day(datetime.date(2026, 10, 16), h))
        self.assertTrue(sm.trading_day(datetime.date(2026, 11, 17), h))
        self.assertFalse(sm.trading_day(datetime.date(2026, 11, 15), h))  # Sunday
        self.assertEqual(sm.next_trading_day(datetime.date(2026, 4, 10), h), datetime.date(2026, 4, 16))
        self.assertIn("not confirmed", sm.calendar_note(datetime.date(2026, 12, 7), h) or "")
        self.assertIn("2027", sm.calendar_note(datetime.date(2027, 3, 1), h) or "")

    def test_phase(self):
        f = lambda s: sm.phase(sm.parse_now(s), sm.load_holidays(None))  # noqa: E731
        self.assertEqual(f("2026-11-17 09:59"), "pre-open")
        self.assertEqual(f("2026-11-17 10:00"), "morning")
        self.assertEqual(f("2026-11-17 13:00"), "lunch")
        self.assertEqual(f("2026-11-17 14:00"), "afternoon")
        self.assertEqual(f("2026-11-17 16:35"), "closing-auction")
        self.assertEqual(f("2026-11-17 17:00"), "closed")
        self.assertEqual(f("2026-04-14 11:00"), "closed-day")

    def test_ticks(self):
        self.assertEqual(sm.classic_tick(38.6), Decimal("0.25"))
        self.assertEqual(sm.tick_down(38.62, "0.05"), Decimal("38.60"))
        self.assertEqual(sm.tick_up(38.61, "0.05"), Decimal("38.65"))
        self.assertEqual(sm.snap(38.599998474121094, "0.05"), Decimal("38.60"))
        self.assertEqual(sm.ticks_between(38.35, 38.60, "0.05"), 5)
        self.assertEqual(sm.ticks_between(24.9, 25.25), 2)   # classic ladder walks across 25
        self.assertEqual(sm.infer_tick(bars(PTT), 38.6)[0], Decimal("0.05"))
        self.assertEqual(sm.infer_tick(bars(DELTA), 185)[0], Decimal("0.5"))
        self.assertEqual(sm.stock_tick("PTT", [], 38.6, {"ticks": {"PTT": 0.1}})[0], Decimal("0.1"))

    def test_limits(self):
        ceil, floor = sm.price_limits(38.25, 30)
        self.assertEqual((ceil, floor), (Decimal("49.50"), Decimal("27.00")))

    def test_symbols(self):
        self.assertEqual(sm.to_yahoo("ptt"), "PTT.BK")
        self.assertEqual(sm.from_yahoo("PTT.BK"), "PTT")

    def test_full_sessions(self):
        days = sm.by_day(bars(PTT))
        full = [d for d in days if sm.full_session(days[d])]
        self.assertEqual(len(full), 59)          # the last day in the file is partial
        self.assertFalse(sm.full_session(days[datetime.date(2026, 11, 17)]))


class Entry(unittest.TestCase):
    def ev(self, now, **kw):
        return entry.evaluate(bars(PTT), sm.parse_now(now), holidays=sm.load_holidays(None), **kw)

    def test_forming(self):
        self.assertEqual(self.ev("2026-11-16 10:12")["status"], "forming")

    def test_waiting(self):
        r = self.ev("2026-11-16 10:40")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual((r["or_low"], round(r["or_high"], 2)), (38.20000076293945, 38.5))

    def test_triggered(self):
        r = self.ev("2026-11-16 15:45")
        self.assertEqual((r["status"], r["entry_time"], round(r["entry"], 2)), ("triggered", "11:25", 38.6))

    def test_level_and_expired(self):
        r = self.ev("2026-11-16 16:00", level=40)
        self.assertEqual(r["status"], "expired")

    def test_closed(self):
        self.assertEqual(self.ev("2026-11-15 11:00")["status"], "closed-day")
        self.assertEqual(self.ev("2026-11-16 09:30")["status"], "pre-open")


class Exit(unittest.TestCase):
    def test_or_mid_2r(self):
        c = exitp.compute(38.6, "or-mid", None, "r", Decimal("2"), 38.5, 38.2, step=Decimal("0.05"),
                          prev_close=38.25)
        self.assertEqual((c["entry"], c["stop"], c["target"], c["stop_ticks"]), (38.6, 38.35, 39.1, 5))

    def test_refusals(self):
        with self.assertRaises(exitp.PlanError):   # 1 tick
            exitp.compute(38.6, "price", Decimal("38.55"), "r", Decimal("2"), step=Decimal("0.05"))
        with self.assertRaises(exitp.PlanError):   # above the ceiling
            exitp.compute(38.6, "price", Decimal("30"), "r", Decimal("2"), step=Decimal("0.05"), prev_close=38.25)
        with self.assertRaises(exitp.PlanError):   # stop above entry
            exitp.compute(38.6, "price", Decimal("39"), "r", Decimal("2"), step=Decimal("0.05"))


class Pipeline(unittest.TestCase):
    """entry -> exit -> timemachine -> budget on the PTT fixture, in a temp dir."""

    def test_flow(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(entry.main(["check", "PTT", "--offline", PTT, "--now", "2026-11-16 11:30",
                                                 "--write"]), 0)
                    self.assertEqual(exitp.main(["plan", "--offline", PTT, "--write"]), 0)
                plan = sm.read_json("trader-set/plan.json")
                self.assertEqual((plan["entry"], plan["stop"], plan["target"], plan["tick"]),
                                 (38.6, 38.35, 39.1, 0.05))
                doc = tm.run(sm.read_offline(PTT), plan, 10000, 19, "16:20")
                self.assertEqual(doc["sessions"], 58)
                self.assertAlmostEqual(doc["replay"]["target"], 0.3158, places=4)
                self.assertAlmostEqual(doc["replay"]["stop"], 0.6834, places=4)
                self.assertEqual(doc["replay"], tm.run(sm.read_offline(PTT), plan, 10000, 19, "16:20")["replay"])
                cfg = sm.load_config("trader-set/config.json")
                s = size.size(plan, cfg)
                self.assertEqual((s["shares"], s["decided_by"]), (1200, "position cap (50 % of the account)"))
                self.assertAlmostEqual(s["loss_at_stop"], 456.978, places=2)
                res = {r["check"]: r["ok"] for r in size.check(plan, cfg, s, sm.parse_now("2026-11-16 11:30"),
                                                                {"trades": []}, sm.load_holidays(None))}
                self.assertFalse(res["reward:risk"])          # 2R gross is 0.97R after fees
                self.assertTrue(res["max loss"] and res["window"] and res["tick"])
                res = {r["check"]: r["ok"] for r in size.check(plan, cfg, s, sm.parse_now("2026-11-16 13:00"),
                                                                {"trades": []}, sm.load_holidays(None))}
                self.assertFalse(res["window"])               # lunch break
                s2 = size.size(plan, cfg, max_loss=30)
                self.assertEqual(s2["shares"], 0)             # stop too far for one lot
            finally:
                os.chdir(cwd)


class Scanner(unittest.TestCase):
    def test_rsi(self):
        self.assertEqual(scan.rsi([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]), 100.0)

    def test_orb_offline(self):
        class A:
            offline_dir = FIX
        b = sm.by_day(sm.parse_bars(scan.get("PTT", "5d", "5m", A))).get(datetime.date(2026, 11, 16))
        h = scan.orb_hit(b, sm.parse_now("2026-11-16 11:30"), 3)
        self.assertTrue(h["hit"])
        self.assertEqual(h["first_close_above"], "11:25")
        self.assertFalse(scan.orb_hit(b, sm.parse_now("2026-11-16 11:00"), 3)["hit"])

    def test_universe(self):
        u = scan.read_universe(os.path.join(ROOT, "set-scanner", "universe.txt"))
        self.assertEqual(len(u), 89)
        self.assertIn("PTT", u)


class Repo(unittest.TestCase):
    def test_setmarket_copies_match(self):
        for d in glob.glob(os.path.join(ROOT, "set-*")):
            self.assertTrue(filecmp.cmp(os.path.join(ROOT, "setmarket.py"), os.path.join(d, "setmarket.py"),
                                        shallow=False), d)

    def test_skill_files(self):
        for d in glob.glob(os.path.join(ROOT, "set-*")):
            with open(os.path.join(d, "SKILL.md"), encoding="utf-8") as f:
                head = f.read(400)
            self.assertTrue(head.startswith("---\nname: %s\n" % os.path.basename(d)), d)


if __name__ == "__main__":
    unittest.main()
