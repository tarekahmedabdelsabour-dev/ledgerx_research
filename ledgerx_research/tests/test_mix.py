import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ledgerx_research.engine import mix


class TestMix(unittest.TestCase):
	def test_textbook_wyndor(self):
		# max 3x + 5y ; x <= 4 ; 2y <= 12 ; 3x + 2y <= 18  -> x=2, y=6, z=36, duals 0, 1.5, 1
		prods = [{"code": "door", "margin": 3, "usage": {"p1": 1, "p3": 3}}, {"code": "window", "margin": 5, "usage": {"p2": 2, "p3": 2}}]
		r = mix.solve(prods, {"p1": 4, "p2": 12, "p3": 18})
		self.assertEqual(r["status"], "optimal")
		self.assertAlmostEqual(r["objective"], 36, 6)
		self.assertAlmostEqual(r["quantities"]["door"], 2, 6)
		self.assertAlmostEqual(r["quantities"]["window"], 6, 6)
		self.assertAlmostEqual(r["shadow_price"]["p1"], 0, 6)
		self.assertAlmostEqual(r["shadow_price"]["p2"], 1.5, 6)
		self.assertAlmostEqual(r["shadow_price"]["p3"], 1.0, 6)
		self.assertTrue(r["verified"])

	def test_integer_knapsack(self):
		prods = [{"code": "a", "margin": 60, "usage": {"w": 10}, "max_qty": 1}, {"code": "b", "margin": 100, "usage": {"w": 20}, "max_qty": 1},
			{"code": "c", "margin": 120, "usage": {"w": 30}, "max_qty": 1}]
		r = mix.solve(prods, {"w": 50}, integer=True)
		self.assertEqual(r["objective"], 220)
		self.assertEqual((r["quantities"]["b"], r["quantities"]["c"]), (1, 1))
		self.assertTrue(r["verified"])

	def test_demand_cap_and_min(self):
		prods = [{"code": "a", "margin": 5, "usage": {"h": 1}, "max_qty": 10}, {"code": "b", "margin": 4, "usage": {"h": 1}, "min_qty": 3}]
		r = mix.solve(prods, {"h": 20})
		self.assertAlmostEqual(r["quantities"]["a"], 10)
		self.assertAlmostEqual(r["quantities"]["b"], 10)
		self.assertTrue(r["verified"])

	def test_infeasible_and_unbounded(self):
		self.assertEqual(mix.solve([{"code": "a", "margin": 1, "usage": {"h": 1}, "min_qty": 50}], {"h": 10})["status"], "infeasible")
		self.assertEqual(mix.solve([{"code": "a", "margin": 1, "usage": {}}], {})["status"], "unbounded")

	def test_negative_margin_makes_nothing(self):
		r = mix.solve([{"code": "a", "margin": -2, "usage": {"h": 1}}], {"h": 5})
		self.assertEqual(r["quantities"]["a"], 0)

	def test_random_integer_against_brute_force(self):
		rnd = random.Random(7)
		for _ in range(60):
			n = rnd.randint(2, 3)
			prods = [{"code": f"p{j}", "margin": rnd.randint(1, 20), "usage": {"r1": rnd.randint(1, 6), "r2": rnd.randint(0, 6)}, "max_qty": rnd.randint(1, 6)} for j in range(n)]
			res = {"r1": rnd.randint(5, 30), "r2": rnd.randint(5, 30)}
			best = -1
			for xs in itertools.product(*[range(int(p["max_qty"]) + 1) for p in prods]):
				if all(sum(p["usage"][r] * x for p, x in zip(prods, xs)) <= res[r] for r in res):
					best = max(best, sum(p["margin"] * x for p, x in zip(prods, xs)))
			got = mix.solve(prods, res, integer=True)
			self.assertAlmostEqual(got["objective"], best, 5)
			self.assertTrue(got["verified"])

	def test_random_lp_certificate_and_upper_bound_by_integer_relaxation(self):
		rnd = random.Random(11)
		for _ in range(80):
			n = rnd.randint(2, 5)
			prods = [{"code": f"p{j}", "margin": rnd.randint(1, 30), "usage": {f"r{i}": rnd.randint(0, 5) for i in range(3)}, "max_qty": rnd.choice([None, rnd.randint(1, 20)])} for j in range(n)]
			for p in prods:
				if all(v == 0 for v in p["usage"].values()) and p["max_qty"] is None:
					p["max_qty"] = 5
			res = {f"r{i}": rnd.randint(10, 60) for i in range(3)}
			lp = mix.solve(prods, res)
			ip = mix.solve(prods, res, integer=True)
			self.assertEqual(lp["status"], "optimal")
			self.assertTrue(lp["verified"], (prods, res, lp))
			self.assertLessEqual(ip["objective"], lp["objective"] + 1e-6)


if __name__ == "__main__":
	unittest.main()
