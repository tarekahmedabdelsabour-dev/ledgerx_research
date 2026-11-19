import unittest
from datetime import datetime

from ledgerx_research import bridge as b


class Bridge(unittest.TestCase):
	def test_demand_stats(self):
		daily = {"2026-01-05": 10, "2026-01-20": 20, "2026-02-03": 30}
		s = b.demand_stats(daily, 60)
		self.assertAlmostEqual(s["daily_mean"], 1.0)
		self.assertAlmostEqual(s["annual_demand"], 365.0)
		self.assertEqual(s["monthly"], [30, 30])
		# sd over 60 days, 57 zeros: sqrt(E[x^2]-mean^2)
		self.assertAlmostEqual(s["daily_sd"], ((100 + 400 + 900) / 60 - 1) ** 0.5)

	def test_mix_wyndor(self):
		prods = [{"item_code": "Doors", "price": 3, "unit_cost": 0, "usage": {"P1": 1, "P3": 3}}, {"item_code": "Windows", "price": 5, "unit_cost": 0, "usage": {"P2": 2, "P3": 2}}]
		res = [{"resource": "P1", "available": 4}, {"resource": "P2", "available": 12}, {"resource": "P3", "available": 18}]
		r = b.run_mix(prods, res)
		self.assertEqual(r["status"], "Solved")
		self.assertTrue(r["verified"])
		self.assertAlmostEqual(r["objective"], 36)
		self.assertAlmostEqual(r["shadow"]["P3"], 1.0)
		r2 = b.run_mix(prods, res, integer=True)
		self.assertEqual(r2["quantities"], {"Doors": 2.0, "Windows": 6.0})

	def test_mix_unlimited_product_is_flagged(self):
		r = b.run_mix([{"item_code": "X", "price": 5, "unit_cost": 1, "usage": {}}], [])
		self.assertNotEqual(r["status"], "Solved")

	def test_mix_infeasible_minimum(self):
		r = b.run_mix([{"item_code": "X", "price": 5, "unit_cost": 1, "min_qty": 10, "usage": {"R": 1}}], [{"resource": "R", "available": 5}])
		self.assertEqual(r["status"], "Infeasible")

	def test_reorder(self):
		item = {"item_code": "A", "annual_demand": 3650, "daily_sd": 2, "lead_days": 5, "unit_cost": 10, "on_hand": 5, "on_order": 0, "moq": 0, "monthly": [300] * 12}
		r = b.run_reorder([item], {"service_level_pct": 95, "holding_rate_pct": 20, "order_cost": 50, "default_lead_days": 7})
		row = r["rows"][0]
		self.assertAlmostEqual(row["eoq"], (2 * 3650 * 50 / 2) ** 0.5)
		self.assertGreater(row["order_qty"], 0)
		self.assertEqual(row["abc"], "A")
		self.assertAlmostEqual(row["forecast_next"], 300, delta=1)

	def test_distribution_with_coordinates(self):
		src = [{"location": "S1", "qty": 100, "lat": 30.0, "lng": 31.0}, {"location": "S2", "qty": 100, "lat": 31.2, "lng": 29.9}]
		dst = [{"location": "D1", "demand": 80, "lat": 30.1, "lng": 31.1}, {"location": "D2", "demand": 90, "lat": 31.1, "lng": 30.0}]
		r = b.run_distribution(src, dst, [], 1.0)
		self.assertTrue(r["verified"])
		sent = {(f["source"], f["destination"]): f["qty"] for f in r["flows"]}
		self.assertAlmostEqual(sent[("S1", "D1")], 80)
		self.assertAlmostEqual(sent[("S2", "D2")], 90)

	def test_distribution_blocked_and_shortage(self):
		src = [{"location": "S", "qty": 50}]
		dst = [{"location": "D", "demand": 80}]
		r = b.run_distribution(src, dst, [{"source": "S", "destination": "D", "unit_cost": 2}], 1)
		self.assertAlmostEqual(r["shortage"]["D"], 30)
		r2 = b.run_distribution(src, dst, [{"source": "S", "destination": "D", "blocked": 1}], 1)
		self.assertEqual(r2["status"], "Infeasible")

	def test_routes(self):
		stops = [{"stop": f"c{i}", "lat": 30 + i * 0.05, "lng": 31 + (i % 2) * 0.05, "demand": 10} for i in range(6)]
		r = b.run_routes((30.0, 31.0), stops, 25)
		self.assertTrue(r["verified"])
		self.assertEqual(sorted(l["stop"] for l in r["legs"]), sorted(s["stop"] for s in stops))
		self.assertTrue(all(l["route_load"] <= 25 for l in r["legs"]))
		self.assertGreaterEqual(r["total_km"], r["lower_bound_km"] - 1e-6)
		bad = b.run_routes((30.0, 31.0), stops, 5)
		self.assertEqual(bad["status"], "Infeasible")

	def test_schedule_and_clock(self):
		self.assertEqual(b.clock("2026-01-01 08:00:00", 10, 8), datetime(2026, 1, 2, 10, 0))
		ops = [{"work_order": "W1", "operation": "Cut", "workstation": "M1", "sequence": 1, "hours": 2}, {"work_order": "W1", "operation": "Weld", "workstation": "M2", "sequence": 2, "hours": 3},
			{"work_order": "W2", "operation": "Cut", "workstation": "M1", "sequence": 1, "hours": 4}]
		r = b.run_schedule(ops, "2026-01-01 08:00:00", 8, "Finish Time of the Last Order")
		self.assertTrue(r["verified"])
		self.assertEqual(len(r["rows"]), 3)
		self.assertGreaterEqual(r["makespan_hours"], r["lower_bound_hours"] - 1e-9)
		# operation names stay attached to the right row
		w1 = {x["operation"]: x for x in r["rows"] if x["work_order"] == "W1"}
		self.assertLessEqual(w1["Cut"]["end_at"], w1["Weld"]["start_at"])

	def test_informational_notes_do_not_need_attention(self):
		stops = [{"stop": f"c{i}", "lat": 30 + i * 0.05, "lng": 31 + (i % 2) * 0.05, "demand": 10} for i in range(4)]
		r = b.run_routes((30.0, 31.0), stops, 25)
		self.assertEqual(r["status"], "Solved")
		self.assertTrue(any("straight-line" in w for w in r["warnings"]))
		ops = [{"work_order": "W1", "operation": "Cut", "workstation": "M1", "sequence": 1, "hours": 2}]
		r = b.run_schedule(ops, "2026-01-01 08:00:00", 8, "Finish Time of the Last Order")
		self.assertEqual(r["status"], "Solved")
		self.assertTrue(any("Working days" in w for w in r["warnings"]))
		prods = [{"item_code": "A", "price": 3, "unit_cost": 0, "usage": {"P": 1}}, {"item_code": "Loss", "price": 1, "unit_cost": 2, "usage": {"P": 1}}]
		r = b.run_mix(prods, [{"resource": "P", "available": 4}])
		self.assertEqual(r["status"], "Solved")
		self.assertEqual(len(r["warnings"]), 1)

	def test_notes_survive_translation(self):
		old = b._
		b._ = lambda s: "XX " + s  # a translated message no longer starts with the English text
		try:
			stops = [{"stop": f"c{i}", "lat": 30 + i * 0.05, "lng": 31, "demand": 10} for i in range(3)]
			self.assertEqual(b.run_routes((30.0, 31.0), stops, 25)["status"], "Solved")
			ops = [{"work_order": "W1", "operation": "Cut", "workstation": "M1", "sequence": 1, "hours": 2}]
			self.assertEqual(b.run_schedule(ops, "2026-01-01 08:00:00", 8, "Finish Time of the Last Order")["status"], "Solved")
			prods = [{"item_code": "A", "price": 3, "unit_cost": 0, "usage": {"P": 1}}, {"item_code": "Loss", "price": 1, "unit_cost": 2, "usage": {"P": 1}}]
			self.assertEqual(b.run_mix(prods, [{"resource": "P", "available": 4}])["status"], "Solved")
		finally:
			b._ = old

	def test_allocation(self):
		needs = [{"item_code": "I", "qty": 100}]
		offers = [{"supplier": "A", "item_code": "I", "price": 10, "capacity": 60, "lead_days": 3}, {"supplier": "B", "item_code": "I", "price": 12, "capacity": 100, "lead_days": 5}]
		r = b.run_allocation(needs, offers)
		self.assertTrue(r["verified"])
		got = {a["supplier"]: a["qty"] for a in r["allocation"]}
		self.assertAlmostEqual(got["A"], 60)
		self.assertAlmostEqual(got["B"], 40)
		self.assertAlmostEqual(r["total_cost"], 60 * 10 + 40 * 12)
		r2 = b.run_allocation(needs, offers, max_lead_days=4)
		self.assertEqual(r2["status"], "Infeasible")

	def test_summary_escapes(self):
		h = b.html_summary("<x>", True, ["a<b"], ["w&"])
		self.assertNotIn("<x>", h)
		self.assertIn("a&lt;b", h)


if __name__ == "__main__":
	unittest.main()
