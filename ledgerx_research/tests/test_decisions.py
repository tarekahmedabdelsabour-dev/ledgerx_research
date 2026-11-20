import itertools
import math
import unittest

import numpy as np

from ledgerx_research.engine import accuracy as ac
from ledgerx_research.engine import breakeven as be
from ledgerx_research.engine import invest as iv
from ledgerx_research.engine import mix
from ledgerx_research.engine import profit as pf
from ledgerx_research.engine import sensitivity as sn

WYNDOR = ([{"code": "D", "margin": 3, "usage": {"P1": 1, "P3": 3}}, {"code": "W", "margin": 5, "usage": {"P2": 2, "P3": 2}}], {"P1": 4, "P2": 12, "P3": 18})


class BreakEven(unittest.TestCase):
	def test_single_product_textbook(self):
		# price 50, variable 30, fixed 10,000 -> 500 units, revenue 25,000
		r = be.break_even([{"code": "A", "price": 50, "variable_cost": 30, "qty": 800}], 10000)
		self.assertAlmostEqual(r["break_even_units"], 500)
		self.assertAlmostEqual(r["break_even_revenue"], 25000)
		self.assertAlmostEqual(r["margin_of_safety_pct"], 37.5)
		self.assertAlmostEqual(r["operating_leverage"], 800 * 20 / (800 * 20 - 10000))
		self.assertTrue(r["verified"])

	def test_target_profit(self):
		r = be.break_even([{"code": "A", "price": 50, "variable_cost": 30, "qty": 100}], 10000, target_profit=4000)
		self.assertAlmostEqual(r["target_units"], 700)

	def test_mix_keeps_shares_and_profit_zero(self):
		ps = [{"code": "A", "price": 100, "variable_cost": 60, "qty": 300}, {"code": "B", "price": 50, "variable_cost": 40, "qty": 700}]
		r = be.break_even(ps, 20000)
		self.assertAlmostEqual(r["break_even_units"], 20000 / 19.0)
		self.assertAlmostEqual(sum(x["units"] for x in r["per_product"]), r["break_even_units"])
		profit = sum(x["units"] * x["contribution"] for x in r["per_product"]) - 20000
		self.assertAlmostEqual(profit, 0, places=6)

	def test_never_breaks_even(self):
		r = be.break_even([{"code": "A", "price": 10, "variable_cost": 12, "qty": 5}], 100)
		self.assertEqual(r["status"], "never")

	def test_cash_break_even_lower(self):
		r = be.break_even([{"code": "A", "price": 50, "variable_cost": 30, "qty": 100}], 10000, cash_fixed=6000)
		self.assertAlmostEqual(r["cash_break_even_units"], 300)

	def test_capacity_flag(self):
		r = be.break_even([{"code": "A", "price": 50, "variable_cost": 30, "qty": 100}], 10000, capacity=400)
		self.assertFalse(r["reachable"])

	def test_sensitivity_directions(self):
		ps = [{"code": "A", "price": 50, "variable_cost": 30, "qty": 800}]
		rows = {(r["what"], r["change_pct"]): r for r in be.sensitivity(ps, 10000, 800)}
		self.assertLess(rows[("price", 10.0)]["break_even_units"], 500)
		self.assertGreater(rows[("fixed", 10.0)]["break_even_units"], 500)
		self.assertGreater(rows[("variable_cost", 10.0)]["break_even_units"], 500)

	def test_risk_reproducible_and_sane(self):
		ps = [{"code": "A", "price": 50, "variable_cost": 30, "qty": 800}]
		a = be.risk(ps, 10000, 800, 10)
		b = be.risk(ps, 10000, 800, 10)
		self.assertEqual(a, b)
		self.assertLess(a["p5"], a["p50"] < a["p95"] and a["p95"])
		# far above break-even with low noise: almost never a loss
		self.assertLess(be.risk(ps, 1000, 800, 5)["loss_probability_pct"], 1)
		# far below break-even: almost always a loss
		self.assertGreater(be.risk(ps, 30000, 800, 5)["loss_probability_pct"], 99)


