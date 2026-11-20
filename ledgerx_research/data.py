"""Reads the business data the solvers need, and writes the draft documents. Nothing here decides anything: the
numbers go to `bridge.py` and the verified solvers. Every loader returns (rows, warnings)."""
import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

MAX_ITEMS = 500
CONSUMING_ENTRIES = ("Material Issue", "Manufacture", "Material Consumption for Manufacture", "Send to Subcontractor")


def company_warehouses(company, warehouse=None):
	if warehouse:
		if frappe.db.get_value("Warehouse", warehouse, "is_group"):
			lft, rgt = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"])
			return frappe.get_all("Warehouse", filters={"lft": [">=", lft], "rgt": ["<=", rgt], "is_group": 0}, pluck="name")
		return [warehouse]
	return frappe.get_all("Warehouse", filters={"company": company, "is_group": 0, "disabled": 0}, pluck="name")


def coords_of(link_doctype, link_name):
	"""Latitude/longitude from the first Address linked to the record that has them."""
	rows = frappe.db.sql(
		"""select a.lx_latitude, a.lx_longitude from `tabAddress` a join `tabDynamic Link` dl on dl.parent = a.name and dl.parenttype = 'Address'
		where dl.link_doctype = %s and dl.link_name = %s and ifnull(a.lx_latitude, 0) != 0 and ifnull(a.lx_longitude, 0) != 0
		order by a.is_shipping_address desc, a.is_primary_address desc limit 1""", (link_doctype, link_name))
	return (flt(rows[0][0]), flt(rows[0][1])) if rows else (0.0, 0.0)


def address_coords(address):
	if not address:
		return (0.0, 0.0)
	r = frappe.db.get_value("Address", address, ["lx_latitude", "lx_longitude"])
	return (flt(r[0]), flt(r[1])) if r else (0.0, 0.0)


# ----------------------------------------------------------------------------------- product mix
def _working_hours_per_day(workstation):
	rows = frappe.get_all("Workstation Working Hour", filters={"parent": workstation}, fields=["start_time", "end_time"])
	total = 0.0
	for r in rows:
		try:
			total += (r.end_time - r.start_time).total_seconds() / 3600.0
		except Exception:
			continue
	return total


def load_mix(company, planning_days, cap_by_orders):
	warnings = []
	demand = {}
	for r in frappe.db.sql(
		"""select soi.item_code, sum(soi.qty - soi.delivered_qty) q, sum(soi.base_net_amount) / nullif(sum(soi.qty), 0) rate
		from `tabSales Order Item` soi join `tabSales Order` so on so.name = soi.parent
		where so.docstatus = 1 and so.company = %s and so.status not in ('Closed', 'Completed', 'Cancelled', 'On Hold')
		group by soi.item_code having sum(soi.qty - soi.delivered_qty) > 0""", (company,), as_dict=True):
		demand[r.item_code] = (flt(r.q), flt(r.rate))
	boms = frappe.get_all("BOM", filters={"docstatus": 1, "is_active": 1, "is_default": 1, "company": company}, fields=["name", "item", "quantity", "total_cost"])
	products, uses, ws_names = [], {}, set()
	for b in boms:
		if cap_by_orders and b.item not in demand:
			continue
		qty = flt(b.quantity) or 1.0
		usage = {}
		expl = frappe.get_all("BOM Explosion Item", filters={"parent": b.name}, fields=["item_code", "stock_qty"])
		comps = expl or frappe.get_all("BOM Item", filters={"parent": b.name}, fields=["item_code", "stock_qty"])
		for c in comps:
			usage[c.item_code] = usage.get(c.item_code, 0.0) + flt(c.stock_qty) / qty
		for op in frappe.get_all("BOM Operation", filters={"parent": b.name}, fields=["operation", "workstation", "time_in_mins"]):
			ws = op.workstation or frappe.db.get_value("Operation", op.operation, "workstation")
			if not ws:
				warnings.append(_("{0}: operation {1} has no workstation, so its time is not limited.").format(b.item, op.operation))
				continue
			key = f"WS: {ws}"
			usage[key] = usage.get(key, 0.0) + flt(op.time_in_mins) / 60.0 / qty
			ws_names.add(ws)
		price = frappe.db.get_value("Item Price", {"item_code": b.item, "selling": 1}, "price_list_rate", order_by="valid_from desc") or 0
		if not price:
			price = frappe.db.get_value("Item", b.item, "standard_rate") or (demand.get(b.item) or (0, 0))[1]
		if not price:
			warnings.append(_("{0}: no selling price found: set one before trusting the plan.").format(b.item))
		products.append({"item_code": b.item, "bom_no": b.name, "price": flt(price), "unit_cost": flt(b.total_cost) / qty, "min_qty": 0,
			"max_qty": demand[b.item][0] if cap_by_orders and b.item in demand else 0, "usage": usage})
		uses[b.item] = usage
	if not products:
		warnings.append(_("No product with an active default BOM and open sales orders was found.") if cap_by_orders else _("No product with an active default BOM was found."))
	items = sorted({k for u in uses.values() for k in u if not k.startswith("WS: ")})
	resources = []
	if items:
		whs = company_warehouses(company)
		stock = defaultdict(float)
		if whs:
			for r in frappe.get_all("Bin", filters={"item_code": ["in", items], "warehouse": ["in", whs]}, fields=["item_code", "actual_qty"]):
				stock[r.item_code] += flt(r.actual_qty)
		for it in items:
			resources.append({"resource": it, "kind": "Material", "available": stock[it]})
	for ws in sorted(ws_names):
		hours = _working_hours_per_day(ws)
		if not hours:
			hours = 8.0
			warnings.append(_("{0}: no working hours set, 8 hours a day assumed.").format(ws))
		resources.append({"resource": f"WS: {ws}", "kind": "Workstation Hours", "available": hours * planning_days})
	warnings.append(_("Margin = selling price - BOM cost. Material available = stock on hand (incoming purchases are not counted). Edit any number before solving."))
	return products, resources, warnings


