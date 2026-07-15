import os
import json
import base64
import tempfile
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, html, dcc, dash_table, Input, Output, State, ctx
from dash.exceptions import PreventUpdate
from dotenv import load_dotenv
from supabase import create_client

from auth import sign_in_user, sign_up_user, sign_out_user

from pages.ftir_page import layout as ftir_layout
from pages.lab_page import layout as lab_layout
from pages.resources_page import layout as resources_layout
from pages.about_page import layout as about_layout

load_dotenv()



# DATA PLAN:
# CSV = temporary mock data for dashboard testing
# PostgreSQL = real data storage for dashboard, with Supabase used only for login/signup/authentication
# Supabase = login/signup/authentication and access request workflow
USE_POSTGRES = os.getenv("USE_POSTGRES", "false").strip().lower() in {"1", "true", "yes", "on"}

# TEMP ROLE TESTING:
# This lets us test the different dashboard views before we create real role tables.
# Later, this should come from Supabase/PostgreSQL instead of being hardcoded.
#
# IMPORTANT:
# Admins should NOT need an access_requests row because they are not farmers/site users.
# If your email is in ADMIN_EMAILS, the login callback skips the access-request check.

# Local fallback admins for testing.
# Add/remove emails here while prototyping.
LOCAL_ADMIN_EMAILS = [
    "trevell.pruitt@gmail.com",
    "trevell.pruitt8@gmail.com",
]

# Optional config file: config/admins.json
# Example file content:
# {
#   "admin_emails": [
#     "trevell.pruitt@gmail.com"
#   ]
# }
CONFIG_ADMIN_EMAILS = []
try:
    admin_config_path = Path(__file__).resolve().parent / "config" / "admins.json"
    if admin_config_path.exists():
        with open(admin_config_path, "r") as f:
            ADMIN_CONFIG = json.load(f)
        CONFIG_ADMIN_EMAILS = ADMIN_CONFIG.get("admin_emails", [])
except Exception as e:
    print(f"Could not load config/admins.json: {e}")
    CONFIG_ADMIN_EMAILS = []

# Optional .env admin emails.
# Supports either:
# ADMIN_EMAIL=trevell.pruitt@gmail.com
# or
# ADMIN_EMAILS=trevell.pruitt@gmail.com,other.admin@gmail.com
ENV_ADMIN_EMAILS = []
for env_key in ["ADMIN_EMAIL", "ADMIN_EMAILS"]:
    raw_value = os.getenv(env_key, "")
    if raw_value:
        ENV_ADMIN_EMAILS.extend([email.strip() for email in raw_value.split(",")])

ADMIN_EMAILS = sorted({
    str(email).lower().strip()
    for email in (LOCAL_ADMIN_EMAILS + CONFIG_ADMIN_EMAILS + ENV_ADMIN_EMAILS)
    if str(email).strip()
})

print("Loaded admin emails:", ADMIN_EMAILS)

BASE_DIR = Path(__file__).resolve().parent / "data"

# Public/general dashboard data stays on the original mock statewide CSV.
PUBLIC_CSV_PATH = BASE_DIR / "hsh_mock_synthetic_database_new.csv"

# Private My Data / Admin Preview time-series data uses the mentor-style master CSV.
# Put this file in your project data/ folder.
TIMESERIES_CSV_PATH = BASE_DIR / "synthetic_hsh_master_timeseries_examples.csv"

# The time-series CSV stores the 0-1 Soil Health Score here.
# We rename this to "shs" internally so the rest of the dashboard can reuse existing code.
# Use the official v4 raw Soil Health Score.
# The CSV loader also supports the older v4_shs_cdf name as a temporary fallback.
TIMESERIES_SHS_COLUMN = "v4_shs_raw"
TIMESERIES_SHS_FALLBACK_COLUMNS = ["v4_shs_raw", "v4_shs_cdf", "shs"]

DATABASE_URL = os.getenv("DATABASE_URL")
POSTGRES_SCHEMA = os.getenv("POSTGRES_SCHEMA", "public")
POSTGRES_TABLE = os.getenv("POSTGRES_TABLE", "soil_samples")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in your .env file.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


REQUIRED_COLUMNS = [
    "SH_1",
    "site_name",
    "plot_name",
    "latitude",
    "longitude",
    "shs",
    "minerals",
    "order",
    "suborder",
    "great_group",
    "PIAL_none",
    "management_category",
    "current_land_use",
    "most_previous_land_use",
]

# The farm/project value saved in Supabase access_requests.farm_name
# should match this dashboard column.
# You confirmed SH_1 is the unique identifier for the soil data.
FARM_ID_COLUMN = "SH_1"
SITE_NAME_COLUMN = "site_name"
PLOT_NAME_COLUMN = "plot_name"
SAMPLE_DATE_COLUMN = "date_sampled"


# Data reuse choices shown to users during signup and in Privacy Settings.
# Supabase stores the short value. The dashboard shows the plain-English label.
DATA_REUSE_OPTIONS = [
    {
        "label": "Unrestricted reuse of non-aggregated data with geolocation.",
        "value": "non_aggregated_with_geolocation",
    },
    {
        "label": "Default: Unrestricted reuse of non-aggregated data without geolocation.",
        "value": "non_aggregated_without_geolocation",
    },
    {
        "label": "Unrestricted reuse of aggregated data (for example: mean values across multiple sites) without geolocation.",
        "value": "aggregated_without_geolocation",
    },
    {
        "label": "Restricted reuse of data without geolocation for University of Hawaiʻi S(HEE)R Lab research only, no commercial use by third parties.",
        "value": "uh_research_only",
    },
    {
        "label": "Restricted reuse only with data provider permissions. Please contact a specific data provider for permission. If contact cannot be made specify what happens here.",
        "value": "permission_required",
    },
]

DATA_REUSE_DISPLAY = {option["value"]: option["label"] for option in DATA_REUSE_OPTIONS}
DEFAULT_DATA_REUSE_PERMISSION = "non_aggregated_without_geolocation"


MINERAL_MAP = {
    "HAC": "High Activity Clay",
    "LAC": "Low Activity Clay",
    "PNCM": "Poorly or Non-Crystalline",
    "HIST": "Organic",
    "Sand": "Sand",
}

LAND_USE_DISPLAY_MAP = {
    "Cropland": "Annual cropland",
    "crop land": "Annual cropland",
    "horticulutral and vegetable": "Annual cropland",
    "Cropland-banana": "Annual cropland",
    "Pineapple or sugarcane plantation": "Annual cropland",
    "Plantain": "Annual cropland",
    "Platano": "Annual cropland",
    "Mal": "Annual cropland",
    "Orchard": "Orchard",
    "Pasture": "Pasture",
    "Unmanaged pasture": "Pasture",
    "Managed pasture": "Pasture",
    "Protected forest": "Forest",
    "Unmanaged forest": "Forest",
    "Managed forest": "Forest",
    "Agroforestry": "Agroforestry",
    "Silvopasture": "Agroforestry",
    "Unmanaged/abandoned": "Unmanaged, abandoned",
    "Unmanaged/abandoned ag land": "Unmanaged, abandoned",
    "City/state park": "City/state park",
}


BOX_GROUP_ORDER = ["Conventional", "Organic", "Abandoned", "Pasture", "Forest"]

LAND_USE_COVERAGE_ORDER = [
    "Annual cropland",
    "Forest",
    "Orchard",
    "Pasture",
    "Agroforestry",
    "Unmanaged, abandoned",
    "City/state park",
]

MINERAL_COVERAGE_ORDER = [
    "High Activity Clay",
    "Low Activity Clay",
    "Poorly or Non-Crystalline",
    "Organic",
    "Sand",
]


GREEN = "#156f34"
DARK_GREEN = "#0c5527"
BLUE = "#6366f1"
LIGHT_BG = "#f7f9f6"
CARD_BORDER = "1px solid #dfe5df"


def clean_pial_status(value):
    if pd.isna(value):
        return "No PIAL"

    value = str(value).strip().lower()

    if value in ["pial", "yes", "y"]:
        return "PIAL"

    if value in ["no", "none", "no pial", "non-pial"]:
        return "No PIAL"

    return "Other"


def make_box_land_use_group(row):
    management = str(row.get("management_category", "")).lower()
    land_use = str(row.get("current_land_use", "")).lower()

    if "organic" in management and "conventional" not in management:
        return "Organic"
    if "conventional" in management:
        return "Conventional"
    if "abandon" in management or "abandon" in land_use:
        return "Abandoned"
    if "pasture" in management or "pasture" in land_use:
        return "Pasture"
    if "forest" in management or "forest" in land_use:
        return "Forest"

    return pd.NA


def clean_dashboard_data(df):
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()

    df["SH_1"] = df["SH_1"].astype(str).str.strip()
    df = df[(df["SH_1"] != "") & (df["SH_1"].str.lower() != "nan")]

    df["shs"] = pd.to_numeric(df["shs"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    text_cols = [c for c in REQUIRED_COLUMNS if c not in ["SH_1", "shs", "latitude", "longitude"]]
    for col in text_cols:
        df[col] = df[col].astype("string").str.strip()
        df[col] = df[col].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})

    if "mineral_class" not in df.columns:
        df["mineral_class"] = df["minerals"]

    if "land_use_display" not in df.columns:
        df["land_use_display"] = df["current_land_use"]

    if SAMPLE_DATE_COLUMN in df.columns:
        df[SAMPLE_DATE_COLUMN] = pd.to_datetime(df[SAMPLE_DATE_COLUMN], errors="coerce")

    df["pial_status"] = df["PIAL_none"].apply(clean_pial_status)
    df["box_land_use_group"] = df.apply(make_box_land_use_group, axis=1)

    return df


def add_display_columns(df):
    """Add cleaned display columns used by charts, tables, and filters."""
    df = df.copy()

    if "minerals" in df.columns:
        df["mineral_class"] = df["minerals"].map(MINERAL_MAP).fillna(df["minerals"])
    else:
        df["minerals"] = pd.NA
        df["mineral_class"] = pd.NA

    if "current_land_use" in df.columns:
        df["land_use_display"] = (
            df["current_land_use"]
            .map(LAND_USE_DISPLAY_MAP)
            .fillna(df["current_land_use"])
        )
    else:
        df["current_land_use"] = pd.NA
        df["land_use_display"] = pd.NA

    return df


def load_public_data_from_csv():
    """Load the old/general public CSV. This keeps the public dashboard unchanged."""
    if not os.path.exists(PUBLIC_CSV_PATH):
        raise FileNotFoundError(f"Could not find {PUBLIC_CSV_PATH}")

    # Your original public mock file has a units/notes row first, then headers.
    df = pd.read_csv(PUBLIC_CSV_PATH, header=1)
    df.columns = [str(c).strip() for c in df.columns]
    df = add_display_columns(df)
    return clean_dashboard_data(df)


def load_timeseries_data_from_csv():
    """
    Load the new mentor-style time-series CSV for My Data/Admin Preview.

    This file is organized as:
    site_name -> plot_name -> date_sampled -> sample SH_1

    The dashboard still stores the selected internal SH_1 in Supabase, but for private
    views it expands that SH_1 into the full site+plot timeline.
    """
    if not os.path.exists(TIMESERIES_CSV_PATH):
        print(f"Warning: Could not find {TIMESERIES_CSV_PATH}. Falling back to public CSV for private views.")
        return load_public_data_from_csv()

    df = pd.read_csv(TIMESERIES_CSV_PATH)
    df.columns = [str(c).strip() for c in df.columns]

    shs_source_column = next(
        (column for column in TIMESERIES_SHS_FALLBACK_COLUMNS if column in df.columns),
        None,
    )
    if shs_source_column is None:
        raise ValueError(
            f"Missing an SHS column in {TIMESERIES_CSV_PATH}. "
            f"Expected one of: {TIMESERIES_SHS_FALLBACK_COLUMNS}"
        )

    # Keep the rest of the dashboard unchanged by mapping the selected v4 score to "shs".
    df["shs"] = pd.to_numeric(df[shs_source_column], errors="coerce")

    # Make sure common optional metadata columns exist so hover/summary code never crashes.
    optional_columns = [
        "primary_project",
        "secondary_project",
        "tertiary_project",
        "sampling_round",
        "treatment",
        "plot_area",
        "current_plant_cover",
        "fertilizer_type_1",
        "fertilizer_rate_1",
        "fertilizer_type_2",
        "fertilizer_rate_2",
        "island",
    ]
    for col in optional_columns:
        if col not in df.columns:
            df[col] = pd.NA

    df = add_display_columns(df)
    return clean_dashboard_data(df)


def load_data_from_csv():
    """Backward-compatible public CSV loader used by older code paths."""
    return load_public_data_from_csv()


def _safe_sql_identifier(value, setting_name):
    """Allow only simple PostgreSQL schema/table identifiers from environment settings."""
    clean_value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", clean_value):
        raise ValueError(
            f"{setting_name} must contain only letters, numbers, and underscores "
            "and cannot start with a number."
        )
    return clean_value


def load_data_from_postgres():
    """
    Load the real PostgreSQL data.

    PostgreSQL's official v4 columns are preserved in the DataFrame, while
    v4_shs_raw is also aliased to "shs" so all existing dashboard charts,
    summaries, filters, and temporal-graph code continue to work.
    """
    if not DATABASE_URL:
        raise ValueError(
            "DATABASE_URL is missing. Add the PostgreSQL connection string to your .env file."
        )

    from sqlalchemy import create_engine

    schema = _safe_sql_identifier(POSTGRES_SCHEMA, "POSTGRES_SCHEMA")
    table = _safe_sql_identifier(POSTGRES_TABLE, "POSTGRES_TABLE")

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"sslmode": os.getenv("POSTGRES_SSLMODE", "require")},
    )

    query = f"""
        SELECT
            s."SH_1",
            s.date_sampled,
            s.site_name,
            s.plot_name,
            s.latitude,
            s.longitude,

            -- Official v4 Soil Health Score and factors
            s.v4_shs_raw,
            s.v4_factor1_raw,
            s.v4_factor2_raw,
            s.v4_factor3_raw,

            -- Internal compatibility alias used throughout the existing dashboard
            s.v4_shs_raw AS shs,

            s.minerals,
            s."order",
            s.suborder,
            s.great_group,
            s."PIAL_none",
            s.management_category,
            s.current_land_use,
            s.most_previous_land_use,

            -- Optional time-series metadata used in private graph hover details
            s.primary_project,
            s.secondary_project,
            s.tertiary_project,
            s.sampling_round,
            s.treatment,
            s.plot_area,
            s.current_plant_cover,
            s.fertilizer_type_1,
            s.fertilizer_rate_1,
            s.fertilizer_type_2,
            s.fertilizer_rate_2,
            s.island
        FROM "{schema}"."{table}" AS s;
    """

    try:
        df = pd.read_sql(query, engine)
    finally:
        engine.dispose()

    # Make optional fields safe if the real table omits any non-required display metadata.
    optional_columns = [
        "primary_project",
        "secondary_project",
        "tertiary_project",
        "sampling_round",
        "treatment",
        "plot_area",
        "current_plant_cover",
        "fertilizer_type_1",
        "fertilizer_rate_1",
        "fertilizer_type_2",
        "fertilizer_rate_2",
        "island",
        "v4_factor1_raw",
        "v4_factor2_raw",
        "v4_factor3_raw",
    ]
    for column in optional_columns:
        if column not in df.columns:
            df[column] = pd.NA

    df = add_display_columns(df)
    return clean_dashboard_data(df)


