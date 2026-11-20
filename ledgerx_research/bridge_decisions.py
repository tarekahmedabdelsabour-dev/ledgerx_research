"""Break-even, what-if and risk, investment, make-or-buy, lease-or-buy, profitability, pricing and decision review.

Pure functions (no database) like bridge.py: plain rows in, plain values out, every answer carries `verified` and `warnings`.
"""
from .bridge import ATTENTION, INFEASIBLE, SOLVED, _, _status
from .engine import accuracy as ac
from .engine import breakeven as be
from .engine import invest as iv
from .engine import mix as mixmod
from .engine import profit as pf
from .engine import sensitivity as sn
from .engine.common import num


def _fmt(v, nd=2):
	return f"{num(v):,.{nd}f}"


# --------------------------------------------------------------------------- break-even
def run_breakeven(products, fixed_rows, target_profit=0, capacity=0, risk_sd_pct=0):
	"""products: [{item_code, price, variable_cost, qty}] (qty = expected sales in the period, it also gives the mix);
	fixed_rows: [{name, amount, is_cash}] for the same period."""
	warnings, info = [], []
	prods = []
	for p in products:
		price, vc = num(p.get("price")), num(p.get("variable_cost"))
		if vc <= 0:
			warnings.append(_("{0}: no variable cost found, so its contribution may look better than it is.").format(p["item_code"]))
		if price <= vc:
			warnings.append(_("{0}: the price does not cover the variable cost.").format(p["item_code"]))
		prods.append({"code": p["item_code"], "price": price, "variable_cost": vc, "qty": num(p.get("qty"))})
	if not prods:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Add at least one product.")]}
	fixed = sum(num(r.get("amount")) for r in fixed_rows)
	cash = sum(num(r.get("amount")) for r in fixed_rows if r.get("is_cash"))
	if fixed <= 0:
		warnings.append(_("No fixed costs entered: every sale is profit, so the break-even is zero."))
	if sum(p["qty"] for p in prods) <= 0:
		warnings.append(_("No expected quantities: the mix between products is assumed equal."))
	out = be.break_even(prods, fixed, target_profit=num(target_profit), capacity=num(capacity) or None, cash_fixed=cash if any(r.get("is_cash") for r in fixed_rows) else None)
	if out["status"] == "never":
		warnings.append(_("At this price and cost mix every unit loses money: no volume breaks even."))
		return {"status": INFEASIBLE, "verified": True, "warnings": warnings}
	if out.get("reachable") is False:
		info.append(_("The volume needed for the target is above the capacity."))
	if out.get("expected_profit") is not None and out["expected_profit"] < 0:
		info.append(_("At the expected sales the period makes a loss."))
	sens = be.sensitivity(prods, fixed, out.get("expected_units"))
	res = {"verified": bool(out["verified"]), "fixed": fixed, "cash_fixed": cash, "out": out, "per_product": out["per_product"], "sensitivity": sens}
	if num(risk_sd_pct) > 0 and out.get("expected_units"):
		res["risk"] = be.risk(prods, fixed, out["expected_units"], num(risk_sd_pct))
		info.append(_("Risk simulation: prices, costs and volume vary by about {0}% (normal spread), 2000 trials, fixed seed so the same input gives the same answer.").format(_fmt(risk_sd_pct, 0)))
	res["status"] = _status(True, res["verified"], warnings)
	res["warnings"] = warnings + info
	return res


