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
	f("crm_default_probability", "Percent", "Default Deal Probability %", default=30, description="Used for CRM deals that have no probability of their own."),
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
	f("margin_low", "Float", "Margin Can Fall To", read_only=1, description="The plan stays the best one while the margin stays between these two numbers."),
	f("margin_high", "Float", "Margin Can Rise To", read_only=1),
	f("usage_json", "Code", "Resource Use per Unit", hidden=1),
], istable=1)

doctype("Mix Resource", [
	f("resource", "Data", "Resource", reqd=1, in_list_view=1),
	f("kind", "Select", "Kind", options="Material\nWorkstation Hours", in_list_view=1),
	f("available", "Float", "Available", in_list_view=1),
	f("used", "Float", "Used", read_only=1, in_list_view=1),
	f("slack", "Float", "Left Over", read_only=1),
	f("shadow_price", "Float", "Value of One More Unit", read_only=1, in_list_view=1, description="How much the total margin would rise if you had one more unit of this resource: the real bottleneck shows the highest number."),
	f("range_low", "Float", "Can Fall To", read_only=1, description="The value of one more unit holds while the available amount stays between these two numbers."),
	f("range_high", "Float", "Can Rise To", read_only=1),
], istable=1)

doctype("Mix Scenario", [
	f("scenario", "Data", "Scenario", reqd=1, in_list_view=1, description="Rows with the same name are applied together."),
	f("kind", "Select", "What Changes", options="Resource\nMargin\nMax Quantity\nMin Quantity", reqd=1, in_list_view=1),
	f("key", "Data", "Name", reqd=1, in_list_view=1, description="The resource name, or the item code of the product."),
	f("pct", "Percent", "Change %", reqd=1, in_list_view=1),
], istable=1)

doctype("Mix Scenario Result", [
	f("scenario", "Data", "Scenario", read_only=1, in_list_view=1),
	f("total_margin", "Currency", "Total Margin", read_only=1, in_list_view=1),
	f("change", "Currency", "Change", read_only=1, in_list_view=1),
	f("moved", "Small Text", "Products That Change", read_only=1, in_list_view=1),
], istable=1)

doctype("Product Mix Plan", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("planning_days", "Int", "Planning Days", default=30, description="Workstation capacity = daily working hours x these days."),
	col("cb1"),
	f("whole_units", "Check", "Whole Units Only"),
	f("cap_by_orders", "Check", "Do Not Produce More Than Open Sales Orders", default=1),
	f("include_crm", "Check", "Add Expected Demand From CRM Deals", description="Deals closing within the planning days count in proportion to their probability."),
	sec("sb_p", "Products"),
	f("products", "Table", "Products", options="Mix Product"),
	sec("sb_r", "Resources"),
	f("resources", "Table", "Resources", options="Mix Resource"),
	sec("sb_o", "Outcome"),
	f("objective", "Currency", "Total Margin", read_only=1),
	f("production_plan", "Link", "Production Plan", options="Production Plan", read_only=1),
	sec("sb_w", "What-if and Risk"),
	f("scenarios", "Table", "Scenarios", options="Mix Scenario", description="Try a change (more of a material, a price drop...) and press What-if to see the new best plan."),
	f("scenario_results", "Table", "Scenario Results", options="Mix Scenario Result", read_only=1),
	f("risk_sd_pct", "Percent", "How Much Can Numbers Vary %", default=10),
	f("risk_draws", "Int", "Simulations", default=300),
	col("cb_w"),
	f("risk_p5", "Currency", "Worst Realistic Margin (5%)", read_only=1),
	f("risk_p50", "Currency", "Typical Margin", read_only=1),
	f("risk_p95", "Currency", "Best Realistic Margin (95%)", read_only=1),
	f("risk_keep_pct", "Percent", "Plan Still Possible In % of Cases", read_only=1),
	f("risk_regret", "Currency", "Average Loss From Not Re-planning", read_only=1),
	*result_block(),
], autoname="format:MIX-.YYYY.-.#####", icon="fa fa-industry", perms=PERMS)

