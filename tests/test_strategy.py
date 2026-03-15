"""Tests for strategy.py signal generation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
from strategy import generate_signals, BUY, SELL_SOFT, SELL_HARD, SELL_PANIC, HOLD, SKIP


def _make_data(price=100.0, rsi=40.0, cushion=-10.0, trend="UP",
               weekly_up=True, below_sma50=False, upper_band=120.0,
               volume_ratio=1.5, atr=2.0, trail_stop=80.0, recent_high=111.0):
    return {
        "valid": True, "price": price, "rsi": rsi, "cushion": cushion,
        "trend": trend, "is_weekly_uptrend": weekly_up,
        "is_below_sma50_confirmed": below_sma50,
        "upper_band": upper_band, "volume_ratio": volume_ratio,
        "atr": atr, "trail_stop": trail_stop, "recent_high": recent_high,
        "sma20": price * 0.97,
    }


class TestBuySignals(unittest.TestCase):

    def _run(self, market, positions=None, buying_power=50_000, regime="NORMAL", vix=20.0):
        positions = positions or {}
        sigs = generate_signals(market, positions, buying_power, regime, vix)
        return {s.ticker: s for s in sigs}

    def test_buy_all_conditions_met(self):
        market = {"TQQQ": _make_data()}
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, BUY)

    def test_skip_vix_too_high(self):
        market = {"TQQQ": _make_data()}
        sigs = self._run(market, vix=35.0)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_skip_regime_defense(self):
        market = {"TQQQ": _make_data()}
        sigs = self._run(market, regime="DEFENSE")
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_skip_weekly_down(self):
        market = {"TQQQ": _make_data(weekly_up=False)}
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_skip_rsi_too_high(self):
        market = {"TQQQ": _make_data(rsi=50.0)}
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_skip_cushion_too_shallow(self):
        market = {"TQQQ": _make_data(cushion=-3.0)}
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

    def test_skip_volume_too_low(self):
        market = {"TQQQ": _make_data(volume_ratio=0.8)}
        sigs = self._run(market)
        self.assertEqual(sigs["TQQQ"].action, SKIP)

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
        # trail_stop=95, price=90 → panic
        market = {"TQQQ": _make_data(price=90.0, trail_stop=95.0, cushion=-5.0)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, SELL_PANIC)

    def test_sell_panic_cushion_floor(self):
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
        # owned, trend ok, no exit conditions met
        market = {"TQQQ": _make_data(rsi=55.0, cushion=-3.0)}
        sigs = self._run(market, {"TQQQ": {"qty": 100}})
        self.assertEqual(sigs["TQQQ"].action, HOLD)


class TestRiskGuards(unittest.TestCase):

    def test_cooldown_set_and_detected(self):
        import risk, json, os, config
        # Clean slate
        if os.path.exists(config.COOLDOWN_FILE):
            os.remove(config.COOLDOWN_FILE)
        blocked, _ = risk.is_in_cooldown("TQQQ", "buy")
        self.assertFalse(blocked)
        risk.set_cooldown("TQQQ", "buy")
        blocked, reason = risk.is_in_cooldown("TQQQ", "buy")
        self.assertTrue(blocked)
        # Clean up
        if os.path.exists(config.COOLDOWN_FILE):
            os.remove(config.COOLDOWN_FILE)

    def test_atr_sizing_reduces_position_on_high_vol(self):
        import risk
        # High ATR = smaller position
        qty_high_vol, _ = risk.calc_qty("TQQQ", 50.0, atr=10.0,
                                         buying_power=100_000, portfolio_value=200_000)
        qty_low_vol, _  = risk.calc_qty("TQQQ", 50.0, atr=1.0,
                                         buying_power=100_000, portfolio_value=200_000)
        self.assertLess(qty_high_vol, qty_low_vol)


if __name__ == "__main__":
    unittest.main(verbosity=2)
