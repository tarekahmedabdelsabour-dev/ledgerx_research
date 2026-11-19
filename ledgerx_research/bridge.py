"""Pure translation layer between plan documents (plain dict rows) and the verified solvers.

No database access here, so everything in this file is unit-tested. Each `run_*` takes plain rows and returns
{"status", "verified", "warnings", ...rows to write back}. The documents only copy these values into fields.
"""
import json
import math
from datetime import datetime, timedelta

try:
	from frappe import _
except Exception:  # unit tests run without frappe
	def _(s):
		return s

from .engine import forecast as fc
from .engine import inventory as inv
from .engine import mix as mixmod
from .engine import procure
from .engine import schedule as sch
from .engine import transport as tr
from .engine.common import num

SOLVED, INFEASIBLE, ATTENTION = "Solved", "Infeasible", "Needs Attention"


def _status(ok_status, verified, warnings):
	if not ok_status:
		return INFEASIBLE
	if not verified:
		return ATTENTION
	return ATTENTION if warnings else SOLVED


def demand_stats(daily, lookback_days):
	"""daily: {date_str 'YYYY-MM-DD': qty consumed}. Returns yearly demand, daily mean and sd over the whole look-back
	(days without movement count as zero) and the monthly series (oldest first)."""
	n = max(int(lookback_days), 1)
	tot = sum(daily.values())
	mean = tot / n
	var = max(sum(v * v for v in daily.values()) / n - mean * mean, 0.0)
	months = {}
	for d, q in daily.items():
		months[d[:7]] = months.get(d[:7], 0.0) + q
	series = [months[k] for k in sorted(months)]
	return {"annual_demand": mean * 365.0, "daily_mean": mean, "daily_sd": math.sqrt(var), "monthly": series}


# --------------------------------------------------------------------------- product mix
def run_mix(products, resources, integer=False):
	"""products: [{item_code, price, unit_cost, min_qty, max_qty (0 = no limit), usage: {resource: per unit}}]
	resources: [{resource, available}]"""
	warnings = []
	notes = []  # informational warnings: shown, but they do not change the status
	res = {}
	for r in resources:
		res[r["resource"]] = res.get(r["resource"], 0.0) + num(r.get("available"))
	prods = []
	for p in products:
		usage = p.get("usage") or {}
		margin = num(p.get("price")) - num(p.get("unit_cost"))
		if margin <= 0:
			msg = _("{0}: margin is not positive, so it will not be produced.").format(p["item_code"])
			warnings.append(msg)
			notes.append(msg)
		missing = [k for k in usage if k not in res]
		if missing:
			warnings.append(_("{0} uses {1} which is not in the resource list, so it is treated as unlimited.").format(p["item_code"], ", ".join(missing[:3])))
		mx = num(p.get("max_qty"))
		prods.append({"code": p["item_code"], "margin": margin, "usage": usage, "min_qty": num(p.get("min_qty")), "max_qty": mx if mx > 0 else None})
	out = mixmod.solve(prods, res, integer=integer)
	if out["status"] == "optimal":
		for p in prods:
			if p["max_qty"] is None and not any(num(v) > 0 for v in p["usage"].values()) and p["margin"] > 0:
				return {"status": ATTENTION, "verified": False, "warnings": [_("{0} has no resource use and no demand limit: the plan has no upper end.").format(p["code"])], "solution": out}
	ok = out["status"] == "optimal"
	if not ok:
		warnings.append({"infeasible": _("The minimum quantities cannot be met with the available resources."),
			"unbounded": _("A product has no limit at all: add a demand limit or a resource it uses.")}.get(out["status"], _("The solver could not finish.")))
	return {"status": _status(ok, out.get("verified"), [w for w in warnings if not any(w is n for n in notes)]), "verified": bool(out.get("verified")), "warnings": warnings,
		"objective": out.get("objective", 0.0), "quantities": out.get("quantities", {}), "usage": out.get("usage", {}), "slack": out.get("slack", {}),
		"shadow": out.get("shadow_price", {}), "solution": out}


