import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from ledgerx_research.engine import transport as T


def ssp_min_cost(supply, demand, cost):
	"""Independent oracle: successive shortest paths (Bellman-Ford) on a balanced problem, pure Python."""
	S, D = list(supply), list(demand)
	n = 2 + len(S) + len(D)
	src, snk = 0, n - 1
	graph = [[] for _ in range(n)]

	def add(u, v, cap, c):
		graph[u].append([v, cap, c, len(graph[v])])
		graph[v].append([u, 0, -c, len(graph[u]) - 1])
	for i, sname in enumerate(S):
		add(src, 1 + i, supply[sname], 0)
	for j, dname in enumerate(D):
		add(1 + len(S) + j, snk, demand[dname], 0)
	for i, sname in enumerate(S):
		for j, dname in enumerate(D):
			if (sname, dname) in cost:
				add(1 + i, 1 + len(S) + j, 10 ** 9, cost[(sname, dname)])
	total = 0
	while True:
		dist = [float("inf")] * n
		prev = [None] * n
		dist[src] = 0
		for _ in range(n):
			changed = False
			for u in range(n):
				if dist[u] == float("inf"):
					continue
				for k, (v, cap, c, _r) in enumerate(graph[u]):
					if cap > 0 and dist[u] + c < dist[v]:
						dist[v], prev[v], changed = dist[u] + c, (u, k), True
			if not changed:
				break
		if dist[snk] == float("inf"):
			return total
		f, v = 10 ** 9, snk
		while v != src:
			u, k = prev[v]
			f = min(f, graph[u][k][1])
			v = u
		v = snk
		while v != src:
			u, k = prev[v]
			graph[u][k][1] -= f
			graph[v][graph[u][k][3]][1] += f
			v = u
		total += f * dist[snk]


class TestTransportation(unittest.TestCase):
	def test_classic(self):
		supply = {"A": 20, "B": 30, "C": 25}
		demand = {"1": 10, "2": 25, "3": 15, "4": 25}
		cost = {("A", "1"): 8, ("A", "2"): 6, ("A", "3"): 10, ("A", "4"): 9, ("B", "1"): 9, ("B", "2"): 12, ("B", "3"): 13, ("B", "4"): 7,
			("C", "1"): 14, ("C", "2"): 9, ("C", "3"): 16, ("C", "4"): 5}
		r = T.transportation(supply, demand, cost)
		self.assertEqual(r["status"], "optimal")
		self.assertTrue(r["verified"])
		self.assertEqual(r["shortage"], {})
		self.assertAlmostEqual(r["total_cost"], ssp_min_cost(supply, demand, cost), 4)

	def test_shortage_reported(self):
		r = T.transportation({"A": 10}, {"x": 8, "y": 8}, {("A", "x"): 1, ("A", "y"): 5})
		self.assertEqual(r["status"], "optimal")
		self.assertAlmostEqual(sum(r["shortage"].values()), 6, 6)
		self.assertAlmostEqual(r["flows"][("A", "x")], 8, 6)  # cheaper lane gets served first
		self.assertTrue(r["verified"])

	def test_no_shortage_allowed(self):
		r = T.transportation({"A": 5}, {"x": 8}, {("A", "x"): 1}, allow_shortage=False)
		self.assertEqual(r["status"], "infeasible")

	def test_forbidden_lane(self):
		r = T.transportation({"A": 10, "B": 10}, {"x": 10}, {("B", "x"): 3})
		self.assertAlmostEqual(r["flows"][("B", "x")], 10, 6)

	def test_random_balanced_against_independent_oracle(self):
		rnd = random.Random(21)
		for _ in range(60):
			ns, nd = rnd.randint(2, 5), rnd.randint(2, 6)
			dem = {f"d{j}": rnd.randint(1, 20) for j in range(nd)}
			total = sum(dem.values())
			cuts = sorted(rnd.sample(range(1, total), ns - 1)) if ns > 1 and total > ns else []
			parts = [b - a for a, b in zip([0] + cuts, cuts + [total])]
			sup = {f"s{i}": parts[i] for i in range(len(parts)) if parts[i] > 0}
			cst = {(s, d): rnd.randint(1, 30) for s in sup for d in dem}
			r = T.transportation(sup, dem, cst)
			self.assertTrue(r["verified"])
			self.assertAlmostEqual(r["total_cost"], ssp_min_cost(sup, dem, cst), 4)

	def test_random_against_brute_force(self):
		rnd = random.Random(3)
		for _ in range(40):
			ns, nd = 2, 2
			sup = {f"s{i}": rnd.randint(3, 8) for i in range(ns)}
			dem = {f"d{j}": rnd.randint(2, 6) for j in range(nd)}
			cst = {(s, d): rnd.randint(1, 9) for s in sup for d in dem}
			r = T.transportation(sup, dem, cst)
			self.assertTrue(r["verified"])
			# brute force on the integer grid (the LP optimum is integral)
			best = None
			big = (max(cst.values()) + 1) * 1000
			ranges = [range(0, min(sup[s], dem[d]) + 1) for s in sup for d in dem]
			for xs in itertools.product(*ranges):
				f = dict(zip(cst, xs))
				if any(sum(f[(s, d)] for d in dem) > sup[s] for s in sup):
					continue
				if any(sum(f[(s, d)] for s in sup) > dem[d] for d in dem):
					continue
				val = sum(cst[k] * q for k, q in f.items()) + big * sum(dem[d] - sum(f[(s, d)] for s in sup) for d in dem)
				best = val if best is None else min(best, val)
			got = r["total_cost"] + big * sum(r["shortage"].values())
			self.assertAlmostEqual(got, best, 4)


