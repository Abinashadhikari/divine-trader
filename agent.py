"""
agent.py — Main orchestration loop for the Divine Trader agent.

Run manually:  python agent.py
Dry-run mode:  python agent.py --dry-run
Setup sched:   python agent.py --setup-scheduler

Normally triggered hourly by Windows Task Scheduler.
Exits silently if the market is closed.
"""

import argparse
import json
import os
import sys
from datetime import datetime

import config
import market_data
import portfolio
import risk
import executor
import strategy as strat
from scheduler import is_market_open, print_task_scheduler_instructions
from strategy import BUY, SELL_SOFT, SELL_HARD, SELL_PANIC

# ─── Peak value state (for regime calculation) ────────────────────────────
_STATE_FILE = "state.json"

def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"peak_portfolio_value": 0.0}

def _save_state(s: dict) -> None:
    with open(_STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


# ─── Main ─────────────────────────────────────────────────────────────────

def run(dry_run: bool = False):
    if dry_run:
        os.environ["DRY_RUN"] = "true"
        # Reload config so DRY_RUN flag is picked up
        import importlib
        importlib.reload(config)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  Divine Trader Agent — {now}")
    print(f"  Mode: {'DRY RUN' if config.DRY_RUN else ('PAPER' if config.PAPER_TRADING else '🔴 LIVE')}")
    print(f"{'='*60}")

    # 1. Market hours check
    market_open, reason = is_market_open()
    print(f"\n[1] Market: {reason}")
    if not market_open:
        print("    Agent exiting — nothing to do outside market hours.")
        return

    # 2. Fetch live account + positions
    print("\n[2] Fetching account & positions from Alpaca...")
    acct      = portfolio.get_account_info()
    positions = portfolio.get_live_positions()
    buying_power    = acct["buying_power"]
    portfolio_value = acct["portfolio_value"]
    print(f"    Portfolio value: ${portfolio_value:,.0f} | Buying power: ${buying_power:,.0f}")
    print(f"    Open positions: {list(positions.keys()) or 'None'}")

    # 3. Regime check (drawdown from peak)
    state = _load_state()
    peak  = max(state.get("peak_portfolio_value", 0.0), portfolio_value)
    state["peak_portfolio_value"] = peak
    _save_state(state)
    regime = portfolio.calc_regime(portfolio_value, peak)
    print(f"    Regime: {regime} (peak=${peak:,.0f}, drawdown={((portfolio_value/peak-1)*100) if peak>0 else 0:.1f}%)")

    # 4. Fetch VIX
    print("\n[3] Fetching VIX...")
    vix = market_data.get_vix()
    vix_str = f"{vix:.1f}" if vix else "unavailable"
    vix_flag = "🚫 BUYS BLOCKED" if (vix and vix > config.VIX_BUY_BLOCK_THRESHOLD) else "✅ OK"
    print(f"    VIX: {vix_str}  {vix_flag}")

    # 5. Fetch market data for all watchlist tickers
    print(f"\n[4] Fetching market data for {len(config.WATCHLIST)} tickers...")
    market = market_data.get_market_data(config.WATCHLIST)
    valid  = sum(1 for d in market.values() if d.get("valid"))
    print(f"    Valid: {valid}/{len(config.WATCHLIST)}")

    # 6. Generate signals
    print("\n[5] Generating signals...")
    signals = strat.generate_signals(market, positions, buying_power, regime, vix)

    buys   = [s for s in signals if s.action == BUY]
    sells  = [s for s in signals if s.action in (SELL_SOFT, SELL_HARD, SELL_PANIC)]
    others = [s for s in signals if s.action not in (BUY, SELL_SOFT, SELL_HARD, SELL_PANIC)]

    print(f"    BUYs: {len(buys)}  |  SELLs: {len(sells)}  |  SKIP/HOLD: {len(others)}")
    for s in signals:
        icon = {"BUY": "🚀", "SELL_SOFT": "⚠️", "SELL_HARD": "🛑", "SELL_PANIC": "🆘"}.get(s.action, "·")
        print(f"    {icon} {s.ticker:<6} {s.action:<12} {s.reason}")

    # 7. Execute SELLs first
    print("\n[6] Processing sell signals...")
    for s in sells:
        d = market.get(s.ticker, {})
        pos = positions.get(s.ticker, {})
        held_qty = int(pos.get("qty", 0))
        if held_qty < 1:
            print(f"  SKIP {s.ticker}: no shares held")
            continue

        # Set qty: 50% for soft exit, 100% for hard/panic
        s.qty = max(1, held_qty // 2) if s.action == SELL_SOFT else held_qty

        approved, reason = risk.check_order(
            s, d, positions, buying_power, portfolio_value, market_open
        )
        if not approved:
            print(f"  BLOCKED {s.ticker}: {reason}")
            continue

        placed = executor.execute(s, s.price)
        if placed:
            risk.set_cooldown(s.ticker, "sell")

    # 8. Execute BUYs
    print("\n[7] Processing buy signals...")
    for s in buys:
        d = market.get(s.ticker, {})
        approved, reason = risk.check_order(
            s, d, positions, buying_power, portfolio_value, market_open
        )
        if not approved:
            print(f"  BLOCKED {s.ticker}: {reason}")
            continue

        placed = executor.execute(s, s.price)
        if placed:
            risk.set_cooldown(s.ticker, "buy")
            buying_power -= s.qty * s.price  # track remaining budget this run

    print(f"\n{'='*60}")
    print(f"  Run complete — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Divine Trader Agent")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate without placing real orders")
    parser.add_argument("--setup-scheduler", action="store_true",
                        help="Print Windows Task Scheduler setup instructions")
    args = parser.parse_args()

    if args.setup_scheduler:
        print_task_scheduler_instructions()
        sys.exit(0)

    run(dry_run=args.dry_run)
