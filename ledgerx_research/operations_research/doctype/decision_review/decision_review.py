import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, bridge_decisions, data
from ledgerx_research.plan_base import PlanDocument


class DecisionReview(PlanDocument):
	RESULT_TABLES = ("rows",)

	@frappe.whitelist()
	def load_data(self):
		rows, warnings = data.load_review(self.company, self.plan_type, self.from_date, self.to_date)
		self.flags.solving = True
		self.set("rows", [{"plan": r["plan"], "item_code": r["item_code"], "supplier": r.get("supplier"), "expected": r["expected"], "actual": r["actual"]} for r in rows])
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} comparisons. Press Solve.").format(len(rows))], warnings)
		self.save()
		return len(rows)

	@frappe.whitelist()
	def solve(self):
		def run():
			res = bridge_decisions.run_review([{"plan": r.plan, "item": r.item_code, "expected": r.expected, "actual": r.actual} for r in self.rows])
			lines = []
			if res["status"] != "Infeasible":
				for r, o in zip(self.rows, res["rows"]):
					r.error, r.error_pct = o["error"], o["error_pct"]
				ov = res["overall"]
				self.comparisons, self.wape, self.bias, self.tracking_signal = ov["n"], ov.get("wape") or 0, ov.get("bias") or 0, ov.get("tracking_signal") or 0
				self.verdict = {"reliable": _("Reliable"), "usable": _("Usable with a buffer"), "unreliable": _("Unreliable"), "no_data": _("No data")}[ov["verdict"]]
				lines = [_("Verdict: {0}. Average error {1}%, bias {2}%.").format(self.verdict, f"{self.wape:,.1f}", f"{self.bias:,.1f}")]
			self.finish(res, _("Decision review"), lines)
		return self.run_and_save(run)
