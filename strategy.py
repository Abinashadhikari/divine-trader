"""
strategy.py — Signal generation for leveraged ETF trading.

Returns per-ticker signals: BUY / SELL_SOFT / SELL_HARD / SELL_PANIC / HOLD / SKIP

Improvements over original active_trade.py:
  - VIX gate blocks all buys when fear is elevated
  - Volume confirmation required on entries
  - Trailing ATR stop replaces fixed panic cushion
  - Intraday shock filter preserved
"""

from typing import Dict, Any, List
from dataclasses import dataclass
import config

# ─── Signal types ─────────────────────────────────────────────────────────
BUY         = "BUY"
SELL_SOFT   = "SELL_SOFT"    # RSI overbought → sell 50%
SELL_HARD   = "SELL_HARD"    # 2-day close below SMA50 → full exit
SELL_PANIC  = "SELL_PANIC"   # Trailing ATR stop OR -15% cushion → full exit
HOLD        = "HOLD"
SKIP        = "SKIP"         # Not eligible (no data / regime block)


@dataclass
class Signal:
    ticker:  str
    action:  str            # one of the constants above
    price:   float
    reason:  str
    qty:     int  = 0       # filled in by risk.py before execution


def generate_signals(
    market: Dict[str, Dict[str, Any]],
    positions: Dict[str, Dict[str, Any]],
    buying_power: float,
    regime: str,
    vix: float | None,
) -> List[Signal]:
    """
    market    — output of market_data.get_market_data()
    positions — output of portfolio.get_live_positions()
    buying_power — available cash from Alpaca account
    regime    — "NORMAL" | "DEFENSE" | "PRESERVATION"
    vix       — current VIX level (None = unknown)
    """
    signals: List[Signal] = []

    vix_blocked = (vix is not None and vix > config.VIX_BUY_BLOCK_THRESHOLD)
    buy_frozen  = (regime != "NORMAL") or vix_blocked

    for ticker in config.WATCHLIST:
        d = market.get(ticker, {})
        if not d.get("valid"):
            signals.append(Signal(ticker, SKIP, 0.0, "No valid data"))
            continue

        price          = d["price"]
        rsi            = d.get("rsi")
        cushion        = d.get("cushion")
        trail_stop     = d.get("trail_stop")
        atr            = d.get("atr")
        volume_ratio   = d.get("volume_ratio")
        is_weekly_up   = d.get("is_weekly_uptrend", False)
        is_below_sma50 = d.get("is_below_sma50_confirmed", False)
        upper_band     = d.get("upper_band")

        is_owned = ticker in positions

        # ── EXIT checks (always run regardless of regime) ─────────────────

        # SELL_HARD: 2-day confirmed close below SMA50
        if is_below_sma50 and is_owned:
            signals.append(Signal(ticker, SELL_HARD, price,
                                  "2-day confirmed close below SMA50"))
            continue

        # SELL_PANIC: trailing ATR stop breached OR cushion hits floor
        if is_owned:
            atr_stop_hit = trail_stop is not None and price < trail_stop
            cushion_hit  = cushion is not None and cushion <= config.CUSHION_PANIC_PCT
            if atr_stop_hit or cushion_hit:
                reason = (f"Trailing ATR stop breached (stop={trail_stop:.2f})"
                          if atr_stop_hit else
                          f"Panic cushion floor hit ({cushion:.1f}%)")
                signals.append(Signal(ticker, SELL_PANIC, price, reason))
                continue

        # SELL_SOFT: RSI overbought or price above upper Bollinger Band
        if is_owned:
            rsi_hot  = rsi is not None and rsi > config.RSI_SOFT_EXIT
            band_hit = upper_band is not None and price > upper_band
            if rsi_hot or band_hit:
                reason = (f"RSI overbought ({rsi:.1f})"
                          if rsi_hot else
                          f"Price above upper Bollinger Band ({upper_band:.2f})")
                signals.append(Signal(ticker, SELL_SOFT, price, reason))
                continue

        # ── ENTRY checks ──────────────────────────────────────────────────

        if buy_frozen:
            reason = (f"VIX={vix:.1f} > {config.VIX_BUY_BLOCK_THRESHOLD}"
                      if vix_blocked else f"Regime={regime}, buying frozen")
            signals.append(Signal(ticker, SKIP, price, reason))
            continue

        if is_owned:
            signals.append(Signal(ticker, HOLD, price, "Position held, criteria not met for exit"))
            continue

        if not is_weekly_up:
            signals.append(Signal(ticker, SKIP, price, "Weekly trend down"))
            continue

        if rsi is None or rsi > config.RSI_BUY_MAX:
            signals.append(Signal(ticker, SKIP, price,
                                  f"RSI={rsi:.1f} above buy max {config.RSI_BUY_MAX}" if rsi else "RSI unavailable"))
            continue

        if cushion is None or cushion > config.CUSHION_BUY_PCT:
            signals.append(Signal(ticker, SKIP, price,
                                  f"Cushion={cushion:.1f}%, needs ≤{config.CUSHION_BUY_PCT}%" if cushion else "Cushion unavailable"))
            continue

        # Volume confirmation (new)
        if volume_ratio is not None and volume_ratio < config.VOLUME_CONFIRM_MULT:
            signals.append(Signal(ticker, SKIP, price,
                                  f"Volume ratio {volume_ratio:.2f}x below {config.VOLUME_CONFIRM_MULT}x threshold"))
            continue

        # Intraday shock filter (price already reflects live, check vs sma50)
        intraday_drop = (price / d.get("sma20", price) - 1.0) if d.get("sma20") else 0.0
        if intraday_drop < config.INTRADAY_SHOCK_PCT:
            signals.append(Signal(ticker, SKIP, price,
                                  f"Intraday shock filter triggered ({intraday_drop*100:.1f}%)"))
            continue

        # All checks passed → BUY
        signals.append(Signal(ticker, BUY, price,
                              f"RSI={rsi:.1f}, cushion={cushion:.1f}%, vol_ratio={volume_ratio:.2f}x, "
                              f"weekly_up={is_weekly_up}"))

    return signals