def make_production_plan(doc):
	rows = [r for r in doc.products if flt(r.plan_qty) > 0]
	if not rows:
		frappe.throw(_("The plan has no quantity to produce."))
	pp = frappe.new_doc("Production Plan")
	pp.company = doc.company
	pp.posting_date = nowdate()
	fg = frappe.db.get_single_value("Manufacturing Settings", "default_fg_warehouse")
	for r in rows:
		row = {"item_code": r.item_code, "bom_no": r.bom_no, "planned_qty": flt(r.plan_qty), "planned_start_date": nowdate()}
		if fg:
			row["warehouse"] = fg
		pp.append("po_items", row)
	pp.flags.ignore_mandatory = True
	pp.insert()
	return pp.name


# ----------------------------------------------------------------------------------- reorder
def load_reorder(company, warehouse, lookback_days, default_lead_days):
	from .bridge import demand_stats
	warnings = []
	whs = company_warehouses(company, warehouse)
	if not whs:
		return [], [_("No warehouse found.")]
	since = add_days(nowdate(), -int(lookback_days))
	ph = ", ".join(["%s"] * len(whs))
	rows = frappe.db.sql(
		f"""select sle.item_code, sle.posting_date d, sum(-sle.actual_qty) q from `tabStock Ledger Entry` sle
		where sle.is_cancelled = 0 and sle.actual_qty < 0 and sle.posting_date >= %s and sle.warehouse in ({ph})
		and (sle.voucher_type in ('Delivery Note', 'Sales Invoice') or (sle.voucher_type = 'Stock Entry' and sle.voucher_no in
		(select name from `tabStock Entry` where purpose in %s and docstatus = 1)))
		group by sle.item_code, sle.posting_date""", [since, *whs, CONSUMING_ENTRIES], as_dict=True)
	daily = defaultdict(dict)
	for r in rows:
		daily[r.item_code][str(r.d)] = flt(r.q)
	codes = sorted(daily, key=lambda c: -sum(daily[c].values()))
	if len(codes) > MAX_ITEMS:
		warnings.append(_("Only the {0} items with the highest movement are planned.").format(MAX_ITEMS))
		codes = codes[:MAX_ITEMS]
	if not codes:
		return [], [_("No stock movement in the chosen period.")]
	meta = {i.name: i for i in frappe.get_all("Item", filters={"name": ["in", codes], "disabled": 0}, fields=["name", "lead_time_days", "min_order_qty", "valuation_rate", "last_purchase_rate", "standard_rate"])}
	bins = defaultdict(lambda: [0.0, 0.0])
	for b in frappe.get_all("Bin", filters={"item_code": ["in", codes], "warehouse": ["in", whs]}, fields=["item_code", "actual_qty", "ordered_qty"]):
		bins[b.item_code][0] += flt(b.actual_qty)
		bins[b.item_code][1] += flt(b.ordered_qty)
	out = []
	for c in codes:
		m = meta.get(c)
		if not m:
			continue
		st = demand_stats(daily[c], lookback_days)
		cost = flt(m.valuation_rate) or flt(m.last_purchase_rate) or flt(m.standard_rate)
		out.append({"item_code": c, "annual_demand": st["annual_demand"], "daily_sd": st["daily_sd"], "lead_days": int(m.lead_time_days or 0), "unit_cost": cost,
			"on_hand": bins[c][0], "on_order": bins[c][1], "moq": flt(m.min_order_qty), "monthly": st["monthly"]})
	if int(lookback_days) < 180:
		warnings.append(_("Less than 6 months of history: forecasts and safety stock are rough."))
	return out, warnings


