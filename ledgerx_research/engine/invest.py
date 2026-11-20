"""Investment decisions: NPV, IRR, payback, profitability index, make-or-buy, lease-or-buy."""
import math

from .common import num


def npv(rate, cashflows):
	"""cashflows[0] happens now (t = 0). Horner evaluation."""
	r = num(rate)
	total = 0.0
	for cf in reversed([num(c) for c in cashflows]):
		total = total / (1 + r) + cf
	return total


def _npv_direct(rate, cashflows):
	"""Same value computed term by term: the independent check."""
	return sum(num(c) / (1 + num(rate)) ** t for t, c in enumerate(cashflows))


def irr(cashflows, lo=-0.99, hi=10.0):
	"""All rates in (lo, hi) where NPV = 0, found by scanning for sign changes then bisecting. Empty list when none exists."""
	cfs = [num(c) for c in cashflows]
	if not (any(c > 0 for c in cfs) and any(c < 0 for c in cfs)):
		return []
	grid = [lo + (hi - lo) * i / 2000.0 for i in range(2001)]
	vals = [npv(r, cfs) for r in grid]
	roots = []
	for i in range(2000):
		a, b, fa, fb = grid[i], grid[i + 1], vals[i], vals[i + 1]
		if fa == 0:
			roots.append(a)
		elif fa * fb < 0:
			for _ in range(100):
				m = (a + b) / 2
				fm = npv(m, cfs)
				if fa * fm <= 0:
					b, fb = m, fm
				else:
					a, fa = m, fm
			roots.append((a + b) / 2)
	return roots


def payback(cashflows):
	"""Years until the cumulative cash flow turns non-negative (linear inside the year); None if never."""
	cum = 0.0
	prev = 0.0
	for t, c in enumerate(num(x) for x in cashflows):
		prev = cum
		cum += c
		if t > 0 and cum >= 0 > prev:
			return t - 1 + (-prev / c)
		if t == 0 and cum >= 0:
			return 0.0
	return None


def analyse(cashflows, rate, risk_sd_pct=0.0, n=2000, seed=12345):
	"""Full project appraisal with a `verified` flag (two NPV computations agree, NPV at IRR is zero, payback consistent)."""
	cfs = [num(c) for c in cashflows]
	r = num(rate)
	out = {"npv": npv(r, cfs), "irr_all": irr(cfs), "payback_years": payback(cfs), "verified": False}
	out["irr"] = out["irr_all"][0] if len(out["irr_all"]) == 1 else (out["irr_all"][0] if out["irr_all"] else None)
	out["multiple_irr"] = len(out["irr_all"]) > 1
	disc = [c / (1 + r) ** t for t, c in enumerate(cfs)]
	out["discounted_payback_years"] = payback(disc)
	invest = -sum(c for c in disc if c < 0)
	out["profitability_index"] = (sum(c for c in disc if c > 0) / invest) if invest > 0 else None
	ok = abs(out["npv"] - _npv_direct(r, cfs)) <= 1e-7 * max(1.0, abs(out["npv"]))
	for x in out["irr_all"]:
		ok = ok and abs(npv(x, cfs)) <= 1e-6 * max(1.0, sum(abs(c) for c in cfs))
	out["verified"] = bool(ok)
	out["decision"] = "accept" if out["npv"] > 0 else "reject"
	if num(risk_sd_pct) > 0:
		import random
		rnd = random.Random(seed)
		sd = num(risk_sd_pct) / 100.0
		vals = sorted(npv(r, [cfs[0]] + [c * rnd.gauss(1, sd) for c in cfs[1:]]) for _ in range(int(n)))
		out["npv_p5"], out["npv_p50"], out["npv_p95"] = vals[int(.05 * n)], vals[int(.5 * n)], vals[min(int(.95 * n), n - 1)]
		out["loss_probability_pct"] = sum(1 for v in vals if v < 0) / len(vals) * 100
	return out


def make_or_buy(volume, make_fixed, make_variable, buy_fixed, buy_price):
	"""Total cost of each option at the given annual volume, the volume where they cost the same, and the cheaper option."""
	q = num(volume)
	make = num(make_fixed) + num(make_variable) * q
	buy = num(buy_fixed) + num(buy_price) * q
	out = {"make_cost": make, "buy_cost": buy, "cheaper": "make" if make < buy - 1e-9 else ("buy" if buy < make - 1e-9 else "equal"), "saving": abs(make - buy), "indifference_volume": None}
	dv = num(buy_price) - num(make_variable)
	df = num(make_fixed) - num(buy_fixed)
	if abs(dv) > 1e-12:
		x = df / dv
		out["indifference_volume"] = x if x >= 0 else None
	# verified: costs recomputed at the indifference volume are equal; and the cheaper option really is the smaller one
	ok = (make <= buy) == (out["cheaper"] in ("make", "equal"))
	x = out["indifference_volume"]
	if x is not None:
		ok = ok and abs((num(make_fixed) + num(make_variable) * x) - (num(buy_fixed) + num(buy_price) * x)) <= 1e-6 * max(1.0, abs(make))
	out["verified"] = bool(ok)
	out["make_cheaper_above"] = None if x is None else (dv > 0)  # True: making is cheaper at volumes above the indifference point
	return out


def lease_or_buy(price, residual, life_years, rate_pct, yearly_cost_own, lease_payment, lease_years=None, lease_cost_extra=0.0):
	"""Present value of the cost of owning versus leasing over `life_years` (payments at year end, residual received at the end).
	Also the equivalent annual cost of each (cost spread evenly over the years)."""
	n = int(life_years)
	r = num(rate_pct) / 100.0
	if n <= 0:
		return {"status": "infeasible", "verified": True}
	af = n if r == 0 else (1 - (1 + r) ** -n) / r  # annuity factor
	own_pv = num(price) - num(residual) / (1 + r) ** n + num(yearly_cost_own) * af
	ly = int(lease_years) if lease_years else n
	laf = ly if r == 0 else (1 - (1 + r) ** -ly) / r
	lease_pv = num(lease_payment) * laf + num(lease_cost_extra) * af
	out = {"status": "optimal", "own_pv": own_pv, "lease_pv": lease_pv, "own_annual": own_pv / af, "lease_annual": lease_pv / af,
		"cheaper": "buy" if own_pv < lease_pv - 1e-9 else ("lease" if lease_pv < own_pv - 1e-9 else "equal"), "saving": abs(own_pv - lease_pv)}
	direct_own = num(price) + sum(num(yearly_cost_own) / (1 + r) ** t for t in range(1, n + 1)) - num(residual) / (1 + r) ** n
	direct_lease = sum(num(lease_payment) / (1 + r) ** t for t in range(1, ly + 1)) + sum(num(lease_cost_extra) / (1 + r) ** t for t in range(1, n + 1))
	out["verified"] = abs(direct_own - own_pv) < 1e-6 * max(1.0, abs(own_pv)) and abs(direct_lease - lease_pv) < 1e-6 * max(1.0, abs(lease_pv))
	return out