# --------------------------------------------------------------------------- mix sensitivity and risk
def run_mix_sensitivity(products, resources, scenarios, integer=False, max_ranges=30):
	"""products/resources as for run_mix (rows from the plan); scenarios: [{name, kind, key, pct}] (one change each; same name = one scenario)."""
	prods = [{"code": p["item_code"], "margin": num(p["price"]) - num(p["unit_cost"]), "usage": p.get("usage") or {}, "min_qty": num(p.get("min_qty")),
		"max_qty": (num(p.get("max_qty")) or None)} for p in products]
	res = {}
	for r in resources:
		res[r["resource"]] = res.get(r["resource"], 0.0) + num(r.get("available"))
	warnings, info = [], []
	base = mixmod.solve(prods, res, integer=integer)
	if base["status"] != "optimal":
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Solve the plan first: it has no valid solution.")]}
	grouped = {}
	for sc in scenarios:
		grouped.setdefault(sc["name"], []).append({"kind": sc["kind"], "key": sc["key"], "pct": num(sc["pct"])})
	bad = []
	for name, ch in grouped.items():
		for c in ch:
			known = res if c["kind"] == "resource" else [p["code"] for p in prods]
			if c["key"] not in known:
				bad.append(f"{name}: {c['key']}")
	if bad:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Scenario refers to something that is not in the plan: {0}").format(", ".join(bad))]}
	cmp_ = sn.compare(prods, res, [{"name": n, "changes": c} for n, c in grouped.items()], integer=integer) if grouped else {"rows": []}
	rows = []
	for r in cmp_["rows"]:
		rows.append({"scenario": r["name"], "status": r["status"], "total_margin": r["objective"] or 0.0, "change": r["delta"] or 0.0, "moved": ", ".join(r["moved"]), "verified": r["verified"]})
		if r["status"] != "optimal":
			warnings.append(_("Scenario {0} has no valid plan (a minimum quantity cannot be met).").format(r["name"]))
	resource_ranges, margin_ranges = {}, {}
	if not integer:
		binding = [k for k in res if base["shadow_price"].get(k, 0) > 1e-9][:max_ranges]
		for k in binding:
			rr = sn.resource_range(prods, res, k)
			if rr:
				resource_ranges[k] = {"low": round(rr["low"], 4), "high": round(rr["high"], 4)}
		inplan = [p["code"] for p in prods if base["quantities"].get(p["code"], 0) > 1e-9][:max_ranges]
		for c in inplan:
			mr = sn.margin_range(prods, res, c)
			if mr:
				margin_ranges[c] = {"low": round(mr["low"], 4), "high": round(mr["high"], 4)}
		if len([k for k in res if base["shadow_price"].get(k, 0) > 1e-9]) > max_ranges or len([p for p in prods if base["quantities"].get(p["code"], 0) > 1e-9]) > max_ranges:
			info.append(_("Ranges are shown for the first {0} only.").format(max_ranges))
	else:
		info.append(_("Whole-unit plan: ranges are not shown (they exist only for the continuous plan)."))
	ok = all(r["verified"] for r in rows) and base.get("verified", False)
	return {"status": _status(True, ok, warnings), "verified": ok, "warnings": warnings + info, "rows": rows,
		"resource_ranges": resource_ranges, "margin_ranges": margin_ranges, "base_objective": base["objective"]}


def run_mix_risk(products, resources, sd_pct, draws=300, integer=False):
	prods = [{"code": p["item_code"], "margin": num(p["price"]) - num(p["unit_cost"]), "usage": p.get("usage") or {}, "min_qty": num(p.get("min_qty")),
		"max_qty": (num(p.get("max_qty")) or None)} for p in products]
	res = {}
	for r in resources:
		res[r["resource"]] = res.get(r["resource"], 0.0) + num(r.get("available"))
	if num(sd_pct) <= 0:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Enter how much the numbers can vary (%).")]}
	out = sn.monte_carlo(prods, res, num(sd_pct), n=min(int(draws or 300), 2000), integer=integer)
	if out["status"] != "optimal":
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Solve the plan first: it has no valid solution.")]}
	warnings = [_("Margins and available resources each vary by about {0}% (normal spread) in {1} draws; every draw is solved again from scratch. Fixed seed: the same input gives the same answer.").format(_fmt(sd_pct, 0), out["draws"])]
	if out["keep_plan_possible_pct"] < 100:
		warnings.append(_("In {0}% of the draws the current plan would no longer fit the resources: re-plan when availability drops.").format(_fmt(100 - out["keep_plan_possible_pct"], 0)))
	return {"status": SOLVED if out["verified"] else ATTENTION, "verified": out["verified"], "warnings": warnings, **{k: out[k] for k in ("base_objective", "p5", "p50", "p95", "mean", "draws", "appear_pct", "keep_plan_possible_pct", "avg_regret")}}


