---
name: set-entry
description: >-
  [Thai stocks only: the Stock Exchange of Thailand (SET), symbols like PTT,
  CPALL, ADVANC or PTT.BK. Never use for US stocks: those go to the trader-*
  skills. Run from the thai-stocks folder.]
  SET Entry Timer for Thai stocks. Watches a Stock Exchange of Thailand stock
  bar by bar on free Yahoo 5-minute data and says when an opening-range
  breakout triggers: the first completed bar after the first 15 minutes
  (10:00-10:15 Bangkok) that CLOSES above the range high, or above the user's
  own level. Knows the lunch break, the SET holidays and the closing auction.
  Says pre-open, forming, waiting (and how far), triggered (time and price)
  or expired, and writes trader-set/entry.json for /set-exit. Long only;
  never places an order. Use when the user says "เข้าตอนไหนดี", "PTT เบรคยัง",
  "บอกจุดเข้า", "watch PTT", "has it broken out", "time my entry on SET", or
  after /set-scanner.
---

# set-entry

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check PTT --write       # one look, save it if triggered
python3 "${CLAUDE_SKILL_DIR}/entry.py" check DELTA --level 190 # breakout over your own level
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist               # every symbol from /set-scanner
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch PTT --every 60 --write   # loop until it triggers
```

Options: `--or-minutes 15`, `--from 10:15` (no entries before), `--until
15:30` (no entries after), `--vol 1.5` (trigger bar volume at least 1.5x the
range bars' average, auction bar left out).

## Steps

1. Run `check` (or `watchlist`). For `watch`, run it in the background and
   tell the user it stops when it triggers or expires.
2. Report the status in one or two lines: the range, the trigger, and how far
   the last close is. If it printed a delay note, say the user must confirm
   the live price in their broker's app.
3. On TRIGGERED with `--write`: hand off to `/set-exit` before any order.

## Thai market facts every SET skill uses

- Times are Bangkok (UTC+7). Sessions: morning 10:00-12:30, lunch break,
  afternoon 14:00-16:30, closing auction (ATC) 16:30-16:40. Yahoo's 5-minute
  bars: 10:00-12:25 and 13:55-16:25 (61 a day; 13:55 holds the afternoon auction).
- Holidays: 2026 is checked against real trading days. Dates after
  2026-11-17 are expected but unconfirmed, and 2027 is not on file: add them
  to `trader-set/holidays.json` (`{"2027-01-01": "New Year's Day"}`) and say so.
- Tick size: SET uses finer ticks for some stocks than the classic table
  (PTT at 38 baht moves in 0.05, IVL at 28 in 0.25). The tools read each
  stock's tick from its own recent prices; `"ticks": {"PTT": 0.05}` in
  `trader-set/config.json` overrides it. Tell the user to check prices are
  valid in their broker's app.
- Board lot 100 shares (`board_lot` in config). Daily price limit +-30 % of
  the previous close (`price_limit_pct`).
- Yahoo's SET bars are free, unofficial and delayed (about 15-25 minutes in
  testing). Never present them as live: before any order, the user checks
  the price in their broker's app (Streaming, etc.).

## How to answer

- Answer in the user's language (Thai if they write Thai). Keep symbols,
  prices and times as the tool prints them.
- Run the tool, then explain the result in a few plain lines. Do not invent
  numbers the tool did not print.
- Education and tooling, not financial advice. Nothing in this pack places an
  order: the user types any order into their own broker's app.
- Everything is written under `trader-set/` in the current folder.