def make_material_request(doc, warehouse):
	rows = [r for r in doc.items if flt(r.order_qty) > 0]
	if not rows:
		frappe.throw(_("Nothing needs to be ordered now."))
	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Purchase"
	mr.company = doc.company
	mr.transaction_date = nowdate()
	for r in rows:
		mr.append("items", {"item_code": r.item_code, "qty": flt(r.order_qty), "schedule_date": add_days(nowdate(), int(r.lead_days or doc.default_lead_days or 0)),
			"warehouse": warehouse or frappe.db.get_value("Item Default", {"parent": r.item_code, "company": doc.company}, "default_warehouse")})
	mr.schedule_date = max(i.schedule_date for i in mr.items)
	mr.flags.ignore_mandatory = True
	mr.insert()
	return mr.name


# ----------------------------------------------------------------------------------- distribution
def load_distribution(company, item_code):
	warnings = []
	whs = company_warehouses(company)
	sources, dests = [], []
	for b in frappe.get_all("Bin", filters={"item_code": item_code, "warehouse": ["in", whs], "actual_qty": [">", 0]}, fields=["warehouse", "actual_qty"]):
		lat, lng = coords_of("Warehouse", b.warehouse)
		sources.append({"location": b.warehouse, "qty": flt(b.actual_qty), "lat": lat, "lng": lng})
	for r in frappe.db.sql(
		"""select mri.warehouse, sum(mri.qty - mri.ordered_qty) q from `tabMaterial Request Item` mri join `tabMaterial Request` mr on mr.name = mri.parent
		where mr.docstatus = 1 and mr.company = %s and mr.material_request_type = 'Material Transfer' and mr.status not in ('Stopped', 'Cancelled', 'Transferred', 'Received')
		and mri.item_code = %s and ifnull(mri.warehouse, '') != '' group by mri.warehouse having sum(mri.qty - mri.ordered_qty) > 0""", (company, item_code), as_dict=True):
		lat, lng = coords_of("Warehouse", r.warehouse)
		dests.append({"location": r.warehouse, "demand": flt(r.q), "lat": lat, "lng": lng})
	if not sources:
		warnings.append(_("No warehouse holds this item."))
	if not dests:
		warnings.append(_("No open transfer requests for this item: add destinations by hand."))
	if any(not (x["lat"] or x["lng"]) for x in sources + dests):
		warnings.append(_("Some warehouses have no latitude/longitude on a linked Address: give a lane cost for them or fill the coordinates."))
	return sources, dests, warnings


def make_stock_entry(doc):
	if not doc.item_code:
		frappe.throw(_("Choose the item first."))
	rows = [f for f in doc.flows if flt(f.qty) > 0 and frappe.db.exists("Warehouse", f.source) and frappe.db.exists("Warehouse", f.destination)]
	if not rows:
		frappe.throw(_("The plan has no flow between existing warehouses."))
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.purpose = "Material Transfer"
	se.company = doc.company
	for f in rows:
		se.append("items", {"item_code": doc.item_code, "qty": flt(f.qty), "s_warehouse": f.source, "t_warehouse": f.destination})
	se.flags.ignore_mandatory = True
	se.insert()
	return se.name


