"""setmarket: the Stock Exchange of Thailand (SET) in one small module.

Standard library only. Every skill folder in this pack carries an identical
copy of this file (run `python3 sync.py` after editing the one at the repo
root; a test checks the copies match).

What lives here:
  - Bangkok time (UTC+7, no daylight saving).
  - SET trading sessions and the 5-minute bar slots Yahoo publishes for them.
  - SET holidays: 2026 checked against real trading data, the rest flagged.
  - SET tick sizes (price spreads), board lots and the daily price limit.
  - Fetching Yahoo Finance chart JSON for SET symbols (PTT -> PTT.BK).
"""

import datetime
import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

VERSION = "1.0.0"

# ------------------------------------------------------------------ time

BKK = datetime.timezone(datetime.timedelta(hours=7), "ICT")


def now_bkk():
    return datetime.datetime.now(BKK)


def parse_now(text):
    """'2026-11-17 10:15' (Bangkok) -> aware datetime. None -> the real clock."""
    if not text:
        return now_bkk()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text.strip(), fmt).replace(tzinfo=BKK)
        except ValueError:
            pass
    raise ValueError("--now wants 'YYYY-MM-DD HH:MM' in Bangkok time, got %r" % text)


def parse_hhmm(text, what="time"):
    try:
        h, m = text.strip().split(":")
        return datetime.time(int(h), int(m))
    except Exception:
        raise ValueError("%s wants HH:MM (24-hour, Bangkok time), got %r" % (what, text))


def hm(t):
    return t.strftime("%H:%M")


def at(day, t):
    return datetime.datetime.combine(day, t).replace(tzinfo=BKK)


# ------------------------------------------------------------------ sessions
#
# SET equities, Bangkok time (checked against Yahoo 5-minute bars, Sep-Nov 2026):
#   09:55-10:00  pre-open auction (morning opening price at a random moment)
#   10:00-12:30  morning session
#   13:55-14:00  pre-open auction (afternoon)
#   14:00-16:30  afternoon session
#   16:30-16:40  pre-close: ATC closing auction
# Yahoo's 5-minute bars for a full day: 10:00..12:25 (30 bars) and
# 13:55..16:25 (31 bars) = 61 bars. The 13:55 bar holds the afternoon auction.

MORNING_OPEN = datetime.time(10, 0)
MORNING_CLOSE = datetime.time(12, 30)
AFTERNOON_OPEN = datetime.time(14, 0)
AFTERNOON_CLOSE = datetime.time(16, 30)
ATC_END = datetime.time(16, 40)


def _slots():
    out = []
    t = datetime.datetime(2000, 1, 1, 10, 0)
    while t.time() < MORNING_CLOSE:
        out.append(t.time())
        t += datetime.timedelta(minutes=5)
    t = datetime.datetime(2000, 1, 1, 13, 55)
    while t.time() < AFTERNOON_CLOSE:
        out.append(t.time())
        t += datetime.timedelta(minutes=5)
    return out


SLOTS = _slots()                      # 61 bar start times
SLOT_INDEX = {t: i for i, t in enumerate(SLOTS)}
BAR = datetime.timedelta(minutes=5)

# ------------------------------------------------------------------ holidays
#
# 2025-12 to 2026-11: every weekday with no SET trading in Yahoo's daily bars
# for PTT, ADVANC and KBANK (all three agree). Dates after 2026-11-17 are the
# expected Thai holidays and are NOT yet confirmed: check SET's calendar
# (set.or.th > Market > Holidays). Add your own in trader-set/holidays.json:
#   {"2027-01-01": "New Year's Day", ...}

