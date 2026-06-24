import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, html, dcc, dash_table, Input, Output, State, ctx

from auth import sign_in_user, sign_up_user, sign_out_user



# DATA PLAN:
# CSV = temporary mock data for dashboard testing
# PostgreSQL = real data storage for dashboard, with Supabase used only for login/signup/authentication
# Supabase = login/signup/authentication only, not final soil data storage
USE_POSTGRES = False

# TEMP ROLE TESTING:
# This lets us test the different dashboard views before we create real role tables.
# Later, this should come from Supabase/PostgreSQL instead of being hardcoded.
ADMIN_EMAILS = [
    "trevell.pruitt@gmail.com",
]

BASE_DIR = Path(__file__).resolve().parent / "data"
CSV_PATH = BASE_DIR / "hsh_mock_synthetic_database_for_sql.csv"

DATABASE_URL = os.getenv("DATABASE_URL")


REQUIRED_COLUMNS = [
    "SH_1",
    "plot_name",
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

    text_cols = [c for c in REQUIRED_COLUMNS if c not in ["SH_1", "shs"]]
    for col in text_cols:
        df[col] = df[col].astype("string").str.strip()
        df[col] = df[col].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})

    if "mineral_class" not in df.columns:
        df["mineral_class"] = df["minerals"]

    if "land_use_display" not in df.columns:
        df["land_use_display"] = df["current_land_use"]

    df["pial_status"] = df["PIAL_none"].apply(clean_pial_status)
    df["box_land_use_group"] = df.apply(make_box_land_use_group, axis=1)

    return df


def load_data_from_csv():
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"Could not find {CSV_PATH}")

    df = pd.read_csv(CSV_PATH, header=1)
    df.columns = [str(c).strip() for c in df.columns]

    df["mineral_class"] = df["minerals"].map(MINERAL_MAP).fillna(df["minerals"])

    df["land_use_display"] = (
        df["current_land_use"]
        .map(LAND_USE_DISPLAY_MAP)
        .fillna(df["current_land_use"])
    )

    return clean_dashboard_data(df)


def load_data_from_postgres():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is missing. Set it before using PostgreSQL.")

    from sqlalchemy import create_engine

    engine = create_engine(DATABASE_URL)

    query = """
        SELECT
            s."SH_1",
            s.plot_name,
            s.shs,
            s.minerals,
            s."order",
            s.suborder,
            s.great_group,
            s."PIAL_none",
            s.management_category,
            s.current_land_use,
            s.most_previous_land_use,
            COALESCE(m.display_mineral, s.minerals) AS mineral_class,
            COALESCE(l.display_land_use, s.current_land_use) AS land_use_display
        FROM soil_samples s
        LEFT JOIN mineral_lookup m
            ON s.minerals = m.raw_mineral
        LEFT JOIN land_use_lookup l
            ON s.current_land_use = l.raw_land_use;
    """

    df = pd.read_sql(query, engine)
    return clean_dashboard_data(df)


def load_data():
    if USE_POSTGRES:
        return load_data_from_postgres()

    return load_data_from_csv()


df_original = load_data()


