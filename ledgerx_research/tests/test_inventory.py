import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ledgerx_research.engine import forecast as F
from ledgerx_research.engine import inventory as I


class TestInventory(unittest.TestCase):
	def test_eoq_known(self):
		self.assertAlmostEqual(I.eoq(1000, 50, 2), 223.6068, 3)
		self.assertEqual(I.eoq(0, 50, 2), 0)
		self.assertEqual(I.eoq(1000, 50, 0), 0)

	def test_eoq_is_the_cost_minimum(self):
		q = I.eoq(1200, 40, 3)
		c = I.annual_cost(q, 1200, 40, 3)
		for d in (-20, -5, -1, 1, 5, 20):
			self.assertLess(c, I.annual_cost(q + d, 1200, 40, 3))

	def test_price_breaks_matches_brute_force(self):
		breaks = [(0, 10.0), (100, 9.5), (500, 9.0)]
		got = I.eoq_price_breaks(2400, 30, 0.2, breaks)
		best = min((I.annual_cost(q, 2400, 30, 0.2 * next(p for lo, p in reversed(breaks) if q >= lo), next(p for lo, p in reversed(breaks) if q >= lo)), q) for q in range(1, 3000))
		self.assertAlmostEqual(got["total_cost"], best[0], delta=abs(best[0]) * 1e-3)

	def test_safety_stock(self):
		self.assertAlmostEqual(I.z_for_service(0.95), 1.6449, 3)
		self.assertAlmostEqual(I.safety_stock(0.95, 10, 4), 1.6449 * 20, 2)
		self.assertAlmostEqual(I.safety_stock(0.5, 10, 4), 0, 6)
		self.assertGreater(I.safety_stock(0.95, 10, 4, 50, 1), I.safety_stock(0.95, 10, 4))

	def test_reorder_point(self):
		self.assertEqual(I.reorder_point(10, 5, 20), 70)

	def test_abc(self):
		c = I.abc_classes({"a": 800, "b": 100, "c": 60, "d": 30, "e": 10})
		self.assertEqual(c["a"], "A")
		self.assertEqual(c["b"], "B")
		self.assertEqual(c["e"], "C")
		self.assertEqual(I.abc_classes({}), {})

	def test_plan_item_flags_order(self):
		p = I.plan_item(3650, 3, 7, 50, 10, 0.2, 0.95, on_hand=20)
		self.assertTrue(p["order_now"])
		self.assertGreater(p["eoq"], 0)
		p2 = I.plan_item(3650, 3, 7, 50, 10, 0.2, 0.95, on_hand=5000)
		self.assertFalse(p2["order_now"])
		self.assertEqual(p2["order_qty"], 0)

	def test_order_qty_lifts_position_above_rop(self):
		for onhand in (0, 10, 50, 90):
			p = I.plan_item(3650, 3, 7, 50, 10, 0.2, 0.95, on_hand=onhand)
			if p["order_now"]:
				self.assertGreater(p["inventory_position"] + p["order_qty"], p["reorder_point"])
				self.assertAlmostEqual(p["order_qty"] % p["eoq"], 0, 6)

	def test_moq_and_pack(self):
		p = I.plan_item(365, 1, 3, 20, 5, 0.2, 0.9, on_hand=0, moq=500, pack=24)
		self.assertEqual(p["eoq"] % 24, 0)
		self.assertGreaterEqual(p["eoq"], 500)


class TestForecast(unittest.TestCase):
	def test_constant_series(self):
		s = [10.0] * 12
		self.assertAlmostEqual(F.ses(s, 1)[0], 10, 6)
		self.assertAlmostEqual(F.holt(s, 1)[0], 10, 6)
		r = F.forecast(s, 3)
		self.assertAlmostEqual(r["forecast"][0], 10, 5)

	def test_linear_trend_exact_with_holt(self):
		s = [5 + 2 * t for t in range(12)]
		self.assertAlmostEqual(F.holt(s, 1)[0], 5 + 2 * 12, 6)
		r = F.forecast(s, 2)
		self.assertEqual(r["method"], "holt_trend")
		self.assertAlmostEqual(r["forecast"][1], 5 + 2 * 13, 4)

	def test_seasonal_picks_seasonal_naive(self):
		base = [10, 20, 30, 40]
		s = base * 6
		r = F.forecast(s, 4, period=4)
		self.assertEqual(r["method"], "seasonal_naive")
		self.assertEqual([round(v) for v in r["forecast"]], base)

	def test_short_history_is_flagged(self):
		r = F.forecast([5, 7], 2)
		self.assertEqual(r["method"], "average")
		self.assertIn("short", r["warning"])
		self.assertEqual(F.forecast([], 2)["forecast"], [0.0, 0.0])

	def test_band_contains_forecast_and_non_negative(self):
		r = F.forecast([3, 9, 2, 8, 4, 10, 3, 9, 5, 7], 3)
		for lo, f, hi in zip(r["low"], r["forecast"], r["high"]):
			self.assertLessEqual(lo, f)
			self.assertLessEqual(f, hi)
			self.assertGreaterEqual(lo, 0)


if __name__ == "__main__":
	unittest.main()
