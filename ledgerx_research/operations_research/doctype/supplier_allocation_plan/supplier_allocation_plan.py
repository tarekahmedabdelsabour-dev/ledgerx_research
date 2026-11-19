import frappe
from frappe import _

from ledgerx_research import bridge, data
from ledgerx_research.plan_base import PlanDocument


class SupplierAllocationPlan(PlanDocument):
	RESULT_TABLES = ("results",)

	@frappe.whitelist()
	def load_data(self):
		needs, offers, warnings = data.load_allocation(self.company)
		self.flags.solving = True
		self.set("needs", needs)
		self.set("offers", offers)
		self.set("results", [])
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} items needed, {1} offers. Press Solve.").format(len(needs), len(offers))], warnings)
		self.save()
		return len(needs)

	@frappe.whitelist()
	def solve(self):
		def run():
			if not self.needs or not self.offers:
				frappe.throw(_("Add needs and offers or press Load Data."))
			res = bridge.run_allocation([{"item_code": n.item_code, "qty": n.qty} for n in self.needs],
				[{"supplier": o.supplier, "item_code": o.item_code, "price": o.price, "capacity": o.capacity, "moq": o.moq, "lead_days": o.lead_days, "quality": o.quality} for o in self.offers],
				self.max_share_pct, self.max_lead_days, self.min_quality_pct, self.budget, self.supplier_setup_cost)
			self.set("results", [{"supplier": a["supplier"], "item_code": a["item"], "qty": a["qty"], "price": a["price"], "amount": a["amount"], "lead_days": a["lead_days"]} for a in res.get("allocation", [])])
			self.total_cost = res.get("total_cost", 0.0)
			lines = [] if res["status"] == "Infeasible" else [_("Total cost {0} across {1} suppliers").format(f"{self.total_cost:,.2f}", len({r.supplier for r in self.results}))]
			self.finish(res, _("Supplier allocation"), lines)
		return self.run_and_save(run)

	@frappe.whitelist()
	def create_draft(self):
		self.require_usable()
		names = data.make_purchase_orders(self)
		self.db_set("purchase_orders", ", ".join(names))
		return names