def normalize_access_request(row):
    """Make Supabase rows display cleanly inside Dash tables/dropdowns."""
    row = dict(row or {})

    if row.get("status"):
        row["status"] = str(row["status"]).strip().title()
    else:
        row["status"] = "Pending"

    permission_value = row.get("permission_acknowledged")
    if isinstance(permission_value, bool):
        row["permission_acknowledged"] = "Yes" if permission_value else "No"

    for key in [
        "first_name",
        "last_name",
        "email",
        "phone",
        "farm_name",
        "site_name",
        "created_at",
        "reviewed_by",
        "reviewed_at",
        "admin_note",
        "request_type",
        "data_reuse_permission",
        "data_reuse_updated_at",
    ]:
        if row.get(key) is None:
            row[key] = ""

    if not row.get("data_reuse_permission"):
        row["data_reuse_permission"] = DEFAULT_DATA_REUSE_PERMISSION

    row["data_reuse_display"] = DATA_REUSE_DISPLAY.get(
        row.get("data_reuse_permission"),
        "Site data without location",
    )

    return row


def load_access_requests():
    """Load access requests from Supabase instead of local JSON."""
    try:
        response = (
            supabase
            .table("access_requests")
            .select("*")
            .order("request_id", desc=False)
            .execute()
        )
        return [normalize_access_request(row) for row in (response.data or [])]
    except Exception as e:
        print(f"Error loading access requests from Supabase: {e}")
        return []


def get_access_request_by_email(email):
    """Return the newest access request for an email, or None."""
    if not email:
        return None

    clean_email = str(email).lower().strip()

    try:
        response = (
            supabase
            .table("access_requests")
            .select("*")
            .ilike("email", clean_email)
            .order("request_id", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return normalize_access_request(rows[0]) if rows else None
    except Exception as e:
        print(f"Error finding request by email: {e}")
        return None


def create_access_request(request_data):
    """Create a new pending access request in Supabase."""
    response = (
        supabase
        .table("access_requests")
        .insert(request_data)
        .execute()
    )
    return response.data or []


def update_access_request_status(request_id, new_status, reviewed_by, admin_note="", farm_name=None):
    """Approve or deny an access request in Supabase, save admin note, and optionally update farm."""
    reviewed_at = datetime.now(timezone.utc).isoformat()

    update_data = {
        "status": new_status,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "admin_note": admin_note or "",
    }

    if farm_name is not None:
        clean_farm_name = str(farm_name or "").strip()
        update_data["farm_name"] = clean_farm_name
        update_data["site_name"] = get_site_name(clean_farm_name)

    response = (
        supabase
        .table("access_requests")
        .update(update_data)
        .eq("request_id", request_id)
        .execute()
    )
    return response.data or []


def update_access_request_profile(
    request_id,
    first_name,
    last_name,
    phone,
    farm_name=None,
    data_reuse_permission=None,
    reset_to_pending=False,
):
    """Let a user update editable request/profile fields."""
    update_data = {
        "first_name": str(first_name or "").strip(),
        "last_name": str(last_name or "").strip(),
        "phone": str(phone or "").strip(),
    }

    if farm_name is not None:
        clean_farm_name = str(farm_name or "").strip()
        update_data["farm_name"] = clean_farm_name
        update_data["site_name"] = get_site_name(clean_farm_name)

    if data_reuse_permission is not None:
        update_data["data_reuse_permission"] = str(data_reuse_permission or DEFAULT_DATA_REUSE_PERMISSION).strip()
        update_data["data_reuse_updated_at"] = datetime.now(timezone.utc).isoformat()

    if reset_to_pending:
        update_data.update({
            "status": "Pending",
            "reviewed_by": "",
            "reviewed_at": None,
            "admin_note": "",
            "request_type": "Profile Update",
        })

    response = (
        supabase
        .table("access_requests")
        .update(update_data)
        .eq("request_id", request_id)
        .execute()
    )
    return response.data or []


def request_farm_change(request_id, first_name, last_name, phone, old_farm_name, new_farm_name, data_reuse_permission=None):
    """Approved users can ask to change sites by sending their existing row back to Pending."""
    old_site_name = get_site_name(old_farm_name) or old_farm_name or "N/A"
    new_site_name = get_site_name(new_farm_name) or new_farm_name or "N/A"
    note = (
        f"User requested site/project change from '{old_site_name}' "
        f"to '{new_site_name}'. Admin should verify before approving."
    )

    response = (
        supabase
        .table("access_requests")
        .update({
            "first_name": str(first_name or "").strip(),
            "last_name": str(last_name or "").strip(),
            "phone": str(phone or "").strip(),
            "farm_name": str(new_farm_name or "").strip(),
            "site_name": get_site_name(new_farm_name),
            "data_reuse_permission": str(data_reuse_permission or DEFAULT_DATA_REUSE_PERMISSION).strip(),
            "data_reuse_updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "Pending",
            "reviewed_by": "",
            "reviewed_at": None,
            "admin_note": note,
            "request_type": "Farm Change",
        })
        .eq("request_id", request_id)
        .execute()
    )
    return response.data or []

def load_data():
    if USE_POSTGRES:
        return load_data_from_postgres()

    return load_public_data_from_csv()


def load_private_timeseries_data():
    if USE_POSTGRES:
        # Later this can point to a private PostgreSQL time-series query.
        # For now, keep public PostgreSQL behavior as a fallback.
        return load_data_from_postgres()

    return load_timeseries_data_from_csv()


# Public/general data source. This keeps the public dashboard and filters on the old CSV.
df_public = load_data()

# Private My Data/Admin Preview data source. This uses the new time-series CSV.
df_timeseries = load_private_timeseries_data()

# Keep the old variable name so the rest of the file does not need to be rewritten.
# df_original means the public/general dataset.
df_original = df_public


def options_from_column(df, column):
    counts = df[column].dropna().value_counts()

    if column == "land_use_display":
        counts = counts[counts >= 10]

    values = sorted(counts.index)
    return [{"label": str(v), "value": str(v)} for v in values]


def find_record_by_farm_id(farm_id, source_df=None):
    """Find one row by SH_1, preferring the private time-series dataset."""
    if not farm_id:
        return pd.DataFrame()

    clean_farm_id = str(farm_id).strip()
    candidate_dfs = []

    if source_df is not None:
        candidate_dfs.append(source_df)

    candidate_dfs.extend([df_timeseries, df_original])

    for candidate in candidate_dfs:
        if candidate is None or candidate.empty or FARM_ID_COLUMN not in candidate.columns:
            continue

        matches = candidate[
            candidate[FARM_ID_COLUMN].astype(str).str.strip() == clean_farm_id
        ].copy()

        if not matches.empty:
            return matches

    return pd.DataFrame()


def get_farm_display_name(farm_id):
    """Return the farmer-facing site/project name for an internal SH_1 value."""
    matches = find_record_by_farm_id(farm_id)

    if matches.empty or SITE_NAME_COLUMN not in matches.columns:
        return str(farm_id) if farm_id else "N/A"

    site_name = str(matches.iloc[0].get(SITE_NAME_COLUMN, "")).strip()

    if site_name and site_name.lower() not in ["nan", "none", "", "<na>"]:
        return site_name

    return str(farm_id) if farm_id else "N/A"


def get_site_name(farm_id):
    """Return site_name for an internal SH_1 value, or blank if not found."""
    matches = find_record_by_farm_id(farm_id)

    if matches.empty or SITE_NAME_COLUMN not in matches.columns:
        return ""

    site_name = str(matches.iloc[0].get(SITE_NAME_COLUMN, "")).strip()

    if site_name and site_name.lower() not in ["nan", "none", "", "<na>"]:
        return site_name

    return ""


def farm_options_from_data(df, show_internal_id=False):
    """
    Build site/project dropdown options.

    Saved value = internal SH_1 identifier.
    User-facing label = site_name and plot_name when available.

    For the time-series CSV, each SH_1 is one sample. Selecting any SH_1 from a site+plot
    timeline lets the dashboard find the full timeline for that same site+plot.
    """
    if df is None or df.empty or FARM_ID_COLUMN not in df.columns:
        return []

    display_cols = [FARM_ID_COLUMN]
    for col in [SITE_NAME_COLUMN, PLOT_NAME_COLUMN, SAMPLE_DATE_COLUMN]:
        if col in df.columns:
            display_cols.append(col)

    temp = df[display_cols].dropna(subset=[FARM_ID_COLUMN]).copy()
    temp[FARM_ID_COLUMN] = temp[FARM_ID_COLUMN].astype(str).str.strip()

    if SITE_NAME_COLUMN not in temp.columns:
        temp[SITE_NAME_COLUMN] = "Farm/project record"
    else:
        temp[SITE_NAME_COLUMN] = temp[SITE_NAME_COLUMN].astype(str).str.strip()

    if PLOT_NAME_COLUMN not in temp.columns:
        temp[PLOT_NAME_COLUMN] = ""
    else:
        temp[PLOT_NAME_COLUMN] = temp[PLOT_NAME_COLUMN].astype(str).str.strip()

    if SAMPLE_DATE_COLUMN in temp.columns:
        temp[SAMPLE_DATE_COLUMN] = pd.to_datetime(temp[SAMPLE_DATE_COLUMN], errors="coerce")

    temp = temp.drop_duplicates(subset=[FARM_ID_COLUMN]).sort_values([SITE_NAME_COLUMN, PLOT_NAME_COLUMN, FARM_ID_COLUMN])

    options = []
    for _, row in temp.iterrows():
        farm_id = row[FARM_ID_COLUMN]
        site_name = row.get(SITE_NAME_COLUMN, "")
        plot_name = row.get(PLOT_NAME_COLUMN, "")

        if site_name and str(site_name).lower() not in ["nan", "none", "", "<na>"]:
            label = str(site_name)
        else:
            label = "Farm/project record"

        if plot_name and str(plot_name).lower() not in ["nan", "none", "", "<na>"]:
            label = f"{label} — Plot {plot_name}"

        if show_internal_id:
            label = f"{label} — SH_1 {farm_id}"

        options.append({"label": label, "value": farm_id})

    return options


def get_site_scope_from_farm_id(farm_id):
    """
    Return all time-series rows that belong to the same site+plot as an approved SH_1.

    Important data model:
    - Supabase access_requests.farm_name still stores one approved internal SH_1.
    - SH_1 identifies one sample/record, not the whole site history.
    - For the private view, the approved SH_1 expands into all rows with the same
      site_name and plot_name from the time-series CSV.
    - date_sampled orders the points on the time-series chart.
    """
    required_scope_cols = {FARM_ID_COLUMN, SITE_NAME_COLUMN, PLOT_NAME_COLUMN}
    if not farm_id or not required_scope_cols.issubset(df_timeseries.columns):
        return pd.DataFrame()

    clean_farm_id = str(farm_id).strip()

    approved_record = df_timeseries[
        df_timeseries[FARM_ID_COLUMN].astype(str).str.strip() == clean_farm_id
    ].copy()

    if approved_record.empty:
        # Fallback for older approvals that still point to the old public CSV.
        return find_record_by_farm_id(clean_farm_id, df_original)

    approved_row = approved_record.iloc[0]

    site_name = str(approved_row.get(SITE_NAME_COLUMN, "")).strip()
    plot_name = str(approved_row.get(PLOT_NAME_COLUMN, "")).strip()

    if (not site_name or site_name.lower() in ["nan", "none", "<na>"] or
            not plot_name or plot_name.lower() in ["nan", "none", "<na>"]):
        return approved_record.copy()

    scoped = df_timeseries[
        (df_timeseries[SITE_NAME_COLUMN].astype(str).str.strip() == site_name)
        & (df_timeseries[PLOT_NAME_COLUMN].astype(str).str.strip() == plot_name)
    ].copy()

    if SAMPLE_DATE_COLUMN in scoped.columns:
        scoped = scoped.sort_values(SAMPLE_DATE_COLUMN)

    return scoped if not scoped.empty else approved_record.copy()


def get_farm_preview_rows(farm_id):
    """
    Return all soil rows from the same site as the selected internal SH_1.
    This lets admins preview the full site history, not only one sample row.
    """
    return get_site_scope_from_farm_id(farm_id)


def get_dashboard_data_for_user(user, access_requests, admin_preview_farm_id=None):
    """
    Return the correct dashboard data scope.

    Public visitors see the aggregate dataset.
    Admins normally see the aggregate dataset, but can temporarily preview one full site
    using a selected internal SH_1.
    Approved regular users are authorized by access_requests.farm_name = SH_1, then the
    dashboard shows all rows with the same site_name and plot_name so the private chart can
    show multiple samples from that site/plot location.
    Pending or denied users continue to see the aggregate/public dashboard, but My Data
    explains that private farm/project data is not available until approval.
    """
    if not user:
        return df_original.copy(), "Public aggregate dashboard"

    role = get_user_role(user)
    if role == "admin":
        if admin_preview_farm_id:
            preview_id = str(admin_preview_farm_id).strip()
            scoped = get_site_scope_from_farm_id(preview_id)
            return scoped, f"Admin preview: {get_farm_display_name(preview_id)}"

        return df_original.copy(), "Admin aggregate dashboard"

    user_request = get_request_for_email(user, access_requests or [])
    if not user_request:
        return df_original.copy(), "Public aggregate dashboard"

    status = str(user_request.get("status", "Pending")).title()
    farm_name = str(user_request.get("farm_name", "")).strip()

    if status == "Approved" and farm_name:
        scoped = get_site_scope_from_farm_id(farm_name)
        return scoped, f"My Data: {get_farm_display_name(farm_name)}"

    return df_original.copy(), "Public aggregate dashboard"



def get_approved_user_request(user, access_requests):
    """Return the logged-in regular user's approved access request, or None."""
    if not user or get_user_role(user) == "admin":
        return None

    user_request = get_request_for_email(user, access_requests or [])
    if not user_request:
        return None

    status = str(user_request.get("status", "Pending")).title()
    farm_name = str(user_request.get("farm_name", "")).strip()

    if status == "Approved" and farm_name:
        return user_request

    return None


def make_user_shs_over_time_figure(df, user_request):
    """Create the private-user time-series chart using the mentor-style CSV."""
    title = "Your Soil Health Score Over Time"

    if SAMPLE_DATE_COLUMN not in df.columns:
        return empty_figure(title, 550)

    time_df = df.dropna(subset=["shs", SAMPLE_DATE_COLUMN]).copy()

    if time_df.empty:
        return empty_figure(title, 550)

    time_df = time_df.sort_values(SAMPLE_DATE_COLUMN)
    time_df["sample_date_label"] = time_df[SAMPLE_DATE_COLUMN].dt.strftime("%Y-%m-%d")

    # Make sure optional metadata columns exist for hover details.
    hover_cols = [
        "sample_date_label",
        "site_name",
        "plot_name",
        "primary_project",
        "secondary_project",
        "treatment",
        "current_plant_cover",
        "fertilizer_type_1",
        "fertilizer_rate_1",
        "land_use_display",
    ]
    for col in hover_cols:
        if col not in time_df.columns:
            time_df[col] = "N/A"

    # If multiple samples exist on the same date, average SHS but keep representative metadata.
    time_summary = (
        time_df
        .groupby(SAMPLE_DATE_COLUMN, as_index=False)
        .agg(
            shs=("shs", "mean"),
            sample_count=("SH_1", "count"),
            sample_date_label=("sample_date_label", "first"),
            site_name=("site_name", "first"),
            plot_name=("plot_name", "first"),
            primary_project=("primary_project", "first"),
            secondary_project=("secondary_project", "first"),
            treatment=("treatment", "first"),
            current_plant_cover=("current_plant_cover", "first"),
            fertilizer_type_1=("fertilizer_type_1", "first"),
            fertilizer_rate_1=("fertilizer_rate_1", "first"),
            land_use=("land_use_display", "first"),
        )
        .sort_values(SAMPLE_DATE_COLUMN)
    )

    for col in [
        "site_name",
        "plot_name",
        "primary_project",
        "secondary_project",
        "treatment",
        "current_plant_cover",
        "fertilizer_type_1",
        "fertilizer_rate_1",
        "land_use",
    ]:
        time_summary[col] = time_summary[col].apply(summary_value)

    mode = "lines+markers" if len(time_summary) > 1 else "markers"

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=time_summary[SAMPLE_DATE_COLUMN],
            y=time_summary["shs"],
            mode=mode,
            name="Your SHS",
            line=dict(color=GREEN, width=3),
            marker=dict(size=10, color=GREEN),
            customdata=time_summary[[
                "sample_date_label",
                "sample_count",
                "site_name",
                "plot_name",
                "primary_project",
                "secondary_project",
                "treatment",
                "current_plant_cover",
                "fertilizer_type_1",
                "fertilizer_rate_1",
                "land_use",
            ]],
            hovertemplate=(
                "<b>Sampling event</b><br>"
                "Date sampled: %{customdata[0]}<br>"
                "SHS: %{y:.2f}<br>"
                "Samples on this date: %{customdata[1]}<br>"
                "Site: %{customdata[2]}<br>"
                "Plot: %{customdata[3]}<br>"
                "Primary project: %{customdata[4]}<br>"
                "Secondary project: %{customdata[5]}<br>"
                "Treatment: %{customdata[6]}<br>"
                "Plant cover: %{customdata[7]}<br>"
                "Fertilizer type: %{customdata[8]}<br>"
                "Fertilizer rate: %{customdata[9]}<br>"
                "Land use: %{customdata[10]}"
                "<extra></extra>"
            ),
        )
    )

    public_avg = df_original["shs"].mean()
    if not pd.isna(public_avg):
        fig.add_hline(
            y=public_avg,
            line_dash="dash",
            line_color="#f28e2b",
            annotation_text=f"Public average SHS: {public_avg:.2f}",
            annotation_position="top left",
        )

    site_label = user_request.get("site_name") or get_farm_display_name(user_request.get("farm_name"))

    fig.update_layout(
        template="plotly_white",
        height=550,
        autosize=False,
        title=dict(
            text=f"{title}<br><sup>{site_label}</sup>",
            x=0.02,
            font=dict(size=16, color="#17223b"),
        ),
        margin=dict(l=55, r=35, t=85, b=65),
        font=dict(family="Arial", size=12, color="#17223b"),
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
    )

    fig.update_xaxes(
        title="Date Sampled",
        tickformat="%b %Y",
        hoverformat="%B %d, %Y",
    )
    fig.update_yaxes(title="Soil Health Score (SHS)", range=[0, 1.05], dtick=0.25)

    return fig



