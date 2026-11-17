---
name: set-exit
description: >-
  [Thai stocks only: the Stock Exchange of Thailand (SET), symbols like PTT,
  CPALL, ADVANC or PTT.BK. Never use for US stocks: those go to the trader-*
  skills. Run from the thai-stocks folder.]
  SET Exit Planner for Thai stocks. Sets the stop and the target before the
  user buys: stop at the opening-range midpoint by default (or one tick under
  the range low, a percent, a price, or a multiple of the 5-minute ATR),
  target at 2R by default (or 1R, 3R, or a price), every price on the
  stock's own SET tick ladder read from its recent prices, checked against
  the day's +-30 % ceiling and floor, flat by 16:20 before the closing
  auction. Refuses a stop under 2 ticks away. Writes trader-set/plan.json for
  /set-timemachine and /set-budget. Use when the user says "ตั้ง stop loss",
  "จุดตัดขาดทุน", "เป้าขาย", "where's my stop", "plan the exit", "risk reward"
  for a Thai stock, or right after /set-entry triggers.
---

# set-exit

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --write                 # from trader-set/entry.json
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-low --target 1R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol PTT --entry 38.60 --entry-time 11:25 \
    --stop price:38.20 --target 2R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

Stop rules: `or-mid` (default), `or-low`, `pct:1.5`, `price:38.20`, `atr:1.5`.
Target: `1R`, `2R` (default), `3R`, `price:39.50`. The stop rounds down to a
valid price and the target rounds up, so the printed R can be a little over
the one asked for.

## Steps

1. Run `plan --write`. If it refuses, say why in one line and offer the
   obvious fix (a wider stop, a smaller target).
2. Report entry, stop, target, R, ticks and the tick size, plus any note
   (a plan that crosses a price band, a very tight stop).
3. Remind the user that SET fees are about 0.17 % a side: on a tight day
   trade they eat a real share of the reward (`/set-budget` shows it).
4. Hand off: `/set-timemachine`, then `/set-budget`.

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
