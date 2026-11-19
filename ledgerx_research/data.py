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