def summary_value(value):
    """Format dashboard values for the private site summary card."""
    if pd.isna(value):
        return "N/A"
    value = str(value).strip()
    if not value or value.lower() in ["nan", "none", "<na>"]:
        return "N/A"
    return value


def make_user_site_summary(df, user_request):
    """Create the private-user summary card that replaces the public suborder chart."""
    if df is None or df.empty:
        return html.Div(
            [
                html.H3("Your Site Summary", style={"marginTop": 0, "color": DARK_GREEN}),
                html.P("No private site data is available for the current filters."),
            ]
        )

    latest_df = df.copy()
    if SAMPLE_DATE_COLUMN in latest_df.columns and latest_df[SAMPLE_DATE_COLUMN].notna().any():
        latest_df = latest_df.sort_values(SAMPLE_DATE_COLUMN)
        latest = latest_df.dropna(subset=[SAMPLE_DATE_COLUMN]).iloc[-1]
    else:
        latest = latest_df.iloc[-1]
    avg_shs = latest_df["shs"].mean()
    latest_shs = latest.get("shs")
    public_avg = df_original["shs"].mean()

    site_name = user_request.get("site_name") or summary_value(latest.get("site_name"))
    farm_id = user_request.get("farm_name") or summary_value(latest.get(FARM_ID_COLUMN))

    if SAMPLE_DATE_COLUMN in latest_df.columns and not pd.isna(latest.get(SAMPLE_DATE_COLUMN)):
        latest_date = latest.get(SAMPLE_DATE_COLUMN).strftime("%b %Y")
    else:
        latest_date = "N/A"

    if not pd.isna(avg_shs) and not pd.isna(public_avg):
        comparison = avg_shs - public_avg
        comparison_text = f"{comparison:+.2f} compared with public average"
    else:
        comparison_text = "Public comparison unavailable"

       
    summary_items = [
        ("Site name", site_name),
        ("Total Samples", len(latest_df)),
        ("Latest sample date", latest_date),
        ("Most Recent SHS", "N/A" if pd.isna(latest_shs) else f"{latest_shs:.2f}"),
        ("Average SHS", "N/A" if pd.isna(avg_shs) else f"{avg_shs:.2f}"),
        ("Public average SHS", "N/A" if pd.isna(public_avg) else f"{public_avg:.2f}"),
        ("Compared with public average", comparison_text),
        ("Current land use", summary_value(latest.get("land_use_display"))),
        ("Management category", summary_value(latest.get("management_category"))),
        ("Mineralogical class", summary_value(latest.get("mineral_class"))),
        ("Soil order", summary_value(latest.get("order"))),
        ("Suborder", summary_value(latest.get("suborder"))),
        ("Great group", summary_value(latest.get("great_group"))),
        ("PIAL history", summary_value(latest.get("pial_status"))),
    ]

    return html.Div(
        children=[
            html.H3("Your Site Summary", style={"marginTop": 0, "color": DARK_GREEN}),
            html.P(
                "Quick details for all samples from your approved site/location.",
                style={"fontSize": "13px", "color": "#6b7280", "marginTop": "-4px"},
            ),
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "1fr 1fr",
                    "gap": "10px",
                    "marginTop": "12px",
                },
                children=[
                    html.Div(
                        style={
                            "padding": "10px",
                            "border": CARD_BORDER,
                            "borderRadius": "9px",
                            "backgroundColor": "#f7f9f6",
                        },
                        children=[
                            html.Div(label, style={"fontSize": "11px", "fontWeight": "800", "color": "#4b5563"}),
                            html.Div(value, style={"fontSize": "14px", "fontWeight": "700", "marginTop": "4px"}),
                        ],
                    )
                    for label, value in summary_items
                ],
            ),
        ]
    )


def apply_filters(
    df,
    current_land_use,
    management_category,
    mineral_class,
    order,
    suborder,
    great_group,
    pial_status,
):
    filters = {
        "land_use_display": current_land_use,
        "management_category": management_category,
        "mineral_class": mineral_class,
        "order": order,
        "suborder": suborder,
        "great_group": great_group,
        "pial_status": pial_status,
    }

    filtered = df.copy()

    for col, selected in filters.items():
        if selected:
            filtered = filtered[filtered[col].astype(str).isin(selected)]

    return filtered


def make_count_table(df, column, label, preferred_order=None):
    temp = (
        df[column]
        .dropna()
        .value_counts()
        .rename_axis(label)
        .reset_index(name="Count")
    )

    if preferred_order:
        temp = temp[temp[label].isin(preferred_order)]
        order_lookup = {name: i for i, name in enumerate(preferred_order)}
        temp["_sort"] = temp[label].map(order_lookup)
        temp = temp.sort_values("_sort").drop(columns="_sort")
    else:
        temp = temp.sort_values("Count", ascending=False)

    total = temp["Count"].sum()

    if total == 0:
        temp["Percent"] = "0%"
    else:
        temp["Percent"] = (temp["Count"] / total * 100).round(1).astype(str) + "%"

    return temp


def style_figure(fig):
    fig.update_layout(
        template="plotly_white",
        autosize=False,
        margin=dict(l=50, r=35, t=55, b=55),
        font=dict(family="Arial", size=12, color="#17223b"),
        paper_bgcolor="white",
        plot_bgcolor="white",
        title=dict(x=0.02, font=dict(size=16, color="#17223b")),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
    )
    return fig


def empty_figure(title, height=420):
    fig = px.scatter(title=title)
    fig.update_layout(
        template="plotly_white",
        height=height,
        autosize=False,
        annotations=[
            dict(
                text="No data available for selected filters.",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=15),
            )
        ],
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def card(children, style=None):
    base = {
        "backgroundColor": "white",
        "border": CARD_BORDER,
        "borderRadius": "10px",
        "padding": "16px",
        "boxShadow": "0 2px 8px rgba(16,24,40,0.06)",
        "overflow": "visible",
    }

    if style:
        base.update(style)

    return html.Div(children=children, style=base)


def metric_card(icon, title, value, subtitle):
    return html.Div(
        style={
            "backgroundColor": "white",
            "border": CARD_BORDER,
            "borderRadius": "10px",
            "padding": "20px 24px",
            "display": "flex",
            "alignItems": "center",
            "gap": "20px",
            "boxShadow": "0 2px 8px rgba(16,24,40,0.06)",
            "height": "92px",
        },
        children=[
            html.Div(
                icon,
                style={
                    "width": "58px",
                    "height": "58px",
                    "borderRadius": "8px",
                    "backgroundColor": "#e8f2e9",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "fontSize": "30px",
                    "color": "#4b8123",
                },
            ),
            html.Div(
                children=[
                    html.Div(title, style={"fontSize": "14px", "fontWeight": "800"}),
                    html.Div(
                        value,
                        style={
                            "fontSize": "31px",
                            "fontWeight": "800",
                            "color": GREEN,
                            "marginTop": "6px",
                            "lineHeight": "1",
                        },
                    ),
                    html.Div(
                        subtitle,
                        style={
                            "fontSize": "13px",
                            "color": "#6b7280",
                            "marginTop": "10px",
                        },
                    ),
                ]
            ),
        ],
    )


def filter_dropdown(label, id_name, options):
    return html.Div(
        style={"marginBottom": "18px"},
        children=[
            html.Label(
                label,
                style={
                    "display": "block",
                    "fontSize": "13px",
                    "fontWeight": "800",
                    "marginBottom": "7px",
                },
            ),
            dcc.Dropdown(
                id=id_name,
                options=options,
                multi=True,
                placeholder="All",
                style={"fontSize": "13px"},
            ),
        ],
    )


def graph_component(graph_id, height):
    return dcc.Graph(
        id=graph_id,
        config={"displayModeBar": True, "responsive": False},
        style={"height": f"{height}px", "width": "100%"},
    )


table_style = {
    "fontFamily": "Arial",
    "fontSize": "13px",
    "padding": "8px",
    "textAlign": "left",
    "border": "none",
}

header_style = {
    "backgroundColor": "#f3f4f6",
    "fontWeight": "bold",
    "border": "none",
}


INFO_ICON_STYLE = {
    "display": "inline-flex",
    "alignItems": "center",
    "justifyContent": "center",
    "width": "17px",
    "height": "17px",
    "borderRadius": "50%",
    "backgroundColor": "#e8f2e9",
    "color": DARK_GREEN,
    "fontSize": "12px",
    "fontWeight": "800",
    "cursor": "help",
    "marginLeft": "7px",
    "verticalAlign": "middle",
}

SHS_TOOLTIP = (
    "Soil Health Score (SHS): A composite score that summarizes overall soil function "
    "using multiple measured indicators. Higher values generally indicate stronger soil "
    "biological activity, nutrient cycling, soil structure, and water-related function "
    "relative to other samples in this dataset."
)

SUBORDER_TOOLTIP = (
    "Suborder: A category within Soil Taxonomy that groups soils with similar properties "
    "and environmental characteristics. This chart compares the average Soil Health Score "
    "across soil suborders."
)

MINERAL_TOOLTIP = (
    "Mineralogical Class: Classification based on the dominant mineral types present in the soil. "
    "High Activity Clay (HAC): clay minerals with high nutrient-holding capacity. "
    "Low Activity Clay (LAC): clay minerals with lower nutrient-holding capacity. "
    "Poorly/Non-Crystalline Minerals (PNCM): short-range-order minerals with very high surface area "
    "and pH-dependent charge. Organic (Histosol): soils primarily composed of organic matter. "
    "Sand: mineral particles ranging from 2 to 0.05 mm in size."
)

LAND_USE_TOOLTIP = (
    "Land Use: The purpose of human activity on the land. Land use includes categories such as "
    "annual cropland, forest, orchard, pasture, agroforestry, unmanaged land, and city/state parks. "
    "It describes how land is used, rather than simply what covers the land surface."
)

PIAL_TOOLTIP = (
    "PIAL: Indicates whether a site has a history of intensive agricultural use. "
    "This chart shows the proportion of soil samples with and without previous intensive agriculture."
)


def info_icon(tooltip_text):
    return html.Span(
        [
            "i",
            html.Span(
                tooltip_text,
                className="custom-tooltip-text"
            )
        ],
        className="custom-tooltip-container",
    )


def title_with_info(title, tooltip_text):
    return html.Span(
        children=[
            html.Span(title),
            info_icon(tooltip_text),
        ],
        style={"display": "inline-flex", "alignItems": "center"},
    )


MODAL_OVERLAY_STYLE = {
    "display": "block",
    "position": "fixed",
    "top": 0,
    "left": 0,
    "width": "100%",
    "height": "100%",
    "backgroundColor": "rgba(0,0,0,0.45)",
    "zIndex": "9999",
}

MODAL_HIDDEN_STYLE = {**MODAL_OVERLAY_STYLE, "display": "none"}

MODAL_CARD_STYLE = {
    "width": "400px",
    "maxWidth": "90%",
    "margin": "115px auto",
    "backgroundColor": "white",
    "padding": "26px",
    "borderRadius": "12px",
    "boxShadow": "0 12px 30px rgba(0,0,0,0.25)",
}

AUTH_INPUT_STYLE = {
    "width": "100%",
    "padding": "11px",
    "marginBottom": "12px",
    "borderRadius": "7px",
    "border": "1px solid #d1d5db",
    "fontSize": "14px",
    "boxSizing": "border-box",
}

AUTH_BUTTON_STYLE = {
    "padding": "10px 16px",
    "border": "none",
    "borderRadius": "7px",
    "cursor": "pointer",
    "fontWeight": "800",
}

AUTH_PRIMARY_BUTTON_STYLE = {
    **AUTH_BUTTON_STYLE,
    "backgroundColor": DARK_GREEN,
    "color": "white",
}

AUTH_SECONDARY_BUTTON_STYLE = {
    **AUTH_BUTTON_STYLE,
    "backgroundColor": "#eef2f0",
    "color": DARK_GREEN,
}


def get_user_email(user_obj):
    """Safely pull email from different Supabase response shapes."""
    if user_obj is None:
        return None

    if hasattr(user_obj, "email"):
        return user_obj.email

    if isinstance(user_obj, dict):
        return user_obj.get("email")

    return None


def get_user_role(user):
    """
    Temporary role logic for testing the access-level design.

    public = not logged in
    user = logged in normal account
    admin = logged in email listed in ADMIN_EMAILS

    Later, this should be replaced with a real role column/table
    from Supabase/PostgreSQL.
    """
    if not user:
        return "public"

    email = str(user.get("email", "")).lower().strip()

    if email in ADMIN_EMAILS:
        return "admin"

    return "user"


def get_request_for_email(user, access_requests):
    """Find the latest access request for the logged-in user's email."""
    if not user or not access_requests:
        return None

    email = str(user.get("email", "")).lower().strip()

    matches = [
        request for request in access_requests
        if str(request.get("email", "")).lower().strip() == email
    ]

    if not matches:
        return None

    return matches[-1]


def make_request_id(access_requests):
    """Create a simple temporary request ID for the prototype."""
    if not access_requests:
        return 1

    existing_ids = []
    for request in access_requests:
        try:
            existing_ids.append(int(request.get("request_id", 0)))
        except Exception:
            pass

    return max(existing_ids) + 1 if existing_ids else 1


