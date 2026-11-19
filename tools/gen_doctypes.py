"""Builds every DocType JSON of ledgerx_research from the compact table below.
Run from the repo root:  python3 tools/gen_doctypes.py   (rewrites ledgerx_research/operations_research/doctype/*)"""
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..", "ledgerx_research", "operations_research", "doctype")
TS = "2026-11-16 08:00:00.000000"
MODULE = "Operations Research"

MGR, ANA = "Research Manager", "Research Analyst"


def f(name, ftype, label=None, **kw):
	d = {"fieldname": name, "fieldtype": ftype}
	if ftype not in ("Section Break", "Column Break", "Tab Break"):
		d["label"] = label or name.replace("_", " ").title()
	elif label:
		d["label"] = label
	d.update(kw)
	return d


def sec(name, label=None, **kw):
	return f(name, "Section Break", label, **kw)


def col(name):
	return f(name, "Column Break")


def perms(*rows):
	out = []
	for role, mode in rows:
		p = {"role": role, "read": 1, "report": 1, "print": 1, "export": 1}
		if mode in ("rw", "rwc", "all"):
			p["write"] = 1
		if mode in ("rwc", "all"):
			p["create"] = 1
		if mode == "all":
			p["delete"] = 1
		out.append(p)
	out.append({"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "print": 1, "export": 1})
	return out


DT = {}


def doctype(name, fields, **kw):
	DT[name] = {"name": name, "fields": fields, **kw}


PERMS = perms((MGR, "all"), (ANA, "rwc"))
STATUS = "Draft\nSolved\nInfeasible\nNeeds Attention"


def result_block():
	return [sec("sb_res", "Result"), f("status", "Select", "Status", options=STATUS, default="Draft", read_only=1, in_list_view=1, in_standard_filter=1),
		col("cb_r"), f("verified", "Check", "Independently Verified", read_only=1, description="The solution was re-checked by separate code: every constraint holds and, for linear problems, optimality is proven by a duality certificate."),
		f("solved_on", "Datetime", "Solved On", read_only=1), f("summary_html", "Text Editor", "Summary", read_only=1)]


doctype("OR Settings", [
	f("company", "Link", "Default Company", options="Company"),
	f("holding_rate_pct", "Percent", "Holding Cost per Year %", default=20),
	f("default_order_cost", "Currency", "Cost of Placing One Order", default=50),
	f("default_lead_days", "Int", "Default Lead Time (days)", default=7),
	f("service_level_pct", "Percent", "Service Level %", default=95),
	f("max_stops_exact", "Int", "Exact Route Order up to (stops)", default=12, read_only=1),
], issingle=1, icon="fa fa-calculator", perms=perms((MGR, "rw")))

# ------------------------------------------------------------------ product mix
doctype("Mix Product", [
	f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
	f("item_name", "Data", "Item Name", read_only=1, fetch_from="item_code.item_name"),
	f("bom_no", "Link", "BOM", options="BOM", in_list_view=1),
	f("price", "Currency", "Selling Price", in_list_view=1),
	f("unit_cost", "Currency", "Unit Cost", in_list_view=1),
	f("margin", "Currency", "Margin per Unit", read_only=1, in_list_view=1),
	f("min_qty", "Float", "Minimum Quantity"),
	f("max_qty", "Float", "Maximum Quantity (demand)", description="0 = no limit"),
	f("plan_qty", "Float", "Recommended Quantity", read_only=1, in_list_view=1),
	f("usage_json", "Code", "Resource Use per Unit", hidden=1),
], istable=1)

doctype("Mix Resource", [
	f("resource", "Data", "Resource", reqd=1, in_list_view=1),
	f("kind", "Select", "Kind", options="Material\nWorkstation Hours", in_list_view=1),
	f("available", "Float", "Available", in_list_view=1),
	f("used", "Float", "Used", read_only=1, in_list_view=1),
	f("slack", "Float", "Left Over", read_only=1),
	f("shadow_price", "Float", "Value of One More Unit", read_only=1, in_list_view=1, description="How much the total margin would rise if you had one more unit of this resource: the real bottleneck shows the highest number."),
], istable=1)

doctype("Product Mix Plan", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("planning_days", "Int", "Planning Days", default=30, description="Workstation capacity = daily working hours x these days."),
	col("cb1"),
	f("whole_units", "Check", "Whole Units Only"),
	f("cap_by_orders", "Check", "Do Not Produce More Than Open Sales Orders", default=1),
	sec("sb_p", "Products"),
	f("products", "Table", "Products", options="Mix Product"),
	sec("sb_r", "Resources"),
	f("resources", "Table", "Resources", options="Mix Resource"),
	sec("sb_o", "Outcome"),
	f("objective", "Currency", "Total Margin", read_only=1),
	f("production_plan", "Link", "Production Plan", options="Production Plan", read_only=1),
	*result_block(),
], autoname="format:MIX-.YYYY.-.#####", icon="fa fa-industry", perms=PERMS)

# ------------------------------------------------------------------ reorder
doctype("Reorder Item", [
	f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
	f("item_name", "Data", "Item Name", read_only=1, fetch_from="item_code.item_name"),
	f("abc", "Select", "ABC", options="\nA\nB\nC", read_only=1, in_list_view=1),
	f("annual_demand", "Float", "Yearly Demand", in_list_view=1),
	f("daily_sd", "Float", "Daily Demand Std Dev"),
	f("lead_days", "Int", "Lead Time (days)"),
	f("unit_cost", "Currency", "Unit Cost"),
	f("on_hand", "Float", "On Hand"),
	f("on_order", "Float", "On Order"),
	f("eoq", "Float", "Economic Order Qty", read_only=1),
	f("safety_stock", "Float", "Safety Stock", read_only=1),
	f("reorder_point", "Float", "Reorder Point", read_only=1, in_list_view=1),
	f("order_qty", "Float", "Order Now", read_only=1, in_list_view=1),
	f("forecast_method", "Data", "Forecast Method", read_only=1),
	f("forecast_next", "Float", "Next Month Forecast", read_only=1),
], istable=1)

doctype("Reorder Plan", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("warehouse", "Link", "Warehouse", options="Warehouse", description="Leave empty for all warehouses of the company."),
	f("lookback_days", "Int", "History (days)", default=365),
	col("cb1"),
	f("service_level_pct", "Percent", "Service Level %", default=95),
	f("holding_rate_pct", "Percent", "Holding Cost per Year %", default=20),
	f("order_cost", "Currency", "Cost of Placing One Order", default=50),
	f("default_lead_days", "Int", "Default Lead Time (days)", default=7),
	sec("sb_i", "Items"),
	f("items", "Table", "Items", options="Reorder Item"),
	sec("sb_o", "Outcome"),
	f("material_request", "Link", "Material Request", options="Material Request", read_only=1),
	*result_block(),
], autoname="format:ROP-.YYYY.-.#####", icon="fa fa-cubes", perms=PERMS)

