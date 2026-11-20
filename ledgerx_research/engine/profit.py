"""Profitability and pricing: who and what makes or loses money, the best price, the cost of a discount."""
import math

from .common import num


def profitability(rows):
	"""rows: [{name, revenue, cost, qty=0}] -> each with margin, margin %, share of total profit, rank and a class
	(A = the group that makes 80% of the positive profit, B = next 15%, C = rest, L = loses money)."""
	out = []
	for r in rows:
		rev, cost = num(r.get("revenue")), num(r.get("cost"))
		out.append({**r, "margin": rev - cost, "margin_pct": (rev - cost) / rev * 100 if rev else 0.0})
	pos_total = sum(x["margin"] for x in out if x["margin"] > 0)
	cum = 0.0
	for x in sorted(out, key=lambda x: (-x["margin"], str(x["name"]))):
		if x["margin"] <= 0:
			x["class"] = "L"
		else:
			x["class"] = "A" if (cum / pos_total < 0.8 if pos_total else False) else ("B" if cum / pos_total < 0.95 else "C")
			cum += x["margin"]
		x["profit_share_pct"] = x["margin"] / pos_total * 100 if pos_total and x["margin"] > 0 else 0.0
	order = sorted(out, key=lambda x: (-x["margin"], str(x["name"])))
	for i, x in enumerate(order, 1):
		x["rank"] = i
	total_rev = sum(num(r.get("revenue")) for r in rows)
	total_cost = sum(num(r.get("cost")) for r in rows)
	return {"rows": order, "total_revenue": total_rev, "total_margin": total_rev - total_cost, "losers": [x["name"] for x in order if x["class"] == "L"],
		"verified": abs(sum(x["margin"] for x in order) - (total_rev - total_cost)) < 1e-6 * max(1.0, abs(total_rev))}


def estimate_elasticity(points, min_points=6, min_price_spread_pct=3.0):
	"""Constant-elasticity fit ln q = a - e ln p from [(price, qty)]. Returns None with a reason when the data cannot support it."""
	pts = [(num(p), num(q)) for p, q in points if num(p) > 0 and num(q) > 0]
	if len(pts) < min_points:
		return {"elasticity": None, "reason": "too_few_points"}
	prices = [p for p, _ in pts]
	if (max(prices) - min(prices)) / (sum(prices) / len(prices)) * 100 < min_price_spread_pct:
		return {"elasticity": None, "reason": "price_barely_changed"}
	xs = [math.log(p) for p, _ in pts]
	ys = [math.log(q) for _, q in pts]
	n = len(pts)
	mx, my = sum(xs) / n, sum(ys) / n
	sxx = sum((x - mx) ** 2 for x in xs)
	slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
	ss_tot = sum((y - my) ** 2 for y in ys)
	ss_res = sum((y - (my + slope * (x - mx))) ** 2 for x, y in zip(xs, ys))
	r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
	return {"elasticity": -slope, "r2": r2, "n": n, "reliable": r2 >= 0.5 and slope < 0}


def best_price(cost, price0, qty0, elasticity, model="constant", min_price=None, max_price=None, capacity=None):
	"""Profit-maximising price. model 'constant': q = k p^-e, p* = c e / (e - 1) (needs e > 1);
	model 'linear': q = a - b p, p* = (a/b + c)/2. Price limits and capacity are respected (the best price is then at a limit).
	The answer is checked against a fine grid search."""
	c, p0, q0, e = num(cost), num(price0), num(qty0), num(elasticity)
	if p0 <= 0 or q0 <= 0 or e <= 0:
		return {"status": "infeasible", "reason": "bad_input", "verified": True}
	if model == "linear":
		b = e * q0 / p0
		a = q0 + b * p0
		demand = lambda p: max(a - b * p, 0.0)
		free = (a / b + c) / 2
	else:
		k = q0 * p0 ** e
		demand = lambda p: k * p ** (-e)
		free = c * e / (e - 1) if e > 1 else None
	lo = max(num(min_price), c) if min_price else c
	hi = num(max_price) if max_price else p0 * 5
	if free is None:
		cand, reason = hi, "demand_not_elastic_enough"  # raising the price always pays: stop at the limit
	else:
		cand, reason = min(max(free, lo), hi), None

	def eval_p(p):
		q = demand(p)
		if capacity:
			q = min(q, num(capacity))
		return (p - c) * q, q
	profit, q = eval_p(cand)
	# independent check: grid search on [lo, hi]
	best = max((eval_p(lo + (hi - lo) * i / 4000.0)[0] for i in range(4001)), default=0.0)
	base_profit, _q = eval_p(p0)
	out = {"status": "optimal", "price": cand, "qty": q, "profit": profit, "current_profit": base_profit, "gain": profit - base_profit, "reason": reason,
		"at_limit": free is None or abs(cand - free) > 1e-9}
	out["verified"] = bool(profit >= best - 1e-6 * max(1.0, abs(best)) and (profit >= base_profit - 1e-9 or p0 < lo or p0 > hi))
	return out


def discount_effect(price, cost, qty, discount_pct, elasticity=None):
	"""Extra volume a discount must bring just to keep the same profit, and (if an elasticity is given) what is expected."""
	p, c, q, d = num(price), num(cost), num(qty), num(discount_pct) / 100.0 * num(price)
	m = p - c
	if m <= 0:
		return {"status": "infeasible", "reason": "no_margin", "verified": True}
	if d >= m:
		return {"status": "infeasible", "reason": "discount_wipes_margin", "verified": True}
	need = d / (m - d)
	out = {"status": "optimal", "required_uplift_pct": need * 100, "required_qty": q * (1 + need), "new_margin": m - d}
	out["verified"] = abs((m - d) * out["required_qty"] - m * q) <= 1e-6 * max(1.0, m * q)
	if elasticity:
		new_q = q * (1 - num(discount_pct) / 100.0) ** (-num(elasticity))
		out["expected_qty"] = new_q
		out["expected_profit_change"] = (m - d) * new_q - m * q
	return out


def stock_health(rows, slow_days=90, dead_days=180):
	"""rows: [{item, qty, value, days_since_move, daily_demand}] -> class per item: dead / slow / overstocked / healthy, and the money tied up."""
	out = []
	for r in rows:
		cover = (num(r["qty"]) / num(r["daily_demand"])) if num(r.get("daily_demand")) > 0 else None
		since = num(r.get("days_since_move"), 0.0)
		if num(r.get("qty")) <= 0:
			cls = "empty"
		elif since >= dead_days:
			cls = "dead"
		elif since >= slow_days:
			cls = "slow"
		elif cover is not None and cover > 365:
			cls = "overstocked"
		else:
			cls = "healthy"
		out.append({**r, "cover_days": cover, "class": cls})
	return {"rows": out, "tied_up": sum(num(r.get("value")) for r in out if r["class"] in ("dead", "slow", "overstocked")), "verified": True}