HOLIDAYS = {
    "2025-12-05": "King Bhumibol's Birthday",
    "2025-12-10": "Constitution Day",
    "2025-12-31": "New Year's Eve",
    "2026-01-01": "New Year's Day",
    "2026-01-02": "Special holiday",
    "2026-03-03": "Makha Bucha Day",
    "2026-04-06": "Chakri Day",
    "2026-04-13": "Songkran",
    "2026-04-14": "Songkran",
    "2026-04-15": "Songkran",
    "2026-05-01": "Labour Day",
    "2026-05-04": "Coronation Day",
    "2026-06-01": "Visakha Bucha Day (substitute)",
    "2026-06-03": "Queen Suthida's Birthday",
    "2026-07-28": "King's Birthday",
    "2026-07-29": "Asarnha Bucha Day",
    "2026-08-12": "Queen Mother's Birthday / Mother's Day",
    "2026-10-13": "King Bhumibol Memorial Day",
    "2026-10-16": "Special holiday",
    "2026-10-23": "Chulalongkorn Day",
}
UNCONFIRMED = {
    "2026-12-07": "King Bhumibol's Birthday (substitute for Sat 5 Dec) - unconfirmed",
    "2026-12-10": "Constitution Day - unconfirmed",
    "2026-12-31": "New Year's Eve - unconfirmed",
}
CONFIRMED_THROUGH = datetime.date(2026, 11, 17)


def load_holidays(path="trader-set/holidays.json"):
    h = dict(HOLIDAYS)
    h.update(UNCONFIRMED)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            extra = json.load(f)
        if isinstance(extra, dict):
            h.update({str(k): str(v) for k, v in extra.items()})
    return h


def holiday_name(day, holidays=None):
    return (holidays if holidays is not None else load_holidays()).get(day.isoformat())


def trading_day(day, holidays=None):
    return day.weekday() < 5 and not holiday_name(day, holidays)


def calendar_note(day, holidays=None):
    """A warning when the calendar for `day` has not been checked."""
    h = holidays if holidays is not None else load_holidays()
    if day.isoformat() in UNCONFIRMED and day.isoformat() in h and h[day.isoformat()] == UNCONFIRMED[day.isoformat()]:
        return "%s is an expected holiday that is not confirmed: check set.or.th" % day.isoformat()
    if day > datetime.date(2026, 12, 31) and not any(k.startswith(str(day.year)) for k in h):
        return ("no SET holidays are on file for %d: weekdays are treated as trading days. "
                "Add the year's holidays to trader-set/holidays.json" % day.year)
    return None


def next_trading_day(day, holidays=None):
    d = day + datetime.timedelta(days=1)
    while not trading_day(d, holidays):
        d += datetime.timedelta(days=1)
    return d


def phase(now, holidays=None):
    """Where the market is at `now` (Bangkok): closed-day, pre-open, morning,
    lunch, afternoon, closing-auction, closed."""
    if not trading_day(now.date(), holidays):
        return "closed-day"
    t = now.timetz().replace(tzinfo=None)
    if t < MORNING_OPEN:
        return "pre-open"
    if t < MORNING_CLOSE:
        return "morning"
    if t < AFTERNOON_OPEN:
        return "lunch"
    if t < AFTERNOON_CLOSE:
        return "afternoon"
    if t < ATC_END:
        return "closing-auction"
    return "closed"


PHASE_TEXT = {
    "closed-day": "SET is closed today",
    "pre-open": "before the 10:00 open",
    "morning": "morning session (10:00-12:30)",
    "lunch": "lunch break (12:30-14:00)",
    "afternoon": "afternoon session (14:00-16:30)",
    "closing-auction": "closing auction (ATC, 16:30-16:40)",
    "closed": "closed for the day",
}

# ------------------------------------------------------------------ prices

# SET price spreads. The CLASSIC table below is the long-standing one, but
# Yahoo's 2026 prices show SET now uses finer ticks for some stocks (PTT at
# 38 baht trades in 0.05 steps, IVL at 28 in 0.25 steps, HMPRO at 6 in 0.01
# steps). So each tool infers the tick from the stock's own recent prices
# (infer_tick) and falls back to this table only when there is too little
# data. Override one in trader-set/config.json: "ticks": {"PTT": 0.05}.
TICKS = [
    (Decimal("400"), Decimal("2.00")),
    (Decimal("200"), Decimal("1.00")),
    (Decimal("100"), Decimal("0.50")),
    (Decimal("25"), Decimal("0.25")),
    (Decimal("10"), Decimal("0.10")),
    (Decimal("5"), Decimal("0.05")),
    (Decimal("2"), Decimal("0.02")),
    (Decimal("0"), Decimal("0.01")),
]


