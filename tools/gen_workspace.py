"""Writes the workspace, sidebar and dock JSON of ledgerx_research. Run from the repo root."""
import json
import os
import uuid

BASE = os.path.join(os.path.dirname(__file__), "..", "ledgerx_research")
TS = "2026-11-19 07:00:00.000000"  # raise this whenever the workspace changes: migrate only re-reads a file that is newer than the saved one
PLANS = ["Product Mix Plan", "Reorder Plan", "Distribution Plan", "Route Plan", "Schedule Plan", "Supplier Allocation Plan"]
CARDS = [(f"{p}s Needing Attention" if not p.endswith("s") else p, p, [[p, "status", "=", "Needs Attention"]], "Count", None) for p in PLANS]
CARDS += [("Solved Plans This Month", "Product Mix Plan", [["Product Mix Plan", "status", "=", "Solved"], ["Product Mix Plan", "solved_on", "Timespan", "this month"]], "Count", None)]
CHARTS = [(f"{p} by Status", p, "Donut", "group", {"by": "status"}) for p in ("Product Mix Plan", "Reorder Plan", "Supplier Allocation Plan")]
GROUPS = [
	("Decisions", None, 0, [
		("Product Mix Plan", "DocType", "Product Mix Plan", "operations_research"), ("Reorder Plan", "DocType", "Reorder Plan", "package-search"),
		("Distribution Plan", "DocType", "Distribution Plan", "truck"), ("Route Plan", "DocType", "Route Plan", "route"),
		("Schedule Plan", "DocType", "Schedule Plan", "calendar-range"), ("Supplier Allocation Plan", "DocType", "Supplier Allocation Plan", "handshake")]),
	("Drafts Created", "file-pen", 0, [
		("Production Plan", "DocType", "Production Plan", "calendar-range"), ("Material Request", "DocType", "Material Request", "package-search"),
		("Purchase Order", "DocType", "Purchase Order", "shopping-cart"), ("Stock Entry", "DocType", "Stock Entry", "package")]),
	("Source Data", "database", 1, [
		("BOM", "DocType", "BOM", "list-tree"), ("Item", "DocType", "Item", "box"), ("Warehouse", "DocType", "Warehouse", "warehouse"), ("Workstation", "DocType", "Workstation", "cpu"),
		("Work Order", "DocType", "Work Order", "clipboard-list"), ("Sales Order", "DocType", "Sales Order", "file-text"), ("Item Price", "DocType", "Item Price", "tag"),
		("Address", "DocType", "Address", "map-pin")]),
	("Setup", "settings", 1, [("OR Settings", "DocType", "OR Settings", "settings")]),
]
TOP = ["Product Mix Plan", "Reorder Plan", "Route Plan", "Supplier Allocation Plan"]


def write(path, data):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as fh:
		json.dump(data, fh, indent=1, ensure_ascii=False)
		fh.write("\n")


def slug(n):
	return n.lower().replace(" ", "_").replace("-", "_")


def write_cards():
	for label, dt, flt, fn, _f in CARDS:
		write(os.path.join(BASE, "operations_research", "number_card", slug(label), slug(label) + ".json"), {
			"creation": TS, "docstatus": 0, "doctype": "Number Card", "document_type": dt, "filters_json": json.dumps(flt), "function": fn,
			"idx": 0, "is_public": 1, "is_standard": 1, "label": label, "modified": TS, "modified_by": "Administrator", "module": "Operations Research",
			"name": label, "owner": "Administrator", "show_percentage_stats": 0, "stats_time_interval": "Daily", "type": "Document Type"})
	for name, dt, typ, kind, x in CHARTS:
		d = {"chart_name": name, "creation": TS, "docstatus": 0, "doctype": "Dashboard Chart", "document_type": dt, "dynamic_filters_json": "",
			"idx": 0, "is_public": 1, "is_standard": 1, "modified": TS, "modified_by": "Administrator", "module": "Operations Research", "name": name,
			"number_of_groups": 0, "owner": "Administrator", "type": typ, "use_report_chart": 0, "y_axis": []}
		if kind == "group":
			d.update({"chart_type": "Group By", "group_by_based_on": x["by"], "group_by_type": "Count", "filters_json": json.dumps(x.get("filters", [])), "timeseries": 0})
		else:
			d.update({"chart_type": "Count", "based_on": x["based_on"], "filters_json": json.dumps(x["filters"]), "time_interval": x.get("interval", "Monthly"),
				"timeseries": 1, "timespan": x.get("timespan", "Last Year")})
		write(os.path.join(BASE, "operations_research", "dashboard_chart", slug(name), slug(name) + ".json"), d)


