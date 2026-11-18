"""Shared names used across the app, so they are spelled once (PRD v2)."""

MODULE = "Ataa Hub"

# ---------------------------------------------------------------- roles (PRD §8)
ROLE_EXECUTIVE = "Executive Director"
ROLE_PROJECT_MANAGER = "Project Manager"
ROLE_ACCOUNTANT = "Donations Accountant"
ROLE_API_CLIENT = "Donation API Client"

APP_ROLES = (ROLE_EXECUTIVE, ROLE_PROJECT_MANAGER, ROLE_ACCOUNTANT, ROLE_API_CLIENT)

# Roles that can see every project (a plain Project Manager is row-restricted)
FULL_VISIBILITY_ROLES = {"System Manager", "Administrator", ROLE_EXECUTIVE, ROLE_ACCOUNTANT}

# ------------------------------------------------------------- funds (PRD §6)
FUND_RESTRICTED = "Restricted"
FUND_UNRESTRICTED = "Unrestricted"
GENERAL_PROJECT_CODE = "GENERAL"
GENERAL_PROJECT_TITLE = "الصندوق العام (غير مقيّد)"

# ------------------------------------------------------- channels (PRD §5.2)
CHANNEL_WEBSITE = "Website"
CHANNEL_ONLINE_STORE = "Online Store"
CHANNEL_POS = "POS"
CHANNEL_BANK_TRANSFER = "Bank Transfer"
CHANNEL_PARTNER = "Partner"

# ------------------------------------------- chart of accounts (PRD §5.3)
# key -> (account name, root type, account type, parent group finder)
# Parent finder: ("name", "Direct Income") looks for that group in the company,
# falling back to the company's root group of the same root type.
ACC_RESTRICTED_INCOME = "restricted_income"
ACC_UNRESTRICTED_INCOME = "unrestricted_income"
ACC_MEMBERSHIP_INCOME = "membership_income"
ACC_TRANSFERS_IN = "fund_transfers_in"
ACC_TRANSFERS_OUT = "fund_transfers_out"
ACC_PROGRAM_EXPENSES = "program_expenses"
ACC_MOYASAR_CLEARING = "moyasar_clearing"
ACC_STORE_CLEARING = "store_clearing"
ACC_POS_CLEARING = "pos_clearing"
ACC_MAIN_BANK = "main_bank"
ACC_CUSTODY = "custody"

ACCOUNTS = {
	ACC_RESTRICTED_INCOME: ("Restricted Donations Income", "Income", "Income Account", "Direct Income"),
	ACC_UNRESTRICTED_INCOME: ("Unrestricted Donations Income", "Income", "Income Account", "Direct Income"),
	ACC_MEMBERSHIP_INCOME: ("Membership Income", "Income", "Income Account", "Direct Income"),
	ACC_TRANSFERS_IN: ("Fund Transfers In", "Income", "Income Account", "Direct Income"),
	ACC_TRANSFERS_OUT: ("Fund Transfers Out", "Income", "Income Account", "Direct Income"),
	ACC_PROGRAM_EXPENSES: ("Project Program Expenses", "Expense", "Expense Account", "Direct Expenses"),
	ACC_MOYASAR_CLEARING: ("Moyasar Clearing", "Asset", "Bank", "Bank Accounts"),
	ACC_STORE_CLEARING: ("Online Store Clearing", "Asset", "Bank", "Bank Accounts"),
	ACC_POS_CLEARING: ("mada POS Clearing", "Asset", "Bank", "Bank Accounts"),
	ACC_MAIN_BANK: ("Main Bank Account", "Asset", "Bank", "Bank Accounts"),
	ACC_CUSTODY: ("Staff Custody", "Asset", "", "Current Assets"),
}

# Accounts whose credit is "donation income" for progress bars (PRD §6.2)
DONATION_INCOME_ACCOUNTS = (ACC_RESTRICTED_INCOME, ACC_UNRESTRICTED_INCOME)

# ------------------------------------------------- modes of payment (PRD §4.3)
# name -> (type, account key, Ataa Settings field for the channel)
MODES_OF_PAYMENT = {
	"Moyasar Online": ("Bank", ACC_MOYASAR_CLEARING, "mop_website"),
	"Online Store": ("Bank", ACC_STORE_CLEARING, "mop_online_store"),
	"mada POS": ("Bank", ACC_POS_CLEARING, "mop_pos"),
	"Bank Transfer": ("Bank", ACC_MAIN_BANK, "mop_bank_transfer"),
	"Partner": ("Bank", ACC_MAIN_BANK, "mop_partner"),
}

# ------------------------------------------------------ memberships (PRD §7.5)
CUSTOMER_GROUP_DONORS = "Donors"
ITEM_GROUP_MEMBERSHIPS = "Memberships"

