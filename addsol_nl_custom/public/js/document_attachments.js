// Supporting documents on transaction forms, in the ERPNext desk.
//
// The React panel and this script are two renderings of ONE contract: both read
// the allowed types from get_attachment_config and both call upload/list/delete
// on erpnext_ui.ui_documents. Neither holds an extension list of its own -- that
// is the one thing that would silently drift, because this file is vanilla desk
// JS and the other is React, so a shared constant was not available to them.
// Only the chrome is written twice; every rule lives on the server.
//
// Images preview straight from `file_url`. `thumbnail_url` is deliberately not
// used: Frappe only fills it when `make_thumbnail()` is called explicitly, and
// nothing calls it on an ordinary save, so it is usually empty. Non-images get
// an icon and a link, because an <iframe> would depend on the browser's PDF
// viewer and does nothing useful for a spreadsheet.
//
// A File is attached BY NAME, so an unsaved document has nothing to attach to.
// This says so rather than offering a button that is guaranteed to fail.

const ATTACH_NS = "erpnext_ui.ui_documents";
const FIELD = "custom_document_attachments";

const IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "webp"];

const ext_of = (name) => (name || "").split(".").pop().toLowerCase();
const is_image = (name) => IMAGE_EXT.includes(ext_of(name));

function escape_html(value) {
	return String(value == null ? "" : value).replace(/[&<>"']/g, (c) =>
		({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
	);
}

function render_panel(frm, config, files) {
	const types = (config && config.types) || [];

	const buttons = types
		.map((type, i) => {
			const accept = (type.extensions || []).map((e) => `.${e}`).join(",");
			const size_mb = type.max_size_mb;
			return `<div style="margin-top:6px">
				<input type="file" class="hidden" data-attach-type="${escape_html(type.type_key)}" accept="${escape_html(accept)}">
				<button class="btn btn-xs btn-default" data-attach-upload="${escape_html(type.type_key)}">
					${escape_html(__("Add"))} ${escape_html(__(type.label))}
				</button>
				<span class="text-muted" style="margin-left:8px;font-size:11px">
					${escape_html(size_mb)} MB &middot; ${escape_html((type.extensions || []).join(", "))}
				</span>
			</div>`;
		})
		.join("");

	const gallery = files.length
		? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin-top:10px">
			${files
				.map((file) => {
					const thumb = is_image(file.file_name)
						? `<img src="${escape_html(file.file_url)}" style="width:100%;height:88px;object-fit:cover;border-radius:4px">`
						: `<div style="height:88px;display:flex;align-items:center;justify-content:center;background:var(--gray-100);border-radius:4px">
							<span class="text-muted">${escape_html(ext_of(file.file_name).toUpperCase())}</span>
						</div>`;
					return `<div style="border:1px solid var(--border-color);border-radius:6px;overflow:hidden;position:relative">
						<a href="${escape_html(file.file_url)}" target="_blank" rel="noreferrer">${thumb}</a>
						<div style="padding:4px 6px;font-size:11px" class="text-muted">${escape_html(file.label)}</div>
						<button class="btn btn-xs btn-link" data-attach-delete="${escape_html(file.name)}"
							style="position:absolute;top:2px;right:2px" title="${escape_html(__("Remove"))}">
							<span class="text-danger" style="font-size:14px;line-height:1">&times;</span>
						</button>
					</div>`;
				})
				.join("")}
		</div>`
		: `<div class="text-muted" style="margin-top:8px">${escape_html(
				__("No documents attached yet."),
			)}</div>`;

	const unsaved = frm.is_new()
		? `<div class="text-muted">${escape_html(
				__("Save the document before attaching files to it."),
			)}</div>`
		: "";

	return `${unsaved}<div style="margin-top:8px">${gallery}</div>${buttons}`;
}

function bind_events(frm, container, doctype) {
	container.querySelectorAll("[data-attach-upload]").forEach((button) => {
		const type_key = button.getAttribute("data-attach-upload");
		const input = container.querySelector(
			`[data-attach-type="${CSS.escape(type_key)}"]`,
		);
		if (!input) return;
		button.onclick = () => input.click();
		input.onchange = () => {
			const file = input.files && input.files[0];
			if (!file) return;
			// Reset so re-picking the SAME file fires onchange again -- a second
			// phone photo with the same name is the common case.
			input.value = "";
			upload_one(frm, doctype, type_key, file);
		};
	});

	container.querySelectorAll("[data-attach-delete]").forEach((button) => {
		button.onclick = () => {
			const file_name = button.getAttribute("data-attach-delete");
			frappe.confirm(__("Remove this document?"), () => {
				frappe.call({
					method: `${ATTACH_NS}.delete_document_attachment`,
					args: { file_name },
					callback: () => {
						frappe.show_alert({ message: __("Removed"), indicator: "green" });
						render(frm, doctype);
					},
					error: (r) => frappe.show_alert({ message: r.message || __("Could not remove."), indicator: "red" }),
				});
			});
		};
	});
}

function upload_one(frm, doctype, type_key, file) {
	frappe.call({
		method: `${ATTACH_NS}.upload_document`,
		type: "upload",
		args: { doctype, docname: frm.doc.name, type_key, file },
		freeze: true,
		callback: () => {
			frappe.show_alert({ message: __("Uploaded"), indicator: "green" });
			render(frm, doctype);
		},
		error: (r) =>
			frappe.show_alert({
				message: r.message || __("Upload failed."),
				indicator: "red",
			}),
	});
}

function render(frm, doctype) {
	const container = frm.get_field(FIELD) && frm.get_field(FIELD).$wrapper[0];
	if (!container) return;

	frappe.call({
		method: `${ATTACH_NS}.get_attachment_config`,
		args: { doctype },
		callback: (config_res) => {
			const config = config_res && config_res.message;
			if (!config) return;
			if (frm.is_new()) {
				frappe.model.set_value(
					doctype,
					frm.doc.name,
					FIELD,
					render_panel(frm, config, []),
				);
				return;
			}
			frappe.call({
				method: `${ATTACH_NS}.list_document_attachments`,
				args: { doctype, docname: frm.doc.name },
				callback: (files_res) => {
					const files = (files_res && files_res.message && files_res.message.files) || [];
					frappe.model.set_value(
						doctype,
						frm.doc.name,
						FIELD,
						render_panel(frm, config, files),
					);
					bind_events(frm, container, doctype);
				},
			});
		},
	});
}

// `doctype_js` is a dict, so a doctype gets exactly ONE script. Purchase Receipt
// already has purchase_weight_pricing.js and Plate Offcut already has
// plate_offcut.js, so this file cannot simply claim them. Those two call
// `mount()` from their own refresh instead; the guard is there because script
// order is not guaranteed, and the call happens at form refresh -- long after
// every bundle has loaded.
window.addsol_document_attachments = {
	mount(doctype) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				render(frm, doctype);
			},
		});
	},
};

["Stock Entry", "Quality Inspection"].forEach((doctype) =>
	window.addsol_document_attachments.mount(doctype),
);