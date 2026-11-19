import json

import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, data
from ledgerx_research.plan_base import PlanDocument


class ProductMixPlan(PlanDocument):
	RESULT_TABLES = ()

	@frappe.whitelist()
	def load_data(self):
		products, resources, warnings = data.load_mix(self.company, int(self.planning_days or 30), bool(self.cap_by_orders))
		self.flags.solving = True
		self.set("products", [{**{k: v for k, v in p.items() if k != "usage"}, "usage_json": json.dumps(p["usage"]), "margin": flt(p["price"]) - flt(p["unit_cost"])} for p in products])
		self.set("resources", resources)
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} products and {1} resources. Review the numbers, then press Solve.").format(len(products), len(resources))], warnings)
		self.save()
		return len(products)

	@frappe.whitelist()
	def solve(self):
		def run():
			rows = [{"item_code": p.item_code, "price": p.price, "unit_cost": p.unit_cost, "min_qty": p.min_qty, "max_qty": p.max_qty, "usage": bridge.loads(p.usage_json)} for p in self.products]
			if not rows:
				frappe.throw(_("Add products or press Load Data."))
			res = bridge.run_mix(rows, [{"resource": r.resource, "available": r.available} for r in self.resources], bool(self.whole_units))
			q, used, slack, shadow = res.get("quantities", {}), res.get("usage", {}), res.get("slack", {}), res.get("shadow", {})
			for p in self.products:
				p.plan_qty = q.get(p.item_code, 0.0)
				p.margin = flt(p.price) - flt(p.unit_cost)
			for r in self.resources:
				r.used, r.slack, r.shadow_price = used.get(r.resource, 0.0), slack.get(r.resource, 0.0), shadow.get(r.resource, 0.0)
			self.objective = res.get("objective", 0.0)
			lines = []
			if res["status"] != "Infeasible":
				lines.append(_("Total margin {0}").format(f"{self.objective:,.2f}"))
				tight = sorted(((s, k) for k, s in shadow.items() if s > 1e-9), reverse=True)
				if tight:
					lines.append(_("Bottleneck: {0} (one more unit adds {1} to the margin)").format(tight[0][1], f"{tight[0][0]:,.4f}"))
				if self.whole_units:
					lines.append(_("Whole-unit plan: values of extra resource units are not shown."))
			self.finish(res, _("Product mix"), lines)
		return self.run_and_save(run)

	@frappe.whitelist()
	def create_draft(self):
		self.require_usable()
		name = data.make_production_plan(self)
		self.db_set("production_plan", name)
		return name
