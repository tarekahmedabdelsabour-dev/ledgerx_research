"""Product mix: which quantities to make to maximise contribution margin under limited resources.

max  sum(m_j x_j)   s.t.  sum(a_rj x_j) <= b_r,  lo_j <= x_j <= hi_j,  (x_j integer optionally)
"""
from .common import TOL, num, require_scipy


def solve(products, resources, integer=False):
	"""products: [{code, margin, usage: {resource: per_unit}, min_qty=0, max_qty=None}]
	resources: {name: available}. Returns a dict (see keys below). Never raises on infeasible input."""
	require_scipy()
	import numpy as np
	from scipy.optimize import Bounds, LinearConstraint, linprog, milp

	codes = [p["code"] for p in products]
	names = sorted(resources)
	n, m = len(products), len(names)
	if not n:
		return {"status": "empty", "verified": True, "quantities": {}, "objective": 0.0}
	c = np.array([-num(p["margin"]) for p in products])
	A = np.array([[num(p.get("usage", {}).get(r)) for p in products] for r in names]) if m else np.zeros((0, n))
	b = np.array([num(resources[r]) for r in names])
	lo = np.array([num(p.get("min_qty")) for p in products])
	hi = np.array([np.inf if p.get("max_qty") in (None, "") else num(p["max_qty"]) for p in products])
	out = {"status": None, "objective": 0.0, "quantities": {}, "usage": {}, "slack": {}, "shadow_price": {}, "reduced_cost": {}, "verified": False, "integer": bool(integer)}

	if integer:
		cons = [LinearConstraint(A, -np.inf, b)] if m else []
		res = milp(c, constraints=cons, bounds=Bounds(lo, hi), integrality=np.ones(n))
		ok = res.status == 0
	else:
		res = linprog(c, A_ub=A if m else None, b_ub=b if m else None, bounds=list(zip(lo, [None if np.isinf(h) else h for h in hi])), method="highs")
		ok = res.status == 0
	if not ok:
		out["status"] = {2: "infeasible", 3: "unbounded"}.get(res.status, "failed")
		out["verified"] = True
		return out

	x = np.array([round(v) if integer else v for v in res.x])
	out["status"] = "optimal"
	out["quantities"] = {codes[j]: float(x[j]) for j in range(n)}
	out["objective"] = float(sum(num(products[j]["margin"]) * x[j] for j in range(n)))
	for i, r in enumerate(names):
		used = float(A[i] @ x)
		out["usage"][r] = used
		out["slack"][r] = float(b[i] - used)
	if not integer:
		# HiGHS marginals are for the minimisation; negate to get the value of one more unit of the resource.
		duals = [-float(v) for v in res.ineqlin.marginals] if m else []
		out["shadow_price"] = {r: (duals[i] if abs(duals[i]) > TOL else 0.0) for i, r in enumerate(names)}
		rc = [-float(v) for v in res.lower.marginals]
		out["reduced_cost"] = {codes[j]: rc[j] for j in range(n)}
	out["verified"] = verify(products, resources, out, lo, hi)
	return out


def verify(products, resources, out, lo, hi):
	"""Independent check: every constraint holds; for an LP the optimality certificate also holds."""
	x = [out["quantities"][p["code"]] for p in products]
	for j, v in enumerate(x):
		if v < lo[j] - 1e-6 or v > hi[j] + 1e-6:
			return False
	for r, cap in resources.items():
		if sum(num(p.get("usage", {}).get(r)) * x[j] for j, p in enumerate(products)) > num(cap) + 1e-6:
			return False
	if out["integer"]:
		return all(abs(v - round(v)) < 1e-9 for v in x)
	return _lp_certificate(products, resources, out, lo, hi)


def _lp_certificate(products, resources, out, lo, hi):
	"""Complementary slackness + dual feasibility, checked directly:
	  y_r >= 0, y_r * slack_r = 0, and for each product  margin_j - sum(a_rj y_r) = d_j with
	  d_j > 0 only if x_j is at its upper bound, d_j < 0 only if x_j is at its lower bound."""
	y = out["shadow_price"]
	for r, v in y.items():
		if v < -1e-6 or abs(v * out["slack"][r]) > 1e-5 * max(1.0, abs(num(resources[r]))):
			return False
	for j, p in enumerate(products):
		x = out["quantities"][p["code"]]
		d = num(p["margin"]) - sum(num(p.get("usage", {}).get(r)) * y[r] for r in y)
		at_lo = abs(x - lo[j]) <= 1e-6
		at_hi = hi[j] != float("inf") and abs(x - hi[j]) <= 1e-6
		if d > 1e-6 and not at_hi:
			return False
		if d < -1e-6 and not at_lo:
			return False
	return True
