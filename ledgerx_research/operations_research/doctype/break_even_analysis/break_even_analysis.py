import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, bridge_decisions, data
from ledgerx_research.plan_base import PlanDocument


class BreakEvenAnalysis(PlanDocument):
	RESULT_TABLES = ("sensitivity",)

	@frappe.whitelist()
	def load_data(self):
		if not (self.from_date and self.to_date):
			frappe.throw(_("Choose the history period."))
		fixed = [{"cost_name": r.cost_name, "account": r.account, "amount": r.amount, "is_cash": r.is_cash} for r in self.fixed_costs]
		products, fixed, warnings = data.load_breakeven(self.company, self.from_date, self.to_date, fixed)
		if self.include_depreciation:
			label = _("Depreciation (assets)")
			amount, w = data.depreciation_of_period(self.company, self.from_date, self.to_date)
			warnings.extend(w)
			fixed = [r for r in fixed if r["cost_name"] != label] + [{"cost_name": label, "account": None, "amount": amount, "is_cash": 0}]
		self.flags.solving = True
		self.set("products", products)
		self.set("fixed_costs", fixed)
		self.set("sensitivity", [])
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} products. Add the fixed costs of the same period, then press Solve.").format(len(products))], warnings)
		self.save()
		return len(products)

	@frappe.whitelist()
	def solve(self):
		def run():
			res = bridge_decisions.run_breakeven([{"item_code": p.item_code, "price": p.price, "variable_cost": p.variable_cost, "qty": p.qty} for p in self.products],
				[{"name": r.cost_name, "amount": r.amount, "is_cash": r.is_cash} for r in self.fixed_costs], self.target_profit, self.capacity_units, self.risk_sd_pct)
			self.set("sensitivity", [])
			lines = []
			if res["status"] != "Infeasible":
				o = res["out"]
				by = {r["code"]: r for r in res["per_product"]}
				for p in self.products:
					p.break_even_units = by.get(p.item_code, {}).get("units", 0)
					p.break_even_revenue = by.get(p.item_code, {}).get("revenue", 0)
				self.total_fixed = res["fixed"]
				self.break_even_units, self.break_even_revenue = o["break_even_units"], o["break_even_revenue"]
				self.target_units, self.target_revenue = o["target_units"], o["target_revenue"]
				self.cash_break_even_units = o.get("cash_break_even_units") or 0
				self.margin_of_safety_pct = o.get("margin_of_safety_pct") or 0
				self.operating_leverage = o.get("operating_leverage") or 0
				self.expected_profit = o.get("expected_profit") or 0
				rk = res.get("risk")
				self.loss_probability_pct, self.profit_p5, self.profit_p50, self.profit_p95 = (rk["loss_probability_pct"], rk["p5"], rk["p50"], rk["p95"]) if rk else (0, 0, 0, 0)
				labels = {"price": _("Price"), "variable_cost": _("Variable cost"), "fixed": _("Fixed costs"), "volume": _("Sales volume")}
				self.set("sensitivity", [{"what": labels[r["what"]], "change_pct": r["change_pct"], "break_even_units": r["break_even_units"] or 0, "expected_profit": r["expected_profit"] or 0} for r in res["sensitivity"]])
				lines = [_("Break-even: {0} units, revenue {1}").format(f"{o['break_even_units']:,.0f}", f"{o['break_even_revenue']:,.2f}")]
				if o.get("margin_of_safety_pct") is not None and o.get("expected_units"):
					lines.append(_("Margin of safety {0}%: sales can fall that far before the period makes a loss.").format(f"{o['margin_of_safety_pct']:,.1f}"))
				if o.get("operating_leverage"):
					lines.append(_("Operating leverage {0}: a 1% change in sales changes profit by about {0}%.").format(f"{o['operating_leverage']:,.1f}"))
			self.finish(res, _("Break-even"), lines)
		return self.run_and_save(run)
