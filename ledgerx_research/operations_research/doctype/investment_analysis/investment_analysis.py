import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, bridge_decisions, data
from ledgerx_research.plan_base import PlanDocument


class InvestmentAnalysis(PlanDocument):
	@frappe.whitelist()
	def solve(self):
		def run():
			res = bridge_decisions.run_investment([{"year": c.year, "amount": c.amount} for c in self.cash_flows], self.discount_rate_pct, self.risk_sd_pct)
			lines = []
			if res["status"] != "Infeasible":
				self.npv = res["npv"]
				self.irr_pct = (res["irr"] or 0) * 100
				self.payback_years = res["payback_years"] or 0
				self.discounted_payback_years = res["discounted_payback_years"] or 0
				self.profitability_index = res["profitability_index"] or 0
				self.decision = _("Accept: it earns more than the required return") if res["decision"] == "accept" else _("Reject: it earns less than the required return")
				self.loss_probability_pct, self.npv_p5, self.npv_p95 = res.get("loss_probability_pct", 0), res.get("npv_p5", 0), res.get("npv_p95", 0)
				lines = [self.decision, _("Net present value {0}").format(f"{res['npv']:,.2f}")]
			self.finish(res, _("Investment"), lines)
		return self.run_and_save(run)
