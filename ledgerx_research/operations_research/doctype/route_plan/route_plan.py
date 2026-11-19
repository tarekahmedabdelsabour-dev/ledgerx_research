import frappe
from frappe import _

from ledgerx_research import bridge, data
from ledgerx_research.plan_base import PlanDocument


class RoutePlan(PlanDocument):
	RESULT_TABLES = ("legs",)

	@frappe.whitelist()
	def load_data(self):
		stops, warnings = data.load_routes(self.company)
		self.flags.solving = True
		self.set("stops", stops)
		self.set("legs", [])
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} deliveries waiting. Enter the depot position and the vehicle capacity, then press Solve.").format(len(stops))], warnings)
		self.save()
		return len(stops)

	@frappe.whitelist()
	def solve(self):
		def run():
			if not self.stops:
				frappe.throw(_("Add stops or press Load Data."))
			res = bridge.run_routes((self.depot_lat, self.depot_lng), [{"stop": s.stop, "lat": s.lat, "lng": s.lng, "demand": s.demand} for s in self.stops],
				self.vehicle_capacity, self.max_vehicles or 0)
			self.set("legs", res.get("legs", []))
			for k in ("total_km", "lower_bound_km", "gap_pct", "vehicles_used"):
				self.set(k, res.get(k, 0))
			lines = []
			if res["status"] != "Infeasible":
				lines = [_("{0} vehicles, {1} km in total").format(self.vehicles_used, f"{self.total_km:,.1f}"),
					_("No plan can be shorter than {0} km; this one is {1}% above that floor.").format(f"{self.lower_bound_km:,.1f}", f"{self.gap_pct:.1f}")]
			self.finish(res, _("Routes"), lines)
		return self.run_and_save(run)
