---
name: set-scanner
description: >-
  [Thai stocks only: the Stock Exchange of Thailand (SET), symbols like PTT,
  CPALL, ADVANC or PTT.BK. Never use for US stocks: those go to the trader-*
  skills. Run from the thai-stocks folder.]
  SET Chart Scanner for Thai stocks. Scans a list of liquid Stock Exchange of
  Thailand names (89 by default, or the user's own list) on free Yahoo data
  (PTT -> PTT.BK) for daily setups (20-day closing-high breakout, reclaimed
  the 20-day average, RSI oversold, oversold bounce) and for intraday
  opening-range breakouts on 5-minute bars, in Bangkok time, and writes
  trader-set/watchlist.json for /set-entry. Use when the user says "scan Thai
  stocks", "สแกนหุ้น", "หาหุ้นเบรค", "หุ้นไทยตัวไหนน่าสนใจ", "opening range
  breakout on SET", "oversold SET stocks", "build my SET watchlist", or at the
  start of a Thai trading day.
---

# set-scanner

Finds SET stocks worth a closer look. It does not say what to buy.

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --write          # before the open (or after the close)
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:30 --write # after the 15-minute opening range
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols PTT,AOT,DELTA
python3 "${CLAUDE_SKILL_DIR}/scan.py" --help
```

- The list: `trader-set/universe.txt` if the user made one, else
  `${CLAUDE_SKILL_DIR}/universe.txt` (89 large, liquid names checked on
  Yahoo on 2026-11-17; not an official index).
- `daily` filters: `--min-price` (1 baht) and `--min-value` (50 million baht a
  day, 20-day average). Today's unfinished bar is left out until 16:40.
- `orb`: a hit is a completed 5-minute bar after the opening range that
  CLOSED above the range high, by `--at` (default now). It takes about a
  minute for 89 symbols (one polite request each).

## Steps

1. Run `daily` before the open, or `orb` once the range is done (10:15 or later).
2. Summarise: how many of how many matched, the top few by value traded, and
   one line on what each setup means. Mention the data delay for `orb`.
3. Hand off: `/set-entry` on the names the user picks.

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