# --------------------------------------------------------------------------- reorder
def run_reorder(items, p):
	"""items: [{item_code, annual_demand, daily_sd, lead_days, unit_cost, on_hand, on_order, moq, monthly: [..]}]
	p: {service_level_pct, holding_rate_pct, order_cost, default_lead_days}"""
	warnings = []
	values = {i["item_code"]: num(i["annual_demand"]) * num(i["unit_cost"]) for i in items}
	abc = inv.abc_classes(values) if items else {}
	rows = []
	for i in items:
		lead = num(i.get("lead_days")) or num(p.get("default_lead_days"))
		if not num(i.get("lead_days")):
			warnings.append(_("{0}: no lead time on the item, used {1} days.").format(i["item_code"], int(lead)))
		if num(i.get("unit_cost")) <= 0:
			warnings.append(_("{0}: no cost, so the economic quantity cannot be computed.").format(i["item_code"]))
		plan = inv.plan_item(i["annual_demand"], i["daily_sd"], lead, p["order_cost"], i["unit_cost"], num(p["holding_rate_pct"]) / 100.0,
			num(p["service_level_pct"]) / 100.0, i.get("on_hand", 0), i.get("on_order", 0), i.get("moq", 0))
		f = fc.forecast(i.get("monthly") or [], 1) if i.get("monthly") else None
		rows.append({"item_code": i["item_code"], "abc": abc.get(i["item_code"], ""), "eoq": plan["eoq"], "safety_stock": plan["safety_stock"], "reorder_point": plan["reorder_point"],
			"order_qty": plan["order_qty"], "lead_days": lead, "forecast_method": (f or {}).get("method", ""), "forecast_next": ((f or {}).get("forecast") or [0.0])[0] if f else 0.0,
			"warning": (f or {}).get("warning")})
		if f and f.get("warning"):
			warnings.append(_("{0}: {1}").format(i["item_code"], _(f["warning"])))
	return {"status": _status(True, True, []), "verified": True, "warnings": warnings, "rows": rows}


# --------------------------------------------------------------------------- distribution
def run_distribution(sources, dests, lanes, cost_per_km, allow_shortage=True):
	warnings = []
	lane_cost, blocked = {}, set()
	for ln in lanes:
		key = (ln["source"], ln["destination"])
		if ln.get("blocked"):
			blocked.add(key)
		elif ln.get("unit_cost") not in (None, ""):
			lane_cost[key] = num(ln["unit_cost"])
	supply = {s["location"]: num(s["qty"]) for s in sources}
	demand = {d["location"]: num(d["demand"]) for d in dests}
	cost = {}
	for s in sources:
		for d in dests:
			key = (s["location"], d["location"])
			if key in blocked or s["location"] == d["location"]:
				continue
			if key in lane_cost:
				cost[key] = lane_cost[key]
			elif all(v not in (None, 0, "") for v in (s.get("lat"), s.get("lng"), d.get("lat"), d.get("lng"))):
				cost[key] = tr.haversine((s["lat"], s["lng"]), (d["lat"], d["lng"])) * num(cost_per_km)
			else:
				warnings.append(_("No cost and no location for {0} -> {1}: this lane is not used.").format(s["location"], d["location"]))
	out = tr.transportation(supply, demand, cost, allow_shortage=allow_shortage)
	ok = out["status"] == "optimal"
	if not ok:
		warnings.append(_("No plan can serve the demand with the allowed lanes.") if out["status"] == "infeasible" else _("The solver could not finish."))
	flows = [{"source": s, "destination": d, "qty": q, "unit_cost": cost[(s, d)], "amount": q * cost[(s, d)]} for (s, d), q in sorted(out.get("flows", {}).items())]
	short = out.get("shortage") or {}
	for d, q in short.items():
		warnings.append(_("{0}: {1} cannot be supplied.").format(d, f"{q:g}"))
	return {"status": _status(ok, out.get("verified"), warnings), "verified": bool(out.get("verified")), "warnings": warnings, "flows": flows,
		"total_cost": out.get("total_cost", 0.0), "shortage": short}


