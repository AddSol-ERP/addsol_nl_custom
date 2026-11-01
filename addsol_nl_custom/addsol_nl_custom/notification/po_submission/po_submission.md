<div style="font-family: Arial, sans-serif; font-size: 14px; color: #333; line-height: 1.6;">

    <p>Dear {{ doc.supplier_name }},</p>

    <p>
        Please find attached our Purchase Order
        <strong>{{ doc.name }}</strong>,
        dated {{ frappe.utils.formatdate(doc.transaction_date) }}.
    </p>

    <p>
        Kindly review the Purchase Order and confirm your acceptance.
    </p>

    <p>
        Please ensure that the materials are supplied as per the
        specifications, quantities, rates and terms mentioned in
        the Purchase Order.
    </p>

    <p>
        For any clarification, please contact our purchase department.
    </p>

    <p>
        Regards,<br>
        <strong>Purchase Department</strong><br>
        N L Electromech Private Limited
    </p>

</div>
