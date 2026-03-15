"""
portfolio.py — Live position reconciliation from Alpaca.

Replaces the DB-based ledger from Divine_Wealth_Final.py.
The Alpaca account is the single source of truth for positions and cash.
"""

from typing import Dict, Any, Optional
import config

try:
    from alpaca.trading.client import TradingClient
    _ALPACA_OK = True
except ImportError:
    _ALPACA_OK = False


def _get_client() -> Optional[object]:
    if not _ALPACA_OK or not config.ALPACA_KEY or not config.ALPACA_SECRET:
        return None
    try:
        return TradingClient(
            config.ALPACA_KEY,
            config.ALPACA_SECRET,
            paper=config.PAPER_TRADING,
        )
    except Exception as e:
        print(f"⚠️  Alpaca trading client error: {e}")
        return None


def get_live_positions() -> Dict[str, Dict[str, Any]]:
    """
    Returns {ticker: {qty, avg_entry, market_value, unrealized_pnl, side}}
    Empty dict on failure.
    """
    client = _get_client()
    if client is None:
        print("⚠️  Cannot fetch positions — Alpaca client unavailable")
        return {}

    try:
        positions = client.get_all_positions()
        out = {}
        for p in positions:
            out[p.symbol] = {
                "qty":             float(p.qty),
                "avg_entry":       float(p.avg_entry_price),
                "market_value":    float(p.market_value),
                "unrealized_pnl":  float(p.unrealized_pl),
                "side":            str(p.side),
            }
        return out
    except Exception as e:
        print(f"⚠️  get_live_positions failed: {e}")
        return {}


def get_account_info() -> Dict[str, float]:
    """
    Returns {buying_power, portfolio_value, cash, equity}
    Zeros on failure.
    """
    client = _get_client()
    if client is None:
        return {"buying_power": 0.0, "portfolio_value": 0.0, "cash": 0.0, "equity": 0.0}

    try:
        acct = client.get_account()
        return {
            "buying_power":    float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "cash":            float(acct.cash),
            "equity":          float(acct.equity),
        }
    except Exception as e:
        print(f"⚠️  get_account_info failed: {e}")
        return {"buying_power": 0.0, "portfolio_value": 0.0, "cash": 0.0, "equity": 0.0}


def calc_regime(portfolio_value: float, peak_value: float) -> str:
    """
    Determines market regime based on drawdown from peak portfolio value.
    peak_value should be tracked externally (e.g., in a JSON state file).
    """
    if peak_value <= 0:
        return "NORMAL"
    drawdown = (portfolio_value / peak_value - 1.0) * 100.0
    hyst = config.REGIME_HYSTERESIS_PCT
    if drawdown <= config.DRAWDOWN_PRESERVATION_PCT - hyst:
        return "PRESERVATION"
    if drawdown <= config.DRAWDOWN_DEFENSE_PCT - hyst:
        return "DEFENSE"
    return "NORMAL"