# ------------------------------------------------------------------ distribution
doctype("Plan Source", [
	f("location", "Data", "Source", reqd=1, in_list_view=1, description="A warehouse name when you want a Stock Entry draft."),
	f("qty", "Float", "Available Quantity", in_list_view=1),
	f("lat", "Float", "Latitude", precision="6", in_list_view=1),
	f("lng", "Float", "Longitude", precision="6", in_list_view=1),
], istable=1)

doctype("Plan Destination", [
	f("location", "Data", "Destination", reqd=1, in_list_view=1),
	f("demand", "Float", "Required Quantity", in_list_view=1),
	f("lat", "Float", "Latitude", precision="6", in_list_view=1),
	f("lng", "Float", "Longitude", precision="6", in_list_view=1),
], istable=1)

doctype("Plan Lane", [
	f("source", "Data", "Source", reqd=1, in_list_view=1),
	f("destination", "Data", "Destination", reqd=1, in_list_view=1),
	f("unit_cost", "Currency", "Cost per Unit", in_list_view=1),
	f("blocked", "Check", "Not Allowed", in_list_view=1),
], istable=1)

doctype("Plan Flow", [
	f("source", "Data", "From", read_only=1, in_list_view=1),
	f("destination", "Data", "To", read_only=1, in_list_view=1),
	f("qty", "Float", "Quantity", read_only=1, in_list_view=1),
	f("unit_cost", "Currency", "Cost per Unit", read_only=1, in_list_view=1),
	f("amount", "Currency", "Amount", read_only=1, in_list_view=1),
], istable=1)

