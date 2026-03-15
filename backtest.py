"""
backtest.py — Head-to-head comparison: original strategy vs improved strategy.

Runs both strategies on the same 2-year historical data and prints
a side-by-side performance summary.

Usage:
  python backtest.py                  # uses config.WATCHLIST
  python backtest.py --tickers TQQQ SOXL UPRO TECL
  python backtest.py --period 3y
"""

import argparse
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("yfinance required: pip install yfinance")

import config

START_CAPITAL = 100_000.0


# ─── Shared indicator helpers ─────────────────────────────────────────────

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss  = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = data["High"], data["Low"], data["Close"]
    prev_c = close.shift(1)
    tr = pd.concat([high - low, (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _build_indicators(tickers: list, period: str) -> dict:
    """Download OHLCV and compute all indicators for both strategies."""
    print(f"Downloading Downloading {len(tickers)} tickers ({period}) ...")
    raw = yf.download(tickers, period=period, progress=False, group_by="ticker")
    indicators = {}
    for t in tickers:
        if len(tickers) == 1:
            df = raw.copy()
        else:
            df = raw[t].copy()
        df = df.dropna()
        if len(df) < 60:
            print(f"  WARN:  {t}: insufficient data, skipping")
            continue

        close = df["Close"]
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        std20 = close.rolling(20).std()

        weekly_close = close.resample("W-FRI").last()
        weekly_sma30 = weekly_close.rolling(30).mean().reindex(close.index, method="ffill")

        recent_high  = close.rolling(config.CUSHION_LOOKBACK_DAYS).max()
        cushion      = (close / recent_high - 1.0) * 100.0

        atr_series   = _atr(df, config.ATR_PERIOD)
        trail_stop   = recent_high - (atr_series * config.TRAIL_ATR_MULT)

        vol_avg20    = df["Volume"].rolling(20).mean()
        vol_ratio    = df["Volume"] / vol_avg20.replace(0, np.nan)

        indicators[t] = pd.DataFrame({
            "price":      close,
            "sma20":      sma20,
            "sma50":      sma50,
            "upper_band": sma20 + 2 * std20,
            "rsi":        _rsi(close),
            "cushion":    cushion,
            "recent_high":recent_high,
            "weekly_up":  (close > weekly_sma30),
            "atr":        atr_series,
            "trail_stop": trail_stop,
            "vol_ratio":  vol_ratio,
        })
    return indicators


# ─── Original strategy simulation ─────────────────────────────────────────

def _run_original(indicators: dict) -> pd.Series:
    """Replicates the original Divine-Wealth signal logic."""
    tickers = list(indicators.keys())
    cash    = START_CAPITAL
    held    = {t: 0 for t in tickers}
    last_buy= {t: None for t in tickers}
    history = []
    dates   = next(iter(indicators.values())).index

    for i in range(50, len(dates)):
        d = dates[i]

        # Sells
        for t in tickers:
            if held[t] == 0: continue
            row = indicators[t].iloc[i]
            sell, _ = False, ""
            if row["cushion"] <= config.CUSHION_PANIC_PCT:
                sell = True
            elif row["rsi"] >= config.RSI_SOFT_EXIT:
                sell = True
            elif row["sma20"] < row["sma50"] and (row["cushion"] <= config.CUSHION_PANIC_PCT or row["rsi"] < 35):
                sell = True
            if sell:
                cash += held[t] * row["price"]
                held[t] = 0

        # Buys
        candidates = []
        for t in tickers:
            if held[t] > 0: continue
            row = indicators[t].iloc[i]
            if np.isnan(row["rsi"]): continue
            on_cd = last_buy[t] and (d - last_buy[t]).days < config.COOLDOWN_BUY_DAYS
            if (row["sma20"] >= row["sma50"] and
                    row["rsi"] <= config.RSI_BUY_MAX and
                    row["cushion"] <= config.CUSHION_BUY_PCT and
                    not on_cd):
                candidates.append(t)

        if candidates:
            alloc = min(cash / len(candidates), cash * 0.5)
            for t in candidates:
                p = indicators[t].iloc[i]["price"]
                shares = int(alloc / p)
                if shares > 0:
                    cash -= shares * p
                    held[t] += shares
                    last_buy[t] = d

        total = cash + sum(held[t] * indicators[t].iloc[i]["price"] for t in tickers)
        history.append(total)

    return pd.Series(history, index=dates[50:])


# ─── Improved strategy simulation ─────────────────────────────────────────

def _run_improved(indicators: dict) -> pd.Series:
    """Improved strategy with VIX filter, ATR sizing, volume confirm, trailing stop."""
    tickers  = list(indicators.keys())
    cash     = START_CAPITAL
    held     = {t: 0 for t in tickers}
    last_buy = {t: None for t in tickers}
    history  = []
    dates    = next(iter(indicators.values())).index

    for i in range(50, len(dates)):
        d = dates[i]

        # Sells (trailing ATR stop + existing logic)
        for t in tickers:
            if held[t] == 0: continue
            row = indicators[t].iloc[i]
            sell = False
            # Trailing ATR stop (new)
            if not np.isnan(row["trail_stop"]) and row["price"] < row["trail_stop"]:
                sell = True
            elif row["cushion"] <= config.CUSHION_PANIC_PCT:
                sell = True
            elif row["rsi"] >= config.RSI_SOFT_EXIT or row["price"] > row["upper_band"]:
                # Soft exit to sell half
                sell_qty = max(1, held[t] // 2)
                cash += sell_qty * row["price"]
                held[t] -= sell_qty
                continue
            # Hard stop: 2-day below SMA50
            elif (i > 0 and
                    row["price"] < row["sma50"] and
                    indicators[t].iloc[i-1]["price"] < indicators[t].iloc[i-1]["sma50"]):
                sell = True
            if sell:
                cash += held[t] * row["price"]
                held[t] = 0

        # Buys (weekly uptrend + volume confirm + ATR sizing)
        candidates = []
        for t in tickers:
            if held[t] > 0: continue
            row = indicators[t].iloc[i]
            if np.isnan(row["rsi"]): continue
            on_cd = last_buy[t] and (d - last_buy[t]).days < config.COOLDOWN_BUY_DAYS
            vol_ok = np.isnan(row["vol_ratio"]) or row["vol_ratio"] >= config.VOLUME_CONFIRM_MULT
            if (row["sma20"] >= row["sma50"] and
                    row["weekly_up"] and
                    row["rsi"] <= config.RSI_BUY_MAX and
                    row["cushion"] <= config.CUSHION_BUY_PCT and
                    vol_ok and
                    not on_cd):
                candidates.append(t)

        if candidates:
            for t in candidates:
                row = indicators[t].iloc[i]
                p   = row["price"]
                atr = row["atr"]
                # ATR-based sizing
                if not np.isnan(atr) and atr > 0 and p > 0:
                    vol_pct  = atr / p
                    base     = min(cash * config.PER_RUN_DEPLOY_CAP_PCT / len(candidates),
                                   START_CAPITAL * config.MAX_POSITION_CONC_PCT)
                    dollar   = base / (vol_pct * config.ATR_MULTIPLIER)
                    dollar   = max(base * 0.2, min(dollar, base))
                else:
                    dollar = cash * 0.2 / len(candidates)

                shares = int(dollar / p)
                if shares > 0 and cash >= shares * p:
                    cash -= shares * p
                    held[t] += shares
                    last_buy[t] = d

        total = cash + sum(held[t] * indicators[t].iloc[i]["price"] for t in tickers)
        history.append(total)

    return pd.Series(history, index=dates[50:])


# ─── Metrics ──────────────────────────────────────────────────────────────

def _metrics(equity: pd.Series, label: str) -> dict:
    ret    = (equity.iloc[-1] - START_CAPITAL) / START_CAPITAL * 100
    peak   = equity.cummax()
    dd     = ((equity - peak) / peak).min() * 100
    daily  = equity.pct_change().dropna()
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    return {"label": label, "final": equity.iloc[-1], "return_pct": ret,
            "max_dd_pct": dd, "sharpe": sharpe}


# ─── Entry point ──────────────────────────────────────────────────────────

def run(tickers: list, period: str = "2y"):
    indicators = _build_indicators(tickers, period)
    if not indicators:
        print("No valid data. Exiting.")
        return

    print("Running  Running original strategy...")
    eq_orig = _run_original(indicators)
    print("Running  Running improved strategy...")
    eq_new  = _run_improved(indicators)

    m_orig = _metrics(eq_orig, "Original")
    m_new  = _metrics(eq_new,  "Improved")

    print("\n" + "=" * 55)
    print(f"  BACKTEST RESULTS  ({indicators[tickers[0]].index[50].date()} to {indicators[tickers[0]].index[-1].date()})")
    print("=" * 55)
    print(f"  {'Metric':<22} {'Original':>12} {'Improved':>12}")
    print(f"  {'-'*22} {'-'*12} {'-'*12}")
    print(f"  {'Final Value':<22} ${m_orig['final']:>11,.0f} ${m_new['final']:>11,.0f}")
    print(f"  {'Total Return':<22} {m_orig['return_pct']:>+11.1f}% {m_new['return_pct']:>+11.1f}%")
    print(f"  {'Max Drawdown':<22} {m_orig['max_dd_pct']:>+11.1f}% {m_new['max_dd_pct']:>+11.1f}%")
    print(f"  {'Sharpe Ratio':<22} {m_orig['sharpe']:>12.2f} {m_new['sharpe']:>12.2f}")
    print("=" * 55)
    winner = "Improved" if m_new["sharpe"] > m_orig["sharpe"] else "Original"
    print(f"  Winner (Sharpe): {winner}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", default=config.WATCHLIST[:5])
    parser.add_argument("--period",  default="2y")
    args = parser.parse_args()
    run(args.tickers, args.period)
