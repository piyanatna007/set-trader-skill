---
name: set-budget
description: >-
  [Thai stocks only: the Stock Exchange of Thailand (SET), symbols like PTT,
  CPALL, ADVANC or PTT.BK. Never use for US stocks: those go to the trader-*
  skills. Run from the thai-stocks folder.]
  SET Budget and Risk Manager for Thai stocks. Sizes a day trade from
  trader-set/plan.json in whole board lots of 100 shares inside the max loss
  per trade (fees on both sides included), the position cap and the cash
  buffer, names the limit that decided it, and checks every rule (stop,
  max loss, reward:risk after fees, trades per day, daily loss limit, entry
  window and lunch break, ceiling and floor, blocked list). Prints PASS or
  BLOCK and, on PASS, a plain order ticket for the user to type into their
  own broker's app. Keeps a journal of today's trades. Use when the user says
  "ซื้อได้กี่หุ้น", "คำนวณขนาดไม้", "ตรวจความเสี่ยง", "ฉันมีเงิน 100,000",
  "เสียได้ไม่เกิน 1,000 ต่อไม้", "how many shares", "size this trade", "risk
  check" for a SET stock, or after /set-timemachine.
---

# set-budget

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py" check --write
python3 "${CLAUDE_SKILL_DIR}/size.py" check --account 200000 --max-loss 1500 --price 38.65
python3 "${CLAUDE_SKILL_DIR}/size.py" log              # the user says they placed it
python3 "${CLAUDE_SKILL_DIR}/size.py" close --price 39.10   # the user says they are out
python3 "${CLAUDE_SKILL_DIR}/size.py" today
```

Rules live in `trader-set/config.json` (create it on first use if the user
gives their numbers; anything missing uses the default):

```json
{"account_thb": 100000, "max_loss_per_trade_thb": 1000, "daily_loss_limit_thb": 3000,
 "max_trades_per_day": 3, "max_position_pct": 50, "cash_buffer_pct": 5,
 "min_reward_risk": 1.0, "fee_rate_pct": 0.17, "board_lot": 100,
 "price_limit_pct": 30, "entry_from": "10:15", "entry_until": "15:30",
 "flat_by": "16:20", "blocked": [], "ticks": {}}
```

`fee_rate_pct` is all-in per side (commission + 7 % VAT + exchange fees);
ask the user for their broker's rate, since it varies.

## Steps

1. Run `check --write`. On BLOCK, list what failed (marked XX) and the fix.
   Never loosen a rule unless the user asks to change their config.
2. On PASS, show the ticket. Make clear the stop is the order that matters,
   that Yahoo's price is delayed, and that the user places the order
   themselves. This pack never sends orders.
3. Only when the user says they placed it, run `log`; when they say they are
   out, run `close --price` with their fill.

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