# ------------------------------------------------------------------ reorder
doctype("Reorder Item", [
	f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
	f("item_name", "Data", "Item Name", read_only=1, fetch_from="item_code.item_name"),
	f("abc", "Select", "ABC", options="\nA\nB\nC", read_only=1, in_list_view=1),
	f("annual_demand", "Float", "Yearly Demand", in_list_view=1),
	f("pipeline_qty", "Float", "Expected From CRM Deals", description="Quantity weighted by deal probability for the deals closing within the CRM horizon; added to the yearly demand as a yearly rate."),
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
	f("include_crm", "Check", "Add Expected Demand From CRM Deals"),
	f("crm_horizon_days", "Int", "CRM Horizon (days)", default=90, depends_on="include_crm"),
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
	f("include_branch_needs", "Check", "Add Needs of Pharmacy Branches", description="Needs come from each branch's recent sales, its minimum level and its sellable stock. Needs the Pharmacy app."),
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

doctype("Route Vehicle", [
	f("vehicle", "Data", "Vehicle", reqd=1, in_list_view=1),
	f("driver", "Data", "Driver", in_list_view=1),
	f("capacity", "Float", "Capacity", in_list_view=1, description="In the same unit as the load of the stops."),
	f("cost_per_km", "Currency", "Cost per km", in_list_view=1, description="Load Data reads fuel and maintenance from the fleet records of the last 12 months."),
], istable=1)

doctype("Route Leg", [
	f("route_no", "Int", "Route", read_only=1, in_list_view=1),
	f("sequence", "Int", "Order", read_only=1, in_list_view=1),
	f("stop", "Data", "Stop", read_only=1, in_list_view=1),
	f("route_load", "Float", "Route Load", read_only=1, in_list_view=1),
	f("route_km", "Float", "Route km", read_only=1, in_list_view=1),
	f("vehicle", "Data", "Vehicle", read_only=1, in_list_view=1),
	f("route_cost", "Currency", "Route Cost", read_only=1),
], istable=1)

doctype("Route Plan", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("depot_name", "Data", "Depot"),
	f("depot_lat", "Float", "Depot Latitude", precision="6", reqd=1),
	f("depot_lng", "Float", "Depot Longitude", precision="6", reqd=1),
	col("cb1"),
	f("load_basis", "Select", "Load Measured In", options="Quantity\nWeight (kg)", default="Quantity", description="Choose Weight when the vehicles are listed with their payload in kg."),
	f("vehicle_capacity", "Float", "Vehicle Capacity", description="For identical vehicles. Ignored when the vehicle list below is filled."),
	f("max_vehicles", "Int", "Vehicles Available", description="0 = no limit. Ignored when the vehicle list below is filled."),
	sec("sb_v", "Vehicles (optional)"),
	f("vehicles", "Table", "Vehicles", options="Route Vehicle", description="Different vehicles with their own capacity and cost per km: the plan uses the cheapest ones that fit."),
	sec("sb_s", "Stops"),
	f("stops", "Table", "Stops", options="Route Stop"),
	sec("sb_o", "Routes"),
	f("legs", "Table", "Routes", options="Route Leg", read_only=1),
	f("total_km", "Float", "Total km", read_only=1),
	f("lower_bound_km", "Float", "Lower Bound km", read_only=1),
	f("gap_pct", "Percent", "Distance Above Lower Bound %", read_only=1),
	f("vehicles_used", "Int", "Vehicles Used", read_only=1),
	f("total_cost", "Currency", "Total Cost", read_only=1),
	f("fleet_trips", "Small Text", "Fleet Trip Drafts", read_only=1),
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


# ------------------------------------------------------------------ break-even
doctype("BE Fixed Cost", [
	f("cost_name", "Data", "Fixed Cost", reqd=1, in_list_view=1),
	f("account", "Link", "Account", options="Account", in_list_view=1, description="Optional: Load Data fills the amount from this account for the period."),
	f("amount", "Currency", "Amount for the Period", in_list_view=1),
	f("is_cash", "Check", "Paid in Cash", default=1, in_list_view=1, description="Untick for depreciation and other non-cash costs."),
], istable=1)

doctype("BE Product", [
	f("item_code", "Link", "Item", options="Item", reqd=1, in_list_view=1),
	f("price", "Currency", "Selling Price", in_list_view=1),
	f("variable_cost", "Currency", "Variable Cost per Unit", in_list_view=1),
	f("qty", "Float", "Expected Quantity", in_list_view=1, description="Also sets the sales mix between products."),
	f("break_even_units", "Float", "Break-even Units", read_only=1, in_list_view=1),
	f("break_even_revenue", "Currency", "Break-even Revenue", read_only=1, in_list_view=1),
], istable=1)

doctype("BE Sensitivity", [
	f("what", "Data", "What Changes", read_only=1, in_list_view=1),
	f("change_pct", "Percent", "Change %", read_only=1, in_list_view=1),
	f("break_even_units", "Float", "Break-even Units", read_only=1, in_list_view=1),
	f("expected_profit", "Currency", "Profit at Expected Sales", read_only=1, in_list_view=1),
], istable=1)

doctype("Break Even Analysis", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("from_date", "Date", "History From"),
	f("to_date", "Date", "History To"),
	col("cb1"),
	f("target_profit", "Currency", "Target Profit"),
	f("capacity_units", "Float", "Capacity (units)"),
	f("risk_sd_pct", "Percent", "How Much Can Numbers Vary %", default=10),
	f("include_depreciation", "Check", "Add Asset Depreciation of the Period", description="Load Data adds the scheduled depreciation of the assets as a non-cash fixed cost."),
	sec("sb_f", "Fixed Costs for the Period"),
	f("fixed_costs", "Table", "Fixed Costs", options="BE Fixed Cost"),
	sec("sb_p", "Products"),
	f("products", "Table", "Products", options="BE Product"),
	sec("sb_b", "Break-even"),
	f("total_fixed", "Currency", "Total Fixed Costs", read_only=1),
	f("break_even_units", "Float", "Break-even Units", read_only=1),
	f("break_even_revenue", "Currency", "Break-even Revenue", read_only=1),
	f("cash_break_even_units", "Float", "Cash Break-even Units", read_only=1),
	col("cb_b"),
	f("target_units", "Float", "Units for the Target Profit", read_only=1),
	f("target_revenue", "Currency", "Revenue for the Target Profit", read_only=1),
	f("margin_of_safety_pct", "Percent", "Margin of Safety %", read_only=1, description="How far sales can fall before the period makes a loss."),
	f("operating_leverage", "Float", "Operating Leverage", read_only=1, description="A 1% change in sales changes profit by this many percent."),
	f("expected_profit", "Currency", "Profit at Expected Sales", read_only=1),
	sec("sb_k", "Risk"),
	f("loss_probability_pct", "Percent", "Chance of a Loss %", read_only=1),
	f("profit_p5", "Currency", "Worst Realistic Profit (5%)", read_only=1),
	f("profit_p50", "Currency", "Typical Profit", read_only=1),
	f("profit_p95", "Currency", "Best Realistic Profit (95%)", read_only=1),
	sec("sb_s", "What If"),
	f("sensitivity", "Table", "Sensitivity", options="BE Sensitivity", read_only=1),
	*result_block(),
], autoname="format:BEA-.YYYY.-.#####", icon="fa fa-balance-scale", perms=PERMS)

# ------------------------------------------------------------------ investment
doctype("Investment Cash Flow", [
	f("year", "Int", "Year", reqd=1, in_list_view=1, description="0 = now."),
	f("amount", "Currency", "Cash Flow", reqd=1, in_list_view=1, description="Money out is negative."),
	f("note", "Data", "Note", in_list_view=1),
], istable=1)

doctype("Investment Analysis", [
	f("project_name", "Data", "Project", reqd=1),
	f("company", "Link", "Company", options="Company"),
	col("cb1"),
	f("discount_rate_pct", "Percent", "Required Return per Year %", default=10, reqd=1, description="The return you could get elsewhere with the same risk."),
	f("risk_sd_pct", "Percent", "How Much Can Future Cash Vary %", default=0),
	sec("sb_c", "Cash Flows"),
	f("cash_flows", "Table", "Cash Flows", options="Investment Cash Flow"),
	sec("sb_o", "Appraisal"),
	f("npv", "Currency", "Net Present Value", read_only=1, description="Positive: the project earns more than the required return."),
	f("irr_pct", "Percent", "Internal Rate of Return %", read_only=1),
	f("profitability_index", "Float", "Profitability Index", read_only=1),
	col("cb_o"),
	f("payback_years", "Float", "Payback (years)", read_only=1),
	f("discounted_payback_years", "Float", "Discounted Payback (years)", read_only=1),
	f("decision", "Data", "Decision", read_only=1),
	sec("sb_k", "Risk"),
	f("loss_probability_pct", "Percent", "Chance NPV Is Negative %", read_only=1),
	f("npv_p5", "Currency", "Worst Realistic NPV (5%)", read_only=1),
	f("npv_p95", "Currency", "Best Realistic NPV (95%)", read_only=1),
	*result_block(),
], autoname="format:INV-.YYYY.-.#####", icon="fa fa-line-chart", perms=PERMS)

doctype("Make or Buy Analysis", [
	f("company", "Link", "Company", options="Company"),
	f("item_code", "Link", "Item", options="Item", description="Optional: Load Data fills the making cost from the default BOM and the buying price from the price list."),
	f("annual_volume", "Float", "Yearly Volume", reqd=1),
	sec("sb_m", "Make"),
	f("make_fixed", "Currency", "Fixed Cost of Making per Year"),
	f("make_variable", "Currency", "Making Cost per Unit"),
	sec("sb_b", "Buy"),
	f("buy_fixed", "Currency", "Fixed Cost of Buying per Year"),
	f("buy_price", "Currency", "Buying Price per Unit"),
	sec("sb_o", "Outcome"),
	f("make_cost", "Currency", "Total Cost If Made", read_only=1),
	f("buy_cost", "Currency", "Total Cost If Bought", read_only=1),
	f("cheaper", "Data", "Cheaper Option", read_only=1),
	col("cb_o"),
	f("saving", "Currency", "Saving per Year", read_only=1),
	f("indifference_volume", "Float", "Volume Where Both Cost the Same", read_only=1),
	f("rule", "Data", "Rule", read_only=1),
	*result_block(),
], autoname="format:MOB-.YYYY.-.#####", icon="fa fa-exchange", perms=PERMS)

doctype("Lease or Buy Analysis", [
	f("asset", "Data", "Asset", reqd=1),
	f("asset_ref", "Link", "Existing Asset", options="Asset", description="Optional: Load Data takes the price, value at the end and life from it, and shows its book value."),
	f("rate_pct", "Percent", "Discount Rate per Year %", default=10, reqd=1),
	f("life_years", "Int", "Years of Use", reqd=1),
	sec("sb_b", "If You Buy"),
	f("price", "Currency", "Purchase Price"),
	f("residual", "Currency", "Value at the End"),
	f("yearly_cost_own", "Currency", "Yearly Running Cost (maintenance, insurance)"),
	sec("sb_l", "If You Lease"),
	f("lease_payment", "Currency", "Yearly Lease Payment"),
	f("lease_years", "Int", "Lease Years", description="Leave empty to use the years of use."),
	f("lease_cost_extra", "Currency", "Yearly Extra Cost While Leasing"),
	sec("sb_a", "Existing Asset (information)"),
	f("book_value", "Currency", "Book Value Today", read_only=1),
	f("remaining_years", "Float", "Remaining Depreciation Years", read_only=1),
	f("depreciation_per_year", "Currency", "Depreciation per Year", read_only=1),
	sec("sb_o", "Outcome"),
	f("own_pv", "Currency", "Cost of Buying (today's money)", read_only=1),
	f("lease_pv", "Currency", "Cost of Leasing (today's money)", read_only=1),
	f("cheaper", "Data", "Cheaper Option", read_only=1),
	col("cb_o"),
	f("own_annual", "Currency", "Buying: Equivalent Yearly Cost", read_only=1),
	f("lease_annual", "Currency", "Leasing: Equivalent Yearly Cost", read_only=1),
	f("saving", "Currency", "Saving (today's money)", read_only=1),
	*result_block(),
], autoname="format:LVB-.YYYY.-.#####", icon="fa fa-key", perms=PERMS)

# ------------------------------------------------------------------ profitability
doctype("Profit Row", [
	f("group_name", "Data", "Name", read_only=1, in_list_view=1),
	f("revenue", "Currency", "Revenue", read_only=1, in_list_view=1),
	f("cost", "Currency", "Cost", read_only=1, in_list_view=1),
	f("margin", "Currency", "Margin", read_only=1, in_list_view=1),
	f("margin_pct", "Percent", "Margin %", read_only=1, in_list_view=1),
	f("profit_share_pct", "Percent", "Share of Profit %", read_only=1),
	f("profit_class", "Data", "Class", read_only=1, in_list_view=1, description="A makes 80% of the profit, B the next 15%, C the rest, L loses money."),
	f("rank", "Int", "Rank", read_only=1),
	f("qty", "Float", "Quantity", read_only=1),
], istable=1)

doctype("Stock Health Row", [
	f("item_code", "Link", "Item", options="Item", read_only=1, in_list_view=1),
	f("qty", "Float", "Quantity", read_only=1, in_list_view=1),
	f("value", "Currency", "Value", read_only=1, in_list_view=1),
	f("days_since_move", "Int", "Days Without Movement", read_only=1, in_list_view=1),
	f("cover_days", "Float", "Days of Cover", read_only=1),
	f("health", "Data", "Condition", read_only=1, in_list_view=1),
], istable=1)

doctype("Profitability Analysis", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("from_date", "Date", "From", reqd=1),
	f("to_date", "Date", "To", reqd=1),
	col("cb1"),
	f("group_by", "Select", "Analyse By", options="Item\nCustomer\nItem Group", default="Item"),
	f("slow_days", "Int", "Slow After (days)", default=90),
	f("dead_days", "Int", "Dead After (days)", default=180),
	sec("sb_r", "Profitability"),
	f("rows", "Table", "Profitability", options="Profit Row"),
	f("total_revenue", "Currency", "Total Revenue", read_only=1),
	f("total_margin", "Currency", "Total Margin", read_only=1),
	sec("sb_s", "Stock Health"),
	f("stock_rows", "Table", "Stock Health", options="Stock Health Row"),
	f("tied_up", "Currency", "Money Tied Up in Dead, Slow and Overstocked Items", read_only=1),
	*result_block(),
], autoname="format:PRF-.YYYY.-.#####", icon="fa fa-pie-chart", perms=PERMS)

doctype("Pricing Analysis", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("item_code", "Link", "Item", options="Item", reqd=1),
	f("cost", "Currency", "Unit Cost"),
	f("current_price", "Currency", "Current Price"),
	f("current_qty", "Float", "Current Quantity per Month"),
	col("cb1"),
	f("elasticity", "Float", "Price Elasticity", description="1.5 means a 1% higher price loses 1.5% of the volume. Load Data estimates it from your sales history when the price has varied enough."),
	f("elasticity_note", "Data", "Elasticity Source", read_only=1),
	f("model", "Select", "Demand Model", options="Constant elasticity\nLinear demand", default="Constant elasticity"),
	f("min_price", "Currency", "Lowest Price Allowed"),
	f("max_price", "Currency", "Highest Price Allowed"),
	f("capacity", "Float", "Capacity per Month"),
	f("discount_pct", "Percent", "Discount to Test %"),
	sec("sb_o", "Outcome"),
	f("best_price", "Currency", "Best Price", read_only=1),
	f("expected_qty", "Float", "Expected Quantity per Month", read_only=1),
	f("expected_profit", "Currency", "Expected Profit per Month", read_only=1),
	col("cb_o"),
	f("current_profit", "Currency", "Profit per Month Today", read_only=1),
	f("profit_gain", "Currency", "Gain per Month", read_only=1),
	sec("sb_d", "Discount Test"),
	f("required_uplift_pct", "Percent", "Extra Volume Needed to Break Even %", read_only=1),
	f("discount_expected_qty", "Float", "Expected Quantity at This Discount", read_only=1),
	f("discount_profit_change", "Currency", "Expected Profit Change per Month", read_only=1),
	*result_block(),
], autoname="format:PRC-.YYYY.-.#####", icon="fa fa-tags", perms=PERMS)

