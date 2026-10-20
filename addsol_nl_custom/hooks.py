app_name = "addsol_nl_custom"
app_title = "Addsol Nl Custom"
app_publisher = "Addition Solutions"
app_description = "Customization done for N L Electromech"
# TODO(publisher): replace with the real Addition Solutions contact address.
app_email = "contact@email.com"
# Must agree with license.txt, which is MIT.
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "addsol_nl_custom",
# 		"logo": "/assets/addsol_nl_custom/logo.png",
# 		"title": "Addsol Nl Custom",
# 		"route": "/addsol_nl_custom",
# 		"has_permission": "addsol_nl_custom.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/addsol_nl_custom/css/addsol_nl_custom.css"
# app_include_js = "/assets/addsol_nl_custom/js/addsol_nl_custom.js"

# include js, css files in header of web template
# web_include_css = "/assets/addsol_nl_custom/css/addsol_nl_custom.css"
# web_include_js = "/assets/addsol_nl_custom/js/addsol_nl_custom.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "addsol_nl_custom/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

doctype_js = {
	# Supporting documents. One script for all four forms, and it reads the
	# allowed types from erpnext_ui.ui_documents.get_attachment_config rather
	# than holding its own list -- the React panel calls the same endpoint, and a
	# duplicated extension list is the one thing that would drift silently.
	"Item": "public/js/item.js",
	"Plate Offcut": "public/js/plate_offcut.js",
	"Purchase Order": "public/js/purchase_weight_pricing.js",
	"Purchase Receipt": "public/js/purchase_weight_pricing.js",
	"Sales Order": "public/js/sales_order.js",
	"Serial No": "public/js/serial_no.js",
	"Stock Entry": "public/js/document_attachments.js",
	"Quality Inspection": "public/js/document_attachments.js",
}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "addsol_nl_custom/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "addsol_nl_custom.utils.jinja_methods",
# 	"filters": "addsol_nl_custom.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "addsol_nl_custom.install.before_install"
# after_install = "addsol_nl_custom.install.after_install"

# install-app never executes patches: it marks them all as completed instead
# (frappe.installer.set_all_patches_as_completed). after_sync is the hook that
# runs at the very end of install_app, after sync_fixtures, so the app's master
# data - role, approver permission, scrap Item Group and Item, Plate Settings
# pointers - is seeded on a fresh site here, and by the post_model_sync patch on
# sites that migrate. The PO child-row layout is also applied after fixture
# sync, so fresh installs and migrations both receive it.
after_sync = [
	"addsol_nl_custom.patches.v1_0.setup_plate_defaults.execute",
	"addsol_nl_custom.patches.v1_0.setup_finished_goods_group.execute",
	"addsol_nl_custom.patches.v1_0.setup_purchase_order_item_layout.execute",
	"addsol_nl_custom.patches.v1_0.setup_supplier_quotation_item_layout.execute",
]
after_migrate = [
	"addsol_nl_custom.patches.v1_0.setup_purchase_order_item_layout.execute",
	"addsol_nl_custom.patches.v1_0.setup_supplier_quotation_item_layout.execute",
]

# Uninstallation
# ------------

