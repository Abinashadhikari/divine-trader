"""
executor.py — Alpaca order placement with full audit logging.

Every order (real or dry-run) is written to trades.log.
In dry-run mode no orders are submitted.
"""

import json
import logging
from datetime import datetime
from typing import Optional
import config
from strategy import Signal, BUY, SELL_SOFT, SELL_HARD, SELL_PANIC

# ─── Logger setup ─────────────────────────────────────────────────────────
logging.basicConfig(
    filename=config.LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_console = logging.StreamHandler()
_console.setLevel(logging.INFO)
logging.getLogger().addHandler(_console)

log = logging.getLogger(__name__)

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
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
        log.error(f"Alpaca trading client error: {e}")
        return None


def _log_order(ticker, side, qty, price, action, reason, status, order_id=None):
    record = {
        "time":     datetime.utcnow().isoformat(),
        "ticker":   ticker,
        "side":     side,
        "qty":      qty,
        "price":    price,
        "action":   action,
        "reason":   reason,
        "status":   status,
        "order_id": order_id,
        "paper":    config.PAPER_TRADING,
        "dry_run":  config.DRY_RUN,
    }
    log.info(json.dumps(record))


def execute(signal: Signal, market_price: float) -> bool:
    """
    Places an order for the given signal. Returns True if order was submitted.

    Handles:
      BUY        → market buy signal.qty shares
      SELL_SOFT  → sell 50% of position
      SELL_HARD  → sell 100% of position
      SELL_PANIC → sell 100% of position (emergency)
    """
    ticker = signal.ticker
    action = signal.action
    reason = signal.reason

    # Determine side and qty
    if action == BUY:
        side = "buy"
        qty  = signal.qty
    elif action == SELL_SOFT:
        side = "sell"
        qty  = signal.qty  # risk.py sets this to 50% of held qty
    elif action in (SELL_HARD, SELL_PANIC):
        side = "sell"
        qty  = signal.qty  # risk.py sets this to full held qty
    else:
        return False

    if qty < 1:
        log.warning(f"SKIPPED {ticker}: qty < 1")
        return False

    if config.DRY_RUN:
        _log_order(ticker, side, qty, market_price, action, reason, "DRY_RUN")
        print(f"  [DRY RUN] {side.upper()} {qty}x {ticker} @ ~${market_price:.2f} | {reason}")
        return True

    client = _get_client()
    if client is None:
        _log_order(ticker, side, qty, market_price, action, reason, "FAILED_NO_CLIENT")
        return False

    try:
        # Cancel any existing open orders first to avoid conflicts
        try:
            client.cancel_orders_for_symbol(ticker)
        except Exception:
            pass

        order_req = MarketOrderRequest(
            symbol       = ticker,
            qty          = qty,
            side         = OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force= TimeInForce.DAY,
        )
        order = client.submit_order(order_req)
        _log_order(ticker, side, qty, market_price, action, reason,
                   "SUBMITTED", order_id=str(order.id))
        print(f"  ✅ {side.upper()} {qty}x {ticker} @ ~${market_price:.2f} | {action} | order={order.id}")
        return True

    except Exception as e:
        _log_order(ticker, side, qty, market_price, action, reason, f"FAILED: {e}")
        log.error(f"Order failed for {ticker}: {e}")
        return False
