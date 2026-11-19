import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, data
from ledgerx_research.plan_base import PlanDocument


class ReorderPlan(PlanDocument):
	@frappe.whitelist()
	def load_data(self):
		items, warnings = data.load_reorder(self.company, self.warehouse, int(self.lookback_days or 365), int(self.default_lead_days or 7))
		self.flags.solving = True
		self.set("items", [{"item_code": i["item_code"], "annual_demand": i["annual_demand"], "daily_sd": i["daily_sd"], "lead_days": i["lead_days"], "unit_cost": i["unit_cost"],
			"on_hand": i["on_hand"], "on_order": i["on_order"]} for i in items])
		self._loaded = {i["item_code"]: i for i in items}
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} items with stock movement. Press Solve.").format(len(items))], warnings)
		self.save()
		# the monthly history is large and only needed to forecast: keep it in the cache for the next Solve
		frappe.cache.set_value(f"lx_reorder_hist::{self.name}", {k: v["monthly"] for k, v in self._loaded.items()}, expires_in_sec=3600)
		return len(items)

	def _history(self):
		cached = frappe.cache.get_value(f"lx_reorder_hist::{self.name}")
		if cached:
			return cached
		items, _w = data.load_reorder(self.company, self.warehouse, int(self.lookback_days or 365), int(self.default_lead_days or 7))
		return {i["item_code"]: i["monthly"] for i in items}

	@frappe.whitelist()
	def solve(self):
		def run():
			if not self.items:
				frappe.throw(_("Add items or press Load Data."))
			hist = self._history()
			rows = [{"item_code": i.item_code, "annual_demand": i.annual_demand, "daily_sd": i.daily_sd, "lead_days": i.lead_days, "unit_cost": i.unit_cost,
				"on_hand": i.on_hand, "on_order": i.on_order, "moq": frappe.db.get_value("Item", i.item_code, "min_order_qty") or 0, "monthly": hist.get(i.item_code, [])} for i in self.items]
			res = bridge.run_reorder(rows, {"service_level_pct": self.service_level_pct, "holding_rate_pct": self.holding_rate_pct, "order_cost": self.order_cost,
				"default_lead_days": self.default_lead_days})
			by = {r["item_code"]: r for r in res["rows"]}
			for i in self.items:
				r = by[i.item_code]
				i.abc, i.eoq, i.safety_stock, i.reorder_point, i.order_qty = r["abc"], r["eoq"], r["safety_stock"], r["reorder_point"], r["order_qty"]
				i.lead_days, i.forecast_method, i.forecast_next = r["lead_days"], r["forecast_method"], r["forecast_next"]
			n = sum(1 for i in self.items if flt(i.order_qty) > 0)
			self.finish(res, _("Reorder plan"), [_("{0} of {1} items need an order now.").format(n, len(self.items)),
				_("Policy: order a whole economic quantity whenever stock on hand plus on order falls to the reorder point.")])
		return self.run_and_save(run)

	@frappe.whitelist()
	def create_draft(self):
		self.require_usable()
		name = data.make_material_request(self, self.warehouse)
		self.db_set("material_request", name)
		return name
