import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, bridge_decisions, data
from ledgerx_research.plan_base import PlanDocument


class PricingAnalysis(PlanDocument):
	@frappe.whitelist()
	def load_data(self):
		from ledgerx_research.engine import profit as pf
		d, warnings = data.load_pricing(self.company, self.item_code)
		self.flags.solving = True
		self.cost, self.current_price, self.current_qty = d["cost"], d["price"], d["qty"]
		est = pf.estimate_elasticity(d["points"]) if d["points"] else {"elasticity": None, "reason": "no_sales"}
		if est.get("elasticity") is not None and est["elasticity"] > 0:
			self.elasticity = est["elasticity"]
			self.elasticity_note = _("Estimated from {0} months, fit R2 {1}{2}").format(est["n"], f"{est['r2']:.2f}", "" if est["reliable"] else _(" (weak)"))
		else:
			self.elasticity_note = _("Could not be estimated from history: enter your own figure")
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("Cost, price and monthly quantity were read from the last 12 months. Check the elasticity, then press Solve.")], warnings)
		self.save()
		return 1

	@frappe.whitelist()
	def solve(self):
		def run():
			model = "linear" if self.model == "Linear demand" else "constant"
			res = bridge_decisions.run_pricing(self.cost, self.current_price, self.current_qty, self.elasticity, model, self.min_price, self.max_price, self.capacity, self.discount_pct)
			lines = []
			if res["status"] != "Infeasible":
				b = res["best"]
				self.best_price, self.expected_qty, self.expected_profit, self.current_profit, self.profit_gain = b["price"], b["qty"], b["profit"], b["current_profit"], b["gain"]
				dd = res.get("discount")
				if dd and dd["status"] == "optimal":
					self.required_uplift_pct, self.discount_expected_qty, self.discount_profit_change = dd["required_uplift_pct"], dd.get("expected_qty", 0), dd.get("expected_profit_change", 0)
				else:
					self.required_uplift_pct = self.discount_expected_qty = self.discount_profit_change = 0
				lines = [_("Best price {0} (now {1}): profit per month changes by {2}").format(f"{b['price']:,.2f}", f"{flt(self.current_price):,.2f}", f"{b['gain']:,.2f}")]
			self.finish(res, _("Pricing"), lines)
		return self.run_and_save(run)
