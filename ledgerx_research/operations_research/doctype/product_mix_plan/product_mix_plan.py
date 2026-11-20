import json

import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, bridge_decisions, data
from ledgerx_research.plan_base import PlanDocument


class ProductMixPlan(PlanDocument):
	RESULT_TABLES = ()
	IGNORE_INPUTS = ("scenarios", "risk_sd_pct", "risk_draws")

	@frappe.whitelist()
	def load_data(self):
		products, resources, warnings = data.load_mix(self.company, int(self.planning_days or 30), bool(self.cap_by_orders))
		self.flags.solving = True
		self.set("products", [{**{k: v for k, v in p.items() if k != "usage"}, "usage_json": json.dumps(p["usage"]), "margin": flt(p["price"]) - flt(p["unit_cost"])} for p in products])
		self.set("resources", resources)
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} products and {1} resources. Review the numbers, then press Solve.").format(len(products), len(resources))], warnings)
		self.save()
		return len(products)

	@frappe.whitelist()
	def solve(self):
		def run():
			rows = [{"item_code": p.item_code, "price": p.price, "unit_cost": p.unit_cost, "min_qty": p.min_qty, "max_qty": p.max_qty, "usage": bridge.loads(p.usage_json)} for p in self.products]
			if not rows:
				frappe.throw(_("Add products or press Load Data."))
			res = bridge.run_mix(rows, [{"resource": r.resource, "available": r.available} for r in self.resources], bool(self.whole_units))
			q, used, slack, shadow = res.get("quantities", {}), res.get("usage", {}), res.get("slack", {}), res.get("shadow", {})
			for p in self.products:
				p.plan_qty = q.get(p.item_code, 0.0)
				p.margin = flt(p.price) - flt(p.unit_cost)
			for r in self.resources:
				r.used, r.slack, r.shadow_price = used.get(r.resource, 0.0), slack.get(r.resource, 0.0), shadow.get(r.resource, 0.0)
			self.objective = res.get("objective", 0.0)
			lines = []
			if res["status"] != "Infeasible":
				lines.append(_("Total margin {0}").format(f"{self.objective:,.2f}"))
				tight = sorted(((s, k) for k, s in shadow.items() if s > 1e-9), reverse=True)
				if tight:
					lines.append(_("Bottleneck: {0} (one more unit adds {1} to the margin)").format(tight[0][1], f"{tight[0][0]:,.4f}"))
				if self.whole_units:
					lines.append(_("Whole-unit plan: values of extra resource units are not shown."))
			self.finish(res, _("Product mix"), lines)
		return self.run_and_save(run)

	@frappe.whitelist()
	def create_draft(self):
		self.require_usable()
		name = data.make_production_plan(self)
		self.db_set("production_plan", name)
		return name

	def _rows(self):
		prods = [{"item_code": p.item_code, "price": p.price, "unit_cost": p.unit_cost, "min_qty": p.min_qty, "max_qty": p.max_qty, "usage": bridge.loads(p.usage_json)} for p in self.products]
		return prods, [{"resource": r.resource, "available": r.available} for r in self.resources]

	def _need_solved(self):
		if self.status not in ("Solved", "Needs Attention") or not self.verified:
			frappe.throw(_("Solve the plan first."))

	@frappe.whitelist()
	def what_if(self):
		"""Re-solves the model for every scenario and finds how far each bottleneck and margin can move before the plan changes."""
		self._need_solved()
		kinds = {"Resource": "resource", "Margin": "margin", "Max Quantity": "max_qty", "Min Quantity": "min_qty"}
		prods, res = self._rows()
		out = bridge_decisions.run_mix_sensitivity(prods, res, [{"name": s.scenario, "kind": kinds.get(s.kind, "resource"), "key": s.key, "pct": s.pct} for s in self.scenarios], bool(self.whole_units))
		self.flags.solving = True
		self.set("scenario_results", [{"scenario": r["scenario"], "total_margin": r["total_margin"], "change": r["change"], "moved": r["moved"]} for r in out.get("rows", [])])
		for r in self.resources:
			rg = out.get("resource_ranges", {}).get(r.resource)
			r.range_low, r.range_high = (rg["low"], rg["high"]) if rg else (0, 0)
		for p in self.products:
			mg = out.get("margin_ranges", {}).get(p.item_code)
			p.margin_low, p.margin_high = (mg["low"], mg["high"]) if mg else (0, 0)
		self.summary_html = bridge.html_summary(_("What-if"), out.get("verified", False), [_("{0} scenarios solved again from scratch.").format(len(out.get("rows", []))),
			_("The bottleneck keeps its value while the resource stays between 'Can Fall To' and 'Can Rise To'.")], out.get("warnings", []))
		if out["status"] == "Infeasible":
			frappe.msgprint("<br>".join(out["warnings"]), title=_("What-if"))
		self.save()
		return out["status"]

	@frappe.whitelist()
	def simulate_risk(self):
		self._need_solved()
		prods, res = self._rows()
		out = bridge_decisions.run_mix_risk(prods, res, self.risk_sd_pct, self.risk_draws or 300, bool(self.whole_units))
		if out["status"] == "Infeasible":
			frappe.throw("<br>".join(out["warnings"]))
		self.flags.solving = True
		self.risk_p5, self.risk_p50, self.risk_p95 = out["p5"], out["p50"], out["p95"]
		self.risk_keep_pct, self.risk_regret = out["keep_plan_possible_pct"], out["avg_regret"] or 0
		self.summary_html = bridge.html_summary(_("Risk"), out["verified"], [_("Total margin: typically {0}, between {1} and {2} in 9 cases out of 10.").format(f"{out['p50']:,.2f}", f"{out['p5']:,.2f}", f"{out['p95']:,.2f}")], out["warnings"])
		self.save()
		return out["status"]
