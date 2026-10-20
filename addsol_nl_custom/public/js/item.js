// Item form - MS Plate preview, and the finished-goods code.
//
// The weight is worked out on the server by
// addsol_nl_custom.plates.api.get_theoretical_weight, which runs the Item
// Group's own formula. This file only asks for the number and shows it; it
// must never calculate anything itself, or an import or a script and the form
// would disagree.
//
// The code of a finished good is the server's too:
// addsol_nl_custom.finished_goods.item_hooks names the Item from its
// Project. This file only locks the code field and asks for the Project, so
// the user is not invited to type a code that is going to be replaced.

frappe.ui.form.on("Item", {
	refresh: function (frm) {
		if (is_weighed(frm)) {
			show_weight(frm);
			show_create_offcut(frm);
		}
		refresh_finished_good(frm);
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
		refresh_finished_good(frm);
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

// Is this a group that holds finished goods? The server owns the answer, and
// the only reason to ask is so the form can show the right fields.
function refresh_finished_good(frm) {
	const group = frm.doc.item_group;

	if (!group) {
		set_finished_good_fields(frm, false);
		return;
	}

	frappe.call({
		method: "addsol_nl_custom.addsol_nl_custom.finished_goods.api.get_finished_good_info",
		args: { item_group: group },
		callback: function (r) {
			const info = (r && r.message) || {};
			set_finished_good_fields(frm, !!info.is_finished_good);
			if (info.is_finished_good) prefill_project(frm);
		},
	});
}

// The Project of the order this Item was opened from.
//
// A finished good is usually made while the order is being written, and the
// order already knows its Project. The quick entry that opens from an order
// row does not carry it, so it is read back from the form the Item was
// opened from - and it is only a convenience: the server still refuses a
// finished good with no Project.
function prefill_project(frm) {
	if (frm.doc.custom_project) return;

	const project = project_of_the_order();
	if (!project) return;

	frm.set_value("custom_project", project);
}

function project_of_the_order() {
	const link = frappe._from_link;
	const frm = link && (link.frm || (link.field_obj && link.field_obj.frm));
	if (!frm || frm.doctype !== "Sales Order") return null;

	return frm.doc.project || null;
}

function set_finished_good_fields(frm, is_finished_good) {
	// The field arrives with the fixtures. A site where they have not been
	// synced yet has nothing to show and nothing to ask for.
	if (!frm.meta.get_field("custom_project")) return;

	if (is_finished_good) {
		// The code of a finished good is built from its Project, so the field
		// is locked. Typing one is not an error - it is simply replaced - but
		// there is no point offering it.
		frm.set_df_property("item_code", "read_only", 1);
		frm.set_df_property("custom_project", "reqd", 1);
		frm.__finished_good_locked = true;
		return;
	}

	// Only undo what this script put on. A customer who made item_code
	// read-only for their own reasons keeps it that way.
	if (frm.__finished_good_locked) {
		frm.set_df_property("item_code", "read_only", 0);
		frm.__finished_good_locked = false;
	}
	frm.set_df_property("custom_project", "reqd", 0);
}
