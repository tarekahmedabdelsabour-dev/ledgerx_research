import frappe
from frappe import _

from ledgerx_research import bridge, data
from ledgerx_research.plan_base import PlanDocument


class SchedulePlan(PlanDocument):
	RESULT_TABLES = ("rows",)

	@frappe.whitelist()
	def load_data(self):
		ops, warnings = data.load_schedule(self.company)
		self.flags.solving = True
		self.set("operations", ops)
		self.set("rows", [])
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} operations on open work orders. Press Solve.").format(len(ops))], warnings)
		self.save()
		return len(ops)

	@frappe.whitelist()
	def solve(self):
		def run():
			if not self.operations:
				frappe.throw(_("Add operations or press Load Data."))
			res = bridge.run_schedule([{"work_order": o.work_order, "operation": o.operation, "workstation": o.workstation, "sequence": o.sequence, "hours": o.hours,
				"due_date": o.due_date} for o in self.operations], self.start_at, self.hours_per_day, self.objective)
			self.set("rows", res.get("rows", []))
			for k in ("makespan_hours", "lower_bound_hours", "gap_pct", "rule", "total_lateness_hours"):
				self.set(k, res.get(k))
			lines = []
			if res["status"] != "Infeasible":
				lines = [_("All work finishes after {0} working hours; no schedule can finish before {1}.").format(f"{self.makespan_hours:,.1f}", f"{self.lower_bound_hours:,.1f}"),
					_("Best dispatch rule: {0}. Total lateness {1} hours.").format(self.rule, f"{self.total_lateness_hours:,.1f}")]
			self.finish(res, _("Schedule"), lines)
		return self.run_and_save(run)
