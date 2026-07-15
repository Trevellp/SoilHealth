from dash import html

CARD = {
    "backgroundColor": "white",
    "border": "1px solid #dfe5df",
    "borderRadius": "10px",
    "padding": "18px",
    "boxShadow": "0 2px 8px rgba(16,24,40,0.06)",
}

PERSON_CARD = {
    **CARD,
    "display": "grid",
    "gridTemplateColumns": "90px 1fr",
    "gap": "18px",
    "alignItems": "start",
}

def avatar(initials, color="#496b55"):
    return html.Div(
        initials,
        style={
            "width": "88px",
            "height": "88px",
            "borderRadius": "50%",
            "backgroundColor": color,
            "color": "white",
            "display": "flex",
            "alignItems": "center",
            "justifyContent": "center",
            "fontWeight": "800",
            "fontSize": "20px",
        },
    )

def photo(src):
    return html.Img(
        src=src,
        style={
            "width": "88px",
            "height": "88px",
            "borderRadius": "50%",
            "objectFit": "cover",
            "border": "1px solid #cbd3cd",
        },
    )

def person(name, role, bio, image=None, initials="?", color="#496b55"):
    return html.Div(
        style=PERSON_CARD,
        children=[
            photo(image) if image else avatar(initials, color),
            html.Div([
                html.Div(name, style={"fontWeight": "800"}),
                html.Div(role, style={"fontWeight": "800", "color": "#376246", "margin": "4px 0 8px"}),
                html.P(bio, style={"lineHeight": "1.5", "margin": 0}),
            ]),
        ],
    )

def layout():
    return html.Div(
        style={"padding": "20px"},
        children=[
            html.Div(
                style=CARD,
                children=[
                    html.H2("About the Hawaii Soil Health Portal", style={"marginTop": 0}),
                    html.P(
                        "These tools were built to make soil health assessment more accessible to farmers, land managers, and researchers. "
                        "The portal brings together field and laboratory methods, soil-health scoring, spectroscopy, data stewardship, and web development "
                        "to support practical soil management across Hawaii.",
                        style={"lineHeight": "1.6"},
                    ),
                ],
            ),

            html.H2("Web Team", style={"marginTop": "28px"}),
            html.P("Current and foundational contributors to the application, website, and supporting data systems."),

            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(300px, 1fr))", "gap": "14px"},
                children=[
                    person(
                        "Dr. Tai Maaz",
                        "Professor of Soil Science and project leadership",
                        "A professor in UH Mānoa's Department of Tropical Plant and Soil Sciences, she leads research on soil fertility, nutrient cycling, crop productivity, and practical soil-health assessment.",
                        initials="TM",
                    ),
                    person(
                        "Christian Sanoja Fullmer",
                        "Staff Data Analyst and portal developer",
                        "A staff data analyst with an M.S. in Soil Science, he builds and manages the current portal and supports the project's data systems, reporting, bioinformatics, and reproducible analyses.",
                        image="/assets/christian_fullmer.png",
                    ),
                    person(
                        "Trevell Pruitt",
                        "UH Mānoa Computer Science student",
                        "Develops the portal's aggregate-data dashboard and is helping design data-provider access, privacy controls, consent preferences, and security safeguards for more granular records.",
                        image="/assets/picture of me.png",
                    ),
                    person(
                        "Joe Gan",
                        "UH Mānoa Computer Science graduate student",
                        "Built the first version of the soil health Shiny application, establishing the upload, scoring, results, and download workflow that the current portal expands.",
                        initials="JG",
                        color="#42687a",
                    ),
                ],
            ),

            html.H2("Alumni & Contributors", style={"marginTop": "28px"}),
            html.P("Researchers and staff whose field, laboratory, analytical, and extension work supports the broader soil health project."),

            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(300px, 1fr))", "gap": "14px"},
                children=[
                    person(
                        "Christine Tallamy",
                        "Laboratory and field data quality",
                        "As the Crow Lab manager, supported consistent field operations, laboratory workflows, and quality assurance for the data underlying the soil health project.",
                        initials="CT",
                        color="#87633f",
                    ),
                    person(
                        "Dr. Tanner Beckstrom",
                        "Soil scientist and FTIR researcher",
                        "Recently completed a Ph.D. in Soil Science through UH Mānoa. He led FTIR prediction research connecting raw mid-infrared spectra with soil indicators and soil health scores.",
                        initials="TB",
                        color="#8a702b",
                    ),
                    person(
                        "Arianna Bunnell",
                        "Computer Science Ph.D. candidate and contributor",
                        "A UH Mānoa Computer Science Ph.D. candidate whose research focuses on interpretable deep learning and responsible artificial intelligence. She contributed computing and data-science expertise.",
                        initials="AB",
                        color="#73576e",
                    ),
                    person(
                        "Jubin Choi",
                        "Data and research contributor",
                        "Supported project data, analysis, and operational workflows that helped move soil health measurements toward consistent scoring and reporting.",
                        initials="JC",
                        color="#42687a",
                    ),
                    person(
                        "Dr. Susan Crow",
                        "Soil carbon and ecosystem science",
                        "Provided scientific leadership and research contributions linking soil health assessment with soil carbon, ecosystem function, and sustainable land management in Hawaii.",
                        initials="SC",
                        color="#87633f",
                    ),
                    person(
                        "Dr. Jonathan Deenik",
                        "Soil fertility and extension",
                        "Contributed soil science and extension expertise, helping connect soil health indicators and interpretation with the practical needs of farmers and land managers.",
                        initials="JD",
                        color="#8a702b",
                    ),
                ],
            ),
        ],
    )