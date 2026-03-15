"""Tests for strategy.py signal generation (v2 AI Boom Aggressive)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from strategy import generate_signals, BUY, SELL_SOFT, SELL_HARD, SELL_PANIC, HOLD, SKIP
import config


def _make_data(price=100.0, rsi=40.0, cushion=-10.0, weekly_up=True,
               below_sma50=False, upper_band=120.0, volume_ratio=1.5,
               atr=2.0, trail_stop=80.0, recent_high=111.0, sma50_mult=0.95):
    """
    Build a single ticker market dict.
    sma20 = price * 0.97 (above sma50 by default → daily trend up).
    sma50 = price * sma50_mult (default 0.95, so sma20 > sma50 → uptrend).
    """
    sma20 = price * 0.97
    sma50 = price * sma50_mult
    return {
        "valid": True, "price": price, "rsi": rsi, "cushion": cushion,
        "is_weekly_uptrend": weekly_up,
        "is_below_sma50_confirmed": below_sma50,
        "upper_band": upper_band, "volume_ratio": volume_ratio,
        "atr": atr, "trail_stop": trail_stop, "recent_high": recent_high,
        "sma20": sma20, "sma50": sma50,
    }


def _tier1_market(tickers=None, **kwargs):
    """
    Build a market dict where TIER1_HEALTHY_MIN (2) Tier1 tickers are healthy
    so that TQQQ is included in the active scan tier.
    Extra kwargs override TQQQ's data fields.
    """
    tqqq_data = _make_data(**kwargs)
    # Add a second Tier1 ticker in weekly uptrend to reach TIER1_HEALTHY_MIN=2
    soxl_data = _make_data()
    return {"TQQQ": tqqq_data, "SOXL": soxl_data}


class TestBuySignals(unittest.TestCase):

    def _run(self, market, positions=None, buying_power=50_000, regime="NORMAL", vix=20.0):
        positions = positions or {}
        sigs = generate_signals(market, positions, buying_power, regime, vix)
        return {s.ticker: s for s in sigs}

    def test_buy_all_conditions_met(self):
        # Two TIER1 tickers healthy -> TQQQ in scan tier -> BUY
        market = _tier1_market()
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, BUY)

    def test_skip_vix_too_high(self):
        # VIX threshold is 35 — vix > 35 blocks buys
        market = _tier1_market()
        sigs = self._run(market, vix=36.0)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_vix_at_threshold_not_blocked(self):
        # VIX exactly at 35.0 should NOT block (block is strictly vix > 35)
        market = _tier1_market()
        sigs = self._run(market, vix=35.0)
        self.assertEqual(sigs["TQQQ"].action, BUY)

    def test_skip_regime_defense(self):
        market = _tier1_market()
        sigs = self._run(market, regime="DEFENSE")
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_skip_tier1_rotation_mode(self):
        # Only 1 Tier1 ticker in weekly uptrend -> rotation mode -> TQQQ not in scan tier
        market = {"TQQQ": _make_data(weekly_up=True), "SOXL": _make_data(weekly_up=False)}
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_buy_tier3_in_rotation_mode(self):
        # When tech is down, Tier3 tickers should be in scan tier
        # Use FAS (Tier3) with all entry conditions met
        market = {
            "TQQQ": _make_data(weekly_up=False),  # Tier1 unhealthy -> rotation
            "SOXL": _make_data(weekly_up=False),
            "FAS":  _make_data(),                  # Tier3, all conditions good
        }
        sigs = self._run(market)
        self.assertEqual(sigs["FAS"].action, BUY)

    def test_skip_rsi_too_high(self):
        # RSI threshold is 50 — rsi > 50 blocks buys
        market = _tier1_market(rsi=51.0)
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_rsi_at_threshold_passes(self):
        # RSI exactly at 50.0 should pass (rsi <= 50)
        market = _tier1_market(rsi=50.0)
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, BUY)

    def test_skip_cushion_too_shallow(self):
        # Cushion must be <= -6% to buy
        market = _tier1_market(cushion=-3.0)
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_skip_volume_too_low(self):
        # Volume floor is 0.8x — volume < 0.8 blocks buys
        market = _tier1_market(volume_ratio=0.7)
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_volume_at_floor_passes(self):
        # Volume exactly at 0.8x should pass (>= 0.8)
        market = _tier1_market(volume_ratio=0.8)
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, BUY)

    def test_skip_daily_trend_down(self):
        # SMA20 < SMA50 (daily downtrend) blocks buy even in healthy tier
        # sma50_mult=1.01 means sma50 > sma20 -> downtrend
        market = _tier1_market(sma50_mult=1.01)
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_skip_max_positions_full(self):
        # Both slots already occupied -> no new buys
        market = _tier1_market()
        positions = {"TQQQ": {"qty": 100}, "SOXL": {"qty": 50}}
        sigs = self._run(market, positions=positions)
        # TQQQ and SOXL are owned so they get HOLD (no exit triggers)
        # No new BUY can be generated
        actions = [s.action for s in sigs.values()]
        self.assertNotIn(BUY, actions)

    def test_skip_invalid_data(self):
        market = {"TQQQ": {"valid": False}}
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)


class TestSellSignals(unittest.TestCase):

    def _run(self, market, positions, regime="NORMAL", vix=20.0):
        sigs = generate_signals(market, positions, 50_000, regime, vix)
        return {s.ticker: s for s in sigs}

    def test_sell_hard_below_sma50(self):
        market = {"TQQQ": _make_data(below_sma50=True)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, SELL_HARD)

    def test_sell_panic_trail_stop(self):
        # trail_stop=95, price=90 -> panic
        market = {"TQQQ": _make_data(price=90.0, trail_stop=95.0, cushion=-5.0)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, SELL_PANIC)

    def test_sell_panic_cushion_floor(self):
        # cushion -20% is below panic threshold of -12%
        market = {"TQQQ": _make_data(cushion=-20.0, trail_stop=50.0)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, SELL_PANIC)

    def test_sell_soft_rsi_overbought(self):
        market = {"TQQQ": _make_data(rsi=80.0, cushion=0.0)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, SELL_SOFT)

    def test_sell_soft_above_bollinger(self):
        market = {"TQQQ": _make_data(price=125.0, upper_band=120.0, rsi=65.0, cushion=5.0)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, SELL_SOFT)

    def test_hold_when_owned_no_exit(self):
        # RSI=55, cushion=-3%, trail_stop=50 -> no exit conditions triggered
        market = {"TQQQ": _make_data(rsi=55.0, cushion=-3.0, trail_stop=50.0)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, HOLD)

    def test_sell_priority_hard_over_panic(self):
        # SELL_HARD (below_sma50_confirmed) takes precedence over cushion panic
        market = {"TQQQ": _make_data(below_sma50=True, cushion=-20.0, trail_stop=50.0)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, SELL_HARD)


class TestRiskGuards(unittest.TestCase):

    def test_cooldown_set_and_detected(self):
        import risk, os
        if os.path.exists(config.COOLDOWN_FILE):
            os.remove(config.COOLDOWN_FILE)
        blocked, _ = risk.is_in_cooldown("TQQQ", "buy")
        self.assertFalse(blocked)
        risk.set_cooldown("TQQQ", "buy")
        blocked, reason = risk.is_in_cooldown("TQQQ", "buy")
        self.assertTrue(blocked)
        if os.path.exists(config.COOLDOWN_FILE):
            os.remove(config.COOLDOWN_FILE)

    def test_atr_sizing_reduces_position_on_high_vol(self):
        import risk
        # High ATR = smaller position (80% floor), low ATR = larger (100%)
        qty_high_vol, _ = risk.calc_qty("TQQQ", 50.0, atr=10.0,
                                         buying_power=100_000, portfolio_value=100_000)
        qty_low_vol, _  = risk.calc_qty("TQQQ", 50.0, atr=0.1,
                                         buying_power=100_000, portfolio_value=100_000)
        self.assertLess(qty_high_vol, qty_low_vol)

    def test_calc_qty_concentrated_target(self):
        import risk
        # On $100K portfolio, target is 45% = $45K -> ~900 shares at $50
        qty, reason = risk.calc_qty("TQQQ", 50.0, atr=None,
                                     buying_power=100_000, portfolio_value=100_000)
        # 45% of $100K = $45K -> dry_floor=$10K -> available=$90K -> min($45K, $90K, $90K) = $45K
        # $45K / $50 = 900 shares
        self.assertGreater(qty, 0)
        self.assertIn("Concentrated", reason)

    def test_calc_qty_blocked_no_budget(self):
        import risk
        # If buying_power <= dry_floor, qty = 0
        qty, reason = risk.calc_qty("TQQQ", 50.0, atr=None,
                                     buying_power=4_000, portfolio_value=100_000)
        self.assertEqual(qty, 0)

    def test_calc_qty_slot_aware(self):
        import risk
        # With 1 position already open, slot_cap = available / 1 remaining slot
        qty_0open, _ = risk.calc_qty("TQQQ", 50.0, atr=None,
                                      buying_power=100_000, portfolio_value=100_000,
                                      current_positions=0)
        qty_1open, _ = risk.calc_qty("TQQQ", 50.0, atr=None,
                                      buying_power=60_000, portfolio_value=100_000,
                                      current_positions=1)
        # Both should produce positive quantities
        self.assertGreater(qty_0open, 0)
        self.assertGreater(qty_1open, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