# ----------------------------------------------------------------------------------- routes
def load_routes(company):
	warnings = []
	rows = frappe.db.sql(
		"""select so.name, so.customer, so.customer_name, so.shipping_address_name, so.customer_address, sum(soi.qty - soi.delivered_qty) q
		from `tabSales Order` so join `tabSales Order Item` soi on soi.parent = so.name
		where so.docstatus = 1 and so.company = %s and so.status in ('To Deliver and Bill', 'To Deliver')
		group by so.name having sum(soi.qty - soi.delivered_qty) > 0 order by so.delivery_date""", (company,), as_dict=True)
	stops = []
	for r in rows:
		lat, lng = address_coords(r.shipping_address_name or r.customer_address)
		if not (lat or lng):
			lat, lng = coords_of("Customer", r.customer)
		stops.append({"stop": r.name, "customer": r.customer, "lat": lat, "lng": lng, "demand": flt(r.q)})
	if not rows:
		warnings.append(_("No sales order is waiting for delivery."))
	if any(not (s["lat"] or s["lng"]) for s in stops):
		warnings.append(_("Some customers have no latitude/longitude on their Address: they will be left out until you fill them."))
	return stops, warnings


# ----------------------------------------------------------------------------------- schedule
def load_schedule(company):
	warnings = []
	out = []
	wos = frappe.get_all("Work Order", filters={"docstatus": 1, "company": company, "status": ["in", ["Not Started", "In Process"]]},
		fields=["name", "qty", "planned_end_date", "expected_delivery_date"])
	for wo in wos:
		qty = flt(wo.qty) or 1.0
		for op in frappe.get_all("Work Order Operation", filters={"parent": wo.name}, fields=["operation", "workstation", "time_in_mins", "completed_qty", "idx", "status"], order_by="idx"):
			if op.status == "Completed":
				continue
			hours = flt(op.time_in_mins) / 60.0 * max(qty - flt(op.completed_qty), 0.0) / qty
			if hours <= 0:
				continue
			out.append({"work_order": wo.name, "operation": op.operation, "workstation": op.workstation, "sequence": op.idx, "hours": hours,
				"due_date": wo.expected_delivery_date or wo.planned_end_date})
	if not wos:
		warnings.append(_("No open work order."))
	warnings.append(_("Hours = operation time x remaining share of the order quantity. Each workstation does one job at a time."))
	return out, warnings


# ----------------------------------------------------------------------------------- supplier allocation
def load_allocation(company):
	warnings = []
	needs = frappe.db.sql(
		"""select mri.item_code, sum(mri.stock_qty - mri.ordered_qty * ifnull(mri.conversion_factor, 1)) q, max(mri.stock_uom) uom from `tabMaterial Request Item` mri
		join `tabMaterial Request` mr on mr.name = mri.parent where mr.docstatus = 1 and mr.company = %s and mr.material_request_type = 'Purchase'
		and mr.status in ('Pending', 'Partially Ordered') group by mri.item_code having sum(mri.stock_qty - mri.ordered_qty * ifnull(mri.conversion_factor, 1)) > 0""",
		(company,), as_dict=True)
	needs = [{"item_code": n.item_code, "qty": flt(n.q), "uom": n.uom} for n in needs]
	offers, currencies = {}, set()
	if needs:
		codes = [n["item_code"] for n in needs]
		prices = frappe.get_all("Item Price", filters={"item_code": ["in", codes], "buying": 1, "supplier": ["is", "set"]},
			fields=["supplier", "item_code", "price_list_rate", "currency", "valid_from", "valid_upto", "uom"], order_by="valid_from asc")
		today = getdate(nowdate())
		for p in prices:
			if p.valid_upto and getdate(p.valid_upto) < today:
				continue
			if p.valid_from and getdate(p.valid_from) > today:
				continue
			currencies.add(p.currency)
			offers[(p.supplier, p.item_code)] = p
		meta = {i.name: i for i in frappe.get_all("Item", filters={"name": ["in", codes]}, fields=["name", "lead_time_days", "min_order_qty", "stock_uom"])}
		for (sup, code), p in offers.items():
			if p.uom and p.uom != meta[code].stock_uom:
				warnings.append(_("{0} / {1}: the price is per {2}, not per stock unit: check it.").format(sup, code, p.uom))
	if len(currencies) > 1:
		warnings.append(_("Offers are in different currencies ({0}): convert them before solving.").format(", ".join(sorted(currencies))))
	rows = [{"supplier": s, "item_code": c, "price": flt(p.price_list_rate), "capacity": 0, "moq": flt(meta[c].min_order_qty), "lead_days": int(meta[c].lead_time_days or 0), "quality": 0}
		for (s, c), p in sorted(offers.items())] if needs else []
	if not needs:
		warnings.append(_("No pending purchase requests."))
	elif not rows:
		warnings.append(_("No buying Item Price with a supplier exists for these items."))
	else:
		warnings.append(_("Capacity and quality score are empty: fill them where you know them (0 = no limit)."))
	return needs, rows, warnings


