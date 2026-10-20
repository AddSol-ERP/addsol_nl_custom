// Sales Order - the finished-goods Project.
//
// A finished good is made for one Project and can only be sold against that
// Project. The server refuses a mismatch
// (addsol_nl_custom.finished_goods.sales_order); this script fills the row's
// Project from the item and says so when the order is for another one, so the
// user is told before they save rather than after.
//
// Nothing here decides anything. The row's Project is what ERPNext posts the
// sale against, so it is the Project the item was made for.

frappe.ui.form.on("Sales Order Item", {
	item_code: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;

		frappe.call({
			method: "addsol_nl_custom.addsol_nl_custom.finished_goods.api.get_finished_good_info",
			args: { item_code: row.item_code },
			callback: function (r) {
				const info = (r && r.message) || {};
				if (!info.is_finished_good) return;

				remember_finished_good(frm, row, info.project);
				fill_row_project(frm, cdn, row, info.project);
				warn_on_mismatch(frm, row.item_code, info.project);
			},
		});
	},
});

frappe.ui.form.on("Sales Order", {
	project: function (frm) {
		// The order's Project changed. Every finished good on it is made for
		// another one, so say so - the rows are not touched, because a row
		// Project set by hand is the user's to keep.
		const rows = finished_goods_on(frm);

		Object.keys(rows).forEach(function (name) {
			if (rows[name] !== frm.doc.project) {
				warn_on_mismatch(frm, name, rows[name]);
			}
		});
	},
});

// The finished goods on this order, and the Project each was made for.
//
// Kept on the form as they are picked, so a change to the order's Project can
// be checked without asking the server about every row again.
function remember_finished_good(frm, row, project) {
	if (!frm.__finished_goods) frm.__finished_goods = {};
	frm.__finished_goods[row.name] = project;
}

function finished_goods_on(frm) {
	return frm.__finished_goods || {};
}

function fill_row_project(frm, cdn, row, project) {
	if (!project) return;
	if (row.project) return;

	frappe.model.set_value("Sales Order Item", cdn, "project", project);
}

function warn_on_mismatch(frm, item_code, project) {
	if (!project) return;
	if (!frm.doc.project) return;
	if (frm.doc.project === project) return;

	frappe.msgprint({
		title: __("Finished good for another Project"),
		message: __("{0} is a finished good for project {1}, but this order is for project {2}.", [
			item_code,
			project,
			frm.doc.project,
		]),
		indicator: "orange",
	});
}