def main():
	write_cards()
	rid = lambda: uuid.uuid4().hex[:10]
	content = [{"id": rid(), "type": "header", "data": {"text": '<span class="h4"><b>Operations Research</b></span>', "col": 12}}]
	for label, *_r in CARDS:
		content.append({"id": rid(), "type": "number_card", "data": {"number_card_name": label, "col": 3}})
	for name, *_r in CHARTS:
		content.append({"id": rid(), "type": "chart", "data": {"chart_name": name, "col": 6}})
	shortcuts, links = [], []
	for label in TOP:
		content.insert(1 + len(shortcuts), {"id": rid(), "type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
		kind = "DocType"
		sc = {"label": label, "link_to": label, "type": kind}
		if kind == "DocType":
			sc["doc_view"] = "List"
		else:
			sc["is_query_report"] = 1
		shortcuts.append(sc)
	for title, _i, _c, items in GROUPS:
		content.append({"id": rid(), "type": "card", "data": {"card_name": title, "col": 4}})
		links.append({"type": "Card Break", "label": title, "hidden": 0, "is_query_report": 0, "link_count": len(items), "onboard": 0})
		for label, kind, target, _icon in items:
			links.append({"type": "Link", "label": label, "link_type": kind, "link_to": target, "hidden": 0, "is_query_report": 1 if kind == "Report" else 0,
				"onboard": 0, "dependencies": "", "only_for": ""})
	write(os.path.join(BASE, "operations_research", "workspace", "operations_research", "operations_research.json"), {
		"charts": [{"chart_name": c[0], "label": c[0]} for c in CHARTS], "content": json.dumps(content), "creation": TS, "custom_blocks": [], "docstatus": 0, "doctype": "Workspace",
		"for_user": "", "hide_custom": 1, "icon": "calculator", "idx": 1, "is_hidden": 0, "label": "Operations Research", "links": links, "title": "Operations Research", "modified": TS,
		"modified_by": "Administrator", "module": "Operations Research", "name": "Operations Research", "number_cards": [{"label": c[0], "number_card_name": c[0]} for c in CARDS], "owner": "Administrator",
		"parent_page": "", "public": 1, "quick_lists": [], "roles": [], "sequence_id": 23.0, "shortcuts": shortcuts})
	def row(i, label, kind, target, icon, child):
		d = {"child": child, "collapsible": 1, "doctype": "Sidebar Item", "icon": icon, "idx": i, "indent": 0, "keep_closed": 0, "label": label,
			"parentfield": "items", "parenttype": "Sidebar", "show_arrow": 0, "type": "Link"}
		if kind == "URL":
			d.update({"link_type": "URL", "url": target, "open_in_new_tab": 1})
		else:
			d.update({"link_to": target, "link_type": kind})
		return d
	items = [row(1, "Home", "Workspace", "Operations Research", "house", 0)]
	for title, icon, closed, entries in GROUPS:
		if icon:
			items.append({"child": 0, "collapsible": 1, "doctype": "Sidebar Item", "icon": icon, "idx": len(items) + 1, "indent": 1, "keep_closed": closed,
				"label": title, "link_type": "DocType", "parentfield": "items", "parenttype": "Sidebar", "show_arrow": 0, "type": "Section Break"})
		for label, kind, target, ic in entries:
			items.append(row(len(items) + 1, label, kind, target, ic, 1 if icon else 0))
	write(os.path.join(BASE, "sidebar", "operations_research", "operations_research.json"), {"app": "ledgerx_research", "doctype": "Sidebar", "header_icon": "calculator",
		"items": items, "module": "Operations Research", "name": "Operations Research", "standard": 1, "title": "Operations Research"})
	write(os.path.join(BASE, "dock", "operations_research", "operations_research.json"), {"app": "ledgerx_research", "creation": TS, "docstatus": 0, "doctype": "Dock", "idx": 0,
		"items": [{"added": 0, "hidden": 0, "icon": "calculator", "link_to": "Operations Research", "link_type": "Sidebar", "title": "Operations Research"}],
		"modified": TS, "modified_by": "Administrator", "name": "operations_research", "owner": "Administrator", "standard": 1})


main()
