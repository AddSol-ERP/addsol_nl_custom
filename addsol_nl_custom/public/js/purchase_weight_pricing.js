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
	// ERPNext's Update Items action can add a row to a submitted PO. The server
	// sets this flag while updating the parent; never try to mutate it from the
	// browser after submission, where Frappe correctly locks child fields.
	if (frm.doc.docstatus === 1) {
		return;
	}
	if (Boolean(row.custom_is_plate) !== is_weight_managed) {
		await frappe.model.set_value(cdt, cdn, "custom_is_plate", is_weight_managed ? 1 : 0);
	}
	if (is_weight_managed) {
		if (RATE_IS_ENTERED.includes(cdt)) {
			await suggest_rate_per_kg(frm, cdt, cdn);
		} else {
			await preview_quotation_weights(frm, cdt, cdn);
		}
	}
	frm.refresh_field("items");
}

// ERPNext's standard Update Items dialog only exposes qty and the per-piece
// rate. Add the plate rate alongside those fields and seed existing rows from
// their saved value. The server endpoint below persists and reprices it.
function extend_purchase_order_update_items_dialog(frm) {
	if (frm.doc.doctype !== "Purchase Order" || !erpnext.utils?.update_child_items) return;
	const original = erpnext.utils.update_child_items;
	if (original.__addsol_rate_per_kg) return;
	erpnext.utils.update_child_items = function (opts) {
		if (opts?.frm?.doc?.doctype !== "Purchase Order") return original.call(this, opts);

		const OriginalDialog = frappe.ui.Dialog;
		frappe.ui.Dialog = function (definition, ...args) {
			if (definition?.title === __("Update Items")) {
				const table = (definition.fields || []).find((field) => field.fieldname === "trans_items");
				if (table) {
					const rowsByName = new Map((frm.doc.items || []).map((row) => [row.name, row]));
					(table.data || []).forEach((row) => {
						const source = rowsByName.get(row.docname);
						row.custom_rate_per_kg = source?.custom_rate_per_kg || "";
						row.custom_unit_weight_kg = source?.custom_unit_weight_kg || source?.item_weight_per_unit || "";
					});
					let dialog;
					const previewRate = async function () {
						const row = this.doc;
						const itemCode = row.item_code;
						const qty = frappe.utils.flt(row.qty);
						const ratePerKg = frappe.utils.flt(row.custom_rate_per_kg);
						if (!itemCode || !qty || !ratePerKg) return;

						let unitWeight = frappe.utils.flt(row.custom_unit_weight_kg);
					if (!unitWeight) {
						const result = await frappe.db.get_value("Item", itemCode, "weight_per_unit");
						if (row.item_code !== itemCode) return;
						unitWeight = frappe.utils.flt(result?.message?.weight_per_unit);
					}
					if (!unitWeight) return;

						const amount = frappe.utils.flt(qty * unitWeight * ratePerKg, 2);
						row.rate = frappe.utils.flt(amount / qty, 6);
						const gridRow = (table.data || []).find((item) =>
							(row.docname && item.docname === row.docname) ||
							(row.name && item.name === row.name) ||
							(row.idx != null && item.idx === row.idx),
						);
					if (gridRow) gridRow.rate = row.rate;
					dialog?.fields_dict?.trans_items?.grid?.refresh();
				};
				const qtyField = table.fields.find((field) => field.fieldname === "qty");
				if (qtyField) qtyField.onchange = previewRate;
					table.fields = [
						...(table.fields || []),
						{
								fieldtype: "Currency",
								fieldname: "custom_rate_per_kg",
								options: "currency",
							label: __("Rate per Kg"),
							precision: 4,
							in_list_view: 1,
							onchange: previewRate,
						},
					];
				}
			}
			dialog = new OriginalDialog(definition, ...args);
			return dialog;
		};
		try {
			return original.call(this, opts);
		} finally {
			frappe.ui.Dialog = OriginalDialog;
		}
	};
	erpnext.utils.update_child_items.__addsol_rate_per_kg = true;
}

// The documents where the buyer TYPES the rate per kg. A Supplier Quotation
// is not one of them: there the rate per kg is worked out from the quoted
// rate, so there is nothing to offer and nothing to type.
const RATE_IS_ENTERED = ["Purchase Order Item", "Purchase Receipt Item"];

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

