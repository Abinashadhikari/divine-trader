"""
risk.py — Pre-order guards, ATR-based position sizing, cooldown management.

Every order passes through check_order() before reaching executor.py.
If any guard fails, the order is blocked and the reason is logged.
"""

import json
import os
from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional
import config
from strategy import Signal, BUY, SELL_SOFT, SELL_HARD, SELL_PANIC


# ─── Cooldown management ──────────────────────────────────────────────────

def _load_cooldowns() -> dict:
    if not os.path.exists(config.COOLDOWN_FILE):
        return {}
    try:
        with open(config.COOLDOWN_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cooldowns(cd: dict) -> None:
    with open(config.COOLDOWN_FILE, "w") as f:
        json.dump(cd, f, indent=2)


def is_in_cooldown(ticker: str, side: str) -> tuple[bool, str]:
    """Returns (blocked, reason). side = 'buy' or 'sell'."""
    cd = _load_cooldowns()
    key = f"{ticker}_{side}"
    if key not in cd:
        return False, ""
    until = date.fromisoformat(cd[key])
    today = date.today()
    if today < until:
        return True, f"Cooldown active until {until.isoformat()}"
    return False, ""


def set_cooldown(ticker: str, side: str) -> None:
    cd = _load_cooldowns()
    days = config.COOLDOWN_BUY_DAYS if side == "buy" else config.COOLDOWN_SELL_DAYS
    cd[f"{ticker}_{side}"] = (date.today() + timedelta(days=days)).isoformat()
    _save_cooldowns(cd)


# ─── ATR-based position sizing ────────────────────────────────────────────

def calc_qty(
    ticker:       str,
    price:        float,
    atr:          Optional[float],
    buying_power: float,
    portfolio_value: float,
) -> tuple[int, str]:
    """
    Returns (qty, reason) for a BUY order.

    Sizing logic:
      base_budget  = min(buying_power * PER_RUN_DEPLOY_CAP, portfolio * MAX_CONC)
      If ATR available: scale budget inversely to volatility
        volatility_pct = ATR / price
        position_size  = base_budget / (volatility_pct * ATR_MULTIPLIER)
        (higher ATR → smaller position)
      Else: use base_budget directly.
    """
    # Hard floor: keep dry powder
    dry_floor = max(
        config.DRY_POWDER_FLOOR_MIN,
        portfolio_value * config.DRY_POWDER_FLOOR_PCT,
    )
    available = max(buying_power - dry_floor, 0.0)
    if available <= 0:
        return 0, "No budget above dry powder floor"

    # Per-run deployment cap
    base_budget = min(available * config.PER_RUN_DEPLOY_CAP_PCT,
                      portfolio_value * config.MAX_POSITION_CONC_PCT)

    # ATR volatility scaling: position size shrinks proportionally as ATR rises.
    # Reference: ATR_MULTIPLIER * 1% daily range = "normal vol" → full position.
    # High ATR (e.g. 20% daily range) → small position; low ATR → larger position.
    if atr and atr > 0 and price > 0:
        vol_pct    = atr / price
        normal_vol = config.ATR_MULTIPLIER * 0.01  # e.g. 2.0 * 0.01 = 2% is baseline
        scale      = min(1.0, normal_vol / vol_pct) # 1.0 at normal vol, <1 when high vol
        dollar_size = max(base_budget * 0.2, base_budget * scale)
        reason = f"ATR-scaled: ${dollar_size:,.0f} (ATR={atr:.2f}, vol={vol_pct:.2%}, scale={scale:.2f})"
    else:
        dollar_size = base_budget
        reason = f"Fixed budget: ${dollar_size:,.0f} (ATR unavailable)"

    qty = int(dollar_size / price)
    if qty < 1:
        return 0, f"Dollar size ${dollar_size:.0f} too small for 1 share at ${price:.2f}"

    return qty, reason


# ─── Main pre-order guard ─────────────────────────────────────────────────

def check_order(
    signal:          Signal,
    market_data:     Dict[str, Any],
    positions:       Dict[str, Any],
    buying_power:    float,
    portfolio_value: float,
    market_open:     bool,
) -> tuple[bool, str]:
    """
    Returns (approved, reason).
    If approved=False, do NOT place the order.
    """
    ticker = signal.ticker
    side   = "buy" if signal.action == BUY else "sell"

    # 1. Market must be open
    if not market_open:
        return False, "Market is closed"

    # 2. Cooldown check
    blocked, reason = is_in_cooldown(ticker, side)
    if blocked:
        return False, reason

    # 3. Sells are always approved if market open and no cooldown
    if signal.action in (SELL_SOFT, SELL_HARD, SELL_PANIC):
        if ticker not in positions:
            return False, "No position to sell"
        return True, "Sell approved"

    # 4. BUY-specific guards
    atr = market_data.get("atr")
    qty, size_reason = calc_qty(
        ticker, signal.price, atr, buying_power, portfolio_value
    )
    if qty < 1:
        return False, f"Position sizing blocked: {size_reason}"

    # 5. Concentration check
    pos_value = qty * signal.price
    if portfolio_value > 0 and (pos_value / portfolio_value) > config.MAX_POSITION_CONC_PCT:
        return False, f"Would exceed {config.MAX_POSITION_CONC_PCT:.0%} concentration limit"

    # Attach qty to signal so executor knows how many shares
    signal.qty = qty
    return True, f"Buy approved: {qty} shares — {size_reason}"
