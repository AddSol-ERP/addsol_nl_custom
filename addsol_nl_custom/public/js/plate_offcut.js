// Plate Offcut - live offcut weights, the scrap and the piece the order keeps.
//
// The weight formula and the multiplication factor live on the Item Group, so
// the numbers are worked out on the server by
// addsol_nl_custom.plates.api.estimate_offcut_weights - which calls the very
// functions the save calls (cutting.get_offcut_details, cutting.compute_offcut,
// cutting.offcut_totals). This file only asks for them and shows them; it must
// never calculate anything itself, or the preview and the save would disagree.
//
// Scrap is typed here: the operator knows what the job leaves behind, and the
// rest of the plate - the consumed piece - is what the server reports back as
// the weight and value issued against the Project.
//
// Without this file the operator only met these numbers through the save-time
// error "The offcuts ... add up to more than the plate weighs", with nothing on
// screen to say by how much. Now each row carries its weight, the totals sit
// under the table, and a red indicator names the overage while the dimensions
// are still being drawn.

let estimate_seq = 0;

// Typing dimensions fires on every keystroke; asking the server for each one
// would queue replies out of order.
const request_estimate = frappe.utils.debounce((frm) => refresh_estimates(frm), 300);

frappe.ui.form.on("Plate Offcut", {
	// Straight away on load - a reopened draft must show its numbers without
	// the operator having to touch a field first.
	refresh: function (frm) {
		// `doctype_js` is a dict, so this file owns Plate Offcut and the attachments
		// panel cannot claim it. It lives in document_attachments.js and is
		// mounted from here. Guarded because script load order is not
		// guaranteed; this runs at form refresh, long after every bundle loads.
		if (window.addsol_document_attachments) {{
			window.addsol_document_attachments.mount("Plate Offcut");
		}}


		// Only an Active serial can be cut; the server refuses the rest, and
		// this keeps the dropdown from offering plates that cannot be chosen.
		// Opened from an Item, the list narrows to that Item's own serials.
		frm.set_query("source_serial_no", () => {
			const filters = { status: "Active" };
			if (frm.doc.source_item) filters.item_code = frm.doc.source_item;
			return { filters };
		});

		// A reopened draft already holds its shapes, so the diameter columns
		// have to be shown or hidden for what is on file, not only when the
		// operator flips the field.
		(frm.doc.offcuts || []).forEach((row) => {
			toggle_shape_fields(frm, row.doctype, row.name);
		});

		refresh_estimates(frm);
	},

	source_serial_no: function (frm) {
		request_estimate(frm);
	},

	scrap_weight_kg: function (frm) {
		request_estimate(frm);
	},
});

frappe.ui.form.on("Plate Offcut Item", {
	shape: function (frm, cdt, cdn) {
		// Swapping to a circle leaves the rectangle's length and width in
		// place rather than wiping them: a second thought about the shape
		// must not cost the operator the size they had already typed.
		toggle_shape_fields(frm, cdt, cdn);
		request_estimate(frm);
	},

	length_mm: function (frm) {
		request_estimate(frm);
	},

	width_mm: function (frm) {
		request_estimate(frm);
	},

	diameter_mm: function (frm) {
		request_estimate(frm);
	},

	offcuts_add: function (frm, cdt, cdn) {
		toggle_shape_fields(frm, cdt, cdn);
		request_estimate(frm);
	},

	// The row is already gone from frm.doc.offcuts by the time this runs, so
	// re-asking drops its weight out of the total instead of leaving a stale
	// figure standing above the table.
	offcuts_remove: function (frm) {
		request_estimate(frm);
	},
});

function toggle_shape_fields(frm, cdt, cdn) {
	// The grid shows whichever size the shape takes: a circle has a diameter
	// and no sides, a rectangle the other way round. depends_on on the field
	// handles the row form; a grid row needs the same told to it directly.
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row) return;

	const is_circle = row.shape === "Circle";
	const grid_row = frm.fields_dict.offcuts.grid.grid_rows.find((r) => r.doc.name === cdn);
	if (!grid_row) return;

	grid_row.toggle_display("length_mm", !is_circle);
	grid_row.toggle_display("width_mm", !is_circle);
	grid_row.toggle_display("diameter_mm", is_circle);
}

