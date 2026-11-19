app_name = "ledgerx_research"
app_title = "Operations Research"
app_publisher = "LedgerX"
app_description = "Decision support connected to every LedgerX app: product mix, reorder, distribution, routes, scheduling and supplier allocation, each solved exactly and independently verified"
app_email = "hello@ledgerx.local"
app_license = "mit"

required_apps = ["erpnext"]

add_to_apps_screen = [
	{
		"name": "ledgerx_research",
		"logo": "/assets/ledgerx_research/images/operations_research.svg",
		"title": "Operations Research",
		"route": "/desk/operations-research",
		"has_permission": "ledgerx_research.install.check_app_permission",
	}
]

from ledgerx_research import __version__ as _v  # noqa: E402

app_include_js = [f"/assets/ledgerx_research/js/research_forms.js?v={_v}"]

after_install = "ledgerx_research.install.after_install"
after_migrate = "ledgerx_research.install.after_migrate"