def make_purchase_orders(doc):
	by = defaultdict(list)
	for r in doc.results:
		if flt(r.qty) > 0:
			by[r.supplier].append(r)
	if not by:
		frappe.throw(_("The plan has no quantity to order."))
	names = []
	for sup, rows in by.items():
		po = frappe.new_doc("Purchase Order")
		po.supplier = sup
		po.company = doc.company
		po.transaction_date = nowdate()
		for r in rows:
			po.append("items", {"item_code": r.item_code, "qty": flt(r.qty), "rate": flt(r.price), "schedule_date": add_days(nowdate(), int(r.lead_days or 0))})
		po.schedule_date = max(i.schedule_date for i in po.items)
		po.flags.ignore_mandatory = True
		po.insert()
		names.append(po.name)
	return names


# ----------------------------------------------------------------------------------- break-even
def load_breakeven(company, from_date, to_date, fixed_rows):
	"""Products from the invoices of the period (price, cost at sale, quantity) and the amount of each fixed cost that has an account."""
	warnings = []
	rows = frappe.db.sql(
		"""select sii.item_code, sum(sii.stock_qty) q, sum(sii.base_net_amount) rev, sum(ifnull(sii.incoming_rate, 0) * sii.stock_qty) cost
		from `tabSales Invoice Item` sii join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and si.company = %s and si.posting_date between %s and %s group by sii.item_code having sum(sii.stock_qty) > 0
		order by sum(sii.base_net_amount) desc limit 51""", (company, from_date, to_date), as_dict=True)
	if len(rows) > 50:
		warnings.append(_("Only the 50 items with the highest sales are included."))
		rows = rows[:50]
	products = [{"item_code": r.item_code, "price": flt(r.rev) / flt(r.q), "variable_cost": flt(r.cost) / flt(r.q), "qty": flt(r.q)} for r in rows]
	if not products:
		warnings.append(_("No sales in the chosen period."))
	warnings.append(_("Variable cost = the stock cost at the time of sale. Add direct labour, commissions and delivery per unit if they exist."))
	warnings.append(_("Returns are netted against sales."))
	filled = 0
	for fr in fixed_rows:
		if fr.get("account") and not flt(fr.get("amount")):
			s = frappe.db.sql("select sum(debit - credit) from `tabGL Entry` where account = %s and company = %s and is_cancelled = 0 and posting_date between %s and %s",
				(fr["account"], company, from_date, to_date))
			fr["amount"] = flt(s[0][0]) if s and s[0][0] else 0.0
			filled += 1
	if filled:
		warnings.append(_("{0} fixed cost amounts were read from the ledger for the same period.").format(filled))
	return products, fixed_rows, warnings


# ----------------------------------------------------------------------------------- profitability and stock health
GROUP_COLUMNS = {"Item": "sii.item_code", "Customer": "si.customer", "Item Group": "sii.item_group"}


def load_profitability(company, from_date, to_date, group_by):
	col = GROUP_COLUMNS.get(group_by)
	if not col:
		frappe.throw(_("Choose what to analyse by."))
	rows = frappe.db.sql(
		f"""select {col} g, sum(sii.stock_qty) q, sum(sii.base_net_amount) rev, sum(ifnull(sii.incoming_rate, 0) * sii.stock_qty) cost
		from `tabSales Invoice Item` sii join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and si.company = %s and si.posting_date between %s and %s group by {col} limit 2000""", (company, from_date, to_date), as_dict=True)
	warnings = []
	if len(rows) >= 2000:
		warnings.append(_("Only the first 2000 groups are analysed."))
	warnings.append(_("Cost = the stock cost at the time of sale. Overheads, delivery and returns' handling are not included."))
	return [{"name": r.g or _("(none)"), "revenue": flt(r.rev), "cost": flt(r.cost), "qty": flt(r.q)} for r in rows], warnings


