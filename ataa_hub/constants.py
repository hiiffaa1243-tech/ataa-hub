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

TIER_BRONZE = "Bronze"
TIER_SILVER = "Silver"
TIER_GOLD = "Gold"
TIER_PLATINUM = "Platinum"
TIER_HONORARY = "Honorary"

# tier -> (default monthly amount in SAR, Arabic label, colour)
PAID_TIERS = {
	TIER_BRONZE: (50, "برونزي", "#B08D57"),
	TIER_SILVER: (100, "فضي", "#9CA3AF"),
	TIER_GOLD: (250, "ذهبي", "#AD8F52"),
	TIER_PLATINUM: (500, "بلاتيني", "#4B5563"),
}

MEMBERSHIP_STATUSES = ("Active", "Payment Pending", "Suspended", "Cancelled")