# ------------------------------------------------------------------ decision review
doctype("Review Row", [
	f("plan", "Data", "Plan", read_only=1, in_list_view=1),
	f("item_code", "Link", "Item", options="Item", read_only=1, in_list_view=1),
	f("supplier", "Data", "Supplier", read_only=1),
	f("expected", "Float", "Expected", read_only=1, in_list_view=1),
	f("actual", "Float", "What Happened", read_only=1, in_list_view=1),
	f("error", "Float", "Difference", read_only=1, in_list_view=1),
	f("error_pct", "Percent", "Difference %", read_only=1, in_list_view=1),
], istable=1)

doctype("Decision Review", [
	f("company", "Link", "Company", options="Company", reqd=1),
	f("plan_type", "Select", "Plans to Check", options="Reorder Plan\nProduct Mix Plan\nSupplier Allocation Plan", reqd=1, default="Reorder Plan",
		description="Reorder: forecast vs the demand that followed. Product mix: planned vs produced. Supplier allocation: planned price vs the purchase price paid."),
	col("cb1"),
	f("from_date", "Date", "Plans Solved From", reqd=1),
	f("to_date", "Date", "Plans Solved To", reqd=1),
	sec("sb_r", "Comparison"),
	f("rows", "Table", "Comparison", options="Review Row"),
	sec("sb_a", "Accuracy"),
	f("comparisons", "Int", "Comparisons", read_only=1),
	f("wape", "Percent", "Average Error %", read_only=1, description="Total absolute error as a share of what actually happened."),
	f("bias", "Percent", "Bias %", read_only=1, description="Positive: the plans expected too much. Negative: too little."),
	f("tracking_signal", "Float", "Tracking Signal", read_only=1, description="Beyond about +/-4 the plans are drifting one way."),
	f("verdict", "Data", "Verdict", read_only=1),
	*result_block(),
], autoname="format:REV-.YYYY.-.#####", icon="fa fa-check-square-o", perms=PERMS)



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
		if not istable and "track_changes" not in d and name not in ("Room Night Lock", "Production Scan", "Class Attendance"):
			out["track_changes"] = 1  # who changed what, when
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
