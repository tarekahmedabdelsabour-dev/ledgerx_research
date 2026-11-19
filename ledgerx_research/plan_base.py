"""Shared behaviour of every plan document: solve button flow, stale-result protection, draft guard."""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from .bridge import html_summary

LAYOUT = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}


def _signature(doc):
	"""Values of every field the user types (read-only result fields excluded), child rows included."""
	meta = frappe.get_meta(doc.doctype)
	sig = []
	for df in meta.fields:
		if df.fieldtype in LAYOUT or df.read_only or df.hidden and df.fieldtype != "Code":
			continue
		if df.fieldtype in ("Table", "Table MultiSelect"):
			cm = frappe.get_meta(df.options)
			cols = [c.fieldname for c in cm.fields if c.fieldtype not in LAYOUT and not c.read_only]
			sig.append((df.fieldname, tuple(tuple(str(r.get(c) or "") for c in cols) for r in doc.get(df.fieldname) or [])))
		else:
			sig.append((df.fieldname, str(doc.get(df.fieldname) or "")))
	return tuple(sig)


class PlanDocument(Document):
	# the result fields every subclass clears when the inputs change
	RESULT_TABLES = ()

	def validate(self):
		if self.flags.solving or self.is_new():
			return
		before = self.get_doc_before_save()
		if before and _signature(before) != _signature(self) and self.status != "Draft":
			self.status = "Draft"
			self.verified = 0
			self.summary_html = html_summary(_("Inputs changed"), False, [_("Press Solve again: the earlier result no longer matches the data.")], [])
			for t in self.RESULT_TABLES:
				self.set(t, [])

	def finish(self, result, title, lines):
		"""Writes the common result fields. `result` comes from bridge.run_*."""
		self.status = result["status"]
		self.verified = 1 if result.get("verified") else 0
		self.solved_on = now_datetime()
		self.summary_html = html_summary(title, bool(result.get("verified")), lines, result.get("warnings", []))

	def require_usable(self):
		if self.status not in ("Solved", "Needs Attention") or not self.verified:
			frappe.throw(_("Solve the plan first. A plan that is not verified cannot create documents."))

	def run_and_save(self, fn):
		self.flags.solving = True
		fn()
		self.save()
		return {"status": self.status, "verified": self.verified}