def options_from_column(df, column):
    counts = df[column].dropna().value_counts()

    if column == "land_use_display":
        counts = counts[counts >= 10]

    values = sorted(counts.index)
    return [{"label": str(v), "value": str(v)} for v in values]


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

    if email in [admin_email.lower().strip() for admin_email in ADMIN_EMAILS]:
        return "admin"

    return "user"


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
    return html.Div(
        id="signup-modal",
        style=MODAL_HIDDEN_STYLE,
        children=[
            html.Div(
                style=MODAL_CARD_STYLE,
                children=[
                    html.H3("Sign Up", style={"marginTop": 0, "color": DARK_GREEN}),
                    html.Div(
                        "Create an account for future private dashboard access.",
                        style={"fontSize": "14px", "color": "#556", "marginBottom": "14px"},
                    ),
                    dcc.Input(
                        id="signup-email",
                        type="email",
                        placeholder="Email",
                        style=AUTH_INPUT_STYLE,
                    ),
                    dcc.Input(
                        id="signup-password",
                        type="password",
                        placeholder="Password",
                        style=AUTH_INPUT_STYLE,
                    ),
                    html.Div(
                        style={"display": "flex", "gap": "10px", "alignItems": "center"},
                        children=[
                            html.Button(
                                "Create Account",
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


def access_panel_content(panel_name, user):
    """Small slide-out style content for logged-in user tools."""
    role = get_user_role(user)

    if panel_name == "my-data":
        return [
            html.H3("My Data", style={"marginTop": 0, "color": DARK_GREEN}),
            html.P(
                "This is where a farmer, collaborator, or project user would eventually see only "
                "the soil samples connected to their account."
            ),
            html.P(
                "For now, this is a placeholder. Later this section will filter the PostgreSQL soil "
                "samples by the logged-in user's account, farm, or project."
            ),
        ]

    if panel_name == "privacy":
        return [
            html.H3("Privacy Settings", style={"marginTop": 0, "color": DARK_GREEN}),
            html.P("Future privacy choices could include:"),
            html.Ul(
                children=[
                    html.Li("Private: only the owner/research team can see it."),
                    html.Li("Research-only: usable for internal research summaries."),
                    html.Li("Public aggregate: included only in grouped public trends."),
                ]
            ),
        ]

    if panel_name == "admin" and role == "admin":
        return [
            html.H3("Admin / Researcher", style={"marginTop": 0, "color": DARK_GREEN}),
            html.P("Future admin tools could include:"),
            html.Ul(
                children=[
                    html.Li("User and collaborator management"),
                    html.Li("Research-only data review"),
                    html.Li("Project, farm, and sample ownership checks"),
                    html.Li("Privacy approval workflow"),
                    html.Li("Dashboard administration"),
                ]
            ),
        ]

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
                    "width": "430px",
                    "maxWidth": "92%",
                    "margin": "90px 28px 0 auto",
                    "backgroundColor": "white",
                    "padding": "26px",
                    "borderRadius": "12px",
                    "boxShadow": "0 12px 30px rgba(0,0,0,0.25)",
                    "minHeight": "260px",
                },
                children=[
                    html.Div(id="access-panel-content"),
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


app = Dash(__name__)
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
                                        graph_component("boxplot", 380),
                                        html.Img(
                                            src="/assets/land_use_strip.png",
                                            style={
                                                "width": "90%",
                                                "display": "block",
                                                "margin": "-30px auto 6px auto",
                                            },
                                        ),
                                        html.Div(
                                            "Boxplot shows median, middle 50%, spread, and individual sample points.",
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
        login_modal(),
        signup_modal(),
        access_panel_modal(),
    ],
)


@app.callback(
    Output("total-samples-card", "children"),
    Output("avg-shs-card", "children"),
    Output("filtered-samples-card", "children"),
    Output("boxplot", "figure"),
    Output("suborder-boxplot", "figure"),
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
):
    filtered = apply_filters(
        df_original,
        current_land_use,
        management_category,
        mineral_class,
        order,
        suborder,
        great_group,
        pial_status,
    )

    total_samples = df_original["SH_1"].nunique()
    filtered_samples = filtered["SH_1"].nunique()
    avg_shs = filtered["shs"].mean()

    total_card = metric_card("⚗", "Total Samples", f"{total_samples:,}", "Total soil samples")
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

    box_df = filtered.dropna(subset=["shs", "box_land_use_group"])
    box_df = box_df[box_df["box_land_use_group"].isin(BOX_GROUP_ORDER)]

    if box_df.empty:
        box_fig = empty_figure("Soil Health Score Across Different Land Uses", 430)
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
            height=430,
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
        suborder_fig,
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
    Input("open-login-btn", "n_clicks"),
    Input("close-login-btn", "n_clicks"),
    Input("open-signup-btn", "n_clicks"),
    Input("close-signup-btn", "n_clicks"),
    Input("login-submit-btn", "n_clicks"),
    Input("signup-submit-btn", "n_clicks"),
    Input("logout-btn", "n_clicks"),
    State("login-email", "value"),
    State("login-password", "value"),
    State("signup-email", "value"),
    State("signup-password", "value"),
    State("auth-user-store", "data"),
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
    signup_email,
    signup_password,
    current_user,
):
    triggered_id = ctx.triggered_id

    if triggered_id == "open-login-btn":
        return MODAL_OVERLAY_STYLE, MODAL_HIDDEN_STYLE, current_user, "", ""

    if triggered_id == "close-login-btn":
        return MODAL_HIDDEN_STYLE, MODAL_HIDDEN_STYLE, current_user, "", ""

    if triggered_id == "open-signup-btn":
        return MODAL_HIDDEN_STYLE, MODAL_OVERLAY_STYLE, current_user, "", ""

    if triggered_id == "close-signup-btn":
        return MODAL_HIDDEN_STYLE, MODAL_HIDDEN_STYLE, current_user, "", ""

    if triggered_id == "logout-btn":
        try:
            sign_out_user()
        except Exception:
            pass

        return MODAL_HIDDEN_STYLE, MODAL_HIDDEN_STYLE, None, "", ""

    if triggered_id == "login-submit-btn":
        if not login_email or not login_password:
            return (
                MODAL_OVERLAY_STYLE,
                MODAL_HIDDEN_STYLE,
                current_user,
                "Please enter both email and password.",
                "",
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
                )

            email = get_user_email(user) or login_email

            return (
                MODAL_HIDDEN_STYLE,
                MODAL_HIDDEN_STYLE,
                {"email": email},
                "",
                "",
            )

        except Exception as e:
            return (
                MODAL_OVERLAY_STYLE,
                MODAL_HIDDEN_STYLE,
                current_user,
                f"Login failed: {str(e)}",
                "",
            )

    if triggered_id == "signup-submit-btn":
        if not signup_email or not signup_password:
            return (
                MODAL_HIDDEN_STYLE,
                MODAL_OVERLAY_STYLE,
                current_user,
                "",
                "Please enter both email and password.",
            )

        try:
            # IMPORTANT:
            # Signing up should NOT log the user into the dashboard.
            # Supabase will create the user and send the verification email.
            # The user must verify their email first, then come back and log in.
            sign_up_user(signup_email, signup_password)

            return (
                MODAL_HIDDEN_STYLE,
                MODAL_OVERLAY_STYLE,
                current_user,
                "",
                "Account created. Please check your email and verify your account before logging in.",
            )

        except Exception as e:
            return (
                MODAL_HIDDEN_STYLE,
                MODAL_OVERLAY_STYLE,
                current_user,
                "",
                f"Sign up failed: {str(e)}",
            )

    return MODAL_HIDDEN_STYLE, MODAL_HIDDEN_STYLE, current_user, "", ""


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
    Input("open-my-data-btn", "n_clicks"),
    Input("open-privacy-btn", "n_clicks"),
    Input("open-admin-btn", "n_clicks"),
    Input("close-access-panel-btn", "n_clicks"),
    State("auth-user-store", "data"),
    prevent_initial_call=True,
)
def handle_access_panel(my_data_clicks, privacy_clicks, admin_clicks, close_clicks, user):
    triggered_id = ctx.triggered_id

    if triggered_id == "close-access-panel-btn":
        return MODAL_HIDDEN_STYLE, []

    if triggered_id == "open-my-data-btn":
        return MODAL_OVERLAY_STYLE, access_panel_content("my-data", user)

    if triggered_id == "open-privacy-btn":
        return MODAL_OVERLAY_STYLE, access_panel_content("privacy", user)

    if triggered_id == "open-admin-btn":
        return MODAL_OVERLAY_STYLE, access_panel_content("admin", user)

    return MODAL_HIDDEN_STYLE, []


if __name__ == "__main__":
    app.run(debug=True)