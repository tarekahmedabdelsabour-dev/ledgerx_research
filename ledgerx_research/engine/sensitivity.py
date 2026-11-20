"""What-if and risk for the product mix: scenarios, how far an input can move before the decision changes, Monte Carlo.

Everything re-solves the real model (engine.mix.solve), so a scenario answer is exactly as reliable as a normal plan.
"""
import copy
import random

from . import mix
from .common import num


def _apply(products, resources, changes):
	ps, rs = copy.deepcopy(products), dict(resources)
	for ch in changes:
		f = 1 + num(ch["pct"]) / 100.0
		kind, key = ch["kind"], ch["key"]
		if kind == "resource":
			if key not in rs:
				raise KeyError(key)
			rs[key] = num(rs[key]) * f
		else:
			hit = [p for p in ps if p["code"] == key]
			if not hit:
				raise KeyError(key)
			for p in hit:
				if kind == "margin":
					p["margin"] = num(p["margin"]) * f
				elif kind == "max_qty":
					p["max_qty"] = None if p.get("max_qty") in (None, "") else num(p["max_qty"]) * f
				elif kind == "min_qty":
					p["min_qty"] = num(p.get("min_qty")) * f
				else:
					raise KeyError(kind)
	return ps, rs


def scenario(products, resources, changes, integer=False):
	"""changes: [{kind: resource|margin|max_qty|min_qty, key, pct}] -> the re-optimised plan."""
	ps, rs = _apply(products, resources, changes)
	return mix.solve(ps, rs, integer=integer)


def compare(products, resources, scenarios, integer=False):
	"""scenarios: [{name, changes}] -> rows with the objective, the change versus the base plan and which products moved."""
	base = mix.solve(products, resources, integer=integer)
	rows = []
	for sc in scenarios:
		r = scenario(products, resources, sc["changes"], integer)
		moved = []
		if r["status"] == "optimal" and base["status"] == "optimal":
			moved = sorted(c for c in r["quantities"] if abs(r["quantities"][c] - base["quantities"][c]) > 1e-6)
		rows.append({"name": sc["name"], "status": r["status"], "objective": r.get("objective"), "delta": (r["objective"] - base["objective"]) if r["status"] == "optimal" and base["status"] == "optimal" else None,
			"verified": r.get("verified", False), "moved": moved})
	return {"base": base, "rows": rows}


def resource_range(products, resources, name, max_factor=4.0):
	"""How much a resource can grow or shrink while one extra unit is still worth the shadow price
	(that is, while the bottleneck stays the same). Found by bisection on the re-solved objective. Returns (low, high, price)."""
	base = mix.solve(products, resources)
	if base["status"] != "optimal":
		return None
	price = base["shadow_price"].get(name, 0.0)
	b0 = num(resources[name])

	def linear(b):
		rs = dict(resources)
		rs[name] = b
		r = mix.solve(products, rs)
		if r["status"] != "optimal":
			return False
		return abs(r["objective"] - (base["objective"] + price * (b - b0))) <= 1e-6 * max(1.0, abs(base["objective"]))

	def edge(direction):
		lim = b0 * max_factor if direction > 0 else 0.0
		if b0 == 0 and direction < 0:
			return 0.0
		if linear(lim):
			return lim
		good, bad = b0, lim
		for _ in range(40):
			mid = (good + bad) / 2
			if linear(mid):
				good = mid
			else:
				bad = mid
		return good
	return {"low": edge(-1), "high": edge(+1), "shadow_price": price, "current": b0}


def margin_range(products, resources, code, max_factor=4.0):
	"""How far the margin of one product can move up and down before the best plan changes (the quantities stay the same inside).
	Bisection on a factor of the margin. Returns (low_margin, high_margin)."""
	base = mix.solve(products, resources)
	if base["status"] != "optimal":
		return None
	m0 = num(next(p["margin"] for p in products if p["code"] == code))
	if m0 == 0:
		return None

	def same(m):
		ps = copy.deepcopy(products)
		for p in ps:
			if p["code"] == code:
				p["margin"] = m
		r = mix.solve(ps, resources)
		return r["status"] == "optimal" and all(abs(r["quantities"][c] - base["quantities"][c]) <= 1e-6 * max(1.0, abs(base["quantities"][c])) for c in base["quantities"])

	def edge(factor_limit):
		lim = m0 * factor_limit
		if same(lim):
			return lim
		good, bad = m0, lim
		for _ in range(40):
			mid = (good + bad) / 2
			if same(mid):
				good = mid
			else:
				bad = mid
		return good
	return {"low": edge(0.0), "high": edge(max_factor), "current": m0}


def monte_carlo(products, resources, sd_pct, n=300, seed=12345, integer=False):
	"""Margins and resource availability vary independently (normal, sd = sd_pct % of the value); every draw is re-optimised.
	Returns percentiles of the best total margin, how often each product is in the plan, and the cost of NOT re-planning: in the draws
	where the base plan is still possible with the drawn resources, the average and smallest `regret` = (re-optimised) - (base plan kept)."""
	rnd = random.Random(seed)
	sd = num(sd_pct) / 100.0
	base = mix.solve(products, resources, integer=integer)
	if base["status"] != "optimal":
		return {"status": base["status"], "verified": True}
	objs, appear, regrets = [], {p["code"]: 0 for p in products}, []
	ok = 0
	for _ in range(int(n)):
		ps = copy.deepcopy(products)
		for p in ps:
			p["margin"] = num(p["margin"]) * rnd.gauss(1, sd)
		rs = {k: max(num(v) * rnd.gauss(1, sd), 0.0) for k, v in resources.items()}
		r = mix.solve(ps, rs, integer=integer)
		if r["status"] != "optimal":
			continue
		ok += 1
		objs.append(r["objective"])
		for c, q in r["quantities"].items():
			if q > 1e-9:
				appear[c] += 1
		if all(sum(num(p.get("usage", {}).get(k)) * base["quantities"][p["code"]] for p in ps) <= rs[k] + 1e-9 for k in rs):
			regrets.append(r["objective"] - sum(p["margin"] * base["quantities"][p["code"]] for p in ps))
	if not objs:
		return {"status": "failed", "verified": True}
	objs.sort()
	q = lambda x: objs[min(int(x * len(objs)), len(objs) - 1)]
	return {"status": "optimal", "base_objective": base["objective"], "p5": q(0.05), "p50": q(0.5), "p95": q(0.95), "mean": sum(objs) / len(objs), "draws": ok, "seed": seed,
		"appear_pct": {c: v / ok * 100 for c, v in appear.items()}, "keep_plan_possible_pct": len(regrets) / ok * 100,
		"avg_regret": sum(regrets) / len(regrets) if regrets else None, "min_regret": min(regrets) if regrets else None,
		"verified": all(objs[i] <= objs[i + 1] for i in range(len(objs) - 1)) and ok == len(objs) and (not regrets or min(regrets) >= -1e-6)}