# --------------------------------------------------------------------------- routes
def run_routes(depot, stops, capacity, vehicles=0):
	"""depot: (lat, lng); stops: [{stop, lat, lng, demand}]"""
	warnings = []
	good = []
	for s in stops:
		if not num(s.get("lat")) and not num(s.get("lng")):
			warnings.append(_("{0}: no location, left out.").format(s["stop"]))
		else:
			good.append({"id": s["stop"], "lat": num(s["lat"]), "lng": num(s["lng"]), "demand": num(s.get("demand"))})
	if not good:
		return {"status": INFEASIBLE, "verified": True, "warnings": warnings + [_("No stop has a location.")], "legs": []}
	out = tr.routes(depot, good, num(capacity), int(vehicles) or None)
	if out["status"] == "infeasible":
		reason = {"demand_exceeds_capacity": _("One stop needs more than a vehicle can carry: {0}").format(", ".join(map(str, out.get("stops", [])))),
			"not_enough_vehicles": _("{0} vehicles are needed.").format(out.get("needed"))}.get(out.get("reason"), _("No plan found."))
		return {"status": INFEASIBLE, "verified": True, "warnings": warnings + [reason], "legs": []}
	legs = []
	for k, r in enumerate(out["routes"], 1):
		for seq, sid in enumerate(r["stops"], 1):
			legs.append({"route_no": k, "sequence": seq, "stop": sid, "route_load": r["load"], "route_km": r["km"]})
		if not r["exact_order"]:
			warnings.append(_("Route {0} has more than 12 stops: its stop order is improved but not proven the shortest.").format(k))
	real = list(warnings)
	warnings.append(_("Distances are straight-line (as the crow flies), not road distances."))
	return {"status": _status(True, out.get("verified"), real), "verified": bool(out.get("verified")), "warnings": warnings, "legs": legs, "total_km": out["total_km"],
		"lower_bound_km": out["lower_bound_km"], "gap_pct": out["gap_pct"], "vehicles_used": out["vehicles_used"]}


# --------------------------------------------------------------------------- schedule
def _to_dt(v):
	if isinstance(v, datetime):
		return v
	return datetime.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S") if len(str(v)) > 10 else datetime.strptime(str(v)[:10], "%Y-%m-%d")


