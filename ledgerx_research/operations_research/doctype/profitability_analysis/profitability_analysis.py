import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, bridge_decisions, data
from ledgerx_research.plan_base import PlanDocument


class ProfitabilityAnalysis(PlanDocument):
	RESULT_TABLES = ("rows",)
	IGNORE_INPUTS = ("slow_days", "dead_days")

	@frappe.whitelist()
	def load_data(self):
		rows, warnings = data.load_profitability(self.company, self.from_date, self.to_date, self.group_by)
		self.flags.solving = True
		self.set("rows", [{"group_name": r["name"], "revenue": r["revenue"], "cost": r["cost"], "qty": r["qty"]} for r in rows])
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} rows. Press Solve.").format(len(rows))], warnings)
		self.save()
		return len(rows)

	@frappe.whitelist()
	def solve(self):
		def run():
			res = bridge_decisions.run_profitability([{"name": r.group_name, "revenue": r.revenue, "cost": r.cost, "qty": r.qty} for r in self.rows])
			if res["status"] == "Infeasible":
				self.finish(res, _("Profitability"), [])
				return
			self.set("rows", [{"group_name": r["name"], "revenue": r["revenue"], "cost": r["cost"], "qty": r.get("qty", 0), "margin": r["margin"], "margin_pct": r["margin_pct"],
				"profit_share_pct": r["profit_share_pct"], "profit_class": r["class"], "rank": r["rank"]} for r in res["rows"]])
			self.total_revenue, self.total_margin = res["total_revenue"], res["total_margin"]
			self.finish(res, _("Profitability"), [_("Total margin {0} on revenue {1}").format(f"{res['total_margin']:,.2f}", f"{res['total_revenue']:,.2f}")])
		return self.run_and_save(run)

	@frappe.whitelist()
	def check_stock(self):
		rows = data.load_stock_health(self.company)
		res = bridge_decisions.run_stock_health(rows, self.slow_days, self.dead_days)
		self.flags.solving = True
		cls = {"dead": _("Dead"), "slow": _("Slow"), "overstocked": _("Overstocked"), "healthy": _("Healthy"), "empty": _("Empty")}
		order = {"dead": 0, "slow": 1, "overstocked": 2, "healthy": 3, "empty": 4}
		show = sorted(res["rows"], key=lambda r: (order[r["class"]], -r["value"]))[:500]
		self.set("stock_rows", [{"item_code": r["item"], "qty": r["qty"], "value": r["value"], "days_since_move": min(int(r["days_since_move"]), 9999), "cover_days": r["cover_days"] or 0, "health": cls[r["class"]]} for r in show])
		self.tied_up = res.get("tied_up", 0)
		self.summary_html = bridge.html_summary(_("Stock health"), True, [_("Money tied up in dead, slow and overstocked items: {0}").format(f"{self.tied_up:,.2f}")], res["warnings"])
		self.save()
		return self.tied_up
