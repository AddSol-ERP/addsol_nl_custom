// Item form - MS Plate preview.
//
// The weight is worked out on the server by
// addsol_nl_custom.plates.api.get_theoretical_weight, which runs the Item
// Group's own formula. This file only asks for the number and shows it; it
// must never calculate anything itself, or an import or a script and the form
// would disagree.

frappe.ui.form.on("Item", {
	refresh: function (frm) {
		if (!is_weighed(frm)) return;

		lock_dimensions_if_used(frm);
		show_weight(frm);
		show_create_offcut(frm);
	},

	custom_thickness_dropdown: function (frm) {
		if (is_weighed(frm)) show_weight(frm);
	},

	custom_length_mm: function (frm) {
		if (is_weighed(frm)) show_weight(frm);
	},

	custom_width_mm: function (frm) {
		if (is_weighed(frm)) show_weight(frm);
	},

	item_group: function (frm) {
		if (is_weighed(frm)) show_weight(frm);
	},
});

function is_weighed(frm) {
	return !!(frm.doc.item_group && frm.doc.custom_thickness_dropdown);
}

// The second way into a Plate Offcut: from the plate's own Item. The form
// opens with this Item filled in, and the serial dropdown then only offers
// this Item's Active plates. The server refuses anything that is not really
// cuttable, whatever brought the form up.
function show_create_offcut(frm) {
	if (frm.is_new()) return;

	frm.add_custom_button(
		__("Create Offcut"),
		() => {
			frappe.new_doc("Plate Offcut", { source_item: frm.doc.name });
		},
		__("Plate")
	);
}

function has_dimensions(frm) {
	return !!(
		frm.doc.item_group &&
		frm.doc.custom_thickness_dropdown &&
		frm.doc.custom_length_mm &&
		frm.doc.custom_width_mm
	);
}

function show_weight(frm) {
	if (!has_dimensions(frm)) {
		frm.set_value("custom_estimated_weight", 0);
		return;
	}

	frappe.call({
		method: "addsol_nl_custom.addsol_nl_custom.plates.api.get_theoretical_weight",
		args: {
			item_group: frm.doc.item_group,
			thickness: frm.doc.custom_thickness_dropdown,
			length_mm: frm.doc.custom_length_mm,
			width_mm: frm.doc.custom_width_mm,
		},
		callback: function (r) {
			if (r && r.message !== undefined) {
				frm.set_value("custom_estimated_weight", r.message);
			}
		},
		error: function () {
			// The server refused - missing MF, unsafe formula, a dimension the
			// formula needs but does not have. It has already messaged the
			// reason, so just clear the stale number.
			frm.set_value("custom_estimated_weight", 0);
		},
	});
}

// The server refuses to resize an Item that is in use, so do not even offer
// the fields once that is the case.
function lock_dimensions_if_used(frm) {
	if (frm.is_new()) {
		["custom_thickness_dropdown", "custom_length_mm", "custom_width_mm"].forEach((f) =>
			frm.set_read_only(f, false)
		);
		return;
	}

	frappe.call({
		method: "addsol_nl_custom.addsol_nl_custom.plates.item_hooks.get_item_has_transactions",
		args: { item_code: frm.doc.name },
		callback: function (r) {
			const locked = !!(r && r.message);
			["custom_thickness_dropdown", "custom_length_mm", "custom_width_mm"].forEach((f) =>
				frm.set_read_only(f, locked)
			);
		},
	});
}
