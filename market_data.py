"""
market_data.py — Fetches daily indicators + live intraday price.

Indicators returned per ticker:
  price, rsi, sma20, sma50, upper_band, weekly_sma30,
  cushion, trend, atr, volume_ratio,
  is_weekly_uptrend, is_below_sma50_confirmed
"""

import pandas as pd
from typing import Dict, Any, List, Optional
import config

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest
    _ALPACA_OK = True
except ImportError:
    _ALPACA_OK = False


def _calc_rsi(series: pd.Series, period: int = 14) -> Optional[float]:
    if series is None or len(series) < period + 1:
        return None
    delta = series.diff().dropna()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    return float(100 - (100 / (1 + avg_gain / avg_loss)))


def _calc_atr(hist: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Average True Range — measures daily volatility."""
    if hist is None or len(hist) < period + 1:
        return None
    high = hist["High"]
    low  = hist["Low"]
    prev_close = hist["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def _live_price(client, ticker: str) -> Optional[float]:
    try:
        req = StockLatestTradeRequest(symbol_or_symbols=ticker)
        res = client.get_stock_latest_trade(req)
        return float(res[ticker].price)
    except Exception:
        return None


def get_vix() -> Optional[float]:
    """Fetch current VIX level. Returns None on failure."""
    if yf is None:
        return None
    try:
        hist = yf.Ticker("^VIX").history(period="2d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def get_market_data(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Returns a dict keyed by ticker with all indicators needed by strategy.py.
    Invalid / failed tickers get {"valid": False}.
    """
    out: Dict[str, Dict[str, Any]] = {}

    # Build Alpaca data client once
    data_client = None
    if _ALPACA_OK and config.ALPACA_KEY and config.ALPACA_SECRET:
        try:
            data_client = StockHistoricalDataClient(
                config.ALPACA_KEY, config.ALPACA_SECRET
            )
        except Exception as e:
            print(f"⚠️  Alpaca data client error: {e}")

    for t in tickers:
        try:
            if yf is None:
                out[t] = {"valid": False}
                continue

            hist = yf.Ticker(t).history(period="2y")
            if hist is None or hist.empty or len(hist) < 60:
                out[t] = {"valid": False}
                continue

            # ── Price (live Alpaca → fallback yfinance close) ────────────
            live = _live_price(data_client, t) if data_client else None
            price = live if (live and live > 0) else float(hist["Close"].iloc[-1])

            close = hist["Close"]

            # ── Trend indicators ─────────────────────────────────────────
            sma20 = float(close.rolling(config.SMA_FAST).mean().iloc[-1])
            sma50 = float(close.rolling(config.SMA_SLOW).mean().iloc[-1])
            std20 = float(close.rolling(config.SMA_FAST).std().iloc[-1])
            upper_band = sma20 + 2 * std20
            trend = "UP" if sma20 >= sma50 else "DOWN"

            # ── RSI ───────────────────────────────────────────────────────
            rsi = _calc_rsi(close, config.RSI_PERIOD)

            # ── ATR (new) ─────────────────────────────────────────────────
            atr = _calc_atr(hist, config.ATR_PERIOD)

            # ── Volume ratio vs 20-day avg (new) ──────────────────────────
            vol_today = float(hist["Volume"].iloc[-1])
            vol_avg20 = float(hist["Volume"].rolling(20).mean().iloc[-1])
            volume_ratio = (vol_today / vol_avg20) if vol_avg20 > 0 else None

            # ── Cushion (% below recent high) ─────────────────────────────
            lookback = min(config.CUSHION_LOOKBACK_DAYS, len(close))
            recent_high = float(close.tail(lookback).max())
            if price > recent_high:
                recent_high = price
            cushion = ((price / recent_high) - 1.0) * 100.0 if recent_high > 0 else None

            # ── Trailing ATR stop (new) ───────────────────────────────────
            trail_stop = None
            if atr and recent_high:
                trail_stop = recent_high - (atr * config.TRAIL_ATR_MULT)

            # ── 2-day SMA50 confirmation ──────────────────────────────────
            sma50_series = close.rolling(config.SMA_SLOW).mean()
            is_below_confirmed = False
            if len(close) >= 2:
                prev_px = float(close.iloc[-2])
                prev_ma = float(sma50_series.iloc[-2])
                if (price < sma50) and (prev_px < prev_ma):
                    is_below_confirmed = True

            # ── Weekly uptrend filter ─────────────────────────────────────
            weekly_close = close.resample("W-FRI").last()
            weekly_sma30_val = weekly_close.rolling(config.WEEKLY_MA_FILTER).mean().iloc[-1]
            weekly_sma30 = float(weekly_sma30_val) if pd.notnull(weekly_sma30_val) else None
            is_weekly_uptrend = bool(price > weekly_sma30) if weekly_sma30 else False

            out[t] = {
                "valid":                    True,
                "price":                    price,
                "rsi":                      rsi,
                "sma20":                    sma20,
                "sma50":                    sma50,
                "upper_band":               upper_band,
                "weekly_sma30":             weekly_sma30,
                "cushion":                  cushion,
                "recent_high":              recent_high,
                "trail_stop":               trail_stop,
                "atr":                      atr,
                "volume_ratio":             volume_ratio,
                "trend":                    trend,
                "is_weekly_uptrend":        is_weekly_uptrend,
                "is_below_sma50_confirmed": is_below_confirmed,
            }

        except Exception as e:
            print(f"⚠️  {t}: data fetch failed — {e}")
            out[t] = {"valid": False}

    return out
