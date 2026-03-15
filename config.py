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

# ─── TIERED WATCHLIST ──────────────────────────────────────────────────────
# Tier 1: AI/Tech core — buy first when market is healthy
TIER1 = ["TQQQ", "SOXL", "TECL", "FNGU", "UPRO", "SPXL"]

# Tier 2: Broad market — buy when Tier 1 is dipping but overall market intact
TIER2 = ["UDOW", "TNA"]

# Tier 3: Rotation — buy when tech weekly trend broken (independent sector cycles)
TIER3 = ["FAS", "ERX", "DFEN", "LABU", "CURE", "NUGT", "NAIL"]

# Full list (used by market_data and backtest)
WATCHLIST = TIER1 + TIER2 + TIER3

# Tier rotation threshold: if < this many Tier1 tickers in weekly uptrend, pivot to Tier3
TIER1_HEALTHY_MIN = 2

# ─── STRATEGY SIGNALS ──────────────────────────────────────────────────────
RSI_PERIOD          = 14
RSI_BUY_MAX         = 50.0      # Loosened from 45 — catch more of the rally
RSI_SOFT_EXIT       = 75.0      # Sell 50% when RSI >= this

CUSHION_LOOKBACK_DAYS   = 20
CUSHION_BUY_PCT         = -6.0  # Loosened from -8 — enter earlier on dips
CUSHION_PANIC_PCT       = -12.0 # Tightened from -15 — exit sooner to control losses

SMA_FAST            = 20        # Fast MA period
SMA_SLOW            = 50        # Slow MA period (hard stop reference)
CONFIRMATION_DAYS   = 2         # Days below SMA50 to confirm hard stop
WEEKLY_MA_FILTER    = 30        # Used for tier rotation check only (not per-ticker block)

INTRADAY_SHOCK_PCT  = -0.06     # Block buy if intraday drop > 6%

# ─── INDICATORS ────────────────────────────────────────────────────────────
ATR_PERIOD              = 14    # ATR lookback
ATR_MULTIPLIER          = 2.0   # Scales position size inversely to volatility
TRAIL_ATR_MULT          = 2.0   # Tightened from 3.0 — faster trailing stop exit

VOLUME_CONFIRM_MULT     = 0.8   # Loosened from 1.2 — only block truly dead volume days

VIX_BUY_BLOCK_THRESHOLD = 35.0  # Loosened from 30 — VIX 30-35 is a prime buy zone

# ─── CONCENTRATED POSITION SIZING ──────────────────────────────────────────
MAX_CONCURRENT_POSITIONS = 2    # Hard cap: only 2 open trades at once
POSITION_SIZE_PCT        = 0.45 # Target 45% of portfolio per trade ($45K on $100K)
DRY_POWDER_FLOOR_PCT     = 0.10 # Keep only 10% cash reserve (was 30%)
DRY_POWDER_FLOOR_MIN     = 5_000.0
PER_RUN_DEPLOY_CAP_PCT   = 1.0  # No per-run cap — sizing controlled by POSITION_SIZE_PCT
MAX_POSITION_CONC_PCT    = 0.50 # Allow up to 50% in one position (2 x 45% = 90% deployed)

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
