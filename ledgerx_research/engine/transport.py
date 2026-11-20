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
		if s < -1e-9:  # a merge that adds no distance is still taken: it saves a vehicle
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


EXACT_FLEET_STOPS = 10  # up to this many stops the mixed-fleet plan is solved exactly (dynamic programming over stop subsets)


def _dist_matrix(depot, stops):
	pts = [(depot[0], depot[1])] + [(s["lat"], s["lng"]) for s in stops]
	n = len(pts)
	return [[haversine(pts[i], pts[j]) if i != j else 0.0 for j in range(n)] for i in range(n)]


def _fleet_exact(dist, stops, vs):
	"""Optimal split of the stops among distinct vehicles and the optimal tour of each: minimises sum(cost_per_km x tour km)."""
	n = len(stops)
	INF = float("inf")
	full = (1 << n) - 1
	f = [[INF] * n for _ in range(1 << n)]
	par = [[-1] * n for _ in range(1 << n)]
	for j in range(n):
		f[1 << j][j] = dist[0][j + 1]
	for mask in range(1, 1 << n):
		for j in range(n):
			cur = f[mask][j]
			if cur == INF:
				continue
			for k in range(n):
				if mask >> k & 1:
					continue
				nm = mask | (1 << k)
				v = cur + dist[j + 1][k + 1]
				if v < f[nm][k]:
					f[nm][k], par[nm][k] = v, j
	tour, last = [0.0] * (1 << n), [-1] * (1 << n)
	for mask in range(1, 1 << n):
		best = (INF, -1)
		for j in range(n):
			if f[mask][j] < INF and f[mask][j] + dist[j + 1][0] < best[0]:
				best = (f[mask][j] + dist[j + 1][0], j)
		tour[mask], last[mask] = best
	load = [0.0] * (1 << n)
	for mask in range(1, 1 << n):
		low = (mask & -mask).bit_length() - 1
		load[mask] = load[mask & (mask - 1)] + num(stops[low].get("demand"))

	def order_of(mask):
		seq, j, m = [], last[mask], mask
		while j != -1:
			seq.append(j)
			pj = par[m][j]
			m ^= 1 << j
			j = pj
		return seq[::-1]
	g = [INF] * (1 << n)
	g[0] = 0.0
	choice = []
	for v in vs:
		ng = list(g)
		ch = [0] * (1 << n)
		cap, cpk = num(v["capacity"]), num(v.get("cost_per_km"))
		for mask in range(1, 1 << n):
			sub = mask
			while sub:
				if load[sub] <= cap + 1e-9 and g[mask ^ sub] < INF:
					val = g[mask ^ sub] + cpk * tour[sub]
					if val < ng[mask] - 1e-12:
						ng[mask], ch[mask] = val, sub
				sub = (sub - 1) & mask
		g = ng
		choice.append(ch)
	if g[full] == INF:
		return None
	routes_, mask = [], full
	for idx in range(len(vs) - 1, -1, -1):
		sub = choice[idx][mask]
		if sub:
			seq = order_of(sub)
			routes_.append({"stops": [stops[k]["id"] for k in seq], "load": load[sub], "km": tour[sub], "exact_order": True, "vehicle": vs[idx]["id"],
				"cost": tour[sub] * num(vs[idx].get("cost_per_km")), "capacity": num(vs[idx]["capacity"])})
			mask ^= sub
	return routes_[::-1], g[full]


def _ffd_groups(stops, vs):
	"""Fallback packing: stops by decreasing load into the largest vehicles first-fit. None when it does not fit."""
	bins = [[num(v["capacity"]), []] for v in sorted(vs, key=lambda v: -num(v["capacity"]))]
	for k, s in sorted(enumerate(stops), key=lambda ks: -num(ks[1].get("demand"))):
		for b in bins:
			if b[0] + 1e-9 >= num(s.get("demand")):
				b[0] -= num(s.get("demand"))
				b[1].append(k)
				break
		else:
			return None
	return [b[1] for b in bins if b[1]]


