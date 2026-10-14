// Job Card form - the way into a Plate Cutting Record.
//
// The button only appears when the Job Card's operation is the one named in
// Plate Settings, so a cutting job is not offered on an unrelated operation.

frappe.ui.form.on("Job Card", {
	refresh: function (frm) {
		if (frm.is_new()) return;

		add_record_cutting_button(frm);
	},
});

function add_record_cutting_button(frm) {
	remove_record_cutting_button(frm);

	frappe.call({
		method: "addsol_nl_custom.addsol_nl_custom.plates.api.get_cutting_operation",
		callback: function (r) {
			const cuttingOperation = r && r.message;
			if (!cuttingOperation) return;

			if (frm.doc.operation !== cuttingOperation) return;
			if (frm.doc.status === "Closed" || frm.doc.status === "Cancelled") return;

			frm.add_custom_button(
				__("Record Cutting"),
				function () {
					open_plate_cutting_record(frm);
				},
				__("Plate")
			);
		},
	});
}

function remove_record_cutting_button(frm) {
	if (frm.__record_cutting_button) {
		frm.remove_custom_button(frm.__record_cutting_button, __("Plate"));
		frm.__record_cutting_button = null;
	}
}

function open_plate_cutting_record(frm) {
	frappe.new_doc("Plate Cutting Record", {
		work_order: frm.doc.work_order,
		job_card: frm.doc.name,
	});
}
