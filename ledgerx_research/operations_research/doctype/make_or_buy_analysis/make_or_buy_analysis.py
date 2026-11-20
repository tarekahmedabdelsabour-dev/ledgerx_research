import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, bridge_decisions, data
from ledgerx_research.plan_base import PlanDocument


class MakeorBuyAnalysis(PlanDocument):
	@frappe.whitelist()
	def load_data(self):
		if not self.item_code:
			frappe.throw(_("Choose the item first."))
		mv, bp, warnings = data.load_make_or_buy(self.company, self.item_code)
		self.flags.solving = True
		self.make_variable, self.buy_price = mv, bp
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("Costs read for {0}. Add the yearly volume and the fixed costs, then press Solve.").format(self.item_code)], warnings)
		self.save()
		return 1

	@frappe.whitelist()
	def solve(self):
		def run():
			res = bridge_decisions.run_make_or_buy(self.annual_volume, self.make_fixed, self.make_variable, self.buy_fixed, self.buy_price)
			lines = []
			if res["status"] != "Infeasible":
				self.make_cost, self.buy_cost, self.saving = res["make_cost"], res["buy_cost"], res["saving"]
				self.cheaper = {"make": _("Make"), "buy": _("Buy"), "equal": _("Equal")}[res["cheaper"]]
				self.indifference_volume = res["indifference_volume"] or 0
				self.rule = "" if res["make_cheaper_above"] is None else (_("Making is cheaper above this volume") if res["make_cheaper_above"] else _("Buying is cheaper above this volume"))
				lines = [_("{0} is cheaper by {1} a year").format(self.cheaper, f"{res['saving']:,.2f}")]
			self.finish(res, _("Make or buy"), lines)
		return self.run_and_save(run)