def load_stock_health(company):
	from datetime import date
	whs = company_warehouses(company)
	if not whs:
		return []
	today = getdate(nowdate())
	stock = frappe.get_all("Bin", filters={"warehouse": ["in", whs], "actual_qty": [">", 0]}, fields=["item_code", "actual_qty", "stock_value"], limit_page_length=0)
	agg = defaultdict(lambda: [0.0, 0.0])
	for b in stock:
		agg[b.item_code][0] += flt(b.actual_qty)
		agg[b.item_code][1] += flt(b.stock_value)
	if not agg:
		return []
	codes = list(agg)
	ph = ", ".join(["%s"] * len(codes))
	last = {r.item_code: r.d for r in frappe.db.sql(
		f"select item_code, max(posting_date) d from `tabStock Ledger Entry` where is_cancelled = 0 and actual_qty < 0 and item_code in ({ph}) group by item_code", codes, as_dict=True)}
	since = add_days(nowdate(), -365)
	out_ = {r.item_code: flt(r.q) for r in frappe.db.sql(
		f"select item_code, sum(-actual_qty) q from `tabStock Ledger Entry` where is_cancelled = 0 and actual_qty < 0 and posting_date >= %s and item_code in ({ph}) "
		f"and voucher_type in ('Delivery Note', 'Sales Invoice', 'Stock Entry') group by item_code", [since, *codes], as_dict=True)}
	rows = []
	for c, (q, v) in agg.items():
		d = last.get(c)
		rows.append({"item": c, "qty": q, "value": v, "days_since_move": (today - getdate(d)).days if d else 9999, "daily_demand": out_.get(c, 0.0) / 365.0})
	return rows


# ----------------------------------------------------------------------------------- pricing
def load_pricing(company, item_code):
	"""Cost, current price, monthly quantity and the monthly (price, quantity) history for an elasticity estimate."""
	since = add_days(nowdate(), -365)
	rows = frappe.db.sql(
		"""select si.posting_date d, sum(sii.stock_qty) q, sum(sii.base_net_amount) rev, sum(ifnull(sii.incoming_rate, 0) * sii.stock_qty) cost
		from `tabSales Invoice Item` sii join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus = 1 and si.company = %s and si.posting_date >= %s and sii.item_code = %s group by si.posting_date""", (company, since, item_code), as_dict=True)
	months = defaultdict(lambda: [0.0, 0.0, 0.0])
	for r in rows:
		m = months[str(r.d)[:7]]
		m[0] += flt(r.q)
		m[1] += flt(r.rev)
		m[2] += flt(r.cost)
	tq = sum(m[0] for m in months.values())
	warnings = []
	if not tq:
		warnings.append(_("No sales of this item in the last 12 months."))
		return {"cost": 0, "price": 0, "qty": 0, "points": []}, warnings
	rev = sum(m[1] for m in months.values())
	cost = sum(m[2] for m in months.values()) / tq
	if not cost:
		cost = flt(frappe.db.get_value("Item", item_code, "valuation_rate"))
	n = max(len(months), 1)
	points = [(m[1] / m[0], m[0]) for m in months.values() if m[0] > 0]
	return {"cost": cost, "price": rev / tq, "qty": tq / 12.0, "points": points}, warnings


# ----------------------------------------------------------------------------------- make or buy
def load_make_or_buy(company, item_code):
	warnings = []
	make_var = buy = 0.0
	bom = frappe.db.get_value("BOM", {"item": item_code, "is_active": 1, "is_default": 1, "docstatus": 1}, ["name", "total_cost", "quantity"], as_dict=True)
	if bom:
		make_var = flt(bom.total_cost) / (flt(bom.quantity) or 1.0)
	else:
		warnings.append(_("No active default BOM: enter the making cost."))
	buy = flt(frappe.db.get_value("Item Price", {"item_code": item_code, "buying": 1}, "price_list_rate", order_by="valid_from desc")) or flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))
	if not buy:
		warnings.append(_("No buying price found: enter it."))
	warnings.append(_("The BOM cost includes materials and operations at their standard rates. Add the fixed yearly costs of each option yourself."))
	return make_var, buy, warnings


