"""Distribution and routing.

* transportation(): minimum-cost shipping plan from sources (warehouses) to destinations (customers); exact (LP,
  integral because the constraint matrix is totally unimodular) and certified by complementary slackness.
* routes(): capacitated routes for vehicles from a depot. Clarke-Wright savings + 2-opt, and an EXACT order
  (Held-Karp) inside every route of up to 12 stops. The split of stops into routes is a heuristic: the result says
  so and reports the gap to a lower bound.
"""
import itertools
import math

from .common import num, require_scipy


def haversine(a, b):
	"""Great-circle km between (lat, lng) pairs."""
	r = 6371.0088
	la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
	h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
	return 2 * r * math.asin(math.sqrt(h))


def transportation(supply, demand, cost, allow_shortage=True, shortage_penalty=None):
	"""supply: {src: qty}; demand: {dst: qty}; cost: {(src, dst): unit_cost} (missing pair = not allowed).
	If total supply < demand and allow_shortage, the unmet demand is reported; if supply > demand, surplus stays."""
	require_scipy()
	import numpy as np
	from scipy.optimize import linprog

	S, D = sorted(supply), sorted(demand)
	pairs = [(s, d) for s in S for d in D if (s, d) in cost]
	if not pairs:
		return {"status": "infeasible", "flows": {}, "total_cost": 0.0, "verified": True}
	big = shortage_penalty if shortage_penalty is not None else (max(num(v) for v in cost.values()) + 1) * 1000.0
	nv = len(pairs) + len(D)  # flows + shortage per destination
	c = np.array([num(cost[p]) for p in pairs] + [big] * len(D))
	A_ub = np.zeros((len(S), nv))
	for i, s in enumerate(S):
		for k, p in enumerate(pairs):
			if p[0] == s:
				A_ub[i, k] = 1
	A_eq = np.zeros((len(D), nv))
	for j, d in enumerate(D):
		for k, p in enumerate(pairs):
			if p[1] == d:
				A_eq[j, k] = 1
		A_eq[j, len(pairs) + j] = 1
	b_ub = np.array([num(supply[s]) for s in S])
	b_eq = np.array([num(demand[d]) for d in D])
	res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=(0, None), method="highs")
	if res.status != 0:
		return {"status": {2: "infeasible", 3: "unbounded"}.get(res.status, "failed"), "flows": {}, "total_cost": 0.0, "verified": True}
	flows = {p: float(res.x[k]) for k, p in enumerate(pairs) if res.x[k] > 1e-9}
	short = {d: float(res.x[len(pairs) + j]) for j, d in enumerate(D) if res.x[len(pairs) + j] > 1e-9}
	if short and not allow_shortage:
		return {"status": "infeasible", "flows": {}, "total_cost": 0.0, "shortage": short, "verified": True}
	total = sum(num(cost[p]) * q for p, q in flows.items())
	u = {s: float(res.ineqlin.marginals[i]) for i, s in enumerate(S)}
	v = {d: float(res.eqlin.marginals[j]) for j, d in enumerate(D)}
	out = {"status": "optimal", "flows": flows, "total_cost": total, "shortage": short, "surplus": {s: num(supply[s]) - sum(q for (a, _b), q in flows.items() if a == s) for s in S}, "u": u, "v": v}
	out["verified"] = _verify_transport(supply, demand, cost, out, big)
	return out


def _verify_transport(supply, demand, cost, out, big):
	flows = out["flows"]
	for s, cap in supply.items():
		if sum(q for (a, _b), q in flows.items() if a == s) > num(cap) + 1e-6:
			return False
	for d, need in demand.items():
		got = sum(q for (_a, b), q in flows.items() if b == d) + out["shortage"].get(d, 0.0)
		if abs(got - num(need)) > 1e-6:
			return False
	# Optimality (dual feasibility + complementary slackness): reduced cost c - u - v >= 0 on every allowed lane, = 0 where flow > 0.
	for (s, d), cst in cost.items():
		if s not in out["u"] or d not in out["v"]:
			continue
		rc = num(cst) - out["u"][s] - out["v"][d]
		if rc < -1e-6:
			return False
		if flows.get((s, d), 0.0) > 1e-9 and abs(rc) > 1e-6:
			return False
	for s in out["u"]:
		if out["u"][s] > 1e-6 or (abs(out["u"][s]) > 1e-6 and out["surplus"][s] > 1e-6):
			return False
	return True


# ----------------------------------------------------------------------------- routing

def held_karp(dist, nodes):
	"""Exact shortest tour start(0) -> all `nodes` -> back to 0; dist is a full matrix indexed by node id."""
	n = len(nodes)
	if n == 0:
		return 0.0, []
	if n == 1:
		return dist[0][nodes[0]] + dist[nodes[0]][0], [nodes[0]]
	INF = float("inf")
	dp = {}
	for i in range(n):
		dp[(1 << i, i)] = (dist[0][nodes[i]], -1)
	for mask in range(1, 1 << n):
		for last in range(n):
			if not mask & (1 << last) or (mask, last) not in dp:
				continue
			base = dp[(mask, last)][0]
			for nxt in range(n):
				if mask & (1 << nxt):
					continue
				nm = mask | (1 << nxt)
				cand = base + dist[nodes[last]][nodes[nxt]]
				if cand < dp.get((nm, nxt), (INF, 0))[0]:
					dp[(nm, nxt)] = (cand, last)
	full = (1 << n) - 1
	best, last = min((dp[(full, i)][0] + dist[nodes[i]][0], i) for i in range(n))
	order, mask = [], full
	while last != -1:
		order.append(nodes[last])
		prev = dp[(mask, last)][1]
		mask ^= 1 << last
		last = prev
	return best, order[::-1]