def clock(start_at, hours, hours_per_day):
	"""Working hours from the start -> calendar datetime (working day = hours_per_day hours, days are consecutive)."""
	hpd = max(num(hours_per_day), 0.5)
	day = int(hours // hpd + 1e-9)
	rest = hours - day * hpd
	return _to_dt(start_at) + timedelta(days=day, hours=rest)


def run_schedule(ops, start_at, hours_per_day, objective):
	"""ops: [{work_order, operation, workstation, sequence, hours, due_date}]"""
	warnings = []
	start = _to_dt(start_at)
	byo = {}
	for o in ops:
		byo.setdefault(o["work_order"], []).append(o)
	orders = []
	for wo, lst in byo.items():
		lst.sort(key=lambda r: num(r.get("sequence")))
		rows = []
		for o in lst:
			if not o.get("workstation"):
				warnings.append(_("{0} / {1}: no workstation, left out.").format(wo, o.get("operation")))
				continue
			if num(o.get("hours")) <= 0:
				continue
			rows.append((o["workstation"], num(o["hours"])))
		if not rows:
			continue
		due = lst[0].get("due_date")
		d = None
		if due:
			days = (_to_dt(due) - start).total_seconds() / 86400.0
			d = max(days, 0.0) * num(hours_per_day)
		orders.append({"id": wo, "ops": rows, "due": d})
	if not orders:
		return {"status": INFEASIBLE, "verified": True, "warnings": warnings + [_("Nothing to schedule.")], "rows": []}
	late = objective.lower().startswith("total")
	s = sch.job_shop(orders, objective="total_tardiness" if late else "makespan")
	rows = []
	for r in sorted(s["ops"], key=lambda r: (r["start"], str(r["order"]))):
		src = [o for o in byo[r["order"]] if o.get("workstation")]
		src = [o for o in sorted(src, key=lambda r2: num(r2.get("sequence"))) if num(o.get("hours")) > 0]
		rows.append({"work_order": r["order"], "operation": src[r["op"]].get("operation", ""), "workstation": r["machine"],
			"start_at": clock(start, r["start"], hours_per_day), "end_at": clock(start, r["end"], hours_per_day)})
	if s["gap_pct"] > 15:
		warnings.append(_("The schedule is {0}% above the theoretical minimum; the real optimum lies between the two.").format(f"{s['gap_pct']:.0f}"))
	real = list(warnings)
	warnings.append(_("Working days are counted as consecutive calendar days: weekends and holidays are not skipped."))
	return {"status": _status(True, s["verified"], real), "verified": bool(s["verified"]), "warnings": warnings, "rows": rows, "makespan_hours": s["makespan"],
		"lower_bound_hours": s["lower_bound"], "gap_pct": s["gap_pct"], "rule": s["rule"], "total_lateness_hours": s["total_tardiness"]}


# --------------------------------------------------------------------------- supplier allocation
def run_allocation(needs, offers, max_share_pct=0, max_lead_days=0, min_quality_pct=0, budget=0, setup_cost=0):
	warnings = []
	demand = {}
	for n in needs:
		demand[n["item_code"]] = demand.get(n["item_code"], 0.0) + num(n["qty"])
	offs = [{"supplier": o["supplier"], "item": o["item_code"], "price": num(o["price"]), "capacity": (num(o.get("capacity")) or None), "moq": num(o.get("moq")),
		"lead_days": num(o.get("lead_days")), "quality": (num(o.get("quality")) or None)} for o in offers]
	suppliers = {o["supplier"] for o in offs}
	fixed = {s: num(setup_cost) for s in suppliers} if num(setup_cost) else None
	out = procure.allocate(demand, offs, max_share=(num(max_share_pct) / 100.0 or None), max_lead_days=(num(max_lead_days) or None),
		min_quality=(num(min_quality_pct) or None), budget=(num(budget) or None), fixed_cost=fixed)
	ok = out["status"] == "optimal"
	if not ok:
		warnings.append({"no_offer": _("No offer fits the limits for {0}.").format(out.get("item"))}.get(out.get("reason"), _("No allocation satisfies every limit: relax a limit or add offers.")))
	res = {"status": _status(ok, out.get("verified"), warnings), "verified": bool(out.get("verified")), "warnings": warnings, "allocation": out.get("allocation", []),
		"total_cost": out.get("total_cost", 0.0)}
	if ok and len(res["allocation"]) and len({a["supplier"] for a in res["allocation"]}) == 1 and len(suppliers) > 1:
		sole = res["allocation"][0]["supplier"]
		alt = procure.what_if_without(demand, offs, sole, max_share=(num(max_share_pct) / 100.0 or None), max_lead_days=(num(max_lead_days) or None),
			min_quality=(num(min_quality_pct) or None), fixed_cost=fixed)
		if alt["feasible"]:
			warnings.append(_("All the quantity goes to {0}. If it cannot deliver, the next best plan costs {1} more.").format(sole, f"{alt['extra_cost']:,.2f}"))
		else:
			warnings.append(_("All the quantity goes to {0} and no other supplier can replace it under the same limits.").format(sole))
	return res


def html_summary(title, verified, lines, warnings):
	"""Small HTML block shown at the top of every plan: result, proof flag and the assumptions."""
	from html import escape
	if verified:
		tag = "<b>&#10003; " + escape(_("verified")) + "</b> " + escape(_("(re-checked by separate code)"))
	else:
		tag = "<b>" + escape(_("NOT VERIFIED")) + "</b>"
	body = "".join(f"<li>{escape(str(x))}</li>" for x in lines)
	warn = "".join(f"<li>{escape(str(x))}</li>" for x in warnings[:40])
	more = f"<li>… +{len(warnings) - 40}</li>" if len(warnings) > 40 else ""
	return (f"<div><b>{escape(title)}</b> &nbsp; {tag}</div><ul>{body}</ul>"
		+ (f"<div><b>{escape(_('Read before using'))}</b></div><ul>{warn}{more}</ul>" if warnings else ""))


def loads(s):
	try:
		return json.loads(s) if s else {}
	except ValueError:
		return {}
