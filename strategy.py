"""
strategy.py — Signal generation for leveraged ETF trading (v2: AI Boom Aggressive).

Key changes from v1:
  - Tiered watchlist rotation: when tech weekly trend breaks, pivot to Tier3 (financials/defense)
  - Weekly trend filter removed per-ticker — used only to decide which tier to scan
  - RSI entry loosened to 50, cushion to -6%, VIX block raised to 35
  - Max 2 concurrent positions enforced here
  - Volume filter relaxed to 0.8x (only blocks truly dead days)

Signal types returned: BUY / SELL_SOFT / SELL_HARD / SELL_PANIC / HOLD / SKIP
"""

from typing import Dict, Any, List
from dataclasses import dataclass
import config

BUY         = "BUY"
SELL_SOFT   = "SELL_SOFT"    # RSI/Bollinger overbought -> sell 50%
SELL_HARD   = "SELL_HARD"    # 2-day confirmed close below SMA50 -> full exit
SELL_PANIC  = "SELL_PANIC"   # Trailing ATR stop OR cushion floor -> full exit
HOLD        = "HOLD"
SKIP        = "SKIP"


@dataclass
class Signal:
    ticker:  str
    action:  str
    price:   float
    reason:  str
    qty:     int = 0


def _active_scan_tickers(market: Dict[str, Dict[str, Any]]) -> List[str]:
    """
    Determine which tier to scan based on how many Tier1 tickers are in weekly uptrend.
    >= TIER1_HEALTHY_MIN healthy -> scan Tier1 + Tier2 (tech focus)
    <  TIER1_HEALTHY_MIN healthy -> scan Tier2 + Tier3 (rotation)
    """
    tier1_healthy = sum(
        1 for t in config.TIER1
        if market.get(t, {}).get("is_weekly_uptrend", False)
    )
    if tier1_healthy >= config.TIER1_HEALTHY_MIN:
        return config.TIER1 + config.TIER2
    else:
        return config.TIER2 + config.TIER3


def generate_signals(
    market:       Dict[str, Dict[str, Any]],
    positions:    Dict[str, Dict[str, Any]],
    buying_power: float,
    regime:       str,
    vix:          float | None,
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
    slots_open  = config.MAX_CONCURRENT_POSITIONS - len(positions)

    # Determine which tickers are eligible for buys this run
    scan_tickers = _active_scan_tickers(market)
    tier1_healthy = sum(1 for t in config.TIER1 if market.get(t, {}).get("is_weekly_uptrend", False))
    rotation_mode = tier1_healthy < config.TIER1_HEALTHY_MIN

    # ── Process ALL tickers for exit signals, scan_tickers for entries ────
    all_tickers = list(set(config.WATCHLIST))

    for ticker in all_tickers:
        d = market.get(ticker, {})
        if not d.get("valid"):
            signals.append(Signal(ticker, SKIP, 0.0, "No valid data"))
            continue

        price          = d["price"]
        rsi            = d.get("rsi")
        cushion        = d.get("cushion")
        trail_stop     = d.get("trail_stop")
        upper_band     = d.get("upper_band")
        sma20          = d.get("sma20")
        is_below_sma50 = d.get("is_below_sma50_confirmed", False)
        volume_ratio   = d.get("volume_ratio")
        is_owned       = ticker in positions

        # ── EXIT checks (run for all owned tickers regardless of tier) ────

        if is_owned:
            # SELL_HARD: 2-day confirmed close below SMA50
            if is_below_sma50:
                signals.append(Signal(ticker, SELL_HARD, price,
                                      "2-day confirmed close below SMA50"))
                continue

            # SELL_PANIC: trailing ATR stop breached OR cushion floor hit
            atr_stop_hit = trail_stop is not None and price < trail_stop
            cushion_hit  = cushion is not None and cushion <= config.CUSHION_PANIC_PCT
            if atr_stop_hit or cushion_hit:
                reason = (f"Trailing ATR stop breached (stop={trail_stop:.2f})"
                          if atr_stop_hit else
                          f"Panic cushion floor ({cushion:.1f}%)")
                signals.append(Signal(ticker, SELL_PANIC, price, reason))
                continue

            # SELL_SOFT: RSI overbought or above Bollinger Band
            rsi_hot  = rsi is not None and rsi > config.RSI_SOFT_EXIT
            band_hit = upper_band is not None and price > upper_band
            if rsi_hot or band_hit:
                reason = (f"RSI overbought ({rsi:.1f})"
                          if rsi_hot else f"Above Bollinger Band ({upper_band:.2f})")
                signals.append(Signal(ticker, SELL_SOFT, price, reason))
                continue

            # No exit signal — hold
            signals.append(Signal(ticker, HOLD, price, "Holding — no exit criteria met"))
            continue

        # ── ENTRY checks (only for tickers in active scan tier) ──────────

        if ticker not in scan_tickers:
            tier_label = "Tier1+2" if not rotation_mode else "Tier2+3 (rotation)"
            signals.append(Signal(ticker, SKIP, price,
                                  f"Not in active scan tier ({tier_label})"))
            continue

        if buy_frozen:
            reason = (f"VIX={vix:.1f} > {config.VIX_BUY_BLOCK_THRESHOLD}"
                      if vix_blocked else f"Regime={regime}, buying frozen")
            signals.append(Signal(ticker, SKIP, price, reason))
            continue

        if slots_open <= 0:
            signals.append(Signal(ticker, SKIP, price,
                                  f"Max {config.MAX_CONCURRENT_POSITIONS} positions already open"))
            continue

        # Daily trend: SMA20 >= SMA50 (no weekly filter per-ticker)
        if sma20 is None or d.get("sma50") is None or sma20 < d.get("sma50", 0):
            signals.append(Signal(ticker, SKIP, price, "Daily trend down (SMA20 < SMA50)"))
            continue

        if rsi is None or rsi > config.RSI_BUY_MAX:
            signals.append(Signal(ticker, SKIP, price,
                                  f"RSI={rsi:.1f} above {config.RSI_BUY_MAX}" if rsi else "RSI unavailable"))
            continue

        if cushion is None or cushion > config.CUSHION_BUY_PCT:
            signals.append(Signal(ticker, SKIP, price,
                                  f"Cushion={cushion:.1f}%, needs <={config.CUSHION_BUY_PCT}%" if cushion else "Cushion unavailable"))
            continue

        # Volume: relaxed to 0.8x (only blocks truly dead volume days)
        if volume_ratio is not None and volume_ratio < config.VOLUME_CONFIRM_MULT:
            signals.append(Signal(ticker, SKIP, price,
                                  f"Volume {volume_ratio:.2f}x below {config.VOLUME_CONFIRM_MULT}x floor"))
            continue

        # Intraday shock filter
        intraday_drop = (price / sma20 - 1.0) if sma20 else 0.0
        if intraday_drop < config.INTRADAY_SHOCK_PCT:
            signals.append(Signal(ticker, SKIP, price,
                                  f"Intraday shock ({intraday_drop*100:.1f}%)"))
            continue

        # All checks passed -> BUY
        mode_tag = "ROTATION" if rotation_mode else "TECH"
        signals.append(Signal(ticker, BUY, price,
                              f"[{mode_tag}] RSI={rsi:.1f}, cushion={cushion:.1f}%, "
                              f"vol={volume_ratio:.2f}x"))

    return signals