def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def classic_tick(price):
    p = D(price)
    for floor, step in TICKS:
        if p >= floor:
            return step
    return Decimal("0.01")


CANDIDATE_TICKS = [Decimal(x) for x in ("2", "1", "0.5", "0.25", "0.1", "0.05", "0.02", "0.01")]


def infer_tick(bars, price, band=0.15, min_prices=30):
    """The tick this stock really trades in near `price`: the largest standard
    step that divides every open/high/low/close Yahoo shows within +-15 % of
    the price. Falls back to the classic table with too few prices."""
    p0 = float(price)
    seen = set()
    for b in bars:
        for k in ("o", "h", "l", "c"):
            x = b[k]
            if abs(x - p0) <= band * p0:
                seen.add(D(round(x, 3)))
    if len(seen) < min_prices:
        return classic_tick(price), "classic SET table (too little data to read it)"
    for step in CANDIDATE_TICKS:
        if all(p % step == 0 for p in seen):
            return step, "read from %d recent prices" % len(seen)
    return Decimal("0.01"), "read from %d recent prices" % len(seen)


def stock_tick(sym, bars, price, cfg=None):
    ov = ((cfg or {}).get("ticks") or {}).get(from_yahoo(sym))
    if ov:
        return D(ov), "from config"
    return infer_tick(bars, price)


def tick(price, step=None):
    return D(step) if step is not None else classic_tick(price)


def tick_down(price, step=None):
    """The highest valid price at or below `price`."""
    p = D(price)
    s = tick(p, step)
    return (p / s).to_integral_value(ROUND_FLOOR) * s


def tick_up(price, step=None):
    """The lowest valid price at or above `price`."""
    p = D(price)
    s = tick(p, step)
    return (p / s).to_integral_value(ROUND_CEILING) * s


def snap(price, step=None):
    """Yahoo prints 38.599998474121094: snap to the nearest valid price."""
    p = D(round(float(price), 4))
    lo = tick_down(p, step)
    hi = tick_up(p, step)
    return lo if (p - lo) <= (hi - p) else hi


def ticks_between(lo, hi, step=None):
    """How many ticks from lo up to hi."""
    lo, hi = D(lo), D(hi)
    if step is not None:
        return int(((hi - lo) / D(step)).to_integral_value(ROUND_FLOOR))
    n = 0
    p = lo
    while p < hi and n < 100000:
        p = p + classic_tick(p)
        n += 1
    return n


def board_lot(price, cfg=None):
    cfg = cfg or {}
    if cfg.get("board_lot"):
        return int(cfg["board_lot"])
    return 100


def price_limits(prev_close, pct=30):
    """Ceiling and floor for the day: +-pct % of the previous close, on the
    classic ticks (approximate: check your broker's screen for the exact ones)."""
    pc = D(prev_close)
    band = pc * D(pct) / D(100)
    return tick_down(pc + band), tick_up(pc - band)


def baht(x):
    return "{:,.2f}".format(float(x))


def px(x):
    """A SET price as text: 38.5 -> '38.50'."""
    return "%.2f" % float(x)

# ------------------------------------------------------------------ symbols


def to_yahoo(sym):
    s = sym.strip().upper()
    return s if s.endswith(".BK") else s + ".BK"


def from_yahoo(sym):
    s = sym.strip().upper()
    return s[:-3] if s.endswith(".BK") else s

# ------------------------------------------------------------------ Yahoo

UA = "Mozilla/5.0 (compatible; set-trader-skill/%s)" % VERSION
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")


class DataError(Exception):
    pass


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def chart_path(sym, rng, interval):
    return "/v8/finance/chart/%s?range=%s&interval=%s&includePrePost=false" % (
        urllib.parse.quote(to_yahoo(sym)), rng, interval)


