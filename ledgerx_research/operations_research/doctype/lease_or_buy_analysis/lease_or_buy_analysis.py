import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, bridge_decisions, data
from ledgerx_research.plan_base import PlanDocument


class LeaseorBuyAnalysis(PlanDocument):
	@frappe.whitelist()
	def solve(self):
		def run():
			res = bridge_decisions.run_lease_or_buy(self.price, self.residual, self.life_years, self.rate_pct, self.yearly_cost_own, self.lease_payment, self.lease_years, self.lease_cost_extra)
			lines = []
			if res["status"] != "Infeasible":
				self.own_pv, self.lease_pv, self.own_annual, self.lease_annual, self.saving = res["own_pv"], res["lease_pv"], res["own_annual"], res["lease_annual"], res["saving"]
				self.cheaper = {"buy": _("Buy"), "lease": _("Lease"), "equal": _("Equal")}[res["cheaper"]]
				lines = [_("{0} is cheaper by {1} in today's money").format(self.cheaper, f"{res['saving']:,.2f}")]
			self.finish(res, _("Lease or buy"), lines)
		return self.run_and_save(run)
