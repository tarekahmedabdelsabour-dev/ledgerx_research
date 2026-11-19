import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ledgerx_research.engine import procure as P


class TestProcure(unittest.TestCase):
	def test_cheapest_with_capacity(self):
		offers = [{"supplier": "A", "item": "x", "price": 10, "capacity": 60}, {"supplier": "B", "item": "x", "price": 12, "capacity": 100}]
		r = P.allocate({"x": 100}, offers)
		self.assertEqual(r["status"], "optimal")
		q = {a["supplier"]: a["qty"] for a in r["allocation"]}
		self.assertAlmostEqual(q["A"], 60, 5)
		self.assertAlmostEqual(q["B"], 40, 5)
		self.assertAlmostEqual(r["total_cost"], 60 * 10 + 40 * 12, 4)
		self.assertTrue(r["verified"])

	def test_moq_all_or_nothing(self):
		offers = [{"supplier": "A", "item": "x", "price": 5, "moq": 50}, {"supplier": "B", "item": "x", "price": 8}]
		r = P.allocate({"x": 30}, offers)
		self.assertEqual([a["supplier"] for a in r["allocation"]], ["B"])  # A cannot sell below its MOQ
		r2 = P.allocate({"x": 80}, offers)
		self.assertEqual(r2["status"], "optimal")
		self.assertAlmostEqual(sum(a["qty"] for a in r2["allocation"]), 80, 5)
		self.assertTrue(r2["verified"])

	def test_fixed_cost_consolidates(self):
		offers = [{"supplier": "A", "item": "x", "price": 10}, {"supplier": "B", "item": "x", "price": 9.9}]
		r = P.allocate({"x": 100}, offers, fixed_cost={"A": 0, "B": 50})
		self.assertEqual(r["suppliers_used"], ["A"])  # B's 10 saving does not cover its 50 setup

	def test_share_limit(self):
		offers = [{"supplier": "A", "item": "x", "price": 1}, {"supplier": "B", "item": "x", "price": 2}, {"supplier": "C", "item": "x", "price": 3}]
		r = P.allocate({"x": 90}, offers, max_share=0.5)
		q = {a["supplier"]: a["qty"] for a in r["allocation"]}
		self.assertAlmostEqual(q["A"], 45, 5)
		self.assertAlmostEqual(q["B"], 45, 5)
		self.assertNotIn("C", q)

	def test_filters_and_infeasible(self):
		offers = [{"supplier": "A", "item": "x", "price": 1, "lead_days": 20, "quality": 0.99}, {"supplier": "B", "item": "x", "price": 2, "lead_days": 5, "quality": 0.7}]
		self.assertEqual(P.allocate({"x": 10}, offers, max_lead_days=10)["allocation"][0]["supplier"], "B")
		self.assertEqual(P.allocate({"x": 10}, offers, min_quality=0.9)["allocation"][0]["supplier"], "A")
		self.assertEqual(P.allocate({"x": 10}, offers, max_lead_days=10, min_quality=0.9)["status"], "infeasible")
		self.assertEqual(P.allocate({"x": 10}, [], max_share=1)["status"], "infeasible")

	def test_budget(self):
		offers = [{"supplier": "A", "item": "x", "price": 10}]
		self.assertEqual(P.allocate({"x": 10}, offers, budget=99)["status"], "infeasible")
		self.assertEqual(P.allocate({"x": 10}, offers, budget=100)["status"], "optimal")

	def test_multi_item_independent(self):
		offers = [{"supplier": "A", "item": "x", "price": 1}, {"supplier": "B", "item": "y", "price": 2}, {"supplier": "A", "item": "y", "price": 3}]
		r = P.allocate({"x": 5, "y": 4}, offers)
		self.assertAlmostEqual(r["total_cost"], 5 + 8, 5)

	def test_what_if(self):
		offers = [{"supplier": "A", "item": "x", "price": 10}, {"supplier": "B", "item": "x", "price": 12}]
		w = P.what_if_without({"x": 10}, offers, "A")
		self.assertTrue(w["feasible"])
		self.assertAlmostEqual(w["extra_cost"], 20, 5)
		self.assertFalse(P.what_if_without({"x": 10}, [offers[0]], "A")["feasible"])

	def test_random_against_brute_force(self):
		rnd = random.Random(23)
		for _ in range(40):
			n_s = rnd.randint(2, 3)
			demand = rnd.randint(4, 10)
			offers = [{"supplier": f"s{k}", "item": "x", "price": rnd.randint(1, 9), "capacity": rnd.randint(2, 10), "moq": rnd.choice([0, 0, 3])} for k in range(n_s)]
			fixed = {f"s{k}": rnd.choice([0, 5, 12]) for k in range(n_s)}
			best = None
			for qs in itertools.product(*[range(0, int(o["capacity"]) + 1) for o in offers]):
				if sum(qs) != demand:
					continue
				if any(0 < q < o["moq"] for q, o in zip(qs, offers)):
					continue
				cost = sum(q * o["price"] for q, o in zip(qs, offers)) + sum(fixed[o["supplier"]] for q, o in zip(qs, offers) if q > 0)
				best = cost if best is None else min(best, cost)
			r = P.allocate({"x": demand}, offers, fixed_cost=fixed)
			if best is None:
				self.assertEqual(r["status"], "infeasible")
			else:
				self.assertEqual(r["status"], "optimal")
				self.assertTrue(r["verified"])
				self.assertAlmostEqual(r["total_cost"], best, 4)


if __name__ == "__main__":
	unittest.main()
