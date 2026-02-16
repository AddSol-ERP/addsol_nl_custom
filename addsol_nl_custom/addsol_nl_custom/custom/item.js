frappe.ui.form.on('Item', {
	custom_thickness_dropdown: function(frm) {
		update_item_name(frm);
	},
	
	item_group: function(frm) {
		update_item_name(frm);
	},
	
	refresh: function(frm) {
		// Update on refresh if thickness is set
		if (frm.doc.custom_thickness_dropdown) {
			update_item_name(frm);
		}
	}
});

function update_item_name(frm) {
	// Only update if thickness dropdown has a value
	if (frm.doc.custom_thickness_dropdown && frm.doc.item_group) {
		// Fetch the thickness value
		frappe.db.get_value('Thickness', frm.doc.custom_thickness_dropdown, 'thickness_value', function(r) {
			if (r && r.thickness_value) {
				let new_name = frm.doc.item_group + '-' + r.thickness_value;
				
				// Update item_code
				if (frm.doc.item_code !== new_name) {
					frm.set_value('item_code', new_name);
				}
				
				// Update item_name
				if (frm.doc.item_name !== new_name) {
					frm.set_value('item_name', new_name);
				}
			}
		});
	}
}