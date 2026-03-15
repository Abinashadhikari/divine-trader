"""
scheduler.py — Market hours check + Windows Task Scheduler helper.

agent.py calls is_market_open() at startup and exits silently if closed.
This means Task Scheduler can safely fire every hour 24/7 — the script
self-guards against running outside market hours.
"""

from datetime import datetime, time
import pytz

_ET = pytz.timezone("America/New_York")

# NYSE regular session
MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Market holidays 2025-2026 (NYSE)
_HOLIDAYS = {
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18",
    "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01",
    "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}


def is_market_open() -> tuple[bool, str]:
    """
    Returns (is_open, reason).
    Checks: weekday, holiday, and trading hours (ET).
    """
    now_et = datetime.now(_ET)
    today  = now_et.strftime("%Y-%m-%d")
    t      = now_et.time()

    if now_et.weekday() >= 5:
        return False, f"Weekend ({now_et.strftime('%A')})"

    if today in _HOLIDAYS:
        return False, f"Market holiday ({today})"

    if t < MARKET_OPEN:
        return False, f"Pre-market (opens 09:30 ET, now {t.strftime('%H:%M')} ET)"

    if t >= MARKET_CLOSE:
        return False, f"After-hours (closed 16:00 ET, now {t.strftime('%H:%M')} ET)"

    return True, f"Market open ({t.strftime('%H:%M')} ET)"


def print_task_scheduler_instructions():
    """Prints step-by-step Windows Task Scheduler setup."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║         Windows Task Scheduler Setup — divine-trader         ║
╚══════════════════════════════════════════════════════════════╝

1. Open Task Scheduler (search "Task Scheduler" in Start)
2. Click "Create Basic Task..."
3. Name: "Divine Trader"  Description: "Hourly leveraged ETF agent"
4. Trigger → Daily → Start: 09:00 AM
5. Action → "Start a program"
   Program: C:\\Users\\abina\\AppData\\Local\\Programs\\Python\\Python311\\python.exe
   Arguments: agent.py
   Start in: C:\\Users\\abina\\OneDrive\\Desktop\\divine-trader
6. Finish → then open "Properties" on the task
7. Triggers tab → Edit → check "Repeat task every: 1 hour"
   for a duration of: "Indefinitely"
8. Settings tab → check "Run task as soon as possible after a
   scheduled start is missed"

The script checks market hours itself and exits silently if closed.
    """)


if __name__ == "__main__":
    open_, reason = is_market_open()
    print(f"Market {'OPEN' if open_ else 'CLOSED'}: {reason}")
    print_task_scheduler_instructions()
