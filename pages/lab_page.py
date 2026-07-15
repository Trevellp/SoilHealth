from dash import html, dcc

CARD = {
    "backgroundColor": "white",
    "border": "1px solid #dfe5df",
    "borderRadius": "6px",
    "padding": "16px",
    "boxShadow": "0 2px 8px rgba(16,24,40,0.06)",
}

BUTTON = {
    "backgroundColor": "#4778bd",
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "padding": "10px 16px",
    "fontWeight": "700",
    "cursor": "pointer",
}

def layout():
    return html.Div(
        style={
            "maxWidth": "1180px",
            "margin": "0 auto",
            "padding": "16px 20px",
        },
        children=[
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "360px 1fr",
                    "gap": "18px",
                    "alignItems": "start",
                },
                children=[
                    html.Div([
                        html.Div(
                            style=CARD,
                            children=[
                                html.H2("Upload", style={"marginTop": 0}),
                                html.Button("⬇ Download live CSV template", id="lab-template-btn"),
                                html.Br(),
                                html.Br(),

                                dcc.Checklist(
                                    id="lab-consent-check",
                                    options=[{
                                        "label": " I understand uploaded data may be stored in server logs or temporary files for tool operation, troubleshooting, and maintenance.",
                                        "value": "consent",
                                    }],
                                    value=[],
                                    style={"lineHeight": "1.5"},
                                ),

                                html.Br(),
                                html.Label("CSV file", style={"fontWeight": "800"}),

                                dcc.Upload(
                                    id="lab-upload",
                                    children=html.Div(
                                        id="lab-upload-label",
                                        children="Browse...   No file selected",
                                    ),
                                    style={
                                        "border": "1px solid #d1d5db",
                                        "borderRadius": "4px",
                                        "padding": "10px",
                                        "marginTop": "8px",
                                        "backgroundColor": "#f9fafb",
                                    },
                                ),

                                html.Br(),
                                html.Button("Score samples", id="lab-score-btn", n_clicks=0, style=BUTTON),
                                html.Div(id="lab-status", style={"marginTop": "12px"}),
                            ],
                        ),

                        html.Br(),

                        html.Div(
                            style=CARD,
                            children=[
                                html.H2("Score Bands", style={"marginTop": 0}),
                                html.Div(
                                    style={
                                        "display": "grid",
                                        "gridTemplateColumns": "1fr 1fr",
                                        "gap": "8px",
                                    },
                                    children=[
                                        html.Div("Low: 0–24%", style={"padding": "12px", "backgroundColor": "#d77a7a", "fontWeight": "800", "borderRadius": "4px"}),
                                        html.Div("Moderate-low: 25–49%", style={"padding": "12px", "backgroundColor": "#f2b957", "fontWeight": "800", "borderRadius": "4px"}),
                                        html.Div("Moderate-high: 50–74%", style={"padding": "12px", "backgroundColor": "#fff176", "fontWeight": "800", "borderRadius": "4px"}),
                                        html.Div("High: 75–100%", style={"padding": "12px", "backgroundColor": "#9ac58c", "fontWeight": "800", "borderRadius": "4px"}),
                                    ],
                                ),
                            ],
                        ),

                        html.Br(),

                        html.Div(
                            style=CARD,
                            children=[
                                html.H2("Live Input", style={"marginTop": 0}),
                                html.P(
                                    "The minimum scoring input is a sample ID, mineral class, and nine indicators: toc, co2_burst, ph, beta_glucosidase, beta_glucosaminidase, pmn, whc, hwec, and wsa_mega. Additional master-database columns are accepted and ignored when they are not needed. plot_name, PIAL_none, and bd are optional. Sample IDs may be supplied as sample_id, SH_1, HSH_id, or Intake_number.",
                                    style={"fontSize": "14px", "lineHeight": "1.5"},
                                ),
                            ],
                        ),
                    ]),

                    html.Div([
                        html.Div(
                            style={**CARD, "minHeight": "300px"},
                            children=[
                                html.H2("Results", style={"marginTop": 0}),

                                dcc.Graph(
                                    id="lab-score-graph",
                                    style={"height": "260px", "width": "100%"},
                                    config={"displayModeBar": True},
                                ),

                                dcc.Tabs(
                                    children=[
                                        dcc.Tab(label="Scores", children=html.Div(id="lab-scores-output")),
                                        dcc.Tab(label="Core Dataset", children=html.Div(id="lab-core-output")),
                                    ]
                                ),

                                html.Br(),
                                html.Button("⬇ Download scored results", id="lab-download-btn"),
                            ],
                        ),

                        html.Br(),

                        html.Div(
                            style=CARD,
                            children=[
                                html.H2("Dropped Samples", style={"marginTop": 0}),
                                html.Div(id="lab-dropped-output"),
                            ],
                        ),

                        dcc.Download(id="lab-template-download"),
                        dcc.Download(id="lab-scored-download"),
                        dcc.Store(id="lab-results-store"),
                    ]),
                ],
            ),
        ],
    )