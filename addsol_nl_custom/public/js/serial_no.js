// Serial No form - the way into a Plate Offcut.
//
// An Active plate can be cut straight from its own serial: the button opens a
// new Plate Offcut with this serial already filled in. The server still
// refuses anything that is not a weighed plate sitting in a warehouse; this
// button is only the way in, never the rule.

frappe.ui.form.on("Serial No", {
	refresh: function (frm) {
		if (frm.doc.status !== "Active" || !frm.doc.custom_weight_kg) return;

		frm.add_custom_button(
			__("Create Offcut"),
			() => {
				frappe.new_doc("Plate Offcut", { source_serial_no: frm.doc.name });
			},
			__("Plate")
		);
	},
});