// The two read-only figures on a Supplier Quotation, filled in as a preview
// of what the server will store.
//
// The quoted rate is never touched. That is the field the buyer is typing
// in, and rewriting it under the cursor would fight them; the server prices
// the line on save, and it has the final word on the rounding.
async function preview_quotation_weights(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.custom_is_plate) return;

	const unit_weight = frappe.utils.flt(row.custom_unit_weight_kg);
	if (!unit_weight) return;

	const quoted_rate = frappe.utils.flt(row.rate);
	if (quoted_rate) {
		await frappe.model.set_value(
			cdt,
			cdn,
			"custom_rate_per_kg",
			frappe.utils.flt(quoted_rate / unit_weight, 4)
		);
	}

	await frappe.model.set_value(
		cdt,
		cdn,
		"custom_est_weight_kg",
		frappe.utils.flt(frappe.utils.flt(row.qty) * unit_weight, 3)
	);
}

// Mirror of plates/purchase.py apply_amount so the buyer sees the effect of a
// new rate per kg without waiting for a save. The server still recomputes on
// validate and has the final word; this is only the preview. Rate precision
// matches RATE_PRECISION there so the two paths do not disagree by a paisa.
const RATE_PRECISION = 6;

function apply_weight_pricing(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.custom_is_plate) return;

	const rate_per_kg = frappe.utils.flt(row.custom_rate_per_kg);
	const qty = frappe.utils.flt(row.qty);
	// The server derives the estimated weight from qty x unit weight just
	// before pricing, so do the same and only fall back to the stored
	// estimate when the unit weight has not been fetched yet.
	const billable_kg =
		frappe.utils.flt(row.custom_unit_weight_kg) * qty ||
		frappe.utils.flt(row.custom_est_weight_kg);
	if (!rate_per_kg || !qty || !billable_kg) return;

	const amount = frappe.utils.flt(billable_kg * rate_per_kg, 2);
	const rate = frappe.utils.flt(amount / qty, RATE_PRECISION);

	// Setting rate fires ERPNext's own handlers, which recalculate amount and
	// the base currency fields for us.
	frappe.model.set_value(cdt, cdn, "price_list_rate", rate);
	frappe.model.set_value(cdt, cdn, "rate", rate);
	frappe.model.set_value(cdt, cdn, "discount_percentage", 0);
	frappe.model.set_value(cdt, cdn, "discount_amount", 0);
	frm.refresh_field("items");
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
			if (frm.doc.doctype === "Purchase Order") extend_purchase_order_update_items_dialog(frm);
			refresh_weight_pricing_flags(frm);
			// `doctype_js` is a dict, so this file owns Purchase Receipt and the
			// attachments panel cannot claim it. It lives in
			// document_attachments.js and is mounted from here. Guarded because
			// script load order is not guaranteed; this runs at form refresh,
			// long after every bundle loads.
			if (window.addsol_document_attachments) {
				window.addsol_document_attachments.mount("Purchase Receipt");
			}
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

// Suppliers can enter the rate per kg on a quotation. A per-plate rate can
// also be entered; preview_quotation_weights derives the equivalent rate.
frappe.ui.form.on("Supplier Quotation", {
	refresh(frm) {
		refresh_weight_pricing_flags(frm);
	},
});

for (const child_doctype of [
	"Purchase Order Item",
	"Purchase Receipt Item",
	"Supplier Quotation Item",
]) {
	frappe.ui.form.on(child_doctype, {
		item_code(frm, cdt, cdn) {
			update_weight_pricing_flag(frm, cdt, cdn);
		},
	});
}

// Live preview of the weight-based price. Purchase Receipt Item is left out
// on purpose: its rate per kg is read-only and copied from the order.
frappe.ui.form.on("Purchase Order Item", {
	custom_rate_per_kg(frm, cdt, cdn) {
		apply_weight_pricing(frm, cdt, cdn);
	},
	// The unit weight can be fetched from the Item just after the rate is
	// suggested, so reprice once it lands as well.
	custom_unit_weight_kg(frm, cdt, cdn) {
		if (frappe.utils.flt(locals[cdt][cdn].custom_rate_per_kg)) {
			apply_weight_pricing(frm, cdt, cdn);
		}
	},
});

// The quotation's figures follow its editable per-kg rate and quantity.
frappe.ui.form.on("Supplier Quotation Item", {
	custom_rate_per_kg(frm, cdt, cdn) {
		apply_weight_pricing(frm, cdt, cdn);
	},
	rate(frm, cdt, cdn) {
		preview_quotation_weights(frm, cdt, cdn);
	},
	qty(frm, cdt, cdn) {
		preview_quotation_weights(frm, cdt, cdn);
	},
});
