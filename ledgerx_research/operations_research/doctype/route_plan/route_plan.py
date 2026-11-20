import frappe
from frappe import _
from frappe.utils import flt

from ledgerx_research import bridge, data
from ledgerx_research.plan_base import PlanDocument


class RoutePlan(PlanDocument):
	RESULT_TABLES = ("legs",)

	@frappe.whitelist()
	def load_data(self):
		stops, warnings = data.load_routes(self.company, self.load_basis)
		self.flags.solving = True
		self.set("stops", stops)
		self.set("legs", [])
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Data loaded"), False, [_("{0} deliveries waiting. Enter the depot position and the vehicles, then press Solve.").format(len(stops))], warnings)
		self.save()
		return len(stops)

	@frappe.whitelist()
	def load_vehicles(self):
		vehicles, warnings = data.load_fleet(self.company)
		self.flags.solving = True
		self.set("vehicles", vehicles)
		self.status, self.verified = "Draft", 0
		self.summary_html = bridge.html_summary(_("Vehicles loaded"), False, [_("{0} vehicles. Check the capacity and cost per km, then press Solve.").format(len(vehicles))], warnings)
		self.save()
		return len(vehicles)

	@frappe.whitelist()
	def solve(self):
		def run():
			if not self.stops:
				frappe.throw(_("Add stops or press Load Data."))
			fleet = [{"id": v.vehicle, "capacity": v.capacity, "cost_per_km": v.cost_per_km} for v in self.vehicles]
			if not fleet and not flt(self.vehicle_capacity):
				frappe.throw(_("Enter the vehicle capacity or list the vehicles."))
			res = bridge.run_routes((self.depot_lat, self.depot_lng), [{"stop": s.stop, "lat": s.lat, "lng": s.lng, "demand": s.demand} for s in self.stops],
				self.vehicle_capacity, self.max_vehicles or 0, fleet)
			self.set("legs", res.get("legs", []))
			for k in ("total_km", "lower_bound_km", "gap_pct", "vehicles_used", "total_cost"):
				self.set(k, res.get(k, 0))
			lines = []
			if res["status"] != "Infeasible":
				lines = [_("{0} vehicles, {1} km in total").format(self.vehicles_used, f"{self.total_km:,.1f}")]
				if fleet:
					lines.append(_("Running cost {0}").format(f"{self.total_cost:,.2f}"))
				if res.get("exact"):
					lines.append(_("Solved exactly: no cheaper plan exists for these vehicles."))
				else:
					lines.append(_("No plan can be shorter than {0} km; this one is {1}% above that floor.").format(f"{self.lower_bound_km:,.1f}", f"{self.gap_pct:.1f}"))
			self.finish(res, _("Routes"), lines)
		return self.run_and_save(run)

	@frappe.whitelist()
	def create_draft(self):
		self.require_usable()
		if not self.vehicles:
			frappe.throw(_("List the vehicles first: a trip needs a vehicle."))
		names = data.make_fleet_trips(self)
		self.db_set("fleet_trips", ", ".join(names))
		return names