TIER_MUAZIR = "Muazir"
TIER_MUSANID = "Musanid"
TIER_AOUN = "Aoun"
TIER_ADEED = "Adeed"
TIER_KAREEM = "Kareem"
TIER_DAEM = "Daem"
TIER_HONORARY = "Honorary"

_INFO = "تلقي المعلومات الأساسية عن نشاطات الجمعية بشكل دوري."
_COOPERATE = "التعاون مع الجمعية ومنسوبيها في تحقيق أهدافها."
_TAKE_PART = "إتاحة الفرصة للعضو للمشاركة في أنشطة الجمعية."
_PUBLICATIONS = "الحصول على مطبوعات الجمعية إلكترونياً."
_HALF_TO_PROJECTS = "صرف 50% من قيمة العضوية في مشاريع الجمعية."
_SHARE_NEEDS = "الحصول على نسبة معينة في حال حدوث أي احتياج مالي للجمعية."

# Annual memberships. tier -> (annual amount in SAR, Arabic label, colour, card finish, benefits)
PAID_TIERS = {
	TIER_MUAZIR: (
		1000,
		"المؤازر",
		"#A7ABB1",
		"Silver",
		(
			"إدراج اسم العضو في السجل الخاص بالعضويات بالجمعية.",
			_COOPERATE,
			_TAKE_PART,
			"دعوة خاصة لحضور مناسبات الجمعية الرسمية وفعالياتها المميزة.",
		),
	),
	TIER_MUSANID: (2000, "المساند", "#6B7078", "Graphite", (_INFO, _COOPERATE, _TAKE_PART)),
	TIER_AOUN: (
		5000,
		"العون",
		"#B9BDC3",
		"Silver",
		(_INFO, _COOPERATE, _TAKE_PART, _PUBLICATIONS, _HALF_TO_PROJECTS, _SHARE_NEEDS),
	),
	TIER_ADEED: (
		10000,
		"العضيد",
		"#B49A68",
		"Gold",
		(_INFO, _COOPERATE, _TAKE_PART, _PUBLICATIONS, _HALF_TO_PROJECTS, _SHARE_NEEDS),
	),
	TIER_KAREEM: (
		50000,
		"الكريم",
		"#A8915F",
		"Gold",
		(
			"حق الحضور في اجتماعات الجمعية العمومية دون تصويت.",
			_COOPERATE,
			_INFO,
			_TAKE_PART,
			_PUBLICATIONS,
			_HALF_TO_PROJECTS,
			_SHARE_NEEDS,
		),
	),
	TIER_DAEM: (
		100000,
		"الداعم",
		"#96804F",
		"Gold",
		(
			"حق الحضور والتصويت في الجمعية العمومية وانتخابات مجلس الإدارة.",
			_COOPERATE,
			_INFO,
			_TAKE_PART,
			_PUBLICATIONS,
			_HALF_TO_PROJECTS,
			_SHARE_NEEDS,
		),
	),
}
CARD_FINISHES = ("Silver", "Graphite", "Copper", "Platinum", "Gold")

# Membership card number: fixed prefix + 2-digit year + 10-digit sequence (16 digits)
MEMBERSHIP_NUMBER_PREFIX = "9600"

MEMBERSHIP_STATUSES = ("Active", "Payment Pending", "Suspended", "Cancelled")

# ------------------------------------------ spending workflows (PRD §7.8, §7.9)
DSB_WORKFLOW = "Disbursement Approval"
FAL_WORKFLOW = "Fund Allocation Approval"

STATE_DRAFT = "Draft"
STATE_PENDING_ACCOUNTANT = "Pending Accountant Review"
STATE_PENDING_EXECUTIVE = "Pending Executive Approval"
STATE_APPROVED = "Approved"
STATE_REJECTED = "Rejected"
STATE_PAID = "Paid"

# ------------------------------------------------ role profiles (PRD §8)
# Our roles add Ataa permissions; ERPNext's native roles give access to its own
# doctypes (Project, Journal Entry, Customer...). A Role Profile assigns both at once.
ROLE_PROFILES = {
	"Ataa Accountant": (ROLE_ACCOUNTANT, "Accounts User", "Projects User", "Sales User"),
	"Ataa Project Manager": (ROLE_PROJECT_MANAGER, "Projects User"),
	"Ataa Executive Director": (ROLE_EXECUTIVE, "Projects User", "Auditor"),
}

# Only these roles may change a Project; everyone else with access reads it.
PROJECT_EDITOR_ROLES = {"System Manager", "Administrator", ROLE_PROJECT_MANAGER, "Projects Manager"}