doctype("Distribution Plan", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("item_code", "Link", "Item", options="Item", description="Needed only to create a Stock Entry draft between warehouses."),
	col("cb1"),
	f("cost_per_km", "Currency", "Cost per Unit per km", default=1, description="Used for every lane that has no cost in the table below."),
	f("allow_shortage", "Check", "Allow Unmet Demand", default=1),
	sec("sb_s", "Sources"),
	f("sources", "Table", "Sources", options="Plan Source"),
	sec("sb_d", "Destinations"),
	f("destinations", "Table", "Destinations", options="Plan Destination"),
	sec("sb_l", "Lane Costs (optional)"),
	f("lanes", "Table", "Lane Costs", options="Plan Lane"),
	sec("sb_f", "Shipping Plan"),
	f("flows", "Table", "Shipping Plan", options="Plan Flow", read_only=1),
	f("total_cost", "Currency", "Total Shipping Cost", read_only=1),
	f("stock_entry", "Link", "Stock Entry", options="Stock Entry", read_only=1),
	*result_block(),
], autoname="format:DST-.YYYY.-.#####", icon="fa fa-truck", perms=PERMS)

# ------------------------------------------------------------------ routes
doctype("Route Stop", [
	f("stop", "Data", "Stop", reqd=1, in_list_view=1),
	f("customer", "Link", "Customer", options="Customer"),
	f("lat", "Float", "Latitude", precision="6", in_list_view=1),
	f("lng", "Float", "Longitude", precision="6", in_list_view=1),
	f("demand", "Float", "Load", in_list_view=1),
], istable=1)

doctype("Route Leg", [
	f("route_no", "Int", "Route", read_only=1, in_list_view=1),
	f("sequence", "Int", "Order", read_only=1, in_list_view=1),
	f("stop", "Data", "Stop", read_only=1, in_list_view=1),
	f("route_load", "Float", "Route Load", read_only=1, in_list_view=1),
	f("route_km", "Float", "Route km", read_only=1, in_list_view=1),
], istable=1)

doctype("Route Plan", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("depot_name", "Data", "Depot"),
	f("depot_lat", "Float", "Depot Latitude", precision="6", reqd=1),
	f("depot_lng", "Float", "Depot Longitude", precision="6", reqd=1),
	col("cb1"),
	f("vehicle_capacity", "Float", "Vehicle Capacity", reqd=1),
	f("max_vehicles", "Int", "Vehicles Available", description="0 = no limit."),
	sec("sb_s", "Stops"),
	f("stops", "Table", "Stops", options="Route Stop"),
	sec("sb_o", "Routes"),
	f("legs", "Table", "Routes", options="Route Leg", read_only=1),
	f("total_km", "Float", "Total km", read_only=1),
	f("lower_bound_km", "Float", "Lower Bound km", read_only=1),
	f("gap_pct", "Percent", "Distance Above Lower Bound %", read_only=1),
	f("vehicles_used", "Int", "Vehicles Used", read_only=1),
	*result_block(),
], autoname="format:RTE-.YYYY.-.#####", icon="fa fa-road", perms=PERMS)

# ------------------------------------------------------------------ schedule
doctype("Schedule Operation", [
	f("work_order", "Link", "Work Order", options="Work Order", reqd=1, in_list_view=1),
	f("operation", "Data", "Operation", in_list_view=1),
	f("workstation", "Link", "Workstation", options="Workstation", in_list_view=1),
	f("sequence", "Int", "Sequence", in_list_view=1),
	f("hours", "Float", "Remaining Hours", in_list_view=1),
	f("due_date", "Datetime", "Due"),
], istable=1)

doctype("Schedule Row", [
	f("work_order", "Link", "Work Order", options="Work Order", read_only=1, in_list_view=1),
	f("operation", "Data", "Operation", read_only=1, in_list_view=1),
	f("workstation", "Link", "Workstation", options="Workstation", read_only=1, in_list_view=1),
	f("start_at", "Datetime", "Start", read_only=1, in_list_view=1),
	f("end_at", "Datetime", "End", read_only=1, in_list_view=1),
], istable=1)

doctype("Schedule Plan", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("start_at", "Datetime", "Schedule From", reqd=1),
	col("cb1"),
	f("objective", "Select", "Minimise", options="Finish Time of the Last Order\nTotal Lateness", default="Finish Time of the Last Order"),
	f("hours_per_day", "Float", "Working Hours per Day", default=8, description="Converts hours of work into calendar time in the schedule."),
	sec("sb_o", "Operations"),
	f("operations", "Table", "Operations", options="Schedule Operation"),
	sec("sb_s", "Schedule"),
	f("rows", "Table", "Schedule", options="Schedule Row", read_only=1),
	f("makespan_hours", "Float", "Total Working Hours Needed", read_only=1),
	f("lower_bound_hours", "Float", "Lower Bound (hours)", read_only=1),
	f("gap_pct", "Percent", "Above Lower Bound %", read_only=1),
	f("rule", "Data", "Best Dispatch Rule", read_only=1),
	f("total_lateness_hours", "Float", "Total Lateness (hours)", read_only=1),
	*result_block(),
], autoname="format:SCH-.YYYY.-.#####", icon="fa fa-calendar", perms=PERMS)

