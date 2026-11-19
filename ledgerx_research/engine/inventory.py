"""Inventory decisions: EOQ (also with price breaks), safety stock, reorder point, ABC classes, min-max."""
import math
from statistics import NormalDist

from .common import num


def eoq(annual_demand, order_cost, holding_cost_per_unit):
	"""Wilson formula: Q* = sqrt(2 D S / H). Returns 0 when any input is not positive."""
	d, s, h = num(annual_demand), num(order_cost), num(holding_cost_per_unit)
	if d <= 0 or s <= 0 or h <= 0:
		return 0.0
	return math.sqrt(2 * d * s / h)


def annual_cost(q, annual_demand, order_cost, holding_cost_per_unit, unit_price=0.0):
	q = num(q)
	if q <= 0:
		return float("inf")
	d = num(annual_demand)
	return d / q * num(order_cost) + q / 2 * num(holding_cost_per_unit) + d * num(unit_price)


def eoq_price_breaks(annual_demand, order_cost, holding_rate, breaks):
	"""All-units discount. breaks: [(min_qty, unit_price)] ascending. Holding cost = holding_rate * price.
	Checks each break (its EOQ if feasible in the band, else the band's lower edge) and returns the cheapest."""
	best = None
	bs = sorted((num(a), num(b)) for a, b in breaks)
	for i, (lo, price) in enumerate(bs):
		hi = bs[i + 1][0] if i + 1 < len(bs) else float("inf")
		q = eoq(annual_demand, order_cost, holding_rate * price)
		if q < lo:
			q = lo
		if q >= hi:
			continue  # this band's best point is not reachable inside it (cheaper in the next band)
		cost = annual_cost(q, annual_demand, order_cost, holding_rate * price, price)
		if best is None or cost < best["total_cost"] - 1e-9:
			best = {"quantity": q, "unit_price": price, "total_cost": cost}
	return best


def z_for_service(level):
	level = min(max(num(level), 0.5), 0.9999)
	return NormalDist().inv_cdf(level)


def safety_stock(service_level, daily_demand_sd, lead_time_days, daily_demand_mean=0.0, lead_time_sd_days=0.0):
	"""z * sqrt(L * sd_d^2 + mean_d^2 * sd_L^2): demand and lead-time variability together."""
	var = num(lead_time_days) * num(daily_demand_sd) ** 2 + num(daily_demand_mean) ** 2 * num(lead_time_sd_days) ** 2
	return z_for_service(service_level) * math.sqrt(max(var, 0.0))


def reorder_point(daily_demand_mean, lead_time_days, safety):
	return num(daily_demand_mean) * num(lead_time_days) + num(safety)


def abc_classes(values, a_share=0.8, b_share=0.95):
	"""values: {item: annual_value}. Classes by cumulative share of the total (A up to 80%, B up to 95%)."""
	items = sorted(((k, max(num(v), 0.0)) for k, v in values.items()), key=lambda kv: (-kv[1], str(kv[0])))
	total = sum(v for _k, v in items)
	out, cum = {}, 0.0
	for k, v in items:
		before = cum / total if total else 1.0
		cum += v
		out[k] = "A" if before < a_share else ("B" if before < b_share else "C")
	return out


def min_max(daily_mean, lead_time_days, review_days, safety, max_days_cover=None):
	"""Order-up-to level for periodic review: S = mean * (L + R) + safety."""
	s = num(daily_mean) * (num(lead_time_days) + num(review_days)) + num(safety)
	return {"min": reorder_point(daily_mean, lead_time_days, safety), "max": s if max_days_cover is None else min(s, num(daily_mean) * num(max_days_cover))}


def plan_item(annual_demand, daily_sd, lead_time_days, order_cost, unit_price, holding_rate, service_level, on_hand=0.0, on_order=0.0, moq=0.0, pack=0.0):
	"""One item's full recommendation, with the assumptions the caller must show next to it."""
	h = num(unit_price) * num(holding_rate)
	q = eoq(annual_demand, order_cost, h)
	if num(moq) > 0:
		q = max(q, num(moq))
	if num(pack) > 0 and q > 0:
		q = math.ceil(q / num(pack)) * num(pack)
	mean = num(annual_demand) / 365.0
	ss = safety_stock(service_level, daily_sd, lead_time_days)
	rop = reorder_point(mean, lead_time_days, ss)
	position = num(on_hand) + num(on_order)
	order_now = position <= rop and q > 0
	# (s, Q) policy: order whole lots of Q, enough lots to lift the position back above the reorder point.
	lots = max(1, math.ceil((rop - position) / q)) if order_now else 0
	if order_now and position + lots * q <= rop:
		lots += 1
	return {"eoq": q, "safety_stock": ss, "reorder_point": rop, "inventory_position": position, "order_now": order_now, "order_qty": lots * q if order_now else 0.0,
		"annual_cost": annual_cost(q, annual_demand, order_cost, h, unit_price) if q else 0.0, "days_cover": position / mean if mean else None}