def fetch_chart(sym, rng="60d", interval="5m", tries=3):
    """Yahoo chart JSON text for a SET symbol. query2, then query1."""
    last = None
    path = chart_path(sym, rng, interval)
    for attempt in range(tries):
        for host in HOSTS:
            try:
                return _get(host + path)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 404:
                    raise DataError("Yahoo does not know %s" % to_yahoo(sym))
                if e.code not in (429, 500, 502, 503, 504):
                    raise DataError("Yahoo answered HTTP %d for %s" % (e.code, to_yahoo(sym)))
            except (urllib.error.URLError, OSError) as e:
                last = e
        time.sleep(1.5 * (attempt + 1))
    raise DataError("could not reach Yahoo Finance for %s (%s)" % (to_yahoo(sym), last))


def read_offline(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return f.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def chart_result(text, sym=""):
    try:
        doc = json.loads(text)
    except ValueError:
        raise DataError("Yahoo's answer for %s is not JSON" % sym)
    ch = (doc or {}).get("chart") or {}
    if ch.get("error"):
        raise DataError("Yahoo: %s" % (ch["error"].get("description") or ch["error"]))
    res = ch.get("result") or []
    if not res:
        raise DataError("Yahoo returned no data for %s" % sym)
    return res[0]


def parse_bars(result):
    """Chart result -> list of bars {t, o, h, l, c, v} in Bangkok time.
    Bars with no trade (all None) are dropped."""
    ts = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    o, h, l, c, v = (q.get(k) or [None] * len(ts) for k in ("open", "high", "low", "close", "volume"))
    bars = []
    for i, t in enumerate(ts):
        if c[i] is None or o[i] is None or h[i] is None or l[i] is None:
            continue
        bars.append({
            "t": datetime.datetime.fromtimestamp(t, BKK),
            "o": float(o[i]), "h": float(h[i]), "l": float(l[i]), "c": float(c[i]),
            "v": int(v[i] or 0),
        })
    return bars


def prev_close(result):
    m = result.get("meta") or {}
    for k in ("chartPreviousClose", "previousClose", "regularMarketPreviousClose"):
        if m.get(k):
            return float(m[k])
    return None


def by_day(bars):
    out = {}
    for b in bars:
        out.setdefault(b["t"].date(), []).append(b)
    return out


def complete(bars, now):
    """Only bars that have finished by `now` (a 10:05 bar ends at 10:10)."""
    return [b for b in bars if b["t"] + BAR <= now]


def full_session(bars, min_share=0.9):
    """A past day counts as full when it runs from the 10:00 bar to the 16:20
    bar or later and has at least 90 % of the 61 slots."""
    if not bars:
        return False
    first = bars[0]["t"].timetz().replace(tzinfo=None)
    last = bars[-1]["t"].timetz().replace(tzinfo=None)
    return (first <= datetime.time(10, 5) and last >= datetime.time(16, 20)
            and len(bars) >= int(min_share * len(SLOTS)))


def slot_of(bar):
    return SLOT_INDEX.get(bar["t"].timetz().replace(tzinfo=None, second=0, microsecond=0))

# ------------------------------------------------------------------ files


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
    os.replace(tmp, path)


DEFAULT_CONFIG = {
    "account_thb": 100000,
    "max_loss_per_trade_thb": 1000,
    "daily_loss_limit_thb": 3000,
    "max_trades_per_day": 3,
    "max_position_pct": 50,
    "cash_buffer_pct": 5,
    "min_reward_risk": 1.0,
    "fee_rate_pct": 0.17,
    "board_lot": 100,
    "price_limit_pct": 30,
    "entry_from": "10:15",
    "entry_until": "15:30",
    "flat_by": "16:20",
    "blocked": [],
}


def load_config(path="trader-set/config.json"):
    cfg = dict(DEFAULT_CONFIG)
    doc = read_json(path)
    if isinstance(doc, dict):
        cfg.update(doc)
    return cfg
