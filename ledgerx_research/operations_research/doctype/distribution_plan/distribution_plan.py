import frappe
from frappe import _

from ledgerx_research import bridge, data
from ledgerx_research.plan_base import PlanDocument


class DistributionPlan(PlanDocument):
	RESULT_TABLES = ("flows",)

	@frappe.whitelist()
	def load_data(self):
		if not self.item_code:
			frappe.throw(_("Choose the item first."))
		s, d, warnings = data.load_distribution(self.company, self.item_code, bool(self.include_branch_needs))
		self.flags.solving = True
		self.set("sources", s)
		self.set("destinations", d)
		self.set("flows", [])
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} sources and {1} destinations. Press Solve.").format(len(s), len(d))], warnings)
		self.save()
		return len(s)

	@frappe.whitelist()
	def solve(self):
		def run():
			if not self.sources or not self.destinations:
				frappe.throw(_("Add sources and destinations or press Load Data."))
			res = bridge.run_distribution(
				[{"location": s.location, "qty": s.qty, "lat": s.lat, "lng": s.lng} for s in self.sources],
				[{"location": d.location, "demand": d.demand, "lat": d.lat, "lng": d.lng} for d in self.destinations],
				[{"source": ln.source, "destination": ln.destination, "unit_cost": ln.unit_cost, "blocked": ln.blocked} for ln in self.lanes],
				self.cost_per_km, bool(self.allow_shortage))
			self.set("flows", res.get("flows", []))
			self.total_cost = res.get("total_cost", 0.0)
			lines = [] if res["status"] == "Infeasible" else [_("Total shipping cost {0}").format(f"{self.total_cost:,.2f}"), _("{0} shipments").format(len(res["flows"]))]
			self.finish(res, _("Distribution"), lines)
		return self.run_and_save(run)

	@frappe.whitelist()
	def create_draft(self):
		self.require_usable()
		name = data.make_stock_entry(self)
		self.db_set("stock_entry", name)
		return name
