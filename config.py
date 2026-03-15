import os
from dotenv import load_dotenv

load_dotenv()

# ─── ALPACA ────────────────────────────────────────────────────────────────
ALPACA_KEY    = os.getenv("ALPACA_KEY", "")
ALPACA_SECRET = os.getenv("ALPACA_SECRET", "")
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
ALPACA_BASE_URL = (
    "https://paper-api.alpaca.markets"
    if PAPER_TRADING else
    "https://api.alpaca.markets"
)

# ─── WATCHLIST ─────────────────────────────────────────────────────────────
# Refined to ~15 most liquid leveraged ETFs (>$10M avg daily volume)
WATCHLIST = [
    "TQQQ", "SOXL", "UPRO", "TECL", "FNGU",
    "FAS",  "LABU", "NAIL", "SPXL", "TNA",
    "UDOW", "CURE", "ERX",  "NUGT", "DFEN",
]

# ─── STRATEGY SIGNALS ──────────────────────────────────────────────────────
RSI_PERIOD          = 14
RSI_BUY_MAX         = 45.0      # Enter only when RSI ≤ this (not overbought)
RSI_SOFT_EXIT       = 75.0      # Sell 50% when RSI ≥ this

CUSHION_LOOKBACK_DAYS   = 20
CUSHION_BUY_PCT         = -8.0  # Buy when price is ≥8% below recent high
CUSHION_PANIC_PCT       = -15.0 # Hard panic sell floor

SMA_FAST            = 20        # Fast MA period
SMA_SLOW            = 50        # Slow MA period (hard stop)
CONFIRMATION_DAYS   = 2         # Days below SMA50 to confirm hard stop
WEEKLY_MA_FILTER    = 30        # 30-week MA uptrend filter

INTRADAY_SHOCK_PCT  = -0.06     # Block buy if intraday drop > 6%

# ─── NEW: IMPROVED INDICATORS ──────────────────────────────────────────────
ATR_PERIOD              = 14    # ATR lookback
ATR_MULTIPLIER          = 2.0   # Scales position size inversely to volatility
TRAIL_ATR_MULT          = 3.0   # Trailing stop = recent_high - (ATR * this)

VOLUME_CONFIRM_MULT     = 1.2   # Buy only if volume > 1.2x 20-day avg volume

VIX_BUY_BLOCK_THRESHOLD = 30.0  # Block all buys when VIX > this

# ─── RISK / SIZING ─────────────────────────────────────────────────────────
DRY_POWDER_FLOOR_PCT    = 0.30  # Keep 30% of portfolio in cash
DRY_POWDER_FLOOR_MIN    = 25_000.0
PER_RUN_DEPLOY_CAP_PCT  = 0.33  # Deploy max 33% of available budget per run
MAX_POSITION_CONC_PCT   = 0.20  # Max 20% of portfolio in one position

# ─── COOLDOWNS ─────────────────────────────────────────────────────────────
COOLDOWN_BUY_DAYS   = 3         # No re-buy within 3 days of last buy
COOLDOWN_SELL_DAYS  = 21        # Stay out 21 days after a sell

# ─── REGIME ────────────────────────────────────────────────────────────────
DRAWDOWN_DEFENSE_PCT        = -10.0  # Freeze buys if portfolio down 10%
DRAWDOWN_PRESERVATION_PCT   = -20.0  # Emergency mode at -20%
REGIME_HYSTERESIS_PCT       = 2.0    # Buffer band to avoid flip-flopping

# ─── LOGGING ───────────────────────────────────────────────────────────────
LOG_FILE        = "trades.log"
COOLDOWN_FILE   = "cooldown.json"
DRY_RUN         = os.getenv("DRY_RUN", "false").lower() == "true"
