import unittest

from ledgerx_research import bridge_decisions as d

PRODS = [{"item_code": "Doors", "price": 3, "unit_cost": 0, "usage": {"P1": 1, "P3": 3}}, {"item_code": "Windows", "price": 5, "unit_cost": 0, "usage": {"P2": 2, "P3": 2}}]
RES = [{"resource": "P1", "available": 4}, {"resource": "P2", "available": 12}, {"resource": "P3", "available": 18}]


class Decisions(unittest.TestCase):
	def test_breakeven(self):
		r = d.run_breakeven([{"item_code": "A", "price": 50, "variable_cost": 30, "qty": 800}], [{"name": "rent", "amount": 6000, "is_cash": 1}, {"name": "depr", "amount": 4000, "is_cash": 0}], risk_sd_pct=10)
		self.assertEqual(r["status"], "Solved")
		self.assertTrue(r["verified"])
		self.assertAlmostEqual(r["out"]["break_even_units"], 500)
		self.assertAlmostEqual(r["out"]["cash_break_even_units"], 300)
		self.assertIn("loss_probability_pct", r["risk"])
		self.assertTrue(r["sensitivity"])

	def test_breakeven_never_and_loss_note(self):
		self.assertEqual(d.run_breakeven([{"item_code": "A", "price": 10, "variable_cost": 12, "qty": 5}], [{"amount": 100}])["status"], "Infeasible")
		r = d.run_breakeven([{"item_code": "A", "price": 50, "variable_cost": 30, "qty": 100}], [{"amount": 10000}])
		self.assertEqual(r["status"], "Solved")  # a loss at the expected sales is a finding, not a data problem
		self.assertTrue(any("loss" in w for w in r["warnings"]))

	def test_breakeven_flags_missing_cost(self):
		r = d.run_breakeven([{"item_code": "A", "price": 50, "variable_cost": 0, "qty": 100}], [{"amount": 1000}])
		self.assertEqual(r["status"], "Needs Attention")

	def test_mix_sensitivity(self):
		r = d.run_mix_sensitivity(PRODS, RES, [{"name": "More P3", "kind": "resource", "key": "P3", "pct": 10}])
		self.assertEqual(r["status"], "Solved")
		self.assertAlmostEqual(r["rows"][0]["change"], 1.8)
		self.assertAlmostEqual(r["resource_ranges"]["P3"]["low"], 12, places=2)
		self.assertAlmostEqual(r["resource_ranges"]["P3"]["high"], 24, places=2)
		self.assertAlmostEqual(r["margin_ranges"]["Doors"]["high"], 7.5, places=2)

	def test_mix_sensitivity_unknown_key(self):
		r = d.run_mix_sensitivity(PRODS, RES, [{"name": "x", "kind": "resource", "key": "nope", "pct": 10}])
		self.assertEqual(r["status"], "Infeasible")

	def test_mix_risk(self):
		r = d.run_mix_risk(PRODS, RES, 10, draws=100)
		self.assertTrue(r["verified"])
		self.assertLess(r["p5"], r["p95"])
		self.assertEqual(d.run_mix_risk(PRODS, RES, 0)["status"], "Infeasible")

	def test_investment(self):
		r = d.run_investment([{"year": 0, "amount": -1000}, {"year": 1, "amount": 300}, {"year": 2, "amount": 400}, {"year": 3, "amount": 500}, {"year": 4, "amount": 600}], 10, 10)
		self.assertEqual(r["status"], "Solved")
		self.assertAlmostEqual(r["npv"], 388.77, places=2)
		self.assertTrue(r["verified"])
		self.assertIn("npv_p5", r)

	def test_investment_gap_year_and_sign(self):
		r = d.run_investment([{"year": 0, "amount": -100}, {"year": 3, "amount": 150}], 10)
		self.assertEqual(r["status"], "Solved")  # years left empty count as zero, said in the notes
		self.assertTrue(any("zero" in w for w in r["warnings"]))
		self.assertEqual(d.run_investment([{"year": 0, "amount": 100}, {"year": 1, "amount": 50}], 10)["status"], "Needs Attention")

	def test_make_or_buy_and_lease(self):
		r = d.run_make_or_buy(2000, 20000, 10, 0, 25)
		self.assertEqual(r["cheaper"], "make")
		self.assertEqual(r["status"], "Solved")
		self.assertEqual(d.run_make_or_buy(100, 20000, 10, 0, 0)["status"], "Needs Attention")
		l = d.run_lease_or_buy(100000, 20000, 5, 10, 5000, 28000)
		self.assertEqual(l["status"], "Solved")
		self.assertEqual(d.run_lease_or_buy(1, 0, 0, 10, 0, 1)["status"], "Infeasible")

	def test_profitability_and_stock(self):
		r = d.run_profitability([{"name": "a", "revenue": 1000, "cost": 200}, {"name": "d", "revenue": 100, "cost": 150}])
		self.assertEqual(r["losers"], ["d"])
		self.assertEqual(r["status"], "Solved")
		s = d.run_stock_health([{"item": "x", "qty": 1, "value": 5, "days_since_move": 400, "daily_demand": 0}], 90, 180)
		self.assertEqual(s["rows"][0]["class"], "dead")

	def test_pricing(self):
		r = d.run_pricing(10, 20, 100, 2.5, discount_pct=10)
		self.assertEqual(r["status"], "Solved")
		self.assertAlmostEqual(r["best"]["price"], 16.6667, places=3)
		self.assertAlmostEqual(r["discount"]["required_uplift_pct"], 2 / 8 * 100)
		self.assertEqual(d.run_pricing(10, 20, 100, 0)["status"], "Infeasible")
		self.assertEqual(d.run_pricing(10, 20, 100, 0.8, max_price=30)["status"], "Needs Attention")

	def test_review(self):
		r = d.run_review([{"plan": "P1", "item": "a", "expected": 100, "actual": 105}, {"plan": "P1", "item": "b", "expected": 50, "actual": 48}] * 3)
		self.assertEqual(r["overall"]["verdict"], "reliable")
		self.assertEqual(r["status"], "Solved")
		bad = d.run_review([{"plan": "P1", "item": "a", "expected": 10, "actual": 100}] * 6)
		self.assertEqual(bad["status"], "Needs Attention")
		self.assertEqual(d.run_review([])["status"], "Infeasible")


if __name__ == "__main__":
	unittest.main()