# ------------------------------------------------------------------ supplier allocation
doctype("Allocation Need", [
	f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
	f("qty", "Float", "Required Quantity", reqd=1, in_list_view=1),
	f("uom", "Link", "UOM", options="UOM", in_list_view=1),
], istable=1)

doctype("Allocation Offer", [
	f("supplier", "Link", "Supplier", options="Supplier", reqd=1, in_list_view=1),
	f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
	f("price", "Currency", "Price", reqd=1, in_list_view=1),
	f("capacity", "Float", "Can Supply (max)", in_list_view=1),
	f("moq", "Float", "Minimum Order"),
	f("lead_days", "Int", "Lead Time (days)", in_list_view=1),
	f("quality", "Percent", "Quality Score %"),
], istable=1)

doctype("Allocation Result", [
	f("supplier", "Link", "Supplier", options="Supplier", read_only=1, in_list_view=1),
	f("item_code", "Link", "Item", options="Item", read_only=1, in_list_view=1),
	f("qty", "Float", "Quantity", read_only=1, in_list_view=1),
	f("price", "Currency", "Price", read_only=1, in_list_view=1),
	f("amount", "Currency", "Amount", read_only=1, in_list_view=1),
	f("lead_days", "Int", "Lead Time (days)", read_only=1),
], istable=1)

doctype("Supplier Allocation Plan", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("max_share_pct", "Percent", "Max Share of One Supplier %", description="Empty or 0 = no limit."),
	f("max_lead_days", "Int", "Longest Lead Time (days)", description="0 = no limit."),
	col("cb1"),
	f("min_quality_pct", "Percent", "Lowest Quality Score %", description="0 = no limit. Offers without a score are kept."),
	f("budget", "Currency", "Budget"),
	f("supplier_setup_cost", "Currency", "Cost per Extra Supplier Used", description="Charged once for every supplier that gets an order; pushes the plan to consolidate."),
	sec("sb_n", "Needs"),
	f("needs", "Table", "Needs", options="Allocation Need"),
	sec("sb_of", "Offers"),
	f("offers", "Table", "Offers", options="Allocation Offer"),
	sec("sb_r2", "Allocation"),
	f("results", "Table", "Allocation", options="Allocation Result", read_only=1),
	f("total_cost", "Currency", "Total Cost", read_only=1),
	f("purchase_orders", "Small Text", "Purchase Order Drafts", read_only=1),
	*result_block(),
], autoname="format:ALC-.YYYY.-.#####", icon="fa fa-handshake-o", perms=PERMS)


def build():
	os.makedirs(ROOT, exist_ok=True)
	for name, d in DT.items():
		fields = d["fields"]
		order = [x["fieldname"] for x in fields]
		istable = d.get("istable", 0)
		out = {
			"actions": [], "creation": TS, "doctype": "DocType", "engine": "InnoDB", "field_order": order, "fields": fields,
			"links": [], "modified": TS, "modified_by": "Administrator", "module": MODULE, "name": name, "owner": "Administrator",
			"sort_field": "creation", "sort_order": "DESC", "states": [],
			"permissions": [] if istable else d.get("perms", []),
		}
		for k in ("autoname", "title_field", "icon", "track_changes", "issingle", "istable", "show_title_field_in_link", "search_fields"):
			if k in d:
				out[k] = d[k]
		if "autoname" not in d and not istable and not d.get("issingle"):
			out["autoname"] = "hash"
		out["allow_rename"] = 0
		slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
		folder = os.path.join(ROOT, slug)
		os.makedirs(folder, exist_ok=True)
		open(os.path.join(folder, "__init__.py"), "a").close()
		with open(os.path.join(folder, slug + ".json"), "w", encoding="utf-8") as fh:
			json.dump(out, fh, indent=1, ensure_ascii=False)
			fh.write("\n")
		py = os.path.join(folder, slug + ".py")
		if not os.path.exists(py):
			cls = "".join(w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", name))
			with open(py, "w") as fh:
				fh.write(f"from frappe.model.document import Document\n\n\nclass {cls}(Document):\n\tpass\n")


if __name__ == "__main__":
	build()
	print(len(DT), "doctypes")