# --------------------------------------------------------------------------- investment
def run_investment(cashflows, rate_pct, risk_sd_pct=0):
	"""cashflows: [{year, amount}] (year 0 = now)."""
	by = {}
	for c in cashflows:
		by[int(num(c["year"]))] = by.get(int(num(c["year"])), 0.0) + num(c["amount"])
	if not by:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Add the cash flows.")]}
	last = max(by)
	cfs = [by.get(t, 0.0) for t in range(last + 1)]
	warnings, info = [], []
	if cfs[0] >= 0:
		warnings.append(_("Year 0 is not an outflow: check the signs (money out is negative)."))
	missing = [t for t in range(last + 1) if t not in by]
	if missing:
		info.append(_("Years without a cash flow are counted as zero: {0}").format(", ".join(map(str, missing[:10]))))
	out = iv.analyse(cfs, num(rate_pct) / 100.0, risk_sd_pct=num(risk_sd_pct))
	if out["multiple_irr"]:
		info.append(_("The cash flows change sign more than once, so there are several internal rates of return: rely on the net present value."))
	if out["irr"] is None:
		info.append(_("No internal rate of return exists for these cash flows."))
	if out["payback_years"] is None:
		info.append(_("The investment is not paid back within the years entered."))
	if num(risk_sd_pct) > 0:
		info.append(_("Risk simulation: each future cash flow varies by about {0}% (normal spread), 2000 trials, fixed seed.").format(_fmt(risk_sd_pct, 0)))
	out["status"] = _status(True, out["verified"], warnings)
	out["warnings"] = warnings + info
	return out


def run_make_or_buy(volume, make_fixed, make_variable, buy_fixed, buy_price):
	warnings, info = [], []
	if num(volume) <= 0:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Enter the yearly volume.")]}
	if num(buy_price) <= 0:
		warnings.append(_("No buying price: the buy option costs nothing."))
	if num(make_variable) <= 0:
		warnings.append(_("No making cost per unit: the make option is only its fixed cost."))
	out = iv.make_or_buy(volume, make_fixed, make_variable, buy_fixed, buy_price)
	if out["indifference_volume"] is None:
		info.append(_("One option is cheaper at every volume: there is no switching point."))
	out["status"] = _status(True, out["verified"], warnings)
	out["warnings"] = warnings + info
	return out


def run_lease_or_buy(price, residual, life_years, rate_pct, yearly_cost_own, lease_payment, lease_years=0, lease_cost_extra=0):
	out = iv.lease_or_buy(price, residual, life_years, rate_pct, yearly_cost_own, lease_payment, lease_years or None, lease_cost_extra)
	if out["status"] != "optimal":
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Enter the life of the asset in years.")]}
	warnings = [_("Payments are counted at the end of each year; tax effects and inflation are not included.")]
	out["warnings"] = warnings
	out["status"] = _status(True, out["verified"], [])
	return out


# --------------------------------------------------------------------------- profitability
def run_profitability(rows, group_label=""):
	warnings = []
	clean = []
	for r in rows:
		if num(r.get("revenue")) == 0 and num(r.get("cost")) == 0:
			continue
		if num(r.get("cost")) <= 0:
			warnings.append(_("{0}: no cost recorded on the sales, so its margin may be overstated.").format(r["name"]))
		clean.append(r)
	if not clean:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("No sales found in the period.")], "rows": []}
	out = pf.profitability(clean)
	out["status"] = _status(True, out["verified"], warnings)
	if out["losers"]:
		warnings.append(_("{0} lose money in this period.").format(len(out["losers"])))
	out["warnings"] = warnings
	return out