def access_request_status_badge(status):
    status = str(status or "Pending").title()

    colors = {
        "Pending": {"bg": "#fff7ed", "text": "#9a3412"},
        "Approved": {"bg": "#ecfdf3", "text": "#166534"},
        "Denied": {"bg": "#fef2f2", "text": "#991b1b"},
    }

    color = colors.get(status, colors["Pending"])

    return html.Span(
        status,
        style={
            "display": "inline-block",
            "padding": "4px 9px",
            "borderRadius": "999px",
            "backgroundColor": color["bg"],
            "color": color["text"],
            "fontWeight": "800",
            "fontSize": "12px",
        },
    )


def admin_table_columns():
    """Columns shown in the admin access request table."""
    return [
        {"name": "Request ID", "id": "request_id"},
        {"name": "Status", "id": "status"},
        {"name": "Request Type", "id": "request_type"},
        {"name": "First Name", "id": "first_name"},
        {"name": "Last Name", "id": "last_name"},
        {"name": "Email", "id": "email"},
        {"name": "Phone", "id": "phone"},
        {"name": "Farm SH_1", "id": "farm_name"},
        {"name": "Site Name", "id": "site_name"},
        {"name": "Data Reuse", "id": "data_reuse_display"},
        {"name": "Permission", "id": "permission_acknowledged"},
        {"name": "Created", "id": "created_at"},
        {"name": "Reviewed By", "id": "reviewed_by"},
        {"name": "Reviewed At", "id": "reviewed_at"},
        {"name": "Admin Note", "id": "admin_note"},
    ]


def pending_request_options(access_requests):
    """Dropdown options for requests that still need admin review."""
    access_requests = access_requests or []

    return [
        {
            "label": f"#{request.get('request_id')} - {request.get('request_type', 'New Access')} - {request.get('first_name', '')} {request.get('last_name', '')} ({request.get('email', '')})",
            "value": request.get("request_id"),
        }
        for request in access_requests
        if str(request.get("status", "")).lower() == "pending"
    ]


def admin_panel_layout():
    """
    Admin panel layout for filtering, viewing, and reviewing access requests.
    """
    return html.Div(
        id="admin-panel-section",
        style={"display": "none"},
        children=[
            html.H3("Admin / Access Requests", style={"marginTop": 0, "color": DARK_GREEN}),
            html.P(
                "Review signup requests here. New users stay pending until an admin approves or denies access."
            ),
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "180px minmax(220px, 1fr) minmax(220px, 1fr)",
                    "gap": "10px",
                    "marginTop": "12px",
                    "marginBottom": "12px",
                },
                children=[
                    dcc.Dropdown(
                        id="admin-status-filter",
                        options=[
                            {"label": "All", "value": "All"},
                            {"label": "Pending", "value": "Pending"},
                            {"label": "Approved", "value": "Approved"},
                            {"label": "Denied", "value": "Denied"},
                        ],
                        value="All",
                        clearable=False,
                        style={"fontSize": "13px"},
                    ),
                    dcc.Input(
                        id="admin-search-input",
                        type="text",
                        placeholder="Search email, first name, or last name",
                        style={**AUTH_INPUT_STYLE, "marginBottom": 0},
                    ),
                    dcc.Input(
                        id="admin-farm-search-input",
                        type="text",
                        placeholder="Search site name or SH_1",
                        style={**AUTH_INPUT_STYLE, "marginBottom": 0},
                    ),
                ],
            ),
            dash_table.DataTable(
                id="access-requests-table",
                data=[],
                columns=admin_table_columns(),
                page_size=8,
                style_table={"overflowX": "auto", "marginTop": "12px"},
                style_cell={
                    **table_style,
                    "whiteSpace": "normal",
                    "height": "auto",
                    "minWidth": "120px",
                    "maxWidth": "240px",
                },
                style_header=header_style,
                style_data_conditional=[
                    {
                        "if": {"filter_query": "{status} = Pending"},
                        "backgroundColor": "#fff7ed",
                    },
                    {
                        "if": {"filter_query": "{status} = Approved"},
                        "backgroundColor": "#ecfdf3",
                    },
                    {
                        "if": {"filter_query": "{status} = Denied"},
                        "backgroundColor": "#fef2f2",
                    },
                ],
            ),
            html.Div(
                style={
                    "marginTop": "18px",
                    "padding": "14px",
                    "borderRadius": "10px",
                    "backgroundColor": "#f7f9f6",
                    "border": CARD_BORDER,
                },
                children=[
                    html.Div(
                        "Review pending request",
                        style={"fontWeight": "800", "marginBottom": "8px"},
                    ),
                    dcc.Dropdown(
                        id="admin-request-selector",
                        options=[],
                        value=None,
                        placeholder="Select a pending request",
                        style={"fontSize": "13px", "marginBottom": "10px"},
                    ),
                    html.Label(
                        "Farm/project name admin can update before approving",
                        style={"fontWeight": "800", "fontSize": "13px", "marginBottom": "6px", "display": "block"},
                    ),
                    dcc.Dropdown(
                        id="admin-farm-name-edit",
                        # IMPORTANT: Use the same SH_1-based options as Signup and Privacy.
                        # Users/admins see the friendly farm/project name, but the saved value is SH_1.
                        options=farm_options_from_data(df_timeseries, show_internal_id=True),
                        value=None,
                        placeholder="Select or verify farm/project name",
                        searchable=True,
                        style={"fontSize": "13px", "marginBottom": "10px"},
                    ),
                    html.Div(
                        id="admin-farm-data-preview",
                        children=html.Div(
                            "Select a farm/project above to preview the matching soil data before approving.",
                            style={"fontSize": "13px", "color": "#6b7280"},
                        ),
                        style={"marginBottom": "12px"},
                    ),
                    dcc.Textarea(
                        id="admin-note-input",
                        placeholder="Optional admin note. If denied, explain why or what the user should fix.",
                        style={
                            "width": "100%",
                            "minHeight": "90px",
                            "padding": "10px",
                            "borderRadius": "7px",
                            "border": "1px solid #d1d5db",
                            "fontSize": "14px",
                            "boxSizing": "border-box",
                            "marginBottom": "10px",
                        },
                    ),
                    html.Div(
                        style={"display": "flex", "gap": "10px", "flexWrap": "wrap"},
                        children=[
                            html.Button(
                                "Approve",
                                id="approve-request-btn",
                                n_clicks=0,
                                style=AUTH_PRIMARY_BUTTON_STYLE,
                            ),
                            html.Button(
                                "Deny",
                                id="deny-request-btn",
                                n_clicks=0,
                                style={
                                    **AUTH_BUTTON_STYLE,
                                    "backgroundColor": "#fee2e2",
                                    "color": "#991b1b",
                                },
                            ),
                            html.Button(
                                "Preview Farm on Main Dashboard",
                                id="admin-preview-main-btn",
                                n_clicks=0,
                                style={
                                    **AUTH_BUTTON_STYLE,
                                    "backgroundColor": "#e0f2fe",
                                    "color": "#075985",
                                },
                            ),
                        ],
                    ),
                    html.Div(
                        id="admin-review-message",
                        style={"marginTop": "10px", "fontSize": "13px", "color": "#28623a"},
                    ),
                    html.Div(
                        "Access requests are stored in Supabase. Email notifications can be added later with Supabase Edge Functions + Resend.",
                        style={"fontSize": "12px", "color": "#6b7280", "marginTop": "12px"},
                    ),
                ],
            ),
            html.Div(
                style={
                    "marginTop": "18px",
                    "padding": "14px",
                    "borderRadius": "10px",
                    "backgroundColor": "#ffffff",
                    "border": CARD_BORDER,
                },
                children=[
                    html.Div(
                        "Farm / Project Explorer",
                        style={"fontWeight": "800", "fontSize": "18px", "color": DARK_GREEN, "marginBottom": "6px"},
                    ),
                    html.Div(
                        "Admins can search any farm/project and preview the matching soil data without changing a user request.",
                        style={"fontSize": "13px", "color": "#6b7280", "marginBottom": "10px"},
                    ),
                    dcc.Dropdown(
                        id="admin-farm-explorer-dropdown",
                        options=farm_options_from_data(df_timeseries, show_internal_id=True),
                        value=None,
                        placeholder="Search site name or SH_1",
                        searchable=True,
                        style={"fontSize": "13px", "marginBottom": "10px"},
                    ),
                    html.Button(
                        "Preview Farm on Main Dashboard",
                        id="admin-preview-explorer-btn",
                        n_clicks=0,
                        style={
                            **AUTH_BUTTON_STYLE,
                            "backgroundColor": "#e0f2fe",
                            "color": "#075985",
                            "marginBottom": "12px",
                        },
                    ),
                    html.Div(
                        id="admin-farm-explorer-preview",
                        children=html.Div(
                            "Select a farm/project to view SHS, land use, mineral class, and matching soil rows.",
                            style={"fontSize": "13px", "color": "#6b7280"},
                        ),
                    ),
                ],
            ),
        ],
    )

def login_modal():
    return html.Div(
        id="login-modal",
        style=MODAL_HIDDEN_STYLE,
        children=[
            html.Div(
                style=MODAL_CARD_STYLE,
                children=[
                    html.H3("Log In", style={"marginTop": 0, "color": DARK_GREEN}),
                    html.Div(
                        "Use your Soil Health Dashboard account.",
                        style={"fontSize": "14px", "color": "#556", "marginBottom": "14px"},
                    ),
                    dcc.Input(
                        id="login-email",
                        type="email",
                        placeholder="Email",
                        style=AUTH_INPUT_STYLE,
                    ),
                    dcc.Input(
                        id="login-password",
                        type="password",
                        placeholder="Password",
                        style=AUTH_INPUT_STYLE,
                    ),
                    html.Div(
                        style={"display": "flex", "gap": "10px", "alignItems": "center"},
                        children=[
                            html.Button(
                                "Log In",
                                id="login-submit-btn",
                                n_clicks=0,
                                style=AUTH_PRIMARY_BUTTON_STYLE,
                            ),
                            html.Button(
                                "Cancel",
                                id="close-login-btn",
                                n_clicks=0,
                                style=AUTH_SECONDARY_BUTTON_STYLE,
                            ),
                        ],
                    ),
                    html.Div(
                        id="login-message",
                        style={"marginTop": "12px", "fontSize": "13px", "color": "#b42318"},
                    ),
                ],
            )
        ],
    )


def signup_modal():
    farm_options = farm_options_from_data(df_timeseries)

    return html.Div(
        id="signup-modal",
        style=MODAL_HIDDEN_STYLE,
        children=[
            html.Div(
                style={
                    **MODAL_CARD_STYLE,
                    "width": "520px",
                    "margin": "70px auto",
                    "maxHeight": "86vh",
                    "overflowY": "auto",
                },
                children=[
                    html.H3("Request Access", style={"marginTop": 0, "color": DARK_GREEN}),
                    html.Div(
                        "Create an account and request access to your farm/project data. "
                        "An admin will review your request before private data access is enabled.",
                        style={"fontSize": "14px", "color": "#556", "marginBottom": "14px"},
                    ),

                    html.Div(
                        style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "10px"},
                        children=[
                            dcc.Input(
                                id="signup-first-name",
                                type="text",
                                placeholder="First name",
                                style=AUTH_INPUT_STYLE,
                            ),
                            dcc.Input(
                                id="signup-last-name",
                                type="text",
                                placeholder="Last name",
                                style=AUTH_INPUT_STYLE,
                            ),
                        ],
                    ),

                    dcc.Input(
                        id="signup-email",
                        type="email",
                        placeholder="Email",
                        style=AUTH_INPUT_STYLE,
                    ),
                    dcc.Input(
                        id="signup-phone",
                        type="tel",
                        placeholder="Phone number",
                        style=AUTH_INPUT_STYLE,
                    ),
                    dcc.Input(
                        id="signup-password",
                        type="password",
                        placeholder="Password",
                        style=AUTH_INPUT_STYLE,
                    ),

                    html.Label(
                        "Site name",
                        style={"fontWeight": "800", "fontSize": "13px", "marginBottom": "6px", "display": "block"},
                    ),
                    dcc.Dropdown(
                        id="signup-farm-name",
                        options=farm_options,
                        placeholder="Select your farm/project name",
                        searchable=True,
                        style={"fontSize": "13px", "marginBottom": "12px"},
                    ),

                    html.Div(
                        style={
                            "padding": "12px",
                            "backgroundColor": "#f7f9f6",
                            "border": CARD_BORDER,
                            "borderRadius": "10px",
                            "marginBottom": "14px",
                        },
                        children=[
                            html.Div(
                                "Data Reuse Preference",
                                style={"fontWeight": "800", "fontSize": "14px", "marginBottom": "6px"},
                            ),
                            html.Div(
                                "Choose how the research team may reuse your soil data. Your exact location will never be shared publicly.",
                                style={"fontSize": "12px", "color": "#6b7280", "marginBottom": "10px", "lineHeight": "1.4"},
                            ),
                            dcc.RadioItems(
                                id="signup-data-reuse",
                                options=DATA_REUSE_OPTIONS,
                                value=DEFAULT_DATA_REUSE_PERMISSION,
                                labelStyle={"display": "block", "marginBottom": "8px"},
                                style={"fontSize": "13px", "lineHeight": "1.4"},
                            ),
                        ],
                    ),

                    dcc.Checklist(
                        id="signup-permission-check",
                        options=[
                            {
                                "label": (
                                    " I acknowledge that the research team may review my signup information "
                                    "and connect my account to the correct farm/project data."
                                ),
                                "value": "acknowledged",
                            }
                        ],
                        value=[],
                        style={"fontSize": "13px", "lineHeight": "1.4", "marginBottom": "14px"},
                    ),

                    html.Div(
                        style={"display": "flex", "gap": "10px", "alignItems": "center"},
                        children=[
                            html.Button(
                                "Submit Request",
                                id="signup-submit-btn",
                                n_clicks=0,
                                style=AUTH_PRIMARY_BUTTON_STYLE,
                            ),
                            html.Button(
                                "Cancel",
                                id="close-signup-btn",
                                n_clicks=0,
                                style=AUTH_SECONDARY_BUTTON_STYLE,
                            ),
                        ],
                    ),
                    html.Div(
                        id="signup-message",
                        style={"marginTop": "12px", "fontSize": "13px", "color": "#b42318"},
                    ),
                ],
            )
        ],
    )


def profile_row(label, value):
    return html.Div(
        style={"marginBottom": "10px"},
        children=[
            html.Div(label, style={"fontSize": "12px", "fontWeight": "800", "color": "#4b5563"}),
            html.Div(str(value or "N/A"), style={"fontSize": "14px", "color": "#17223b"}),
        ],
    )