class Invest(unittest.TestCase):
	def test_npv_known(self):
		self.assertAlmostEqual(iv.npv(0.10, [-1000, 300, 400, 500, 600]), 388.7712587938, places=6)

	def test_npv_matches_numpy_roots_irr(self):
		cfs = [-100, 30, 40, 50, 60]
		roots = np.roots(cfs[::-1])  # polynomial in x = 1/(1+r)
		real = [1 / x.real - 1 for x in roots if abs(x.imag) < 1e-9 and x.real > 0]
		mine = iv.irr(cfs)
		self.assertEqual(len(mine), 1)
		self.assertAlmostEqual(mine[0], real[0], places=6)

	def test_irr_simple(self):
		self.assertAlmostEqual(iv.irr([-100, 110])[0], 0.10, places=6)

	def test_multiple_irr_flagged(self):
		a = iv.analyse([-100, 230, -132], 0.10)  # classic two-IRR example: 10% and 20%
		self.assertTrue(a["multiple_irr"])
		self.assertAlmostEqual(a["irr_all"][0], 0.10, places=5)
		self.assertAlmostEqual(a["irr_all"][1], 0.20, places=5)

	def test_no_irr_without_sign_change(self):
		self.assertEqual(iv.irr([100, 100]), [])

	def test_payback(self):
		self.assertAlmostEqual(iv.payback([-1000, 300, 400, 500, 600]), 2.6)
		self.assertIsNone(iv.payback([-1000, 100, 100]))

	def test_analyse_and_risk(self):
		a = iv.analyse([-1000, 300, 400, 500, 600], 0.10, risk_sd_pct=10)
		self.assertTrue(a["verified"])
		self.assertEqual(a["decision"], "accept")
		self.assertAlmostEqual(a["profitability_index"], 1.3887712588, places=6)
		self.assertLess(a["npv_p5"], a["npv_p95"])
		self.assertEqual(a, iv.analyse([-1000, 300, 400, 500, 600], 0.10, risk_sd_pct=10))

	def test_make_or_buy(self):
		r = iv.make_or_buy(1000, make_fixed=20000, make_variable=10, buy_fixed=0, buy_price=25)
		self.assertAlmostEqual(r["indifference_volume"], 20000 / 15)
		self.assertEqual(r["cheaper"], "buy")  # make 30,000 vs buy 25,000
		self.assertEqual(iv.make_or_buy(2000, 20000, 10, 0, 25)["cheaper"], "make")  # above the indifference volume (1,333) making wins
		self.assertTrue(iv.make_or_buy(2000, 20000, 10, 0, 25)["make_cheaper_above"])

	def test_lease_or_buy(self):
		r = iv.lease_or_buy(price=100000, residual=20000, life_years=5, rate_pct=10, yearly_cost_own=5000, lease_payment=28000)
		af = (1 - 1.1 ** -5) / 0.1
		self.assertAlmostEqual(r["own_pv"], 100000 - 20000 / 1.1 ** 5 + 5000 * af, places=4)
		self.assertAlmostEqual(r["lease_pv"], 28000 * af, places=4)
		self.assertTrue(r["verified"])
		self.assertEqual(r["cheaper"], "buy" if r["own_pv"] < r["lease_pv"] else "lease")


class Profit(unittest.TestCase):
	def test_profitability_classes(self):
		rows = [{"name": "a", "revenue": 1000, "cost": 200}, {"name": "b", "revenue": 500, "cost": 300}, {"name": "c", "revenue": 300, "cost": 280}, {"name": "d", "revenue": 100, "cost": 150}]
		r = pf.profitability(rows)
		by = {x["name"]: x for x in r["rows"]}
		self.assertEqual(by["a"]["class"], "A")
		self.assertEqual(by["d"]["class"], "L")
		self.assertEqual(r["losers"], ["d"])
		self.assertTrue(r["verified"])
		self.assertAlmostEqual(r["total_margin"], 1900 - 930)

	def test_elasticity_estimate_recovers_truth(self):
		pts = [(p, 1000 * p ** -2.0) for p in (8, 9, 10, 11, 12, 13)]
		e = pf.estimate_elasticity(pts)
		self.assertAlmostEqual(e["elasticity"], 2.0, places=6)
		self.assertTrue(e["reliable"])

	def test_elasticity_refuses_flat_price(self):
		self.assertIsNone(pf.estimate_elasticity([(10, 100)] * 8)["elasticity"])
		self.assertIsNone(pf.estimate_elasticity([(10, 100), (11, 90)])["elasticity"])

	def test_best_price_constant_and_grid(self):
		r = pf.best_price(cost=10, price0=20, qty0=100, elasticity=2.5)
		self.assertAlmostEqual(r["price"], 10 * 2.5 / 1.5, places=9)
		self.assertTrue(r["verified"])
		self.assertGreaterEqual(r["gain"], 0)
		# brute force over a grid agrees
		k = 100 * 20 ** 2.5
		best = max(((p - 10) * k * p ** -2.5, p) for p in np.linspace(10, 100, 90001))
		self.assertAlmostEqual(best[1], r["price"], delta=0.01)

	def test_best_price_linear(self):
		r = pf.best_price(cost=10, price0=20, qty0=100, elasticity=2.0, model="linear")
		b = 2.0 * 100 / 20
		a = 100 + b * 20
		self.assertAlmostEqual(r["price"], (a / b + 10) / 2, places=9)
		self.assertTrue(r["verified"])

	def test_inelastic_goes_to_the_limit(self):
		r = pf.best_price(cost=10, price0=20, qty0=100, elasticity=0.8, max_price=30)
		self.assertEqual(r["price"], 30)
		self.assertEqual(r["reason"], "demand_not_elastic_enough")

	def test_discount_breakeven_uplift(self):
		r = pf.discount_effect(100, 60, 1000, 10)
		self.assertAlmostEqual(r["required_uplift_pct"], 10 / 30 * 100)
		self.assertTrue(r["verified"])
		self.assertEqual(pf.discount_effect(100, 60, 1000, 40)["status"], "infeasible")

	def test_stock_health(self):
		r = pf.stock_health([{"item": "x", "qty": 10, "value": 100, "days_since_move": 200, "daily_demand": 0}, {"item": "y", "qty": 5, "value": 50, "days_since_move": 10, "daily_demand": 1},
			{"item": "z", "qty": 1000, "value": 900, "days_since_move": 3, "daily_demand": 1}])
		self.assertEqual([x["class"] for x in r["rows"]], ["dead", "healthy", "overstocked"])
		self.assertEqual(r["tied_up"], 1000)