# ----------------------------------------------------------------------------------- decision review
def _demand_in_window(item_code, whs, start, end):
	if not whs:
		return 0.0
	ph = ", ".join(["%s"] * len(whs))
	r = frappe.db.sql(
		f"""select sum(-sle.actual_qty) from `tabStock Ledger Entry` sle where sle.is_cancelled = 0 and sle.actual_qty < 0 and sle.item_code = %s
		and sle.posting_date between %s and %s and sle.warehouse in ({ph}) and (sle.voucher_type in ('Delivery Note', 'Sales Invoice') or (sle.voucher_type = 'Stock Entry'
		and sle.voucher_no in (select name from `tabStock Entry` where purpose in %s and docstatus = 1)))""", [item_code, start, end, *whs, CONSUMING_ENTRIES])
	return flt(r[0][0]) if r and r[0][0] else 0.0


def load_review(company, plan_type, from_date, to_date):
	"""Rows to compare for the plans solved in the period. Only plans old enough for the outcome to be known are used."""
	warnings = []
	rows = []
	today = getdate(nowdate())
	plans = frappe.get_all(plan_type, filters={"company": company, "solved_on": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]], "status": ["in", ["Solved", "Needs Attention"]]},
		fields=["name", "solved_on"] + (["warehouse", "lookback_days"] if plan_type == "Reorder Plan" else ["planning_days"] if plan_type == "Product Mix Plan" else []), limit_page_length=500)
	skipped = 0
	for p in plans:
		solved = getdate(p.solved_on)
		if plan_type == "Reorder Plan":
			end = add_days(solved, 30)
			if getdate(end) > today:
				skipped += 1
				continue
			whs = company_warehouses(company, p.warehouse)
			for it in frappe.get_all("Reorder Item", filters={"parent": p.name, "parenttype": plan_type}, fields=["item_code", "forecast_next"]):
				if flt(it.forecast_next) > 0:
					rows.append({"plan": p.name, "item_code": it.item_code, "expected": flt(it.forecast_next), "actual": _demand_in_window(it.item_code, whs, add_days(solved, 1), end)})
		elif plan_type == "Product Mix Plan":
			days = int(p.planning_days or 30)
			end = add_days(solved, days)
			if getdate(end) > today:
				skipped += 1
				continue
			for it in frappe.get_all("Mix Product", filters={"parent": p.name, "parenttype": plan_type}, fields=["item_code", "plan_qty"]):
				if flt(it.plan_qty) > 0:
					made = frappe.db.sql(
						"""select sum(sed.qty) from `tabStock Entry Detail` sed join `tabStock Entry` se on se.name = sed.parent where se.docstatus = 1 and se.purpose = 'Manufacture'
						and se.company = %s and sed.is_finished_item = 1 and sed.item_code = %s and se.posting_date between %s and %s""", (company, it.item_code, add_days(solved, 1), end))
					rows.append({"plan": p.name, "item_code": it.item_code, "expected": flt(it.plan_qty), "actual": flt(made[0][0]) if made and made[0][0] else 0.0})
		else:
			if solved >= today:
				skipped += 1
				continue
			for it in frappe.get_all("Allocation Result", filters={"parent": p.name, "parenttype": plan_type}, fields=["supplier", "item_code", "price"]):
				paid = frappe.db.sql(
					"""select sum(poi.base_net_amount) / nullif(sum(poi.qty), 0) from `tabPurchase Order Item` poi join `tabPurchase Order` po on po.name = poi.parent
					where po.docstatus = 1 and po.company = %s and po.supplier = %s and poi.item_code = %s and po.transaction_date > %s""", (company, it.supplier, it.item_code, solved))
				if paid and paid[0][0]:
					rows.append({"plan": p.name, "item_code": it.item_code, "supplier": it.supplier, "expected": flt(it.price), "actual": flt(paid[0][0])})
	if skipped:
		warnings.append(_("{0} plans are too recent to be checked yet.").format(skipped))
	if plan_type == "Supplier Allocation Plan":
		warnings.append(_("Compares the planned price with the average price of purchase orders placed with the same supplier after the plan."))
	elif plan_type == "Reorder Plan":
		warnings.append(_("Compares the forecast of next month's demand with the demand of the 30 days that followed."))
	else:
		warnings.append(_("Compares the planned quantity with the quantity produced in the planning days that followed."))
	return rows, warnings
