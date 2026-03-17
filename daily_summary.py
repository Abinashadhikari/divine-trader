"""
daily_summary.py — End-of-day report for Divine Trader.

Reads trades.log, cooldown.json, state.json and fetches live account
snapshot from Alpaca to produce DAILY_SUMMARY.md.

Run by GitHub Actions after market close each weekday.
"""

import json
import os
from datetime import datetime, date, timezone

import config
import portfolio

TODAY = date.today().isoformat()
SUMMARY_FILE = "DAILY_SUMMARY.md"


def _parse_trades_log() -> list[dict]:
    records = []
    if not os.path.exists(config.LOG_FILE):
        return records
    with open(config.LOG_FILE) as f:
        for line in f:
            # Each line: "YYYY-MM-DD HH:MM:SS | {json}"
            if " | " not in line:
                continue
            _, _, payload = line.partition(" | ")
            try:
                records.append(json.loads(payload.strip()))
            except json.JSONDecodeError:
                continue
    return records


def _load_state() -> dict:
    if os.path.exists("state.json"):
        try:
            with open("state.json") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _load_cooldown() -> dict:
    if os.path.exists(config.COOLDOWN_FILE):
        try:
            with open(config.COOLDOWN_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def build_summary() -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    all_trades = _parse_trades_log()
    today_trades = [t for t in all_trades if t.get("time", "").startswith(TODAY)]
    state = _load_state()
    cooldown = _load_cooldown()

    # Account snapshot from Alpaca
    acct = portfolio.get_account_info()
    positions = portfolio.get_live_positions()
    portfolio_value = acct.get("portfolio_value", 0.0)
    buying_power    = acct.get("buying_power", 0.0)
    cash            = acct.get("cash", 0.0)
    peak            = state.get("peak_portfolio_value", portfolio_value)
    drawdown        = ((portfolio_value / peak) - 1) * 100 if peak > 0 else 0.0

    # ── Header ────────────────────────────────────────────────────────────────
    lines = [
        f"# Divine Trader — Daily Summary",
        f"**Date:** {TODAY}  |  **Generated:** {now_utc}  |  **Mode:** {'PAPER' if config.PAPER_TRADING else 'LIVE'}",
        "",
    ]

    # ── Portfolio Snapshot ────────────────────────────────────────────────────
    lines += [
        "## Portfolio Snapshot",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Portfolio Value | ${portfolio_value:,.2f} |",
        f"| Buying Power    | ${buying_power:,.2f} |",
        f"| Cash            | ${cash:,.2f} |",
        f"| Peak Value      | ${peak:,.2f} |",
        f"| Drawdown        | {drawdown:+.2f}% |",
        "",
    ]

    # ── Open Positions ────────────────────────────────────────────────────────
    if positions:
        lines += [
            "## Open Positions",
            "| Ticker | Qty | Avg Entry | Market Value | Unrealized P&L |",
            "|--------|-----|-----------|--------------|----------------|",
        ]
        for ticker, p in positions.items():
            pnl = p.get("unrealized_pnl", 0)
            pnl_icon = "+" if pnl >= 0 else ""
            lines.append(
                f"| {ticker} | {int(p['qty'])} | ${p['avg_entry']:,.2f} "
                f"| ${p['market_value']:,.2f} | {pnl_icon}${pnl:,.2f} |"
            )
        lines.append("")
    else:
        lines += ["## Open Positions", "_No open positions._", ""]

    # ── Today's Trades ────────────────────────────────────────────────────────
    if today_trades:
        lines += [
            f"## Today's Trades ({len(today_trades)} order{'s' if len(today_trades) != 1 else ''})",
            "| Time (UTC) | Ticker | Side | Qty | Price | Action | Status | Reason |",
            "|------------|--------|------|-----|-------|--------|--------|--------|",
        ]
        for t in today_trades:
            ts = t.get("time", "")[:19].replace("T", " ")
            lines.append(
                f"| {ts} | {t.get('ticker','')} | {t.get('side','').upper()} "
                f"| {t.get('qty','')} | ${float(t.get('price') or 0):,.2f} "
                f"| {t.get('action','')} | {t.get('status','')} | {t.get('reason','')} |"
            )
        lines.append("")
    else:
        lines += [f"## Today's Trades", "_No trades executed today._", ""]

    # ── Cooldowns ─────────────────────────────────────────────────────────────
    if cooldown:
        lines += [
            "## Active Cooldowns",
            "| Ticker | Type | Expires |",
            "|--------|------|---------|",
        ]
        for ticker, info in cooldown.items():
            lines.append(f"| {ticker} | {info.get('type','')} | {info.get('until','')} |")
        lines.append("")
    else:
        lines += ["## Active Cooldowns", "_No active cooldowns._", ""]

    # ── All-Time Trade History ────────────────────────────────────────────────
    if all_trades:
        total_buys  = sum(1 for t in all_trades if t.get("side") == "buy"  and t.get("status","").startswith("SUBMITTED"))
        total_sells = sum(1 for t in all_trades if t.get("side") == "sell" and t.get("status","").startswith("SUBMITTED"))
        lines += [
            "## All-Time Stats",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total Submitted Buys  | {total_buys} |",
            f"| Total Submitted Sells | {total_sells} |",
            f"| Total Log Entries     | {len(all_trades)} |",
            "",
        ]

    lines += [
        "---",
        f"_Auto-generated by [divine-trader](https://github.com/Abinashadhikari/divine-trader) daily summary workflow._",
    ]

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    summary = build_summary()
    with open(SUMMARY_FILE, "w") as f:
        f.write(summary)
    print(summary)
    print(f"\nWritten to {SUMMARY_FILE}")