# before_uninstall = "addsol_nl_custom.uninstall.before_uninstall"
# after_uninstall = "addsol_nl_custom.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "addsol_nl_custom.utils.before_app_install"
# after_app_install = "addsol_nl_custom.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "addsol_nl_custom.utils.before_app_uninstall"
# after_app_uninstall = "addsol_nl_custom.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "addsol_nl_custom.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Item": {
		# Two rules, and they are told apart by the Item Group. A plate is
		# named from its grade and its size; a finished good is named from the
		# Project it is made for. The plate rule stands down for a finished
		# good (see plates.item_hooks.is_finished_good), and the finished good
		# rule runs last so it has the final say on the name.
		"autoname": [
			"addsol_nl_custom.addsol_nl_custom.plates.item_hooks.item_autoname",
			"addsol_nl_custom.addsol_nl_custom.finished_goods.item_hooks.item_autoname",
		],
		"validate": [
			"addsol_nl_custom.addsol_nl_custom.plates.item_hooks.item_validate",
			"addsol_nl_custom.addsol_nl_custom.finished_goods.item_hooks.item_validate",
		],
		# Reports a finished good another app renamed. Nothing is changed
		# there - the Item is stored by then - but a code this app did not mint
		# is one the project reports will not find.
		"after_insert": "addsol_nl_custom.addsol_nl_custom.finished_goods.item_hooks.item_after_insert",
	},
	"Item Group": {
		"validate": "addsol_nl_custom.addsol_nl_custom.plates.item_group_hooks.item_group_validate",
	},
	# A finished good is made for one Project and can only be sold against
	# that Project. A finished good made before the rule carries no Project
	# and keeps working.
	"Sales Order": {
		"validate": "addsol_nl_custom.addsol_nl_custom.finished_goods.sales_order.sales_order_validate",
	},
	# A plate line on a Supplier Quotation is priced by weight, exactly as on
	# the Purchase Order, and the rate per kg is worked out from the quoted
	# rate. The Purchase Order built from the quotation inherits it.
	"Supplier Quotation": {
		"before_validate": "addsol_nl_custom.addsol_nl_custom.plates.purchase.sq_before_validate",
	},
	# Part D. All three of these stand down while Plate Settings'
	# enable_weight_based_purchasing is off, so they cannot move money on a
	# half-finished deployment.
	"Purchase Order": {
		"before_validate": "addsol_nl_custom.addsol_nl_custom.plates.purchase.po_before_validate",
	},
	"Purchase Receipt": {
		"before_validate": "addsol_nl_custom.addsol_nl_custom.plates.purchase.pr_before_validate",
		"before_submit": "addsol_nl_custom.addsol_nl_custom.plates.purchase.pr_before_submit",
		"on_submit": "addsol_nl_custom.addsol_nl_custom.plates.receipt_meta.apply_receipt_metadata",
	},
	"Purchase Invoice": {
		"before_validate": "addsol_nl_custom.addsol_nl_custom.plates.purchase.pi_before_validate",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"addsol_nl_custom.tasks.all"
# 	],
# 	"daily": [
# 		"addsol_nl_custom.tasks.daily"
# 	],
# 	"hourly": [
# 		"addsol_nl_custom.tasks.hourly"
# 	],
# 	"weekly": [
# 		"addsol_nl_custom.tasks.weekly"
# 	],
# 	"monthly": [
# 		"addsol_nl_custom.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "addsol_nl_custom.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "addsol_nl_custom.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "addsol_nl_custom.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["addsol_nl_custom.utils.before_request"]
# after_request = ["addsol_nl_custom.utils.after_request"]

# Job Events
# ----------
# before_job = ["addsol_nl_custom.utils.before_job"]
# after_job = ["addsol_nl_custom.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"addsol_nl_custom.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# fixtures = [
#     {"doctype": "Client Script", "filters": [["name", "in", ["calculate_estimated_weight"]]]}
# ]

# Fixtures are filtered so this app only manages its own customisations.
# Anything not matched by a filter here is left alone on the site - Frappe's
# fixture import upserts the records present in the file and never deletes the
# records that are missing from it.
#
# Workspace was dropped entirely: all 33 records this app used to export were
# standard ERPNext/Frappe workspaces, none of them built for this customer.
# The `custom/*.json` files (item.json, item_group.json, item_barcode.json)
# were deleted for the same reason - they were a second source of truth for
# Custom Fields that also shipped India Compliance fields. See Part F1.

# DocTypes touched by the MS Plate specification. Used for Property Setters.
SPEC_DOCTYPES = [
	"Item",
	"Item Group",
	"Thickness",
	"Supplier",
	"Batch",
	"Serial No",
	"Purchase Order",
	"Purchase Order Item",
	"Purchase Receipt",
	"Purchase Receipt Item",
	"Purchase Invoice",
	"Purchase Invoice Item",
	"Supplier Quotation Item",
	"Stock Entry",
	"Stock Entry Detail",
	"Job Card",
	"Work Order",
]

fixtures = [
	{"dt": "Custom Field", "filters": [["fieldname", "like", "custom\\_%"]]},
	{"dt": "Property Setter", "filters": [["doc_type", "in", SPEC_DOCTYPES]]},
	# The remaining scripts are the customer's HR scripts, kept after Part A3-A5.
	{
		"dt": "Client Script",
		"filters": [
			["name", "in", ["Employee Self Service", "Shift Regularization", "Employee File Upload"]]
		],
	},
	{
		"dt": "Server Script",
		"filters": [
			[
				"name",
				"in",
				[
					"Attendance Request",
					"Set Biometric ID as employee id",
					"Componsatory Leave request.",
					"Profession Tax Setup",
					"Fetch Shift",
					"Employee File Upload",
				],
			]
		],
	},
	# The two plate formats are ours. "IRS 1099 Form" is a standard=No US
	# regional format and is not. "MPO Format" is the team's Print Format
	# Builder layout: it ships in print_format.json with the two plate columns
	# already in its format_data, because fixture import runs with force=True
	# after every migrate's patch phases - a column the fixture does not carry
	# is wiped again moments after add_plate_columns_to_mpo_format has added it.
	# If the team confirms a different PO format is the one in use, this entry
	# and that patch move together.
	{
		"dt": "Print Format",
		"filters": [["name", "in", ["MPO Format", "Plate Serial Label", "Plate Purchase Receipt"]]],
	},
	{"dt": "Report", "filters": [["module", "=", "Addsol Nl Custom"]]},
	{"dt": "Role", "filters": [["is_custom", "=", 1]]},
	{
		"dt": "Notification",
		"filters": [
			[
				"name",
				"in",
				["notification After Submission Of SO", "Material Request Receipt Notification"],
			]
		],
	},
	"Role Profile",
	"Module Profile",
	"Workflow",
]