def run_stock_health(rows, slow_days, dead_days):
	if not rows:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("No stock found.")], "rows": []}
	out = pf.stock_health(rows, num(slow_days) or 90, num(dead_days) or 180)
	out["warnings"] = [_("A dead item had no movement for {0} days, a slow one for {1} days; overstocked means more than a year of demand on hand.").format(int(num(dead_days) or 180), int(num(slow_days) or 90))]
	out["status"] = SOLVED
	return out


# --------------------------------------------------------------------------- pricing
def run_pricing(cost, price, qty, elasticity, model="constant", min_price=0, max_price=0, capacity=0, discount_pct=0, estimate=None):
	warnings, info = [], []
	if num(elasticity) <= 0:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Enter the price elasticity (for example 1.5: a 1% higher price loses 1.5% of the volume).")]}
	if num(qty) <= 0 or num(price) <= 0:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("Enter the current price and quantity.")]}
	if num(cost) <= 0:
		warnings.append(_("No unit cost: the best price will look much too low."))
	if estimate is not None:
		if estimate.get("elasticity") is None:
			warnings.append(_("The elasticity could not be estimated from history ({0}): the value you entered is a guess.").format(estimate.get("reason", "")))
		elif not estimate.get("reliable"):
			warnings.append(_("The elasticity estimated from history is weak (R2 {0}): treat the answer as a guide.").format(_fmt(estimate.get("r2", 0), 2)))
	bp = pf.best_price(cost, price, qty, elasticity, model, min_price or None, max_price or None, capacity or None)
	if bp["status"] != "optimal":
		return {"status": INFEASIBLE, "verified": True, "warnings": warnings + [_("The inputs do not describe a valid demand.")]}
	if bp.get("reason") == "demand_not_elastic_enough":
		warnings.append(_("Demand is not elastic enough (elasticity {0} is not above 1): there is no profit-maximising price, the highest allowed price is shown.").format(_fmt(elasticity, 2)))
	elif bp.get("at_limit"):
		info.append(_("The best price is at the limit you set."))
	info.append(_("The elasticity is assumed constant around today's price: do not extend the answer far from it."))
	out = {"best": bp, "verified": bool(bp["verified"])}
	if num(discount_pct) > 0:
		out["discount"] = pf.discount_effect(price, cost, qty, discount_pct, elasticity)
		if out["discount"]["status"] != "optimal":
			warnings.append(_("A discount of {0}% removes the whole margin.").format(_fmt(discount_pct, 1)))
		else:
			out["verified"] = out["verified"] and out["discount"]["verified"]
	out["status"] = _status(True, out["verified"], warnings)
	out["warnings"] = warnings + info
	return out


# --------------------------------------------------------------------------- decision review
def run_review(rows):
	"""rows: [{plan, item, expected, actual, kind}] -> per-row error and the overall accuracy. kind groups the verdicts."""
	if not rows:
		return {"status": INFEASIBLE, "verified": True, "warnings": [_("No earlier plan is old enough to be checked yet.")], "rows": []}
	out_rows = []
	for r in rows:
		out_rows.append({**r, **ac.row_error(r["expected"], r["actual"])})
	overall = ac.errors([(r["expected"], r["actual"]) for r in rows])
	warnings = []
	if overall["verdict"] == "unreliable":
		warnings.append(_("These plans were far from what happened: check the data they were based on before trusting new ones."))
	elif overall["verdict"] == "usable":
		warnings.append(_("The plans were usable but off by a clear margin: keep a safety buffer."))
	if overall.get("bias") is not None and abs(overall["bias"]) > 10:
		warnings.append(_("The plans were consistently too high.") if overall["bias"] > 0 else _("The plans were consistently too low."))
	if overall["n"] < 5:
		warnings.append(_("Only {0} comparisons: the verdict is not yet solid.").format(overall["n"]))
	return {"status": _status(True, True, warnings if overall["verdict"] != "reliable" else []), "verified": True, "warnings": warnings, "rows": out_rows, "overall": overall}