def routes_fleet(depot, stops, vehicles):
	"""Delivery routes for a mixed fleet. vehicles: [{id, capacity, cost_per_km}]; minimises sum(km x cost_per_km), one vehicle per route.
	Up to EXACT_FLEET_STOPS stops: exact (optimal split and stop order). More stops: routes are built for each vehicle capacity and for a
	first-fit packing, then given to different vehicles by an exact assignment; the cheapest feasible candidate wins and the result shows the
	distance lower bound and the gap. Always returns `verified`."""
	from scipy.optimize import linear_sum_assignment
	import numpy as np

	vs = [v for v in vehicles if num(v.get("capacity")) > 0]
	if not vs:
		return {"status": "infeasible", "reason": "no_vehicle", "verified": True}
	biggest = max(num(v["capacity"]) for v in vs)
	too_big = [s["id"] for s in stops if num(s.get("demand")) > biggest + 1e-9]
	if too_big:
		return {"status": "infeasible", "reason": "demand_exceeds_capacity", "stops": too_big, "verified": True}
	if not stops:
		return {"status": "empty", "routes": [], "total_km": 0.0, "total_cost": 0.0, "verified": True}
	dist = _dist_matrix(depot, stops)
	lb = _lower_bound(dist, len(stops) + 1)
	if len(stops) <= EXACT_FLEET_STOPS:
		ex = _fleet_exact(dist, stops, vs)
		if ex is None:
			return {"status": "infeasible", "reason": "not_enough_vehicles", "verified": True}
		rts, total = ex
		km = sum(r["km"] for r in rts)
		out = {"status": "optimal", "routes": rts, "total_km": km, "total_cost": total, "lower_bound_km": lb, "gap_pct": (km / lb - 1) * 100 if lb > 0 else 0.0,
			"vehicles_used": len(rts), "exact": True}
		out["verified"] = _verify_fleet(stops, vs, out)
		return out
	cands = []
	for cap in sorted({num(v["capacity"]) for v in vs}, reverse=True):
		c = routes((depot[0], depot[1]), stops, cap)
		if c["status"] != "infeasible":
			cands.append([{"stops": r["stops"], "load": r["load"], "km": r["km"], "exact_order": r["exact_order"]} for r in c["routes"]])
	groups = _ffd_groups(stops, vs)
	if groups:
		idx = {s["id"]: k + 1 for k, s in enumerate(stops)}
		packed = []
		for g_ in groups:
			order = route_order(dist, [k + 1 for k in g_])
			packed.append({"stops": [stops[k - 1]["id"] for k in order], "load": sum(num(stops[k - 1].get("demand")) for k in order), "km": tour_length(dist, order), "exact_order": len(order) <= 12})
		cands.append(packed)
	best, needed = None, 0
	for rts in cands:
		needed = max(needed, len(rts))
		if len(rts) > len(vs):
			continue
		BIG = 1e12
		cost = np.full((len(rts), len(vs)), BIG)
		for i, r in enumerate(rts):
			for j, v in enumerate(vs):
				if r["load"] <= num(v["capacity"]) + 1e-9:
					cost[i, j] = r["km"] * num(v.get("cost_per_km"))
		rows, cols = linear_sum_assignment(cost)
		if any(cost[i, j] >= BIG for i, j in zip(rows, cols)):
			continue
		total = float(sum(cost[i, j] for i, j in zip(rows, cols)))
		if best is None or total < best[0] - 1e-9:
			best = (total, rts, {int(i): int(j) for i, j in zip(rows, cols)})
	if best is None:
		return {"status": "infeasible", "reason": "not_enough_vehicles", "needed": needed or None, "verified": True}
	total, rts, assign = best
	out_routes = [{**r, "vehicle": vs[assign[i]]["id"], "cost": r["km"] * num(vs[assign[i]].get("cost_per_km")), "capacity": num(vs[assign[i]]["capacity"])} for i, r in enumerate(rts)]
	km = sum(r["km"] for r in out_routes)
	out = {"status": "optimal_order_heuristic_split", "routes": out_routes, "total_km": km, "total_cost": total, "lower_bound_km": lb, "gap_pct": (km / lb - 1) * 100 if lb > 0 else 0.0,
		"vehicles_used": len(out_routes), "exact": False}
	out["verified"] = _verify_fleet(stops, vs, out)
	return out


def _verify_fleet(stops, vehicles, out):
	byv = {v["id"]: v for v in vehicles}
	if sorted(map(str, (x for r in out["routes"] for x in r["stops"]))) != sorted(str(s["id"]) for s in stops):
		return False
	used = [r["vehicle"] for r in out["routes"]]
	if len(set(used)) != len(used):
		return False
	for r in out["routes"]:
		if r["load"] > num(byv[r["vehicle"]]["capacity"]) + 1e-9:
			return False
	if abs(sum(r["cost"] for r in out["routes"]) - out["total_cost"]) > 1e-6 * max(1.0, abs(out["total_cost"])):
		return False
	return True
