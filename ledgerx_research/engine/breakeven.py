"""Break-even analysis: single product and a sales mix, target profit, margin of safety, operating leverage, cash break-even.

profit(Q) = sum_i q_i * (p_i - v_i) - F, with the quantities in a fixed mix (shares of the expected sales).
"""
from .common import num


def _mix(products):
	tot = sum(max(num(p.get("qty")), 0.0) for p in products)
	if tot <= 0:
		n = len(products)
		return [(p, 1.0 / n if n else 0.0) for p in products]
	return [(p, max(num(p.get("qty")), 0.0) / tot) for p in products]


def profit_at(products, fixed, total_units):
	"""Profit when `total_units` are sold in the expected mix."""
	return sum(w * total_units * (num(p["price"]) - num(p["variable_cost"])) for p, w in _mix(products)) - num(fixed)


def break_even(products, fixed, target_profit=0.0, expected_units=None, capacity=None, cash_fixed=None):
	"""products: [{code, price, variable_cost, qty (expected volume; gives the mix)}]; fixed: fixed costs for the period.
	Returns break-even units/revenue in total and per product, margin of safety, operating leverage and a `verified` flag."""
	mix = _mix(products)
	out = {"status": "optimal", "verified": False, "per_product": []}
	if not products:
		return {"status": "empty", "verified": True, "per_product": []}
	cm = sum(w * (num(p["price"]) - num(p["variable_cost"])) for p, w in mix)  # weighted contribution per unit
	rev = sum(w * num(p["price"]) for p, w in mix)  # weighted revenue per unit
	out["contribution_per_unit"] = cm
	out["contribution_ratio"] = cm / rev if rev > 0 else 0.0
	if cm <= 0:
		out.update(status="never", verified=True)
		return out
	need = num(fixed) + num(target_profit)
	units = need / cm
	out["break_even_units"] = num(fixed) / cm
	out["target_units"] = units
	out["break_even_revenue"] = out["break_even_units"] * rev
	out["target_revenue"] = units * rev
	if cash_fixed is not None:
		out["cash_break_even_units"] = num(cash_fixed) / cm
	for p, w in mix:
		u = w * out["break_even_units"]
		out["per_product"].append({"code": p["code"], "share": w, "units": u, "revenue": u * num(p["price"]), "contribution": num(p["price"]) - num(p["variable_cost"])})
	if expected_units is None:
		expected_units = sum(max(num(p.get("qty")), 0.0) for p in products) or None
	if expected_units:
		eu = num(expected_units)
		out["expected_units"] = eu
		out["expected_profit"] = profit_at(products, fixed, eu)
		out["margin_of_safety_units"] = eu - out["break_even_units"]
		out["margin_of_safety_pct"] = (eu - out["break_even_units"]) / eu * 100 if eu > 0 else 0.0
		contrib = cm * eu
		out["operating_leverage"] = contrib / (contrib - num(fixed)) if contrib - num(fixed) > 1e-9 else None
	if capacity and num(capacity) > 0:
		out["capacity"] = num(capacity)
		out["reachable"] = out["target_units"] <= num(capacity) + 1e-9
	out["verified"] = _verify(products, fixed, target_profit, out)
	return out


def _verify(products, fixed, target_profit, out):
	"""Profit at the break-even volume is zero, at the target volume equals the target, and one unit above it is positive."""
	if abs(profit_at(products, fixed, out["break_even_units"])) > 1e-6 * max(1.0, num(fixed)):
		return False
	if abs(profit_at(products, fixed, out["target_units"]) - num(target_profit)) > 1e-6 * max(1.0, num(fixed) + abs(num(target_profit))):
		return False
	if profit_at(products, fixed, out["break_even_units"] + 1.0) <= 0:
		return False
	if sum(r["units"] for r in out["per_product"]) - out["break_even_units"] > 1e-6 * max(1.0, out["break_even_units"]):
		return False
	return True


def sensitivity(products, fixed, expected_units=None, steps=(-0.2, -0.1, 0.1, 0.2)):
	"""How break-even units and profit move when price, variable cost, fixed cost or volume change by a percentage."""
	rows = []
	base = break_even(products, fixed, expected_units=expected_units)
	eu = base.get("expected_units")
	for what in ("price", "variable_cost", "fixed", "volume"):
		for s in steps:
			ps = [dict(p) for p in products]
			f = num(fixed)
			e = eu
			if what == "price":
				for p in ps:
					p["price"] = num(p["price"]) * (1 + s)
			elif what == "variable_cost":
				for p in ps:
					p["variable_cost"] = num(p["variable_cost"]) * (1 + s)
			elif what == "fixed":
				f = f * (1 + s)
			elif eu:
				e = eu * (1 + s)
			r = break_even(ps, f, expected_units=e)
			rows.append({"what": what, "change_pct": s * 100, "break_even_units": r.get("break_even_units"), "expected_profit": r.get("expected_profit"), "status": r["status"]})
	return rows


def risk(products, fixed, expected_units, sd_pct, n=2000, seed=12345):
	"""Monte Carlo: price, variable cost, volume and fixed cost vary independently (normal, sd = sd_pct % of the value).
	Returns the chance of a loss and the 5th/50th/95th percentile of profit. Fixed seed: same input -> same answer."""
	import random
	rnd = random.Random(seed)
	sd = num(sd_pct) / 100.0
	base_units = num(expected_units)
	profits = []
	for _ in range(int(n)):
		ps = []
		for p in products:
			ps.append({**p, "price": max(num(p["price"]) * rnd.gauss(1, sd), 0.0), "variable_cost": max(num(p["variable_cost"]) * rnd.gauss(1, sd), 0.0)})
		units = max(base_units * rnd.gauss(1, sd), 0.0)
		f = max(num(fixed) * rnd.gauss(1, sd / 2), 0.0)
		profits.append(profit_at(ps, f, units))
	profits.sort()
	q = lambda x: profits[min(int(x * len(profits)), len(profits) - 1)]
	return {"loss_probability_pct": sum(1 for v in profits if v < 0) / len(profits) * 100, "p5": q(0.05), "p50": q(0.5), "p95": q(0.95), "mean": sum(profits) / len(profits), "n": len(profits), "seed": seed}
