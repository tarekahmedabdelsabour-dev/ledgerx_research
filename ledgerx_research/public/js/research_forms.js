// Buttons shared by every Operations Research plan: Load Data, Solve, Create Draft.
(function () {
	const PLANS = {
		"Product Mix Plan": { load: true, draft: "production_plan", draftLabel: __("Create Production Plan (draft)"), draftDoctype: "Production Plan" },
		"Reorder Plan": { load: true, draft: "material_request", draftLabel: __("Create Material Request (draft)"), draftDoctype: "Material Request" },
		"Distribution Plan": { load: true, draft: "stock_entry", draftLabel: __("Create Stock Entry (draft)"), draftDoctype: "Stock Entry" },
		"Route Plan": { load: true },
		"Schedule Plan": { load: true },
		"Supplier Allocation Plan": { load: true, draft: "purchase_orders", draftLabel: __("Create Purchase Orders (drafts)"), draftDoctype: "Purchase Order", multi: true },
	};

	function run(frm, method, freeze) {
		return frm.save().then(() => frm.call({ method, doc: frm.doc, freeze: true, freeze_message: freeze }).then((r) => { frm.reload_doc(); return r; }));
	}

	Object.keys(PLANS).forEach((dt) => {
		const cfg = PLANS[dt];
		frappe.ui.form.on(dt, {
			refresh(frm) {
				if (frm.is_new()) return;
				if (cfg.load) frm.add_custom_button(__("Load Data"), () => run(frm, "load_data", __("Reading your data...")), __("Plan"));
				frm.add_custom_button(__("Solve"), () => run(frm, "solve", __("Solving...")).then(() => frappe.show_alert({ message: __("Done"), indicator: "green" })), __("Plan"));
				frm.change_custom_button_type(__("Solve"), __("Plan"), "primary");
				const ok = ["Solved", "Needs Attention"].includes(frm.doc.status) && frm.doc.verified;
				if (cfg.draft && ok && !frm.doc[cfg.draft]) {
					frm.add_custom_button(cfg.draftLabel, () => {
						const go = () => frm.call({ method: "create_draft", doc: frm.doc, freeze: true }).then((r) => {
							frm.reload_doc();
							const names = [].concat(r.message || []);
							frappe.msgprint(__("Draft created: {0}. Review it and submit it yourself.", [names.map((n) => `<a href="/desk/${frappe.router.slug(cfg.draftDoctype)}/${encodeURIComponent(n)}">${n}</a>`).join(", ")]));
						});
						if (frm.doc.status === "Needs Attention") frappe.confirm(__("This plan has notes to read first (see the summary). Create the draft anyway?"), go);
						else go();
					}, __("Plan"));
				}
				if (frm.doc.status === "Draft" && (frm.doc.solved_on || 0)) {
					frm.dashboard.set_headline_alert(__("Inputs changed after the last result: press Solve again."), "orange");
				}
			},
		});
	});
})();