class Sensitivity(unittest.TestCase):
	def test_wyndor_ranges_match_textbook(self):
		ps, res = WYNDOR
		r3 = sn.resource_range(ps, res, "P3")
		self.assertAlmostEqual(r3["low"], 12, places=3)
		self.assertAlmostEqual(r3["high"], 24, places=3)
		r2 = sn.resource_range(ps, res, "P2")
		self.assertAlmostEqual(r2["low"], 6, places=3)
		self.assertAlmostEqual(r2["high"], 18, places=3)
		m = sn.margin_range(ps, res, "D")
		self.assertAlmostEqual(m["high"], 7.5, places=3)
		self.assertAlmostEqual(sn.margin_range(ps, res, "W")["low"], 2.0, places=3)

	def test_scenario_equals_manual_resolve(self):
		ps, res = WYNDOR
		r = sn.compare(ps, res, [{"name": "P3 +10%", "changes": [{"kind": "resource", "key": "P3", "pct": 10}]}])
		manual = mix.solve(ps, {**res, "P3": 19.8})
		self.assertAlmostEqual(r["rows"][0]["objective"], manual["objective"])
		self.assertAlmostEqual(r["rows"][0]["delta"], manual["objective"] - 36)
		self.assertTrue(r["rows"][0]["verified"])

	def test_shadow_price_predicts_scenario_inside_range(self):
		ps, res = WYNDOR
		r = sn.compare(ps, res, [{"name": "x", "changes": [{"kind": "resource", "key": "P3", "pct": 10}]}])
		self.assertAlmostEqual(r["rows"][0]["delta"], 1.0 * 1.8, places=6)

	def test_unknown_key_raises(self):
		ps, res = WYNDOR
		with self.assertRaises(KeyError):
			sn.scenario(ps, res, [{"kind": "resource", "key": "nope", "pct": 5}])

	def test_monte_carlo_reproducible_and_centered(self):
		ps, res = WYNDOR
		a = sn.monte_carlo(ps, res, 10, n=200)
		self.assertEqual(a, sn.monte_carlo(ps, res, 10, n=200))
		self.assertTrue(a["verified"])
		self.assertLess(a["p5"], a["base_objective"] < a["p95"] and a["p95"])
		self.assertAlmostEqual(a["p50"], 36, delta=3)
		self.assertGreaterEqual(a["min_regret"], -1e-6)  # re-planning never does worse than keeping the plan, when keeping it is possible


class Accuracy(unittest.TestCase):
	def test_metrics(self):
		r = ac.errors([(100, 110), (100, 90), (50, 60)])
		self.assertAlmostEqual(r["mae"], 10)
		self.assertAlmostEqual(r["wape"], 30 / 260 * 100)
		self.assertAlmostEqual(r["bias"], -(10 - 10 + 10) / 260 * 100)
		self.assertEqual(r["verdict"], "reliable")

	def test_unreliable_and_empty(self):
		self.assertEqual(ac.errors([(10, 100), (100, 10)])["verdict"], "unreliable")
		self.assertEqual(ac.errors([])["verdict"], "no_data")

	def test_row_error(self):
		self.assertAlmostEqual(ac.row_error(80, 100)["error_pct"], 20)


if __name__ == "__main__":
	unittest.main()
