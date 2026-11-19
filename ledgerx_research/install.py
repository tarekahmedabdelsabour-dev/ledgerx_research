"""Install and migrate steps. Each is idempotent and a failing step never aborts a migrate."""
import os

import frappe

MODULE = "Operations Research"
FOLDER = "operations_research"
ROLES = ["Research Manager", "Research Analyst"]


def check_app_permission():
	if frappe.session.user == "Administrator":
		return True
	roles = set(frappe.get_roles())
	return bool(roles & set(ROLES + ["System Manager", "Manufacturing Manager", "Stock Manager", "Purchase Manager", "Sales Manager"]))


def after_install():
	_all()


def after_migrate():
	_all()


def _all():
	for fn in (ensure_module, ensure_roles, ensure_custom_fields, ensure_settings, check_solver, refresh_workspace):
		try:
			fn()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"ledgerx_research install step failed: {fn.__name__}")
	frappe.clear_cache()


def ensure_module():
	if not frappe.db.exists("Module Def", MODULE):
		frappe.get_doc({"doctype": "Module Def", "module_name": MODULE, "app_name": "ledgerx_research"}).insert(ignore_permissions=True)


def ensure_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


FIELDS = [
	("Address", "lx_latitude", {"label": "Latitude", "fieldtype": "Float", "precision": "6", "insert_after": "pincode", "description": "Used by route and distribution plans. Example: 30.044420"}),
	("Address", "lx_longitude", {"label": "Longitude", "fieldtype": "Float", "precision": "6", "insert_after": "lx_latitude", "description": "Example: 31.235712"}),
]


def ensure_custom_fields():
	for dt, name, spec in FIELDS:
		if frappe.db.exists("DocType", dt) and not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": name}):
			frappe.get_doc({"doctype": "Custom Field", "dt": dt, "fieldname": name, **spec}).insert(ignore_permissions=True)


def ensure_settings():
	s = frappe.get_doc("OR Settings")
	if not s.company:
		s.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value("Company", {}, "name")
		if s.company:
			s.save(ignore_permissions=True)


def check_solver():
	"""The solvers need numpy and scipy: say so loudly in the error log instead of failing at the first Solve."""
	try:
		from ledgerx_research.engine.common import require_scipy
		require_scipy()
	except Exception:
		frappe.log_error(title="ledgerx_research: scipy is missing", message="Run: ./env/bin/pip install numpy scipy")


def refresh_workspace():
	"""Migrate only re-reads a workspace file that is newer than the saved one: force it."""
	base = os.path.join(frappe.get_app_path("ledgerx_research"), FOLDER)
	for dt in ("number_card", "dashboard_chart"):
		folder = os.path.join(base, dt)
		for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
			if os.path.isdir(os.path.join(folder, name)):
				frappe.reload_doc(FOLDER, dt, name, force=True)
	frappe.reload_doc(FOLDER, "workspace", FOLDER, force=True)
