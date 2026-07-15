from dash import html

CARD = {
    "backgroundColor": "white",
    "border": "1px solid #dfe5df",
    "borderRadius": "10px",
    "padding": "18px",
    "boxShadow": "0 2px 8px rgba(16,24,40,0.06)",
}

def resource_card(title, description, link_text, href):
    return html.Div(
        style=CARD,
        children=[
            html.H3(title, style={"marginTop": 0, "color": "#0c5527"}),
            html.P(description, style={"lineHeight": "1.5"}),
            html.A(
                link_text,
                href=href,
                target="_blank",
                style={
                    "fontWeight": "800",
                    "color": "#0c5527",
                    "textDecoration": "none",
                },
            ),
        ],
    )

def layout():
    return html.Div(
        style={"padding": "20px"},
        children=[
            html.Div(
                style=CARD,
                children=[
                    html.H2("Soil Health Resources", style={"marginTop": 0}),
                    html.P(
                        "Extension materials, publications, and supporting information for interpreting soil properties and applying soil-health assessment in Hawaii."
                    ),
                ],
            ),
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(2, minmax(260px, 1fr))",
                    "gap": "14px",
                    "marginTop": "14px",
                },
                children=[
                    resource_card(
                        "CTAHR Hawaii Soils",
                        "Extension information about Hawaii's soils, soil properties, management, and related educational materials for growers and land managers.",
                        "Visit Hawaii Soils resources",
                        "https://www.ctahr.hawaii.edu/site/extsl.aspx",
                    ),
                    resource_card(
                        "CTAHR Publications",
                        "Search extension bulletins and technical publications covering soil and crop management, nutrient management, production practices, and other agricultural topics.",
                        "Search CTAHR publications",
                        "https://www.ctahr.hawaii.edu/site/PubList.aspx?key=Soil+and+Crop+Management",
                    ),
                    resource_card(
                        "Agricultural Diagnostic Service Center",
                        "ADSC provides soil nutrient and plant tissue analysis, plant disease diagnostics, insect identification, and other testing services for Hawaii's farmers and agricultural professionals.",
                        "Visit ADSC services",
                        "https://cms.ctahr.hawaii.edu/adsc/Services",
                    ),
                    resource_card(
                        "GoFarm Hawaii",
                        "GoFarm Hawaii offers hands-on beginning-farmer training, agribusiness support, workshops, and practical resources for new and established agricultural producers.",
                        "Visit GoFarm Hawaii",
                        "https://gofarmhawaii.org/",
                    ),
                ],
            ),
        ],
    )