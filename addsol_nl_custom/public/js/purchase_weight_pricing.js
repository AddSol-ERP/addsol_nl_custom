// Mark weighed grade lines as soon as an Item is selected so fields guarded
// by depends_on: eval:doc.custom_is_plate are visible before the first save.
async function update_weight_pricing_flag(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const item_code = row.item_code;
	const result = item_code
		? await frappe.call({
				method: "addsol_nl_custom.addsol_nl_custom.plates.api.is_weight_managed_item",
				args: { item_code },
			})
		: null;
	if (locals[cdt][cdn].item_code !== item_code) return;

	const is_weight_managed = Boolean(result && result.message);
	if (Boolean(row.custom_is_plate) !== is_weight_managed) {
		await frappe.model.set_value(cdt, cdn, "custom_is_plate", is_weight_managed ? 1 : 0);
	}
	if (is_weight_managed) {
		await suggest_rate_per_kg(frm, cdt, cdn);
	}
	frm.refresh_field("items");
}

// Fill an empty rate per kg with the last one agreed for this item. Never
// overwrites a rate someone has typed - the buyer's figure is the one that
// stands, and this is only here so a repeat order is not typed from scratch.
async function suggest_rate_per_kg(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.item_code || !row.custom_is_plate) return;
	if (frappe.utils.flt(row.custom_rate_per_kg)) return;

	const result = await frappe.call({
		method: "addsol_nl_custom.addsol_nl_custom.plates.api.get_last_rate",
		args: { item_code: row.item_code, supplier: frm.doc.supplier || null },
	});
	// The row may have been retyped onto another item while we waited.
	if (locals[cdt][cdn].item_code !== row.item_code) return;

	const rate = frappe.utils.flt(result && result.message);
	if (rate) {
		await frappe.model.set_value(cdt, cdn, "custom_rate_per_kg", rate);
	}
}

function refresh_weight_pricing_flags(frm) {
	(frm.doc.items || []).forEach((row) => {
		if (row.item_code) {
			update_weight_pricing_flag(frm, row.doctype, row.name);
		}
	});
}

for (const parent_doctype of ["Purchase Order", "Purchase Receipt"]) {
	frappe.ui.form.on(parent_doctype, {
		refresh(frm) {
			refresh_weight_pricing_flags(frm);
		},
		// A different supplier can mean a different going rate, so lines still
		// empty get offered one again.
		supplier(frm) {
			(frm.doc.items || []).forEach((row) => {
				if (row.item_code && row.custom_is_plate) {
					suggest_rate_per_kg(frm, row.doctype, row.name);
				}
			});
		},
	});
}

for (const child_doctype of ["Purchase Order Item", "Purchase Receipt Item"]) {
	frappe.ui.form.on(child_doctype, {
		item_code(frm, cdt, cdn) {
			update_weight_pricing_flag(frm, cdt, cdn);
		},
	});
}
