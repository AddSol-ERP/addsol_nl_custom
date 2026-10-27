<p>Dear Team,</p>

<p>A Purchase Receipt has been submitted successfully. Please find the details below.</p>

<table>
<tr><td><b>Purchase Receipt No.</b></td><td>{{ doc.name }}</td></tr>
<tr><td><b>Supplier</b></td><td>{{ doc.supplier_name }}</td></tr>
<tr><td><b>Posting Date</b></td><td>{{ doc.posting_date }}</td></tr>
<tr><td><b>Purchase Order</b></td><td>{{ doc.items[0].purchase_order if doc.items else "-" }}</td></tr>
<tr><td><b>Company</b></td><td>{{ doc.company }}</td></tr>
</table>

<p>Please review the Purchase Receipt.</p>

<p><a href="{{ frappe.utils.get_url_to_form(doc.doctype, doc.name) }}">Open Purchase Receipt</a></p>