def privacy_panel_content(user, access_requests=None):
    user_request = get_request_for_email(user, access_requests or [])
    farm_options = farm_options_from_data(df_timeseries)

    if not user:
        return [
            html.H3("Privacy Settings", style={"marginTop": 0, "color": DARK_GREEN}),
            html.P("Please log in before viewing privacy settings."),
        ]

    if not user_request:
        return [
            html.H3("Privacy Settings", style={"marginTop": 0, "color": DARK_GREEN}),
            html.P("No access request is connected to this account yet."),
            html.P(f"Logged-in email: {user.get('email', '')}"),
        ]

    status = str(user_request.get("status", "Pending")).title()
    farm_disabled = False

    return [
        html.H3("Privacy Settings", style={"marginTop": 0, "color": DARK_GREEN}),
        html.P(
            "View and update the profile/request information connected to your dashboard account."
        ),
        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "1fr 1fr",
                "gap": "10px",
                "marginBottom": "12px",
            },
            children=[
                dcc.Input(
                    id="privacy-first-name",
                    type="text",
                    value=user_request.get("first_name", ""),
                    placeholder="First name",
                    style=AUTH_INPUT_STYLE,
                ),
                dcc.Input(
                    id="privacy-last-name",
                    type="text",
                    value=user_request.get("last_name", ""),
                    placeholder="Last name",
                    style=AUTH_INPUT_STYLE,
                ),
            ],
        ),
        dcc.Input(
            id="privacy-email",
            type="email",
            value=user_request.get("email", user.get("email", "")),
            disabled=True,
            style={**AUTH_INPUT_STYLE, "backgroundColor": "#f3f4f6", "color": "#6b7280"},
        ),
        dcc.Input(
            id="privacy-phone",
            type="tel",
            value=user_request.get("phone", ""),
            placeholder="Phone number",
            style=AUTH_INPUT_STYLE,
        ),
        html.Label(
            "Site/project",
            style={"fontWeight": "800", "fontSize": "13px", "marginBottom": "6px", "display": "block"},
        ),
        dcc.Dropdown(
            id="privacy-farm-name",
            options=farm_options,
            value=user_request.get("farm_name", None),
            disabled=farm_disabled,
            placeholder="Select your farm/project name",
            searchable=True,
            style={"fontSize": "13px", "marginBottom": "12px"},
        ),
        html.Div(
            "If your request is already Approved, choose the new farm/project here and click Request Farm Change. This will send your request back to Pending Review for admin approval.",
            style={"fontSize": "12px", "color": "#6b7280", "marginTop": "-6px", "marginBottom": "12px"},
        ),
        html.Div(
            style={
                "padding": "12px",
                "backgroundColor": "#f7f9f6",
                "border": CARD_BORDER,
                "borderRadius": "10px",
                "marginBottom": "12px",
            },
            children=[
                html.Div(
                    "Data Reuse Preference",
                    style={"fontWeight": "800", "fontSize": "14px", "marginBottom": "6px"},
                ),
                html.Div(
                    "Choose how the research team may reuse your soil data. Your exact location will never be shared publicly.",
                    style={"fontSize": "12px", "color": "#6b7280", "marginBottom": "10px", "lineHeight": "1.4"},
                ),
                dcc.RadioItems(
                    id="privacy-data-reuse",
                    options=DATA_REUSE_OPTIONS,
                    value=user_request.get("data_reuse_permission", DEFAULT_DATA_REUSE_PERMISSION),
                    labelStyle={"display": "block", "marginBottom": "8px"},
                    style={"fontSize": "13px", "lineHeight": "1.4"},
                ),
            ],
        ),
        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "1fr 1fr",
                "gap": "12px",
                "padding": "12px",
                "backgroundColor": "#f7f9f6",
                "border": CARD_BORDER,
                "borderRadius": "10px",
                "marginBottom": "12px",
            },
            children=[
                profile_row("Request type", user_request.get("request_type", "New Access")),
                profile_row("Permission acknowledged", user_request.get("permission_acknowledged")),
                profile_row("Data reuse preference", user_request.get("data_reuse_display")),
                html.Div([
                    html.Div("Current request status", style={"fontSize": "12px", "fontWeight": "800", "color": "#4b5563"}),
                    access_request_status_badge(status),
                ]),
                profile_row("Request submitted", user_request.get("created_at")),
                profile_row("Reviewed time", user_request.get("reviewed_at")),
                profile_row("Reviewed by", user_request.get("reviewed_by")),
                profile_row("Admin note", user_request.get("admin_note")),
            ],
        ),
        html.Div(
            style={"display": "flex", "gap": "10px", "flexWrap": "wrap"},
            children=[
                html.Button(
                    "Save Privacy Settings",
                    id="privacy-save-btn",
                    n_clicks=0,
                    style=AUTH_PRIMARY_BUTTON_STYLE,
                ),
                html.Button(
                    "Request Farm Change",
                    id="privacy-request-farm-change-btn",
                    n_clicks=0,
                    style={
                        **AUTH_BUTTON_STYLE,
                        "backgroundColor": "#fff7ed",
                        "color": "#9a3412",
                    },
                ),
            ],
        ),
        html.Div(
            id="privacy-save-message",
            style={"marginTop": "10px", "fontSize": "13px", "color": "#28623a"},
        ),
    ]


def access_panel_content(panel_name, user, access_requests=None):
    """Small slide-out style content for logged-in user tools."""
    role = get_user_role(user)
    user_request = get_request_for_email(user, access_requests or [])

    if panel_name == "my-data":
        if not user_request:
            return [
                html.H3("My Data", style={"marginTop": 0, "color": DARK_GREEN}),
                html.P(
                    "No access request is connected to this account yet. Please submit a request through Sign Up / Request Access."
                ),
            ]

        status = str(user_request.get("status", "Pending")).title()

        if status == "Pending":
            return [
                html.H3("My Data", style={"marginTop": 0, "color": DARK_GREEN}),
                html.Div(
                    ["Status: ", access_request_status_badge("Pending"), " Pending Review"],
                    style={"fontSize": "16px", "fontWeight": "800", "marginBottom": "10px"},
                ),
                html.P(
                    "Your request has been received and is waiting for admin review. "
                    "Private farm/project data will not appear until your access is approved."
                ),
                html.Div(
                    f"Farm/project requested: {get_farm_display_name(user_request.get('farm_name'))}",
                    style={
                        "backgroundColor": "#fff7ed",
                        "border": "1px solid #fed7aa",
                        "borderRadius": "10px",
                        "padding": "12px",
                        "fontWeight": "800",
                    },
                ),
            ]

        if status == "Denied":
            return [
                html.H3("My Data", style={"marginTop": 0, "color": DARK_GREEN}),
                html.P(["Current status: ", access_request_status_badge("Denied")]),
                html.P(
                    "Your access request was denied. You can update your request information from Privacy Settings, "
                    "or contact the research team if this was unexpected."
                ),
                html.P(f"Admin note: {user_request.get('admin_note') or 'No note provided.'}"),
            ]

        farm_name = str(user_request.get("farm_name", "")).strip()
        site_scope_df = get_site_scope_from_farm_id(farm_name)
        sample_count = site_scope_df["SH_1"].nunique() if not site_scope_df.empty else 0

        return [
            html.H3("My Data", style={"marginTop": 0, "color": DARK_GREEN}),
            html.P(["Current status: ", access_request_status_badge("Approved")]),
            html.P(
                "Approved. The dashboard is now automatically filtered to your assigned site history."
            ),
            html.Div(
                [
                    html.Div(f"Farm/project: {get_farm_display_name(farm_name)}", style={"fontWeight": "800"}),
                    html.Div(f"Matching soil samples: {sample_count:,}", style={"marginTop": "4px"}),
                ],
                style={
                    "backgroundColor": "#ecfdf3",
                    "border": "1px solid #bbf7d0",
                    "borderRadius": "10px",
                    "padding": "12px",
                },
            ),
        ]

    if panel_name == "privacy":
        return privacy_panel_content(user, access_requests)

    if panel_name == "admin" and role == "admin":
        return []

    return [
        html.H3("General Trends", style={"marginTop": 0, "color": DARK_GREEN}),
        html.P("Public visitors can view the aggregate dashboard only."),
    ]

def access_panel_modal():
    return html.Div(
        id="access-panel",
        style=MODAL_HIDDEN_STYLE,
        children=[
            html.Div(
                style={
                    "width": "720px",
                    "maxWidth": "92%",
                    "margin": "70px 28px 0 auto",
                    "backgroundColor": "white",
                    "padding": "26px",
                    "borderRadius": "12px",
                    "boxShadow": "0 12px 30px rgba(0,0,0,0.25)",
                    "minHeight": "260px",
                    "maxHeight": "86vh",
                    "overflowY": "auto",
                },
                children=[
                    html.Div(id="access-panel-content"),
                    admin_panel_layout(),
                    html.Div(
                        style={"marginTop": "20px"},
                        children=[
                            html.Button(
                                "Close",
                                id="close-access-panel-btn",
                                n_clicks=0,
                                style=AUTH_SECONDARY_BUTTON_STYLE,
                            )
                        ],
                    ),
                ],
            )
        ],
    )


app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server