class TestRouting(unittest.TestCase):
	def test_haversine(self):
		self.assertAlmostEqual(T.haversine((30.0444, 31.2357), (30.0444, 31.2357)), 0, 6)
		self.assertAlmostEqual(T.haversine((0, 0), (0, 1)), 111.195, 1)

	def test_held_karp_matches_permutations(self):
		rnd = random.Random(5)
		for _ in range(25):
			n = rnd.randint(2, 6)
			pts = [(rnd.random(), rnd.random()) for _ in range(n + 1)]
			dist = [[((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for b in pts] for a in pts]
			nodes = list(range(1, n + 1))
			best = min(T.tour_length(dist, p) for p in itertools.permutations(nodes))
			got, order = T.held_karp(dist, nodes)
			self.assertAlmostEqual(got, best, 9)
			self.assertAlmostEqual(T.tour_length(dist, order), got, 9)

	def test_two_opt_never_worse(self):
		rnd = random.Random(9)
		pts = [(rnd.random(), rnd.random()) for _ in range(9)]
		dist = [[((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for b in pts] for a in pts]
		start = list(range(1, 9))
		self.assertLessEqual(T.tour_length(dist, T.two_opt(dist, start)), T.tour_length(dist, start) + 1e-12)

	def test_routes_capacity_and_coverage(self):
		depot = (30.0, 31.0)
		stops = [{"id": f"c{i}", "lat": 30.0 + 0.01 * (i % 4), "lng": 31.0 + 0.01 * (i // 4), "demand": 10 + i} for i in range(1, 9)]
		r = T.routes(depot, stops, capacity=40)
		self.assertTrue(r["verified"])
		for rt in r["routes"]:
			self.assertLessEqual(rt["load"], 40)
		self.assertEqual(sorted(sum((rt["stops"] for rt in r["routes"]), [])), sorted(s["id"] for s in stops))
		self.assertGreaterEqual(r["total_km"], r["lower_bound_km"] - 1e-9)

	def test_single_vehicle_equals_exact_tsp_when_it_fits(self):
		depot = (30.0, 31.0)
		stops = [{"id": f"c{i}", "lat": 30.0 + 0.02 * i, "lng": 31.0 + (0.01 if i % 2 else -0.01), "demand": 1} for i in range(1, 7)]
		r = T.routes(depot, stops, capacity=100)
		self.assertEqual(len(r["routes"]), 1)
		pts = [depot] + [(s["lat"], s["lng"]) for s in stops]
		dist = [[T.haversine(a, b) for b in pts] for a in pts]
		self.assertAlmostEqual(r["total_km"], T.held_karp(dist, list(range(1, 7)))[0], 6)

	def test_infeasible_cases(self):
		stops = [{"id": "big", "lat": 30.1, "lng": 31.1, "demand": 500}]
		self.assertEqual(T.routes((30, 31), stops, 100)["status"], "infeasible")
		many = [{"id": f"c{i}", "lat": 30 + i * 0.01, "lng": 31, "demand": 60} for i in range(3)]
		self.assertEqual(T.routes((30, 31), many, 100, vehicles=1)["status"], "infeasible")


if __name__ == "__main__":
	unittest.main()


class FleetRoutes(unittest.TestCase):
	def stops(self, demands):
		return [{"id": f"s{i}", "lat": 30 + 0.05 * i, "lng": 31 + 0.03 * (i % 3), "demand": d} for i, d in enumerate(demands)]

	def test_every_stop_once_and_fits(self):
		import ledgerx_research.engine.transport as t
		stops = self.stops([40, 30, 20, 10, 25])
		fleet = [{"id": "big", "capacity": 80, "cost_per_km": 3}, {"id": "mid", "capacity": 50, "cost_per_km": 2}, {"id": "small", "capacity": 30, "cost_per_km": 1}]
		r = t.routes_fleet((30.0, 31.0), stops, fleet)
		self.assertTrue(r["verified"])
		seen = sorted(s for rt in r["routes"] for s in rt["stops"])
		self.assertEqual(seen, sorted(s["id"] for s in stops))
		self.assertEqual(len({rt["vehicle"] for rt in r["routes"]}), len(r["routes"]))
		for rt in r["routes"]:
			self.assertLessEqual(rt["load"], rt["capacity"])

	def test_assignment_is_optimal_by_brute_force(self):
		import itertools
		import ledgerx_research.engine.transport as t
		stops = self.stops([45, 45, 20, 20])
		fleet = [{"id": "a", "capacity": 60, "cost_per_km": 5}, {"id": "b", "capacity": 60, "cost_per_km": 1}, {"id": "c", "capacity": 40, "cost_per_km": 2}, {"id": "d", "capacity": 100, "cost_per_km": 4}]
		r = t.routes_fleet((30.0, 31.0), stops, fleet)
		routes = r["routes"]
		best = min(sum(routes[i]["km"] * fleet[j]["cost_per_km"] for i, j in enumerate(p))
			for p in itertools.permutations(range(len(fleet)), len(routes)) if all(routes[i]["load"] <= fleet[j]["capacity"] + 1e-9 for i, j in enumerate(p)))
		self.assertAlmostEqual(r["total_cost"], best, places=6)

	def test_cheap_small_vehicles_preferred_when_they_fit(self):
		import ledgerx_research.engine.transport as t
		stops = self.stops([10, 10, 10])
		fleet = [{"id": "big", "capacity": 100, "cost_per_km": 9}, {"id": "small", "capacity": 40, "cost_per_km": 1}]
		r = t.routes_fleet((30.0, 31.0), stops, fleet)
		self.assertEqual([rt["vehicle"] for rt in r["routes"]], ["small"])

	def test_infeasible_cases(self):
		import ledgerx_research.engine.transport as t
		self.assertEqual(t.routes_fleet((30.0, 31.0), self.stops([500]), [{"id": "a", "capacity": 100, "cost_per_km": 1}])["reason"], "demand_exceeds_capacity")
		self.assertEqual(t.routes_fleet((30.0, 31.0), self.stops([60, 60, 60]), [{"id": "a", "capacity": 100, "cost_per_km": 1}])["reason"], "not_enough_vehicles")
		self.assertEqual(t.routes_fleet((30.0, 31.0), self.stops([1]), [])["reason"], "no_vehicle")


class FleetExactAndHeuristic(unittest.TestCase):
	def make(self, n, seed):
		rnd = random.Random(seed)
		return [{"id": f"s{i}", "lat": 30 + rnd.random() * 0.3, "lng": 31 + rnd.random() * 0.3, "demand": rnd.randint(5, 30)} for i in range(n)]

	def test_exact_equals_brute_force(self):
		stops = self.make(5, 1)
		fleet = [{"id": "a", "capacity": 50, "cost_per_km": 3}, {"id": "b", "capacity": 40, "cost_per_km": 1}, {"id": "c", "capacity": 70, "cost_per_km": 2}]
		depot = (30.15, 31.15)
		r = T.routes_fleet(depot, stops, fleet)
		self.assertTrue(r["exact"] and r["verified"])
		pts = [depot] + [(s["lat"], s["lng"]) for s in stops]
		d = lambda i, j: T.haversine(pts[i], pts[j])

		def tour(group):
			if not group:
				return 0.0
			return min(d(0, p[0] + 1) + sum(d(p[i] + 1, p[i + 1] + 1) for i in range(len(p) - 1)) + d(p[-1] + 1, 0) for p in itertools.permutations(group))
		best = float("inf")
		for assign in itertools.product(range(len(fleet)), repeat=len(stops)):
			groups = [[k for k, v in enumerate(assign) if v == j] for j in range(len(fleet))]
			if any(sum(stops[k]["demand"] for k in g) > fleet[j]["capacity"] for j, g in enumerate(groups)):
				continue
			best = min(best, sum(fleet[j]["cost_per_km"] * tour(g) for j, g in enumerate(groups)))
		self.assertAlmostEqual(r["total_cost"], best, places=6)

	def test_heuristic_valid_and_not_better_than_exact(self):
		stops = self.make(10, 7)
		fleet = [{"id": "a", "capacity": 80, "cost_per_km": 3}, {"id": "b", "capacity": 60, "cost_per_km": 2}, {"id": "c", "capacity": 60, "cost_per_km": 1.5}, {"id": "d", "capacity": 120, "cost_per_km": 4}]
		exact = T.routes_fleet((30.15, 31.15), stops, fleet)
		T_old = T.EXACT_FLEET_STOPS
		try:
			T.EXACT_FLEET_STOPS = 5  # force the heuristic on the same instance
			heur = T.routes_fleet((30.15, 31.15), stops, fleet)
		finally:
			T.EXACT_FLEET_STOPS = T_old
		self.assertTrue(exact["exact"] and not heur["exact"])
		self.assertTrue(heur["verified"])
		self.assertGreaterEqual(heur["total_cost"], exact["total_cost"] - 1e-6)
		self.assertLessEqual(heur["total_cost"], exact["total_cost"] * 1.5)  # sanity: not absurdly worse

	def test_heuristic_handles_14_stops(self):
		stops = self.make(14, 3)
		fleet = [{"id": "a", "capacity": 120, "cost_per_km": 3}, {"id": "b", "capacity": 90, "cost_per_km": 2}, {"id": "c", "capacity": 60, "cost_per_km": 1}, {"id": "e", "capacity": 200, "cost_per_km": 4}]
		r = T.routes_fleet((30.15, 31.15), stops, fleet)
		self.assertTrue(r["verified"])
		self.assertEqual(sorted(x for rt in r["routes"] for x in rt["stops"]), sorted(s["id"] for s in stops))
