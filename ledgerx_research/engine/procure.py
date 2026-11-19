"""Supplier allocation: split the required quantity of each item across suppliers at the lowest total cost.

Handles supplier capacity per offer, minimum order quantity (all-or-nothing via binaries), a fixed cost per supplier
used, a maximum share of any one supplier, a maximum lead time, a minimum quality score and a budget. Exact (MILP).
"""
from .common import num, require_scipy


def allocate(demand, offers, max_share=None, max_lead_days=None, min_quality=None, budget=None, fixed_cost=None):
	"""demand: {item: qty}; offers: [{supplier, item, price, capacity=None, moq=0, lead_days=0, quality=None}];
	fixed_cost: {supplier: cost per supplier used}. Returns allocation + total cost + verified."""
	require_scipy()
	import numpy as np
	from scipy.optimize import Bounds, LinearConstraint, milp

	fixed_cost = fixed_cost or {}
	use = [o for o in offers
		if o["item"] in demand
		and (max_lead_days is None or num(o.get("lead_days")) <= max_lead_days)
		and (min_quality is None or o.get("quality") is None or num(o["quality"]) >= min_quality)]
	items = list(demand)
	sups = sorted({o["supplier"] for o in use})
	n = len(use)
	if not items:
		return {"status": "empty", "allocation": [], "total_cost": 0.0, "verified": True}
	for it in items:
		if num(demand[it]) > 0 and not any(o["item"] == it for o in use):
			return {"status": "infeasible", "reason": "no_offer", "item": it, "allocation": [], "total_cost": 0.0, "verified": True}
	ns = len(sups)
	# variables: x[0..n) quantities, y[n..2n) offer used, z[2n..2n+ns) supplier used
	nv = 2 * n + ns
	c = np.zeros(nv)
	for k, o in enumerate(use):
		c[k] = num(o["price"])
	for s, name in enumerate(sups):
		c[2 * n + s] = num(fixed_cost.get(name))
	A, lo, hi = [], [], []

	def row(entries, low, high):
		r = np.zeros(nv)
		for idx, v in entries:
			r[idx] += v
		A.append(r), lo.append(low), hi.append(high)
	for it in items:
		d = num(demand[it])
		row([(k, 1) for k, o in enumerate(use) if o["item"] == it], d, d)
	for k, o in enumerate(use):
		cap = o.get("capacity")
		upper = num(cap) if cap not in (None, "") else num(demand[o["item"]])
		if max_share is not None:
			upper = min(upper, max_share * num(demand[o["item"]]))
		row([(k, 1), (n + k, -upper)], -np.inf, 0)  # x <= upper * y
		if num(o.get("moq")) > 0:
			row([(k, 1), (n + k, -num(o["moq"]))], 0, np.inf)  # x >= moq * y
		s = sups.index(o["supplier"])
		row([(n + k, 1), (2 * n + s, -1)], -np.inf, 0)  # y <= z
	if budget is not None:
		row([(k, num(o["price"])) for k, o in enumerate(use)] + [(2 * n + s, num(fixed_cost.get(name))) for s, name in enumerate(sups)], -np.inf, num(budget))
	integ = np.concatenate([np.zeros(n), np.ones(n + ns)])
	ub = np.concatenate([np.full(n, np.inf), np.ones(n + ns)])
	res = milp(c, constraints=LinearConstraint(np.array(A), lo, hi), integrality=integ, bounds=Bounds(np.zeros(nv), ub))
	if res.status != 0:
		return {"status": {2: "infeasible", 3: "unbounded"}.get(res.status, "failed"), "allocation": [], "total_cost": 0.0, "verified": True}
	alloc = []
	for k, o in enumerate(use):
		q = float(res.x[k])
		if q > 1e-7:
			alloc.append({"supplier": o["supplier"], "item": o["item"], "qty": q, "price": num(o["price"]), "amount": q * num(o["price"]), "lead_days": num(o.get("lead_days"))})
	used = {a["supplier"] for a in alloc}
	total = sum(a["amount"] for a in alloc) + sum(num(fixed_cost.get(s)) for s in used)
	out = {"status": "optimal", "allocation": alloc, "total_cost": total, "suppliers_used": sorted(used)}
	out["verified"] = verify(demand, use, out, max_share, budget, fixed_cost)
	return out


def verify(demand, offers, out, max_share, budget, fixed_cost):
	got = {}
	for a in out["allocation"]:
		got[a["item"]] = got.get(a["item"], 0.0) + a["qty"]
		off = next((o for o in offers if o["supplier"] == a["supplier"] and o["item"] == a["item"]), None)
		if off is None:
			return False
		if off.get("capacity") not in (None, "") and a["qty"] > num(off["capacity"]) + 1e-6:
			return False
		if a["qty"] < num(off.get("moq")) - 1e-6:
			return False
		if max_share is not None and a["qty"] > max_share * num(demand[a["item"]]) + 1e-6:
			return False
	for it, d in demand.items():
		if abs(got.get(it, 0.0) - num(d)) > 1e-5:
			return False
	if budget is not None and out["total_cost"] > num(budget) + 1e-5:
		return False
	recomputed = sum(a["amount"] for a in out["allocation"]) + sum(num(fixed_cost.get(s)) for s in out["suppliers_used"])
	return abs(recomputed - out["total_cost"]) < 1e-5


def what_if_without(demand, offers, supplier, **kw):
	"""Cost of the best plan if one supplier cannot deliver: shows how exposed the plan is to a single supplier."""
	rest = [o for o in offers if o["supplier"] != supplier]
	base = allocate(demand, offers, **kw)
	alt = allocate(demand, rest, **kw)
	return {"supplier": supplier, "feasible": alt["status"] == "optimal", "cost": alt["total_cost"] if alt["status"] == "optimal" else None,
		"extra_cost": (alt["total_cost"] - base["total_cost"]) if alt["status"] == "optimal" and base["status"] == "optimal" else None}
