---
name: set-timemachine
description: >-
  [Thai stocks only: the Stock Exchange of Thailand (SET), symbols like PTT,
  CPALL, ADVANC or PTT.BK. Never use for US stocks: those go to the trader-*
  skills. Run from the thai-stocks folder.]
  SET Time Machine for Thai stocks. Before the user risks a baht, replays the
  rest of the trading day 10,000 times from the stock's own 5-minute bars
  over the last 60 days (lunch-break gaps included), and re-runs the same
  opening-range rule on every past session. Prints the odds of target first,
  stop first, or neither by the flat-by time, the average R before fees, the
  history, and one honest verdict. Reads trader-set/plan.json. Use when the
  user says "โอกาสถึงเป้าเท่าไหร่", "จำลองเทรด", "backtest", "what are the
  odds", "run the time machine", "monte carlo" for a SET stock, or after
  /set-exit.
---

# set-timemachine

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:30 --seed 7 --replays 20000
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol PTT --date 2026-11-16 \
    --entry 38.60 --stop 38.35 --target 39.10 --entry-time 11:25
```

The method is in the script's header (`--help`). Same plan, data and seed
give the same numbers. It needs 20 full past sessions in the last 60 days.

## Steps

1. Run it. Report target first / stop first / neither, the average R, the
   history line and the verdict, in plain words.
2. Say what the verdict means against break-even (50 % at 1R, 33 % at 2R),
   and that R here is before fees.
3. Say plainly it is a simulation from the last 60 days, not a prediction:
   news, results and market-wide moves can do what those days never did.
4. Hand off: `/set-budget`.

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