function refresh_estimates(frm) {
	// A submitted document already holds the numbers its save wrote, and asking
	// again would only risk marking a finished document dirty.
	if (frm.doc.docstatus) return;
	if (!frm.doc.source_serial_no) return;

	const rows = (frm.doc.offcuts || []).map((row) => ({
		name: row.name,
		shape: row.shape,
		length_mm: row.length_mm,
		width_mm: row.width_mm,
		diameter_mm: row.diameter_mm,
	}));

	// The reply of an older request must not overwrite a newer one, or the
	// last answer in would win the race and show weights for dimensions the
	// operator has already corrected.
	const seq = ++estimate_seq;

	frappe.call({
		method: "addsol_nl_custom.addsol_nl_custom.plates.api.estimate_offcut_weights",
		args: {
			source_serial_no: frm.doc.source_serial_no,
			rows: rows,
			scrap_weight_kg: frm.doc.scrap_weight_kg,
		},
		callback: function (r) {
			if (seq !== estimate_seq) return;
			if (r && r.message !== undefined) apply_estimate(frm, r.message);
		},
		error: function () {
			// The server refused - a serial it cannot read, a formula it will
			// not run. It has already said why, so drop the stale numbers
			// rather than leave last time's weights standing.
			if (seq !== estimate_seq) return;
			clear_estimate(frm);
		},
	});
}

function apply_estimate(frm, message) {
	if (!message) return;

	// Matched on the row's own name, which comes straight back from the
	// server: a reply can therefore never write a weight onto the wrong line.
	(message.rows || []).forEach((estimate) => {
		const row = (frm.doc.offcuts || []).find((r) => r.name === estimate.name);
		if (!row) return;

		// Setting a value the form already holds is a no-op in
		// frappe.model.set_value, so this does not dirty a document the
		// numbers have not actually moved.
		frappe.model.set_value(row.doctype, row.name, "weight_kg", estimate.weight_kg);
		frappe.model.set_value(
			row.doctype,
			row.name,
			"theoretical_weight_kg",
			estimate.theoretical_weight_kg
		);
		frappe.model.set_value(row.doctype, row.name, "value", estimate.value);
	});

	frm.set_value("total_offcut_weight_kg", message.total_offcut_weight_kg);
	frm.set_value("total_offcut_value", message.total_offcut_value);
	frm.set_value("scrap_value", message.scrap_value);
	frm.set_value("consumed_weight_kg", message.consumed_weight_kg);
	frm.set_value("consumed_value", message.consumed_value);
	frm.set_value("remainder_weight_kg", message.consumed_weight_kg);
	frm.set_value("remainder_value", message.consumed_value);

	// The serial says which plate in code; this says it in words - Item and
	// Batch together - so the operator can see what they picked without
	// opening it. It rides back on the same reply rather than its own call,
	// so it can never disagree with the weights beside it.
	frm.set_value("source_plate_text", message.source_plate_text || "");

	frm.refresh_field("offcuts");

	// over_by_kg is already judged against the same tolerance the save uses,
	// so this lights up exactly when the save would refuse - never a gram
	// earlier or later.
	if (message.over_by_kg > 0) {
		frm.page.set_indicator(__("Over by {0} kg", [flt(message.over_by_kg, 3)]), "red");
	} else {
		frm.page.clear_indicator();
	}
}

function clear_estimate(frm) {
	frm.page.clear_indicator();

	(frm.doc.offcuts || []).forEach((row) => {
		frappe.model.set_value(row.doctype, row.name, "weight_kg", 0);
		frappe.model.set_value(row.doctype, row.name, "theoretical_weight_kg", 0);
		frappe.model.set_value(row.doctype, row.name, "value", 0);
	});

	[
		"total_offcut_weight_kg",
		"total_offcut_value",
		"scrap_value",
		"consumed_weight_kg",
		"consumed_value",
		"remainder_weight_kg",
		"remainder_value",
	].forEach((field) => frm.set_value(field, 0));

	// A name is words, not a number - blank it rather than zero it, or the
	// form would read "0" where the plate used to be named.
	frm.set_value("source_plate_text", "");
	frm.refresh_field("offcuts");
}
