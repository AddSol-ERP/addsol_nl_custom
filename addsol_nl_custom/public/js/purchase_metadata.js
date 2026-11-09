// Receipt attachments remain available; monetary pricing is owned by ERP UI.
frappe.ui.form.on("Purchase Receipt", {
    refresh() {
        window.addsol_document_attachments?.mount("Purchase Receipt");
    }
});
