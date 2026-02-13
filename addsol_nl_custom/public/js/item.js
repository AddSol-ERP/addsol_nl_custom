frappe.ui.form.on('Item', {
    refresh: function(frm) {
        // Refresh estimated weight
        calculate_estimated_weight(frm);
    },
    
    custom_length_mm: function(frm) {
        calculate_estimated_weight(frm);
    },
    
    custom_width_mm: function(frm) {
        calculate_estimated_weight(frm);
    },
    
    custom_thickness_mm: function(frm) {
        calculate_estimated_weight(frm);
    },
    
    item_group: function(frm) {
        calculate_estimated_weight(frm);
    }
});

function calculate_estimated_weight(frm) {
    let length = parseFloat(frm.doc.custom_length_mm) || 0;
    let width = parseFloat(frm.doc.custom_width_mm) || 0;
    let thickness = parseFloat(frm.doc.custom_thickness_mm) || 0;
    
    if (!frm.doc.item_group) {
        frm.set_value('custom_estimated_weight', 0);
        return;
    }
    
    if (!length && !width && !thickness) {
        frm.set_value('custom_estimated_weight', 0);
        return;
    }
    
    frappe.db.get_value('Item Group', frm.doc.item_group, ['custom_multiplication_factor', 'custom_formula'])
        .then(function(r) {
            if (!r || !r.message) {
                console.warn('No data returned for Item Group:', frm.doc.item_group);
                frm.set_value('custom_estimated_weight', 0);
                return;
            }
            
            console.log('Fetched Item Group data:', r);
            
            let multiplication_factor = parseFloat(r.message.custom_multiplication_factor) || 0;
            let formula = r.message.custom_formula || '';
            
            console.log('Multiplication factor:', multiplication_factor);
            console.log('Formula:', formula);
            
            if (!multiplication_factor) {
                console.warn('No multiplication factor found for Item Group:', frm.doc.item_group);
                frm.set_value('custom_estimated_weight', 0);
                return;
            }
            
            let estimated_weight = 0;
            
            try {
                switch(formula) {
                    case '(L * W * T * MF) / 100000':
                        if (length && width && thickness) {
                            estimated_weight = (length * width * thickness * multiplication_factor) / 100000;
                        }
                        break;
                    
                    case '(L * W * MF) / 10000':
                        if (length && width) {
                            estimated_weight = (length * width * multiplication_factor) / 10000;
                        }
                        break;
                    
                    case '(L * T * MF) / 10000':
                        if (length && thickness) {
                            estimated_weight = (length * thickness * multiplication_factor) / 10000;
                        }
                        break;
                    
                    case '(W * T * MF) / 10000':
                        if (width && thickness) {
                            estimated_weight = (width * thickness * multiplication_factor) / 10000;
                        }
                        break;
                    
                    default:
                        if (length && width && thickness) {
                            estimated_weight = (length * width * thickness * multiplication_factor) / 100000;
                        }
                }
                
                estimated_weight = Math.round(estimated_weight * 1000) / 1000;
                
                console.log('Calculated estimated weight:', estimated_weight);
                frm.set_value('custom_estimated_weight', estimated_weight);
                
            } catch (error) {
                console.error('Error in calculation:', error);
                frm.set_value('custom_estimated_weight', 0);
            }
        })
        .catch(function(err) {
            console.error('Error fetching Item Group data:', err);
            frm.set_value('custom_estimated_weight', 0);
        });
}