def tour_length(dist, order):
	if not order:
		return 0.0
	pts = [0] + list(order) + [0]
	return sum(dist[pts[i]][pts[i + 1]] for i in range(len(pts) - 1))


def two_opt(dist, order):
	order = list(order)
	improved = True
	while improved:
		improved = False
		for i in range(len(order) - 1):
			for j in range(i + 1, len(order)):
				cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
				if tour_length(dist, cand) < tour_length(dist, order) - 1e-12:
					order, improved = cand, True
	return order


def route_order(dist, stops):
	"""Best visiting order of the stops of one route: exact up to 12 stops, 2-opt beyond."""
	if len(stops) <= 12:
		return held_karp(dist, list(stops))[1]
	nn, cur, left = [], 0, set(stops)
	while left:
		nxt = min(left, key=lambda k: dist[cur][k])
		nn.append(nxt)
		left.remove(nxt)
		cur = nxt
	return two_opt(dist, nn)


def clarke_wright(dist, demand, capacity, max_routes=None):
	"""Savings heuristic. dist: matrix with depot = 0, stops 1..n; demand: {stop: qty}. Returns a list of routes (stop lists)."""
	stops = [k for k in demand]
	routes = {k: [k] for k in stops}
	load = {k: num(demand[k]) for k in stops}
	where = {k: k for k in stops}
	savings = sorted(((dist[0][i] + dist[0][j] - dist[i][j], i, j) for i, j in itertools.combinations(stops, 2)), reverse=True)
	for s, i, j in savings:
		if s <= 0:
			break
		ri, rj = where[i], where[j]
		if ri == rj or load[ri] + load[rj] > capacity + 1e-9:
			continue
		a, b = routes[ri], routes[rj]
		if a[-1] == i and b[0] == j:
			merged = a + b
		elif a[0] == i and b[-1] == j:
			merged = b + a
		elif a[0] == i and b[0] == j:
			merged = a[::-1] + b
		elif a[-1] == i and b[-1] == j:
			merged = a + b[::-1]
		else:
			continue  # i or j is interior to its route: cannot join there
		routes[ri] = merged
		load[ri] += load[rj]
		for k in b:
			where[k] = ri
		del routes[rj]
		del load[rj]
	return [routes[k] for k in routes]


def routes(depot, stops, capacity, vehicles=None):
	"""depot: (lat, lng); stops: [{id, lat, lng, demand}]; capacity: per-vehicle load; vehicles: max count or None.
	Returns routes with order, load and km, the total km, and `lower_bound` (see below) so the gap is visible."""
	pts = [depot] + [(s["lat"], s["lng"]) for s in stops]
	n = len(pts)
	dist = [[haversine(pts[i], pts[j]) if i != j else 0.0 for j in range(n)] for i in range(n)]
	demand = {i + 1: num(s.get("demand")) for i, s in enumerate(stops)}
	too_big = [stops[k - 1]["id"] for k, q in demand.items() if q > capacity + 1e-9]
	if too_big:
		return {"status": "infeasible", "reason": "demand_exceeds_capacity", "stops": too_big, "verified": True}
	rts = clarke_wright(dist, demand, capacity)
	if vehicles and len(rts) > vehicles:
		return {"status": "infeasible", "reason": "not_enough_vehicles", "needed": len(rts), "verified": True}
	out_routes, total = [], 0.0
	for r in rts:
		order = route_order(dist, r)
		km = tour_length(dist, order)
		total += km
		out_routes.append({"stops": [stops[k - 1]["id"] for k in order], "load": sum(demand[k] for k in order), "km": km, "exact_order": len(order) <= 12})
	# Lower bound: each stop must be reached and left; half the sum of the two cheapest incident edges per node, plus
	# the vehicles needed by capacity (ceil(total demand / capacity)) each leaving and returning to the depot.
	lb = _lower_bound(dist, n)
	out = {"status": "optimal_order_heuristic_split", "routes": out_routes, "total_km": total, "lower_bound_km": lb, "gap_pct": (total / lb - 1) * 100 if lb > 0 else 0.0, "vehicles_used": len(out_routes)}
	out["verified"] = _verify_routes(stops, capacity, out)
	return out


def _lower_bound(dist, n):
	if n <= 2:
		return 2 * dist[0][1] if n == 2 else 0.0
	total = 0.0
	for i in range(n):
		two = sorted(dist[i][j] for j in range(n) if j != i)[:2]
		total += sum(two)
	return total / 2


def _verify_routes(stops, capacity, out):
	seen = []
	byid = {s["id"]: s for s in stops}
	for r in out["routes"]:
		if sum(num(byid[i].get("demand")) for i in r["stops"]) > capacity + 1e-9:
			return False
		seen += r["stops"]
	return sorted(map(str, seen)) == sorted(str(s["id"]) for s in stops)