app.layout = html.Div(
    style={
        "fontFamily": "Arial, sans-serif",
        "backgroundColor": LIGHT_BG,
        "minHeight": "100vh",
        "color": "#17223b",
        "position": "relative",
    },
    children=[
        dcc.Store(id="auth-user-store", storage_type="session", data=None),
        dcc.Store(id="access-requests-store", storage_type="session", data=load_access_requests()),
        dcc.Store(id="admin-preview-farm-store", storage_type="session", data=None),
        dcc.Store(id="active-portal-tab-store", storage_type="session", data="dashboard"),
        html.Div(
            style={
                "background": "linear-gradient(135deg, #0c5527 0%, #156f34 55%, #0d4b22 100%)",
                "color": "white",
                "minHeight": "70px",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "space-between",
                "padding": "0 28px",
                "boxShadow": "0 2px 10px rgba(0,0,0,0.18)",
            },
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "14px"},
                    children=[
                        html.Img(
                            src="/assets/Logo.jpg",
                            style={
                                "height": "55px",
                                "width": "auto",
                                "objectFit": "contain",
                            },
                        ),
                        html.Div(
                            children=[
                                html.Div(
                                    "Soil Health Dashboard",
                                    style={"fontSize": "24px", "fontWeight": "800"},
                                ),
                                html.Div(
                                    "Explore soil health patterns across Hawaii soils and land uses",
                                    style={"fontSize": "14px", "opacity": "0.92"},
                                ),
                            ]
                        ),
                    ],
                ),
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "10px"},
                    children=[
                        html.Div(
                            id="auth-status",
                            children="Not logged in",
                            style={"fontSize": "14px", "fontWeight": "700", "marginRight": "8px"},
                        ),
                        html.Button(
                            "Log In",
                            id="open-login-btn",
                            n_clicks=0,
                            style={
                                "padding": "10px 16px",
                                "border": "none",
                                "borderRadius": "7px",
                                "cursor": "pointer",
                                "fontWeight": "800",
                            },
                        ),
                        html.Button(
                            "Sign Up",
                            id="open-signup-btn",
                            n_clicks=0,
                            style={
                                "padding": "10px 16px",
                                "border": "none",
                                "borderRadius": "7px",
                                "cursor": "pointer",
                                "fontWeight": "800",
                            },
                        ),
                        html.Button(
                            "My Data",
                            id="open-my-data-btn",
                            n_clicks=0,
                            style={"display": "none"},
                        ),
                        html.Button(
                            "Privacy",
                            id="open-privacy-btn",
                            n_clicks=0,
                            style={"display": "none"},
                        ),
                        html.Button(
                            "Admin",
                            id="open-admin-btn",
                            n_clicks=0,
                            style={"display": "none"},
                        ),
                        html.Button(
                            "Log Out",
                            id="logout-btn",
                            n_clicks=0,
                            style={
                                "display": "none",
                                "padding": "10px 16px",
                                "border": "none",
                                "borderRadius": "7px",
                                "cursor": "pointer",
                                "fontWeight": "800",
                                "backgroundColor": "#eef2f0",
                                "color": DARK_GREEN,
                            },
                        ),
                    ]
                ),
            ],
        ),

        
        html.Div(
            style={
                "backgroundColor": "white",
                "borderBottom": CARD_BORDER,
                "padding": "0 28px",
                "boxShadow": "0 1px 4px rgba(16,24,40,0.04)",
            },
            children=[
                dcc.Tabs(
                    id="portal-tabs",
                    value="dashboard",
                    children=[
                        dcc.Tab(label="Dashboard", value="dashboard"),
                        dcc.Tab(label="MIR Spectroscopy", value="ftir"),
                        dcc.Tab(label="Lab Indicators", value="lab"),
                        dcc.Tab(label="Resources", value="resources"),
                        dcc.Tab(label="About Us", value="about"),
                    ],
                    style={
                        "fontFamily": "Arial",
                        "fontWeight": "700",
                    },
                ),
            ],
        ),

        html.Div(id="portal-page-content"),

        html.Div(
            id="dashboard-page-wrapper",
            children=[
                html.Div(
                    id="admin-preview-banner",
            style={"display": "none"},
            children=[
                html.Div(id="admin-preview-banner-message"),
                html.Button(
                    "Return to Full Dataset",
                    id="admin-clear-preview-btn",
                    n_clicks=0,
                    style={
                        **AUTH_BUTTON_STYLE,
                        "backgroundColor": "white",
                        "color": "#075985",
                        "border": "1px solid #7dd3fc",
                    },
                ),
            ],
        ),
        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "300px minmax(0, 1fr)",
                "gap": "18px",
                "padding": "20px",
            },
            children=[
                card(
                    style={"alignSelf": "start", "minHeight": "800px"},
                    children=[
                        html.Div(
                            "▽ Filters",
                            style={
                                "fontSize": "18px",
                                "fontWeight": "800",
                                "color": DARK_GREEN,
                                "marginBottom": "20px",
                            },
                        ),
                        filter_dropdown(
                            "Current Land Use",
                            "current-land-use-filter",
                            options_from_column(df_original, "land_use_display"),
                        ),
                        filter_dropdown(
                            "Management Category",
                            "management-category-filter",
                            options_from_column(df_original, "management_category"),
                        ),
                        filter_dropdown(
                            "Mineralogical Class",
                            "mineral-filter",
                            options_from_column(df_original, "mineral_class"),
                        ),
                        filter_dropdown(
                            "Order",
                            "order-filter",
                            options_from_column(df_original, "order"),
                        ),
                        filter_dropdown(
                            "Suborder",
                            "suborder-filter",
                            options_from_column(df_original, "suborder"),
                        ),
                        filter_dropdown(
                            "Great Group",
                            "great-group-filter",
                            options_from_column(df_original, "great_group"),
                        ),
                        filter_dropdown(
                            "PIAL History",
                            "pial-filter",
                            options_from_column(df_original, "pial_status"),
                        ),
                        html.Div(
                            "ⓘ All charts and metrics update automatically based on your selections.",
                            style={
                                "backgroundColor": "#edf7ef",
                                "color": "#28623a",
                                "borderRadius": "8px",
                                "padding": "15px",
                                "fontSize": "13px",
                                "lineHeight": "1.45",
                                "marginTop": "22px",
                            },
                        ),
                    ],
                ),
                html.Div(
                    style={"minWidth": 0},
                    children=[
                        html.Div(
                            style={
                                "display": "grid",
                                "gridTemplateColumns": "repeat(3, minmax(0, 1fr))",
                                "gap": "16px",
                                "marginBottom": "16px",
                            },
                            children=[
                                html.Div(id="total-samples-card"),
                                html.Div(id="avg-shs-card"),
                                html.Div(id="filtered-samples-card"),
                            ],
                        ),
                        html.Div(
                            style={
                                "display": "grid",
                                "gridTemplateColumns": "minmax(0, 1.35fr) minmax(0, 0.9fr)",
                                "gap": "16px",
                                "marginBottom": "16px",
                                "alignItems": "start",
                            },
                            children=[
                                card(
                                    children=[
                                        graph_component("boxplot", 550),
                                        html.Img(
                                            id="land-use-strip-image",
                                            src="/assets/land_use_strip.png",
                                            style={
                                                "width": "90%",
                                                "display": "block",
                                                "margin": "-30px auto 6px auto",
                                            },
                                        ),
                                        html.Div(
                                            id="land-use-chart-caption",
                                            children="Boxplot shows median, middle 50%, spread, and individual sample points.",
                                            style={
                                                "fontSize": "13px",
                                                "color": "#556",
                                                "marginTop": "4px",
                                            },
                                        ),
                                    ]
                                ),
                                card(
                                    style={"alignSelf": "start"},
                                    children=[
                                        html.Div(
                                            id="suborder-section",
                                            children=[
                                                html.Div(
                                                    title_with_info("Average SHS by Suborder", SUBORDER_TOOLTIP),
                                                    style={
                                                        "fontSize": "16px",
                                                        "fontWeight": "800",
                                                        "marginBottom": "10px",
                                                    },
                                                ),
                                                dcc.Dropdown(
                                                    id="suborder-chart-filter",
                                                    options=options_from_column(df_original, "suborder"),
                                                    multi=True,
                                                    searchable=True,
                                                    placeholder="Select suborders to compare (leave blank for Top 10)",
                                                    style={"fontSize": "13px", "marginBottom": "10px"},
                                                ),
                                                graph_component("suborder-boxplot", 570),
                                                html.Div(
                                                    "Hover over the diamond points to see detailed stats for each suborder.",
                                                    style={"fontSize": "13px", "color": "#556"},
                                                ),
                                            ],
                                        ),
                                        html.Div(
                                            id="user-site-summary-section",
                                            style={"display": "none"},
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        html.Div(
                            style={
                                "display": "grid",
                                "gridTemplateColumns": "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.25fr)",
                                "gap": "16px",
                            },
                            children=[
                                card(
                                    children=[
                                        html.Div(
                                            title_with_info("Mineralogical Class Coverage", MINERAL_TOOLTIP),
                                            style={
                                                "fontSize": "16px",
                                                "fontWeight": "800",
                                                "marginBottom": "12px",
                                            },
                                        ),
                                        dash_table.DataTable(
                                            id="mineral-table",
                                            page_size=7,
                                            style_table={"overflowX": "auto"},
                                            style_cell=table_style,
                                            style_header=header_style,
                                            style_data_conditional=[
                                                {
                                                    "if": {"row_index": "odd"},
                                                    "backgroundColor": "#fafafa",
                                                }
                                            ],
                                        ),
                                    ]
                                ),
                                card(
                                    children=[
                                        html.Div(
                                            title_with_info("Land Use Coverage", LAND_USE_TOOLTIP),
                                            style={
                                                "fontSize": "16px",
                                                "fontWeight": "800",
                                                "marginBottom": "12px",
                                            },
                                        ),
                                        dash_table.DataTable(
                                            id="land-use-table",
                                            page_size=8,
                                            style_table={"overflowX": "auto"},
                                            style_cell=table_style,
                                            style_header=header_style,
                                            style_data_conditional=[
                                                {
                                                    "if": {"row_index": "odd"},
                                                    "backgroundColor": "#fafafa",
                                                }
                                            ],
                                        ),
                                    ]
                                ),
                                card(
                                    style={"position": "relative"},
                                    children=[
                                        html.Div(
                                            info_icon(PIAL_TOOLTIP),
                                            style={
                                                "position": "absolute",
                                                "top": "16px",
                                                "right": "18px",
                                                "zIndex": "5",
                                            },
                                        ),
                                        graph_component("pial-pie", 360),
                                        html.Div(
                                            "Pie chart showing samples with and without previous intensive agriculture.",
                                            style={"fontSize": "13px", "color": "#556"},
                                        ),
                                    ]
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
            ],
        ),
        login_modal(),
        signup_modal(),
        access_panel_modal(),
    ],
)



@app.callback(
    Output("portal-page-content", "children"),
    Output("dashboard-page-wrapper", "style"),
    Input("portal-tabs", "value"),
    State("auth-user-store", "data"),
)
def render_portal_tab(active_tab, user):
    if active_tab == "dashboard":
        return None, {"display": "block"}

    if active_tab == "resources":
        return html.Div(
            resources_layout(),
            style={"padding": "20px"},
        ), {"display": "none"}

    if active_tab == "about":
        return html.Div(
            about_layout(),
            style={"padding": "20px"},
        ), {"display": "none"}

    if active_tab == "ftir":
        if not user:
            return html.Div(
                card([
                    html.H3("FTIR Spectroscopy", style={"marginTop": 0, "color": DARK_GREEN}),
                    html.P("Please log in to use the FTIR spectroscopy tools."),
                ]),
                style={"padding": "20px"},
            ), {"display": "none"}

        return html.Div(
            ftir_layout(),
            style={"padding": "20px"},
        ), {"display": "none"}

    if active_tab == "lab":
        if not user:
            return html.Div(
                card([
                    html.H3("Lab Indicators", style={"marginTop": 0, "color": DARK_GREEN}),
                    html.P("Please log in to use the lab indicator tools."),
                ]),
                style={"padding": "20px"},
            ), {"display": "none"}

        return html.Div(
            lab_layout(),
            style={"padding": "20px"},
        ), {"display": "none"}

    return None, {"display": "block"}


@app.callback(
    Output("total-samples-card", "children"),
    Output("avg-shs-card", "children"),
    Output("filtered-samples-card", "children"),
    Output("boxplot", "figure"),
    Output("land-use-strip-image", "style"),
    Output("land-use-chart-caption", "children"),
    Output("suborder-boxplot", "figure"),
    Output("suborder-section", "style"),
    Output("user-site-summary-section", "children"),
    Output("user-site-summary-section", "style"),
    Output("land-use-table", "data"),
    Output("land-use-table", "columns"),
    Output("mineral-table", "data"),
    Output("mineral-table", "columns"),
    Output("pial-pie", "figure"),
    Input("current-land-use-filter", "value"),
    Input("management-category-filter", "value"),
    Input("mineral-filter", "value"),
    Input("order-filter", "value"),
    Input("suborder-filter", "value"),
    Input("great-group-filter", "value"),
    Input("pial-filter", "value"),
    Input("suborder-chart-filter", "value"),
    Input("auth-user-store", "data"),
    Input("access-requests-store", "data"),
    Input("admin-preview-farm-store", "data"),
)
def update_dashboard(
    current_land_use,
    management_category,
    mineral_class,
    order,
    suborder,
    great_group,
    pial_status,
    selected_chart_suborders,
    user,
    access_requests,
    admin_preview_farm_id,
):
    scoped_df, dashboard_scope_label = get_dashboard_data_for_user(user, access_requests, admin_preview_farm_id)

    filtered = apply_filters(
        scoped_df,
        current_land_use,
        management_category,
        mineral_class,
        order,
        suborder,
        great_group,
        pial_status,
    )

    total_samples = scoped_df["SH_1"].nunique()
    filtered_samples = filtered["SH_1"].nunique()
    avg_shs = filtered["shs"].mean()

    total_card = metric_card("⚗", "Total Samples", f"{total_samples:,}", dashboard_scope_label)
    avg_card = metric_card(
        "⌁",
        title_with_info("Average Soil Health Score", SHS_TOOLTIP),
        "N/A" if pd.isna(avg_shs) else f"{avg_shs:.2f}",
        "Average SHS 0–1 scale",
    )
    filtered_card = metric_card(
        "♣",
        "Filtered Samples",
        f"{filtered_samples:,}",
        "Samples after filters",
    )

    approved_user_request = get_approved_user_request(user, access_requests)

    # Admin preview should look like the user's My Data screen, not the public dashboard.
    # Admins do not have access_requests rows, so we create a small preview request object
    # from the selected SH_1 and pass it into the same private chart/summary functions.
    admin_preview_request = None
    if get_user_role(user) == "admin" and admin_preview_farm_id:
        preview_id = str(admin_preview_farm_id).strip()
        admin_preview_request = {
            "farm_name": preview_id,
            "site_name": get_farm_display_name(preview_id),
            "status": "Approved",
        }

    private_view_request = approved_user_request or admin_preview_request

    land_use_strip_style = {
        "width": "90%",
        "display": "block",
        "margin": "-30px auto 6px auto",
    }
    land_use_caption = "Boxplot shows median, middle 50%, spread, and individual sample points."
    suborder_section_style = {"display": "block"}
    user_site_summary_style = {"display": "none"}
    user_site_summary_children = []

    if private_view_request:
        box_fig = make_user_shs_over_time_figure(filtered, private_view_request)
        land_use_strip_style = {"display": "none"}
        land_use_caption = (
            "This private chart shows your Soil Health Score by sample date. "
            "The dashed line shows the public dataset average for comparison."
        )
        suborder_section_style = {"display": "none"}
        user_site_summary_style = {"display": "block"}
        user_site_summary_children = make_user_site_summary(filtered, private_view_request)
    else:
        box_df = filtered.dropna(subset=["shs", "box_land_use_group"])
        box_df = box_df[box_df["box_land_use_group"].isin(BOX_GROUP_ORDER)]

        if box_df.empty:
            box_fig = empty_figure("Soil Health Score Across Different Land Uses", 550)
        else:
            box_fig = px.box(
                box_df,
                x="box_land_use_group",
                y="shs",
                category_orders={"box_land_use_group": BOX_GROUP_ORDER},
                points="all",
                title="Soil Health Score Across Different Land Uses",
                labels={
                    "box_land_use_group": "Current Land Use",
                    "shs": "Soil Health Score (SHS)",
                },
                height=550,
            )

            box_fig.update_traces(
                fillcolor="rgba(99,102,241,0.32)",
                line=dict(color=BLUE, width=1.4),
                marker=dict(color=BLUE, size=4, opacity=0.42, line=dict(width=0)),
                jitter=0.25,
                pointpos=0,
            )

            medians = box_df.groupby("box_land_use_group")["shs"].median().reindex(BOX_GROUP_ORDER)

            box_fig.add_trace(
                go.Scatter(
                    x=BOX_GROUP_ORDER,
                    y=medians,
                    mode="lines+markers",
                    name="Median",
                    line=dict(color="#f28e2b", width=2),
                    marker=dict(size=5),
                )
            )

            box_fig.update_yaxes(range=[0, 1.05], dtick=0.25)
            box_fig.update_xaxes(tickangle=0)
            box_fig = style_figure(box_fig)

            box_fig.update_layout(
                title=dict(
                    text="Soil Health Score Across Different Land Uses",
                    x=0.02,
                    y=0.96,
                    font=dict(size=16),
                ),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.08,
                    xanchor="left",
                    x=0,
                ),
                margin=dict(l=50, r=35, t=85, b=55),
            )

    suborder_df = filtered.dropna(subset=["suborder", "shs"]).copy()
    suborder_df["suborder"] = suborder_df["suborder"].astype(str).str.strip()

    if selected_chart_suborders:
        chosen_suborders = selected_chart_suborders
        chart_title = "Selected Suborders by SHS Distribution"
    else:
        suborder_summary = (
            suborder_df
            .groupby("suborder", as_index=False)
            .agg(
                avg_shs=("shs", "mean"),
                sample_count=("SH_1", "nunique"),
            )
        )

        suborder_summary = (
            suborder_summary[suborder_summary["sample_count"] >= 10]
            .sort_values("avg_shs", ascending=False)
            .head(10)
        )

        chosen_suborders = suborder_summary["suborder"].tolist()
        chart_title = "Top 10 Suborders by Average SHS"

    plot_df = suborder_df[suborder_df["suborder"].isin(chosen_suborders)].copy()

    if plot_df.empty:
        suborder_fig = empty_figure("Average SHS by Suborder", 570)
    else:
        stats_df = (
            plot_df
            .groupby("suborder")
            .agg(
                sample_count=("SH_1", "nunique"),
                minimum=("shs", "min"),
                q1=("shs", lambda x: x.quantile(0.25)),
                median=("shs", "median"),
                mean=("shs", "mean"),
                q3=("shs", lambda x: x.quantile(0.75)),
                maximum=("shs", "max"),
            )
            .reset_index()
        )

        if selected_chart_suborders:
            stats_df["_order"] = stats_df["suborder"].apply(
                lambda x: chosen_suborders.index(x) if x in chosen_suborders else 999
            )
            stats_df = stats_df.sort_values("_order").drop(columns="_order")
        else:
            stats_df = stats_df.sort_values("mean", ascending=False)

        stats_df["suborder_label"] = stats_df.apply(
            lambda row: f"{row['suborder']} (n={int(row['sample_count'])})",
            axis=1,
        )

        label_lookup = dict(zip(stats_df["suborder"], stats_df["suborder_label"]))
        plot_df["suborder_label"] = plot_df["suborder"].map(label_lookup)

        ordered_labels = stats_df["suborder_label"].tolist()

        suborder_fig = go.Figure()

        suborder_fig.add_trace(
            go.Box(
                x=plot_df["shs"],
                y=plot_df["suborder_label"],
                orientation="h",
                name="",
                boxmean=False,
                marker_color=GREEN,
                line=dict(color=GREEN, width=2.6),
                fillcolor="rgba(21,111,52,0.22)",
                showlegend=False,
                hoverinfo="skip",
                hovertemplate=None,
            )
        )

        suborder_fig.add_trace(
            go.Scatter(
                x=stats_df["mean"],
                y=stats_df["suborder_label"],
                mode="markers",
                name="Mean",
                marker=dict(
                    symbol="diamond",
                    size=8,
                    color=GREEN,
                    line=dict(color="white", width=1),
                ),
                customdata=stats_df[
                    ["suborder", "sample_count", "minimum", "q1", "median", "mean", "q3", "maximum"]
                ],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Samples: %{customdata[1]}<br>"
                    "Minimum: %{customdata[2]:.2f}<br>"
                    "25th percentile: %{customdata[3]:.2f}<br>"
                    "Median: %{customdata[4]:.2f}<br>"
                    "Mean: %{customdata[5]:.2f}<br>"
                    "75th percentile: %{customdata[6]:.2f}<br>"
                    "Maximum: %{customdata[7]:.2f}"
                    "<extra></extra>"
                ),
                showlegend=False,
            )
        )

        suborder_fig.update_layout(
            template="plotly_white",
            height=570,
            autosize=False,
            title=dict(text=chart_title, x=0.02, font=dict(size=16)),
            margin=dict(l=115, r=35, t=60, b=65),
            font=dict(family="Arial", size=12, color="#17223b"),
            paper_bgcolor="white",
            plot_bgcolor="white",
            hovermode="closest",
        )

        suborder_fig.update_xaxes(
            title="Soil Health Score (SHS)",
            range=[0, 1.05],
            dtick=0.25,
        )

        suborder_fig.update_yaxes(
            categoryorder="array",
            categoryarray=ordered_labels,
            autorange="reversed",
            title="",
        )

    land_counts = make_count_table(
        filtered,
        "land_use_display",
        "Land Use",
        preferred_order=LAND_USE_COVERAGE_ORDER,
    )

    mineral_counts = make_count_table(
        filtered,
        "mineral_class",
        "Mineralogical Class",
        preferred_order=MINERAL_COVERAGE_ORDER,
    )

    pial_counts = (
        filtered["pial_status"]
        .dropna()
        .value_counts()
        .rename_axis("PIAL Status")
        .reset_index(name="Count")
    )

    if pial_counts.empty:
        pie_fig = empty_figure("History of Previous Intensive Agriculture", 360)
    else:
        pial_counts = pial_counts[pial_counts["PIAL Status"] != "Other"]

        pie_fig = px.pie(
            pial_counts,
            names="PIAL Status",
            values="Count",
            title="History of Previous Intensive Agriculture (PIAL)",
            height=360,
        )

        pie_fig.update_traces(
            textinfo="label+percent",
            textposition="inside",
            sort=False,
            marker=dict(colors=[BLUE, "#4caf69"]),
        )

        pie_fig = style_figure(pie_fig)

        pie_fig.update_layout(
            title=dict(
                text="History of Previous Intensive Agriculture (PIAL)",
                x=0.5,
                font=dict(size=15),
            ),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.12,
                xanchor="center",
                x=0.5,
            ),
            margin=dict(l=25, r=25, t=75, b=75),
        )

    land_columns = [{"name": c, "id": c} for c in land_counts.columns]
    mineral_columns = [{"name": c, "id": c} for c in mineral_counts.columns]

    return (
        total_card,
        avg_card,
        filtered_card,
        box_fig,
        land_use_strip_style,
        land_use_caption,
        suborder_fig,
        suborder_section_style,
        user_site_summary_children,
        user_site_summary_style,
        land_counts.to_dict("records"),
        land_columns,
        mineral_counts.to_dict("records"),
        mineral_columns,
        pie_fig,
    )


@app.callback(
    Output("login-modal", "style"),
    Output("signup-modal", "style"),
    Output("auth-user-store", "data"),
    Output("login-message", "children"),
    Output("signup-message", "children"),
    Output("access-requests-store", "data"),
    Input("open-login-btn", "n_clicks"),
    Input("close-login-btn", "n_clicks"),
    Input("open-signup-btn", "n_clicks"),
    Input("close-signup-btn", "n_clicks"),
    Input("login-submit-btn", "n_clicks"),
    Input("signup-submit-btn", "n_clicks"),
    Input("logout-btn", "n_clicks"),
    State("login-email", "value"),
    State("login-password", "value"),
    State("signup-first-name", "value"),
    State("signup-last-name", "value"),
    State("signup-email", "value"),
    State("signup-phone", "value"),
    State("signup-password", "value"),
    State("signup-farm-name", "value"),
    State("signup-data-reuse", "value"),
    State("signup-permission-check", "value"),
    State("auth-user-store", "data"),
    State("access-requests-store", "data"),
    prevent_initial_call=True,
)
def handle_auth_actions(
    open_login_clicks,
    close_login_clicks,
    open_signup_clicks,
    close_signup_clicks,
    login_clicks,
    signup_clicks,
    logout_clicks,
    login_email,
    login_password,
    signup_first_name,
    signup_last_name,
    signup_email,
    signup_phone,
    signup_password,
    signup_farm_name,
    signup_data_reuse,
    signup_permission_check,
    current_user,
    access_requests,
):
    triggered_id = ctx.triggered_id
    access_requests = access_requests or []

    if triggered_id == "open-login-btn":
        return MODAL_OVERLAY_STYLE, MODAL_HIDDEN_STYLE, current_user, "", "", access_requests

    if triggered_id == "close-login-btn":
        return MODAL_HIDDEN_STYLE, MODAL_HIDDEN_STYLE, current_user, "", "", access_requests

    if triggered_id == "open-signup-btn":
        return MODAL_HIDDEN_STYLE, MODAL_OVERLAY_STYLE, current_user, "", "", access_requests

    if triggered_id == "close-signup-btn":
        return MODAL_HIDDEN_STYLE, MODAL_HIDDEN_STYLE, current_user, "", "", access_requests

    if triggered_id == "logout-btn":
        try:
            sign_out_user()
        except Exception:
            pass

        return MODAL_HIDDEN_STYLE, MODAL_HIDDEN_STYLE, None, "", "", access_requests

    if triggered_id == "login-submit-btn":
        if not login_email or not login_password:
            return (
                MODAL_OVERLAY_STYLE,
                MODAL_HIDDEN_STYLE,
                current_user,
                "Please enter both email and password.",
                "",
                access_requests,
            )

        try:
            user, session = sign_in_user(login_email, login_password)

            # If Supabase requires email confirmation, unverified users should not get
            # a valid session. Do not mark them as logged in unless a session exists.
            if not session:
                return (
                    MODAL_OVERLAY_STYLE,
                    MODAL_HIDDEN_STYLE,
                    current_user,
                    "Please verify your email before logging in.",
                    "",
                    access_requests,
                )

            email = str(get_user_email(user) or login_email).lower().strip()

            # SECURITY / ACCESS-WORKFLOW CHECK:
            # A Supabase Auth account alone is not enough to enter the dashboard.
            # Regular users must also have a matching row in access_requests.
            # This prevents old/orphan Auth accounts from logging in before submitting
            # the Request Access form. Admins are allowed through using config/admins.json.
            latest_requests = load_access_requests()
            is_admin = email in ADMIN_EMAILS

            # Admin accounts are allowed in without an access_requests row.
            # Regular users still need an access request row.
            if is_admin:
                return (
                    MODAL_HIDDEN_STYLE,
                    MODAL_HIDDEN_STYLE,
                    {"email": email},
                    "",
                    "",
                    latest_requests,
                )

            matching_request = get_access_request_by_email(email)

            if matching_request is None:
                try:
                    sign_out_user()
                except Exception:
                    pass

                return (
                    MODAL_OVERLAY_STYLE,
                    MODAL_HIDDEN_STYLE,
                    current_user,
                    "No access request was found for this account. Please click Sign Up / Request Access first.",
                    "",
                    latest_requests,
                )

            return (
                MODAL_HIDDEN_STYLE,
                MODAL_HIDDEN_STYLE,
                {"email": email},
                "",
                "",
                latest_requests,
            )

        except Exception as e:
            return (
                MODAL_OVERLAY_STYLE,
                MODAL_HIDDEN_STYLE,
                current_user,
                f"Login failed: {str(e)}",
                "",
                access_requests,
            )

    if triggered_id == "signup-submit-btn":
        # Always check the latest Supabase requests before validating duplicates.
        access_requests = load_access_requests()

        missing_fields = [
            not signup_first_name,
            not signup_last_name,
            not signup_email,
            not signup_phone,
            not signup_password,
            not signup_farm_name,
        ]

        if any(missing_fields):
            return (
                MODAL_HIDDEN_STYLE,
                MODAL_OVERLAY_STYLE,
                current_user,
                "",
                "Please complete all fields before submitting your request.",
                access_requests,
            )

        if "acknowledged" not in (signup_permission_check or []):
            return (
                MODAL_HIDDEN_STYLE,
                MODAL_OVERLAY_STYLE,
                current_user,
                "",
                "Please check the permission acknowledgement before submitting.",
                access_requests,
            )

        existing_request = get_access_request_by_email(signup_email)

        if existing_request:
            existing_status = str(existing_request.get("status", "Pending")).title()

            if existing_status == "Pending":
                return (
                    MODAL_HIDDEN_STYLE,
                    MODAL_OVERLAY_STYLE,
                    current_user,
                    "",
                    "You already have a request under review.",
                    access_requests,
                )

            if existing_status == "Approved":
                return (
                    MODAL_HIDDEN_STYLE,
                    MODAL_OVERLAY_STYLE,
                    current_user,
                    "",
                    "You already have approved access. Please log in instead.",
                    access_requests,
                )

            if existing_status == "Denied":
                try:
                    update_access_request_profile(
                        request_id=existing_request.get("request_id"),
                        first_name=signup_first_name,
                        last_name=signup_last_name,
                        phone=signup_phone,
                        farm_name=signup_farm_name,
                        data_reuse_permission=signup_data_reuse or DEFAULT_DATA_REUSE_PERMISSION,
                        reset_to_pending=True,
                    )
                    updated_requests = load_access_requests()
                    return (
                        MODAL_HIDDEN_STYLE,
                        MODAL_OVERLAY_STYLE,
                        current_user,
                        "",
                        "Your denied request was updated and resubmitted for admin review.",
                        updated_requests,
                    )
                except Exception as e:
                    return (
                        MODAL_HIDDEN_STYLE,
                        MODAL_OVERLAY_STYLE,
                        current_user,
                        "",
                        f"Could not resubmit your request: {str(e)}",
                        access_requests,
                    )

        try:
            # IMPORTANT:
            # Signing up should NOT log the user into the dashboard.
            # Supabase Auth may already have this email from earlier testing.
            # If the Auth user already exists but there is no access_requests row,
            # we still create the access request so the admin can review it.
            auth_user_already_exists = False
            try:
                sign_up_user(signup_email, signup_password)
            except Exception as auth_error:
                auth_error_text = str(auth_error).lower()
                already_registered_messages = [
                    "already registered",
                    "user already registered",
                    "user already exists",
                    "already exists",
                ]

                if any(message in auth_error_text for message in already_registered_messages):
                    auth_user_already_exists = True
                else:
                    raise auth_error

            new_request = {
                "first_name": str(signup_first_name).strip(),
                "last_name": str(signup_last_name).strip(),
                "email": str(signup_email).lower().strip(),
                "phone": str(signup_phone).strip(),
                "farm_name": str(signup_farm_name).strip(),  # stores SH_1 internally
                "site_name": get_site_name(signup_farm_name),  # friendly site name for Supabase/admin viewing
                "data_reuse_permission": signup_data_reuse or DEFAULT_DATA_REUSE_PERMISSION,
                "data_reuse_updated_at": datetime.now(timezone.utc).isoformat(),
                "permission_acknowledged": True,
                "status": "Pending",
                "request_type": "New Access",
                "admin_note": "",
            }

            create_access_request(new_request)
            updated_requests = load_access_requests()

            if auth_user_already_exists:
                success_message = (
                    "Access request submitted. This email already had a login account, "
                    "so use the existing password when you log in after admin review."
                )
            else:
                success_message = (
                    "Request submitted. Please check your email to verify your account. "
                    "Your data access will stay pending until an admin approves it."
                )

            return (
                MODAL_HIDDEN_STYLE,
                MODAL_OVERLAY_STYLE,
                current_user,
                "",
                success_message,
                updated_requests,
            )

        except Exception as e:
            return (
                MODAL_HIDDEN_STYLE,
                MODAL_OVERLAY_STYLE,
                current_user,
                "",
                f"Sign up failed: {str(e)}",
                access_requests,
            )

    return MODAL_HIDDEN_STYLE, MODAL_HIDDEN_STYLE, current_user, "", "", access_requests


@app.callback(
    Output("auth-status", "children"),
    Output("open-login-btn", "style"),
    Output("open-signup-btn", "style"),
    Output("open-my-data-btn", "style"),
    Output("open-privacy-btn", "style"),
    Output("open-admin-btn", "style"),
    Output("logout-btn", "style"),
    Input("auth-user-store", "data"),
)
def update_auth_header(user):
    base_button = {
        "padding": "10px 16px",
        "border": "none",
        "borderRadius": "7px",
        "cursor": "pointer",
        "fontWeight": "800",
    }

    light_button = {
        **base_button,
        "backgroundColor": "#eef2f0",
        "color": DARK_GREEN,
    }

    hidden_style = {**base_button, "display": "none"}

    if not user:
        return (
            "Not logged in",
            base_button,
            base_button,
            hidden_style,
            hidden_style,
            hidden_style,
            {**light_button, "display": "none"},
        )

    role = get_user_role(user)
    email = user.get("email", "user")

    admin_style = light_button if role == "admin" else hidden_style

    return (
        f"Logged in as: {email}",
        hidden_style,
        hidden_style,
        light_button,
        light_button,
        admin_style,
        light_button,
    )



@app.callback(
    Output("access-panel", "style"),
    Output("access-panel-content", "children"),
    Output("admin-panel-section", "style"),
    Input("open-my-data-btn", "n_clicks"),
    Input("open-privacy-btn", "n_clicks"),
    Input("open-admin-btn", "n_clicks"),
    Input("close-access-panel-btn", "n_clicks"),
    State("auth-user-store", "data"),
    State("access-requests-store", "data"),
    prevent_initial_call=True,
)
def handle_access_panel(my_data_clicks, privacy_clicks, admin_clicks, close_clicks, user, access_requests):
    triggered_id = ctx.triggered_id
    access_requests = load_access_requests()

    hidden_admin_style = {"display": "none"}
    visible_admin_style = {"display": "block"}

    if triggered_id == "close-access-panel-btn":
        return MODAL_HIDDEN_STYLE, [], hidden_admin_style

    if triggered_id == "open-my-data-btn":
        return (
            MODAL_OVERLAY_STYLE,
            access_panel_content("my-data", user, access_requests),
            hidden_admin_style,
        )

    if triggered_id == "open-privacy-btn":
        return (
            MODAL_OVERLAY_STYLE,
            access_panel_content("privacy", user, access_requests),
            hidden_admin_style,
        )

    if triggered_id == "open-admin-btn":
        if get_user_role(user) != "admin":
            return (
                MODAL_OVERLAY_STYLE,
                [
                    html.H3("Admin", style={"marginTop": 0, "color": DARK_GREEN}),
                    html.P("Only admins can view access requests."),
                ],
                hidden_admin_style,
            )

        return MODAL_OVERLAY_STYLE, [], visible_admin_style

    return MODAL_HIDDEN_STYLE, [], hidden_admin_style


@app.callback(
    Output("access-requests-table", "data"),
    Output("admin-request-selector", "options"),
    Output("admin-request-selector", "value"),
    Input("access-requests-store", "data"),
    Input("admin-status-filter", "value"),
    Input("admin-search-input", "value"),
    Input("admin-farm-search-input", "value"),
)
def update_admin_request_table(access_requests, status_filter, search_text, farm_search):
    access_requests = access_requests or []
    filtered = access_requests.copy()

    if status_filter and status_filter != "All":
        filtered = [
            request for request in filtered
            if str(request.get("status", "")).title() == status_filter
        ]

    if search_text:
        needle = str(search_text).lower().strip()
        filtered = [
            request for request in filtered
            if needle in str(request.get("email", "")).lower()
            or needle in str(request.get("first_name", "")).lower()
            or needle in str(request.get("last_name", "")).lower()
        ]

    if farm_search:
        farm_needle = str(farm_search).lower().strip()
        filtered = [
            request for request in filtered
            if farm_needle in str(request.get("farm_name", "")).lower()
            or farm_needle in str(request.get("site_name", "")).lower()
        ]

    return filtered, pending_request_options(access_requests), None


@app.callback(
    Output("admin-farm-name-edit", "value"),
    Output("admin-note-input", "value"),
    Input("admin-request-selector", "value"),
    State("access-requests-store", "data"),
    prevent_initial_call=True,
)
def fill_admin_review_fields(selected_request_id, access_requests):
    if not selected_request_id:
        return None, ""

    for request in access_requests or []:
        if str(request.get("request_id")) == str(selected_request_id):
            return request.get("farm_name"), request.get("admin_note") or ""

    return None, ""


@app.callback(
    Output("admin-farm-data-preview", "children"),
    Input("admin-farm-name-edit", "value"),
    prevent_initial_call=True,
)
def update_admin_farm_data_preview(selected_farm_id):
    if not selected_farm_id:
        return html.Div(
            "Select a farm/project to preview the matching soil data before approving.",
            style={"fontSize": "13px", "color": "#6b7280"},
        )

    preview_df = get_farm_preview_rows(selected_farm_id)
    farm_display_name = get_farm_display_name(selected_farm_id)

    if preview_df.empty:
        return html.Div(
            [
                html.Div("No matching soil data found.", style={"fontWeight": "800", "color": "#991b1b"}),
                html.Div(
                    f"Admin check: selected internal ID is {selected_farm_id}, but no soil rows matched it.",
                    style={"fontSize": "13px", "color": "#6b7280", "marginTop": "4px"},
                ),
            ],
            style={
                "backgroundColor": "#fef2f2",
                "border": "1px solid #fecaca",
                "borderRadius": "10px",
                "padding": "12px",
            },
        )

    preview_columns = [
        col for col in [
            FARM_ID_COLUMN,
            "site_name",
            "latitude",
            "longitude",
            "shs",
            "minerals",
            "mineral_class",
            "order",
            "suborder",
            "great_group",
            "management_category",
            "current_land_use",
            "most_previous_land_use",
            "pial_status",
        ]
        if col in preview_df.columns
    ]

    table_df = preview_df[preview_columns].head(10).copy()

    return html.Div(
        children=[
            html.Div(
                "Admin farm data preview",
                style={"fontWeight": "800", "color": DARK_GREEN, "marginBottom": "6px"},
            ),
            html.Div(
                f"Farm/project: {farm_display_name}",
                style={"fontSize": "13px", "fontWeight": "800"},
            ),
            html.Div(
                f"Internal ID used for matching: {selected_farm_id}",
                style={"fontSize": "12px", "color": "#6b7280", "marginTop": "2px"},
            ),
            html.Div(
                "Site grouping key: site_name + plot_name",
                style={"fontSize": "12px", "color": "#6b7280", "marginTop": "2px"},
            ),
            html.Div(
                f"Matching soil rows: {len(preview_df):,}",
                style={"fontSize": "12px", "color": "#6b7280", "marginTop": "2px", "marginBottom": "10px"},
            ),
            dash_table.DataTable(
                data=table_df.to_dict("records"),
                columns=[{"name": c, "id": c} for c in table_df.columns],
                page_size=5,
                style_table={"overflowX": "auto"},
                style_cell={
                    **table_style,
                    "fontSize": "12px",
                    "minWidth": "100px",
                    "maxWidth": "220px",
                    "whiteSpace": "normal",
                },
                style_header=header_style,
            ),
        ],
        style={
            "backgroundColor": "#ecfdf3",
            "border": "1px solid #bbf7d0",
            "borderRadius": "10px",
            "padding": "12px",
        },
    )


@app.callback(
    Output("lab-template-download", "data"),
    Input("lab-template-btn", "n_clicks"),
    prevent_initial_call=True,
)
def download_lab_template(n_clicks):
    template_path = Path(__file__).resolve().parent / "app" / "data_template.csv"

    if not template_path.exists():
        template_path = Path(__file__).resolve().parent / "data_template.csv"

    if not template_path.exists():
        raise PreventUpdate

    return dcc.send_file(str(template_path))


@app.callback(
    Output("lab-upload-label", "children"),
    Input("lab-upload", "filename"),
)
def update_lab_upload_label(filename):
    if not filename:
        return "Browse...   No file selected"

    return f"Browse...   {filename}"


def make_lab_score_graph(scored_df):
    if scored_df is None or scored_df.empty or "score_percentile" not in scored_df.columns:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_white",
            height=260,
            margin=dict(l=80, r=30, t=20, b=50),
            xaxis_title="Score percentile",
            yaxis_title="",
            annotations=[
                dict(
                    text="No scored samples yet.",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    xref="paper",
                    yref="paper",
                )
            ],
        )
        fig.update_xaxes(range=[0, 100])
        return fig

    graph_df = scored_df.copy()
    graph_df["score_percentile"] = pd.to_numeric(graph_df["score_percentile"], errors="coerce")
    graph_df = graph_df.dropna(subset=["score_percentile"])

    fig = px.bar(
        graph_df,
        x="score_percentile",
        y="sample_id",
        orientation="h",
        text="score_percentile",
    )

    fig.update_traces(
        texttemplate="%{text:.1f}",
        textposition="outside",
    )

    fig.update_layout(
        template="plotly_white",
        height=260,
        margin=dict(l=90, r=40, t=10, b=50),
        xaxis_title="Score percentile",
        yaxis_title="",
        showlegend=False,
    )

    fig.update_xaxes(range=[0, 100])
    fig.update_yaxes(autorange="reversed")

    return fig


def round_lab_dataframe(df):
    if df is None or df.empty:
        return df

    rounded = df.copy()

    for col in rounded.columns:
        if pd.api.types.is_numeric_dtype(rounded[col]):
            rounded[col] = rounded[col].round(2)

    return rounded


@app.callback(
    Output("lab-status", "children"),
    Output("lab-scores-output", "children"),
    Output("lab-core-output", "children"),
    Output("lab-dropped-output", "children"),
    Output("lab-results-store", "data"),
    Output("lab-score-graph", "figure"),
    Input("lab-score-btn", "n_clicks"),
    State("lab-upload", "contents"),
    State("lab-upload", "filename"),
    State("lab-consent-check", "value"),
    prevent_initial_call=True,
)
def score_lab_samples(n_clicks, contents, filename, consent_value):
    empty_fig = make_lab_score_graph(pd.DataFrame())

    if not contents:
        return "Please upload a CSV file first.", None, None, None, None, empty_fig

    if "consent" not in (consent_value or []):
        return "Please check the consent box before scoring samples.", None, None, None, None, empty_fig

    if not filename or not filename.lower().endswith(".csv"):
        return "Please upload a CSV file.", None, None, None, None, empty_fig

    try:
        _content_type, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)

        with tempfile.TemporaryDirectory() as tmpdir_raw:
            tmpdir = Path(tmpdir_raw)
            safe_filename = Path(filename).name
            input_path = tmpdir / safe_filename

            output_path = tmpdir / "lab_scored_results.csv"
            core_path = tmpdir / "lab_core_results.csv"
            dropped_path = tmpdir / "lab_dropped_samples.csv"

            # Fallback names from the R script.
            scores_fallback_path = tmpdir / "scores.csv"
            core_fallback_path = tmpdir / "core.csv"
            dropped_fallback_path = tmpdir / "dropped.csv"

            input_path.write_bytes(decoded)

            script_path = Path(__file__).resolve().parent / "lab_score_cli.R"
            if not script_path.exists():
                return "Scoring failed: lab_score_cli.R was not found in the project folder.", None, None, None, None, empty_fig

            result = subprocess.run(
                [
                    r"C:\Program Files\R\R-4.4.3\bin\x64\Rscript.exe",
                    str(script_path),
                    "--input",
                    str(input_path),
                    "--outdir",
                    str(tmpdir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                error_text = (result.stderr or result.stdout or "Unknown scoring error.").strip()
                return f"Scoring failed: {error_text}", None, None, None, None, empty_fig

            if not output_path.exists() and scores_fallback_path.exists():
                output_path = scores_fallback_path

            if not core_path.exists() and core_fallback_path.exists():
                core_path = core_fallback_path

            if not dropped_path.exists() and dropped_fallback_path.exists():
                dropped_path = dropped_fallback_path

            if not output_path.exists():
                return "Scoring finished, but no scores output file was created.", None, None, None, None, empty_fig

            scored_df = pd.read_csv(output_path)

            if core_path.exists():
                core_df = pd.read_csv(core_path)
            else:
                core_df = scored_df.copy()

            dropped_df = pd.DataFrame()
            if dropped_path.exists():
                try:
                    dropped_df = pd.read_csv(dropped_path)
                except Exception:
                    dropped_df = pd.DataFrame()

            scored_df = round_lab_dataframe(scored_df)
            core_df = round_lab_dataframe(core_df)
            dropped_df = round_lab_dataframe(dropped_df)

            score_fig = make_lab_score_graph(scored_df)

            scores_table = dash_table.DataTable(
                data=scored_df.to_dict("records"),
                columns=[{"name": str(c), "id": str(c)} for c in scored_df.columns],
                page_size=10,
                style_table={"overflowX": "auto", "marginTop": "12px"},
                style_cell={
                    **table_style,
                    "minWidth": "110px",
                    "maxWidth": "240px",
                    "whiteSpace": "normal",
                },
                style_header=header_style,
            )

            core_table = dash_table.DataTable(
                data=core_df.to_dict("records"),
                columns=[{"name": str(c), "id": str(c)} for c in core_df.columns],
                page_size=10,
                style_table={"overflowX": "auto", "marginTop": "12px"},
                style_cell={
                    **table_style,
                    "minWidth": "110px",
                    "maxWidth": "240px",
                    "whiteSpace": "normal",
                },
                style_header=header_style,
            )

            if dropped_df.empty:
                dropped_output = html.P("No dropped samples.")
                dropped_count = 0
            else:
                dropped_count = len(dropped_df)
                dropped_output = dash_table.DataTable(
                    data=dropped_df.to_dict("records"),
                    columns=[{"name": str(c), "id": str(c)} for c in dropped_df.columns],
                    page_size=10,
                    style_table={"overflowX": "auto", "marginTop": "12px"},
                    style_cell={
                        **table_style,
                        "minWidth": "110px",
                        "maxWidth": "240px",
                        "whiteSpace": "normal",
                    },
                    style_header=header_style,
                )

            return (
                f"Scored {len(scored_df):,} sample(s); dropped {dropped_count:,}.",
                scores_table,
                core_table,
                dropped_output,
                scored_df.to_dict("records"),
                score_fig,
            )

    except FileNotFoundError as e:
        if "Rscript" in str(e):
            return "Scoring failed: Rscript was not found. Install R or make sure Rscript is on your PATH.", None, None, None, None, empty_fig
        return f"Scoring failed: {e}", None, None, None, None, empty_fig

    except Exception as e:
        return f"Scoring failed: {e}", None, None, None, None, empty_fig


@app.callback(
    Output("lab-scored-download", "data"),
    Input("lab-download-btn", "n_clicks"),
    State("lab-results-store", "data"),
    prevent_initial_call=True,
)
def download_lab_scored_results(n_clicks, stored_results):
    if not stored_results:
        raise PreventUpdate

    scored_df = pd.DataFrame(stored_results)
    return dcc.send_data_frame(scored_df.to_csv, "lab_scored_results.csv", index=False)

@app.callback(
    Output("admin-farm-explorer-preview", "children"),
    Input("admin-farm-explorer-dropdown", "value"),
)
def update_admin_farm_explorer_preview(selected_farm_id):
    return update_admin_farm_data_preview(selected_farm_id)



@app.callback(
    Output("admin-preview-banner", "style"),
    Output("admin-preview-banner-message", "children"),
    Input("admin-preview-farm-store", "data"),
    Input("auth-user-store", "data"),
)
def update_admin_preview_banner(admin_preview_farm_id, user):
    hidden_style = {"display": "none"}

    if get_user_role(user) != "admin" or not admin_preview_farm_id:
        return hidden_style, None

    preview_df = get_farm_preview_rows(admin_preview_farm_id)
    farm_display_name = get_farm_display_name(admin_preview_farm_id)
    sample_count = preview_df["SH_1"].nunique() if not preview_df.empty and "SH_1" in preview_df.columns else 0
    avg_shs = preview_df["shs"].mean() if not preview_df.empty and "shs" in preview_df.columns else None

    avg_text = "N/A" if pd.isna(avg_shs) else f"{avg_shs:.2f}"

    visible_style = {
        "margin": "14px 20px 0 20px",
        "padding": "12px 16px",
        "borderRadius": "10px",
        "border": "1px solid #bae6fd",
        "backgroundColor": "#e0f2fe",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
        "gap": "14px",
        "flexWrap": "wrap",
    }

    message = html.Div(
        children=[
            html.Div(
                f"Admin preview mode: {farm_display_name}",
                style={"fontWeight": "800", "color": "#075985", "fontSize": "15px"},
            ),
            html.Div(
                f"Internal SH_1: {admin_preview_farm_id} • Matching samples: {sample_count:,} • Average SHS: {avg_text}",
                style={"fontSize": "13px", "color": "#075985", "marginTop": "3px"},
            ),
        ]
    )

    return visible_style, message


@app.callback(
    Output("admin-preview-farm-store", "data"),
    Input("admin-preview-main-btn", "n_clicks"),
    Input("admin-preview-explorer-btn", "n_clicks"),
    Input("admin-clear-preview-btn", "n_clicks"),
    State("admin-farm-name-edit", "value"),
    State("admin-farm-explorer-dropdown", "value"),
    State("auth-user-store", "data"),
    prevent_initial_call=True,
)
def manage_admin_main_dashboard_preview(
    main_preview_clicks,
    explorer_preview_clicks,
    clear_preview_clicks,
    review_farm_id,
    explorer_farm_id,
    user,
):
    if get_user_role(user) != "admin":
        raise PreventUpdate

    triggered_id = ctx.triggered_id

    if triggered_id == "admin-clear-preview-btn":
        return None

    if triggered_id == "admin-preview-main-btn":
        if not review_farm_id:
            raise PreventUpdate
        return str(review_farm_id).strip()

    if triggered_id == "admin-preview-explorer-btn":
        if not explorer_farm_id:
            raise PreventUpdate
        return str(explorer_farm_id).strip()

    raise PreventUpdate


@app.callback(
    Output("access-requests-store", "data", allow_duplicate=True),
    Output("admin-review-message", "children"),
    Input("approve-request-btn", "n_clicks"),
    Input("deny-request-btn", "n_clicks"),
    State("admin-request-selector", "value"),
    State("admin-note-input", "value"),
    State("admin-farm-name-edit", "value"),
    State("access-requests-store", "data"),
    State("auth-user-store", "data"),
    prevent_initial_call=True,
)
def review_access_request(approve_clicks, deny_clicks, selected_request_id, admin_note, admin_farm_name, access_requests, user):
    triggered_id = ctx.triggered_id

    if get_user_role(user) != "admin":
        return load_access_requests(), "Only admins can review access requests."

    if not selected_request_id:
        return load_access_requests(), "Please select a pending request first."

    new_status = "Approved" if triggered_id == "approve-request-btn" else "Denied"

    try:
        update_access_request_status(
            request_id=selected_request_id,
            new_status=new_status,
            reviewed_by=user.get("email", "admin"),
            admin_note=admin_note or "",
            farm_name=admin_farm_name,
        )

        updated_requests = load_access_requests()

        return (
            updated_requests,
            f"Request #{selected_request_id} was marked as {new_status} in Supabase.",
        )

    except Exception as e:
        return load_access_requests(), f"Could not update request in Supabase: {str(e)}"


@app.callback(
    Output("access-requests-store", "data", allow_duplicate=True),
    Output("privacy-save-message", "children"),
    Input("privacy-save-btn", "n_clicks"),
    Input("privacy-request-farm-change-btn", "n_clicks"),
    State("privacy-first-name", "value"),
    State("privacy-last-name", "value"),
    State("privacy-phone", "value"),
    State("privacy-farm-name", "value"),
    State("privacy-data-reuse", "value"),
    State("auth-user-store", "data"),
    State("access-requests-store", "data"),
    prevent_initial_call=True,
)
def save_privacy_settings(
    save_clicks,
    farm_change_clicks,
    first_name,
    last_name,
    phone,
    farm_name,
    data_reuse_permission,
    user,
    access_requests,
):
    triggered_id = ctx.triggered_id

    if triggered_id not in ["privacy-save-btn", "privacy-request-farm-change-btn"]:
        raise PreventUpdate

    if not user:
        return load_access_requests(), "Please log in before saving privacy settings."

    latest_requests = load_access_requests()
    user_request = get_request_for_email(user, latest_requests)

    if not user_request:
        return latest_requests, "No access request is connected to this account yet."

    status = str(user_request.get("status", "Pending")).title()

    if not first_name or not last_name or not phone:
        return latest_requests, "Please keep first name, last name, and phone number filled in."

    try:
        if triggered_id == "privacy-request-farm-change-btn":
            if not farm_name:
                return latest_requests, "Please select the farm/project SH_1 you want to request."

            old_farm_name = user_request.get("farm_name", "")

            if status != "Approved":
                return latest_requests, "Farm/project SH_1 changes can be saved directly while your request is Pending or Denied."

            if str(farm_name).strip() == str(old_farm_name).strip():
                return latest_requests, "Please choose a different farm/project SH_1 before requesting a farm change."

            request_farm_change(
                request_id=user_request.get("request_id"),
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                old_farm_name=old_farm_name,
                new_farm_name=farm_name,
                data_reuse_permission=data_reuse_permission or user_request.get("data_reuse_permission", DEFAULT_DATA_REUSE_PERMISSION),
            )
            updated_requests = load_access_requests()
            return updated_requests, "Farm change request submitted. Your request is now Pending Review again."

        can_change_farm = status in ["Pending", "Denied"]

        update_access_request_profile(
            request_id=user_request.get("request_id"),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            farm_name=farm_name if can_change_farm else None,
            data_reuse_permission=data_reuse_permission or DEFAULT_DATA_REUSE_PERMISSION,
            reset_to_pending=(status == "Denied"),
        )
        updated_requests = load_access_requests()

        if status == "Denied":
            return updated_requests, "Your information and data reuse preference were updated. Your denied request was resubmitted as Pending."

        if status == "Approved":
            return updated_requests, "Privacy settings saved. Farm/project was not changed unless you used Request Farm Change."

        return updated_requests, "Privacy settings saved."

    except Exception as e:
        return load_access_requests(), f"Could not save privacy settings: {str(e)}"





if __name__ == "__main__":
    app.run(debug=True)