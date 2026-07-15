import base64
import io
import json
import subprocess
import sys
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table, Input, Output, State, callback
from dash.exceptions import PreventUpdate

CARD_BORDER = "1px solid #dfe5df"
BLUE = "#2f6eb3"

EXPECTED_WAVENUMBERS = [str(x) for x in range(4000, 618, -2)]

CORE_OUTPUT_COLUMNS = [
    "sample_id",
    "ftir_toc",
    "ftir_toc_sd",
    "ftir_co2_burst",
    "ftir_co2_burst_sd",
    "ftir_pmn",
    "ftir_pmn_sd",
    "ftir_wsa_mega",
    "ftir_wsa_mega_sd",
    "ftir_direct_SH",
    "ftir_direct_SH_sd",
    "direct_shs",
    "direct_shs_low95",
    "direct_shs_high95",
    "direct_score_percentile",
    "direct_score_percentile_low95",
    "direct_score_percentile_high95",
    "direct_score_band",
]

ROUNDING_RULES = {
    "ftir_toc": 1,
    "ftir_toc_sd": 1,
    "ftir_co2_burst": -1,
    "ftir_co2_burst_sd": -1,
    "ftir_pmn": 0,
    "ftir_pmn_sd": 0,
    "ftir_wsa_mega": 1,
    "ftir_wsa_mega_sd": 1,
    "ftir_direct_SH": 2,
    "ftir_direct_SH_sd": 2,
    "direct_shs": 2,
    "direct_shs_low95": 3,
    "direct_shs_high95": 2,
    "direct_score_percentile": 1,
    "direct_score_percentile_low95": 1,
    "direct_score_percentile_high95": 1,
}

PAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PAGE_DIR.parent
FTIR_PREDICT_SCRIPT = PROJECT_ROOT / "ftir_predict.py"
FTIR_MODEL_DIR = PROJECT_ROOT / "ftir_models"
SCORING_BUNDLE_RDS = PROJECT_ROOT / "scoring_bundle.rds"


def panel(children, style=None):
    base = {
        "backgroundColor": "white",
        "border": CARD_BORDER,
        "borderRadius": "8px",
        "padding": "18px",
        "boxShadow": "0 2px 8px rgba(16,24,40,0.06)",
        "marginBottom": "18px",
        "width": "100%",
        "maxWidth": "100%",
        "minWidth": 0,
        "boxSizing": "border-box",
        "overflow": "hidden",
    }
    if style:
        base.update(style)
    return html.Div(children=children, style=base)


def small_button(label, button_id):
    return html.Button(
        [html.Span("⬇", style={"marginRight": "6px"}), label],
        id=button_id,
        n_clicks=0,
        style={
            "display": "block",
            "width": "260px",
            "textAlign": "left",
            "padding": "8px 10px",
            "marginBottom": "6px",
            "border": "1px solid #cfd8cf",
            "borderRadius": "5px",
            "backgroundColor": "white",
            "cursor": "pointer",
            "fontSize": "14px",
        },
    )


def primary_button(label, button_id):
    return html.Button(
        label,
        id=button_id,
        n_clicks=0,
        style={
            "backgroundColor": BLUE,
            "color": "white",
            "border": "none",
            "borderRadius": "4px",
            "padding": "9px 14px",
            "fontWeight": "700",
            "cursor": "pointer",
            "fontSize": "14px",
        },
    )


def empty_results_figure():
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        height=260,
        margin=dict(l=65, r=30, t=15, b=50),
        xaxis=dict(title="Direct FTIR score percentile", range=[0, 100]),
        yaxis=dict(title=""),
        annotations=[
            dict(
                text="Upload a spectra CSV and click Score spectra.",
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=14, color="#6b7280"),
            )
        ],
    )
    return fig


def _pick_sample_id_column(df):
    for col in ["sample_id", "sampleid", "sample", "id", "Sample ID", "SampleID", "SH_1"]:
        if col in df.columns:
            return col
    return None


def _score_percentile_series(df):
    if "direct_score_percentile" in df.columns:
        return pd.to_numeric(df["direct_score_percentile"], errors="coerce")

    if "direct_shs" in df.columns:
        return pd.to_numeric(df["direct_shs"], errors="coerce") * 100

    if "ftir_direct_SH" in df.columns:
        values = pd.to_numeric(df["ftir_direct_SH"], errors="coerce")
        if values.max(skipna=True) <= 1:
            return values * 100
        return values

    return None


def make_score_plot(results_df):
    if results_df is None or results_df.empty:
        return empty_results_figure()

    sample_col = _pick_sample_id_column(results_df)
    scores = _score_percentile_series(results_df)

    if sample_col is None or scores is None:
        return empty_results_figure()

    plot_df = results_df.copy()
    plot_df["_score_percentile"] = scores
    plot_df = plot_df.dropna(subset=["_score_percentile"])
    plot_df = plot_df.sort_values("_score_percentile", ascending=True)

    if plot_df.empty:
        return empty_results_figure()

    fig = go.Figure(
        go.Bar(
            x=plot_df["_score_percentile"],
            y=plot_df[sample_col].astype(str),
            orientation="h",
            marker=dict(color="#fff68a"),
            hovertemplate="<b>%{y}</b><br>Direct FTIR score percentile: %{x:.0f}<extra></extra>",
        )
    )

    fig.update_layout(
        template="plotly_white",
        height=260,
        margin=dict(l=70, r=30, t=15, b=50),
        xaxis=dict(title="Direct FTIR score percentile", range=[0, 100]),
        yaxis=dict(title=""),
        showlegend=False,
    )

    return fig


def parse_upload(contents, filename):
    if not contents:
        raise ValueError("Please upload a CSV file first.")

    _content_type, content_string = contents.split(",", 1)
    decoded = base64.b64decode(content_string)

    try:
        df = pd.read_csv(io.BytesIO(decoded))
    except Exception as exc:
        raise ValueError(f"Could not read {filename or 'uploaded file'} as a CSV: {exc}")

    df.columns = [str(c).strip() for c in df.columns]
    return df


def _validate_real_predictor_files():
    if not FTIR_PREDICT_SCRIPT.exists():
        raise FileNotFoundError(f"Missing ftir_predict.py at: {FTIR_PREDICT_SCRIPT}")

    if not FTIR_MODEL_DIR.exists():
        raise FileNotFoundError(f"Missing ftir_models folder at: {FTIR_MODEL_DIR}")

    bundle_path = FTIR_MODEL_DIR / "bundle_unified_ftir_models.joblib"
    if not bundle_path.exists():
        raise FileNotFoundError(f"Missing unified FTIR model bundle: {bundle_path}")


def _find_rscript():
    """Find Rscript on PATH or in common Windows installation folders."""
    found = shutil.which("Rscript") or shutil.which("Rscript.exe")
    if found:
        return found

    if sys.platform.startswith("win"):
        candidates = []
        for base in [Path("C:/Program Files/R"), Path("C:/Program Files (x86)/R")]:
            if base.exists():
                candidates.extend(base.glob("R-*/bin/Rscript.exe"))
                candidates.extend(base.glob("R-*/bin/x64/Rscript.exe"))
        if candidates:
            return str(sorted(candidates, reverse=True)[0])

    raise FileNotFoundError(
        "Rscript could not be found. Install R or add Rscript to PATH. "
        "The exact Shiny percentile requires scoring_bundle.rds and base R."
    )


def _apply_shiny_scoring(df):
    """Apply the exact post-processing used by the original Shiny app."""
    if df is None or df.empty:
        return df
    if "ftir_direct_SH" not in df.columns or "ftir_direct_SH_sd" not in df.columns:
        raise ValueError("Predictor output is missing ftir_direct_SH or ftir_direct_SH_sd.")
    if not SCORING_BUNDLE_RDS.exists():
        raise FileNotFoundError(
            f"Missing scoring_bundle.rds at: {SCORING_BUNDLE_RDS}. "
            "Copy scoring_bundle.rds from the original Shiny project into the Dash project root."
        )

    rscript = _find_rscript()

    with tempfile.TemporaryDirectory(prefix="ftir_shiny_score_") as tmpdir:
        tmp = Path(tmpdir)
        input_csv = tmp / "raw_predictions.csv"
        output_csv = tmp / "scored_predictions.csv"
        helper_r = tmp / "apply_shiny_scoring.R"

        df.to_csv(input_csv, index=False)

        r_code = r'''args <- commandArgs(trailingOnly = TRUE)
input_csv <- args[[1]]
output_csv <- args[[2]]
bundle_path <- args[[3]]

predictions <- read.csv(input_csv, check.names = FALSE, stringsAsFactors = FALSE)
bundle <- readRDS(bundle_path)

predictions$ftir_toc_low95 <- pmax(0, predictions$ftir_toc - 1.96 * predictions$ftir_toc_sd)
predictions$ftir_toc_high95 <- predictions$ftir_toc + 1.96 * predictions$ftir_toc_sd
predictions$ftir_co2_burst_low95 <- pmax(0, predictions$ftir_co2_burst - 1.96 * predictions$ftir_co2_burst_sd)
predictions$ftir_co2_burst_high95 <- predictions$ftir_co2_burst + 1.96 * predictions$ftir_co2_burst_sd
predictions$ftir_pmn_low95 <- predictions$ftir_pmn - 1.96 * predictions$ftir_pmn_sd
predictions$ftir_pmn_high95 <- predictions$ftir_pmn + 1.96 * predictions$ftir_pmn_sd
predictions$ftir_wsa_mega_low95 <- pmax(0, predictions$ftir_wsa_mega - 1.96 * predictions$ftir_wsa_mega_sd)
predictions$ftir_wsa_mega_high95 <- predictions$ftir_wsa_mega + 1.96 * predictions$ftir_wsa_mega_sd
predictions$ftir_direct_SH_low95 <- predictions$ftir_direct_SH - 1.96 * predictions$ftir_direct_SH_sd
predictions$ftir_direct_SH_high95 <- predictions$ftir_direct_SH + 1.96 * predictions$ftir_direct_SH_sd

predictions$direct_shs <- bundle$sh_ecdf(predictions$ftir_direct_SH)
predictions$direct_shs_low95 <- bundle$sh_ecdf(predictions$ftir_direct_SH_low95)
predictions$direct_shs_high95 <- bundle$sh_ecdf(predictions$ftir_direct_SH_high95)
predictions$direct_score_percentile <- round(predictions$direct_shs * 100, 1)
predictions$direct_score_percentile_low95 <- round(predictions$direct_shs_low95 * 100, 1)
predictions$direct_score_percentile_high95 <- round(predictions$direct_shs_high95 * 100, 1)

predictions$direct_score_band <- ifelse(
  is.na(predictions$direct_shs), NA,
  ifelse(predictions$direct_shs < 0.25, "Low",
    ifelse(predictions$direct_shs < 0.50, "Moderate-low",
      ifelse(predictions$direct_shs < 0.75, "Moderate-high", "High")
    )
  )
)

write.csv(predictions, output_csv, row.names = FALSE, na = "")
'''
        helper_r.write_text(r_code, encoding="utf-8")

        completed = subprocess.run(
            [rscript, str(helper_r), str(input_csv), str(output_csv), str(SCORING_BUNDLE_RDS)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Unknown R scoring error").strip()
            raise RuntimeError(f"Shiny percentile scoring failed: {message}")
        if not output_csv.exists():
            raise FileNotFoundError("R scoring completed but did not create the scored output CSV.")

        return pd.read_csv(output_csv)

def _clean_predictor_output(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=CORE_OUTPUT_COLUMNS)

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    sample_col = _pick_sample_id_column(df)
    if sample_col and sample_col != "sample_id":
        df = df.rename(columns={sample_col: "sample_id"})

    for col in df.columns:
        if col != "sample_id":
            df[col] = pd.to_numeric(df[col], errors="ignore")

    df = _apply_shiny_scoring(df)

    for col, digits in ROUNDING_RULES.items():
        if col in df.columns:
            numeric = pd.to_numeric(df[col], errors="coerce")
            if digits <= 0:
                df[col] = numeric.round(digits).astype("Int64")
            else:
                df[col] = numeric.round(digits)

    ordered_cols = [c for c in CORE_OUTPUT_COLUMNS if c in df.columns]
    extra_cols = [c for c in df.columns if c not in ordered_cols]
    return df[ordered_cols + extra_cols]


def score_spectra_with_live_model(raw_df):
    _validate_real_predictor_files()

    if raw_df is None or raw_df.empty:
        raise ValueError("The uploaded CSV is empty.")

    with tempfile.TemporaryDirectory(prefix="ftir_dash_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_path = tmpdir_path / "uploaded_ftir_input.csv"
        output_path = tmpdir_path / "ftir_predictions_output.csv"

        raw_df.to_csv(input_path, index=False)

        cmd = [
            sys.executable,
            str(FTIR_PREDICT_SCRIPT),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--model-dir",
            str(FTIR_MODEL_DIR),
        ]

        completed = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "Unknown FTIR prediction error.").strip()
            raise RuntimeError(error_text)

        if not output_path.exists():
            raise FileNotFoundError("The FTIR predictor ran, but it did not create an output CSV.")

        results_df = pd.read_csv(output_path)
        results_df = _clean_predictor_output(results_df)

        dropped_path = output_path.with_suffix(".dropped.json")
        if dropped_path.exists():
            dropped_rows = json.loads(dropped_path.read_text())
            dropped_df = pd.DataFrame(dropped_rows)
            if "drop_reason" in dropped_df.columns and "reason" not in dropped_df.columns:
                dropped_df = dropped_df.rename(columns={"drop_reason": "reason"})
        else:
            dropped_df = pd.DataFrame(columns=["sample_id", "reason"])

        return results_df, dropped_df


def make_wide_template(include_example=False):
    if include_example:
        xs = np.arange(len(EXPECTED_WAVENUMBERS))
        rows = []
        for sample_id, offset in [("synthetic-ftir-001", 0.00), ("synthetic-ftir-002", -0.03)]:
            values = 0.55 + offset + 0.08 * np.sin(xs / 90) + 0.02 * np.cos(xs / 35)
            rows.append([sample_id] + [round(float(v), 6) for v in values])
        return pd.DataFrame(rows, columns=["sample_id"] + EXPECTED_WAVENUMBERS)

    return pd.DataFrame(columns=["sample_id"] + EXPECTED_WAVENUMBERS)


def make_long_template():
    return pd.DataFrame(
        {
            "sample_id": ["synthetic-ftir-001", "synthetic-ftir-001", "synthetic-ftir-001"],
            "wavenumber": [4000, 3998, 3996],
            "absorbance": [0.555405, 0.556275, 0.557157],
        }
    )


def layout():
    return html.Div(
        style={
            "maxWidth": "1180px",
            "margin": "0 auto",
            "padding": "20px 20px 40px",
            "fontFamily": "Arial, sans-serif",
        },
        children=[
            dcc.Store(id="ftir-results-store", data=None),
            dcc.Store(id="ftir-dropped-store", data=None),
            dcc.Download(id="download-ftir-wide-template"),
            dcc.Download(id="download-ftir-long-template"),
            dcc.Download(id="download-ftir-results"),

            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "minmax(300px, 360px) minmax(0, 1fr)",
                    "gap": "22px",
                    "width": "100%",
                    "maxWidth": "100%",
                    "minWidth": 0,
                    "alignItems": "start",
                },
                children=[
                    html.Div(
                        style={"minWidth": 0, "width": "100%", "maxWidth": "100%"},
                        children=[
                            panel(
                                [
                                    html.H3("Upload Spectra", style={"marginTop": 0, "fontSize": "26px", "fontWeight": "500"}),
                                    html.Label("Upload type", style={"fontWeight": "700", "display": "block", "marginBottom": "8px"}),
                                    dcc.RadioItems(
                                        id="ftir-upload-mode",
                                        options=[
                                            {"label": "Spectra CSV", "value": "csv"},
                                            {"label": "Raw OPUS files", "value": "opus"},
                                        ],
                                        value="csv",
                                        inline=True,
                                        labelStyle={"marginRight": "16px"},
                                        style={"marginBottom": "14px"},
                                    ),
                                    small_button("Download wide CSV template", "download-wide-template-btn"),
                                    small_button("Download long CSV template", "download-long-template-btn"),
                                    html.Br(),
                                    html.Label("Raw absorbance CSV", style={"fontWeight": "700", "display": "block", "marginBottom": "8px"}),
                                    dcc.Upload(
                                        id="ftir-csv-upload",
                                        children=html.Div(
                                            [
                                                html.Span("Browse...", style={"padding": "8px 12px", "backgroundColor": "#f8f8f8", "borderRight": "1px solid #ccc"}),
                                                html.Span("No file selected", id="ftir-upload-filename", style={"padding": "8px 12px", "color": "#4b5563"}),
                                            ],
                                            style={"display": "flex", "alignItems": "center"},
                                        ),
                                        multiple=False,
                                        style={
                                            "width": "100%",
                                            "border": "1px solid #cfd8cf",
                                            "borderRadius": "5px",
                                            "backgroundColor": "white",
                                            "cursor": "pointer",
                                            "overflow": "hidden",
                                            "marginBottom": "2px",
                                        },
                                    ),
                                    html.Div(
                                        "Upload complete",
                                        id="ftir-upload-complete",
                                        style={
                                            "backgroundColor": "#4b78b8",
                                            "color": "white",
                                            "textAlign": "center",
                                            "padding": "4px",
                                            "fontSize": "13px",
                                            "display": "none",
                                            "borderRadius": "0 0 4px 4px",
                                        },
                                    ),
                                    dcc.Checklist(
                                        id="ftir-consent",
                                        options=[
                                            {
                                                "label": " I understand uploaded spectra may be stored in server logs or temporary files for tool operation, troubleshooting, and maintenance.",
                                                "value": "yes",
                                            }
                                        ],
                                        value=[],
                                        style={"marginTop": "18px", "fontSize": "14px", "lineHeight": "1.45"},
                                    ),
                                    html.Div(style={"height": "12px"}),
                                    primary_button("Score spectra", "score-ftir-btn"),
                                    html.Div(
                                        id="ftir-status",
                                        children="Ready to score the uploaded spectra CSV.",
                                        style={"marginTop": "18px", "fontSize": "12px", "color": "#4b5563"},
                                    ),
                                ]
                            ),
                            panel(
                                [
                                    html.H3("Expected Format", style={"marginTop": 0, "fontSize": "26px", "fontWeight": "500"}),
                                    html.P(
                                        "Upload either one raw absorbance CSV or one or more Bruker OPUS replicate files with .0 or .opus extensions. CSVs may be wide format with one row per sample and numeric wavenumber columns, or long format with sample_id, wavenumber, and absorbance columns. Spectra must cover 4000 to at least 620 cm-1 at 2 cm-1 spacing; wider ranges such as 4000 to 400 are accepted and cropped internally. OPUS uploads require a manifest CSV with file_name and sample_id; replicates are grouped and averaged by manifest sample_id before scoring.",
                                        style={"fontSize": "14px", "lineHeight": "1.45"},
                                    ),
                                ]
                            ),
                        ]
                    ),
                    html.Div(
                        style={"minWidth": 0, "width": "100%", "maxWidth": "100%"},
                        children=[
                            panel(
                                [
                                    html.H3("Spectroscopy Results", style={"marginTop": 0, "fontSize": "26px", "fontWeight": "500"}),
                                    html.Div(id="ftir-error-box"),
                                    dcc.Graph(
                                        id="ftir-score-plot",
                                        figure=empty_results_figure(),
                                        config={"displayModeBar": False, "responsive": True},
                                        responsive=True,
                                        style={
                                            "height": "260px",
                                            "width": "100%",
                                            "maxWidth": "100%",
                                            "minWidth": 0,
                                        },
                                    ),
                                    dash_table.DataTable(
                                        id="ftir-results-table",
                                        data=[],
                                        columns=[{"name": c, "id": c} for c in CORE_OUTPUT_COLUMNS],
                                        page_size=10,
                                        sort_action="native",
                                        filter_action="native",
                                        style_table={
                                            "overflowX": "auto",
                                            "overflowY": "hidden",
                                            "width": "100%",
                                            "maxWidth": "100%",
                                            "minWidth": 0,
                                            "marginTop": "12px",
                                        },
                                        style_cell={
                                            "fontFamily": "Arial",
                                            "fontSize": "13px",
                                            "padding": "8px",
                                            "textAlign": "left",
                                            "minWidth": "105px",
                                            "width": "120px",
                                            "maxWidth": "160px",
                                            "whiteSpace": "nowrap",
                                            "overflow": "hidden",
                                            "textOverflow": "ellipsis",
                                        },
                                        style_header={"backgroundColor": "#f3f4f6", "fontWeight": "bold"},
                                    ),
                                    html.Br(),
                                    html.Button(
                                        [html.Span("⬇", style={"marginRight": "6px"}), "Download spectroscopy results"],
                                        id="download-ftir-results-btn",
                                        n_clicks=0,
                                        style={
                                            "padding": "8px 10px",
                                            "border": "1px solid #cfd8cf",
                                            "borderRadius": "5px",
                                            "backgroundColor": "white",
                                            "cursor": "pointer",
                                            "fontSize": "14px",
                                        },
                                    ),
                                ]
                            ),
                            panel(
                                [
                                    html.H3("Dropped Spectra", style={"marginTop": 0, "fontSize": "26px", "fontWeight": "500"}),
                                    dash_table.DataTable(
                                        id="ftir-dropped-table",
                                        data=[],
                                        columns=[
                                            {"name": "sample_id", "id": "sample_id"},
                                            {"name": "reason", "id": "reason"},
                                        ],
                                        page_size=10,
                                        style_table={"overflowX": "auto"},
                                        style_cell={"fontFamily": "Arial", "fontSize": "13px", "padding": "8px", "textAlign": "left"},
                                        style_header={"backgroundColor": "#f3f4f6", "fontWeight": "bold"},
                                    ),
                                ]
                            ),
                        ]
                    ),
                ],
            ),
        ],
    )


@callback(
    Output("ftir-upload-filename", "children"),
    Output("ftir-upload-complete", "style"),
    Input("ftir-csv-upload", "filename"),
)
def show_uploaded_filename(filename):
    base_style = {
        "backgroundColor": "#4b78b8",
        "color": "white",
        "textAlign": "center",
        "padding": "4px",
        "fontSize": "13px",
        "borderRadius": "0 0 4px 4px",
    }
    if not filename:
        return "No file selected", {**base_style, "display": "none"}
    return filename, {**base_style, "display": "block"}


@callback(
    Output("ftir-results-store", "data"),
    Output("ftir-dropped-store", "data"),
    Output("ftir-score-plot", "figure"),
    Output("ftir-results-table", "data"),
    Output("ftir-results-table", "columns"),
    Output("ftir-dropped-table", "data"),
    Output("ftir-error-box", "children"),
    Output("ftir-status", "children"),
    Input("score-ftir-btn", "n_clicks"),
    State("ftir-csv-upload", "contents"),
    State("ftir-csv-upload", "filename"),
    State("ftir-consent", "value"),
    prevent_initial_call=True,
)
def score_uploaded_ftir(n_clicks, contents, filename, consent):
    if not n_clicks:
        raise PreventUpdate

    if "yes" not in (consent or []):
        return (
            None,
            None,
            empty_results_figure(),
            [],
            [{"name": c, "id": c} for c in CORE_OUTPUT_COLUMNS],
            [],
            html.Div(
                "Please check the acknowledgement box before scoring spectra.",
                style={
                    "backgroundColor": "#f8d7da",
                    "padding": "12px",
                    "borderRadius": "5px",
                    "color": "#7f1d1d",
                    "marginBottom": "10px",
                },
            ),
            "Ready to score the uploaded spectra CSV.",
        )

    try:
        raw_df = parse_upload(contents, filename)
        results_df, dropped_df = score_spectra_with_live_model(raw_df)

        columns = [{"name": c, "id": c} for c in results_df.columns]
        dropped_data = dropped_df.to_dict("records") if not dropped_df.empty else []
        status = f"Scored {len(results_df)} spectrum/spectra; dropped {len(dropped_data)}."

        return (
            results_df.to_dict("records"),
            dropped_data,
            make_score_plot(results_df),
            results_df.to_dict("records"),
            columns,
            dropped_data,
            None,
            status,
        )

    except Exception as exc:
        error_code = datetime.now().strftime("FTIR-%Y%m%d-%H%M%S")
        message = f"Error code: {error_code}\n{exc}"

        return (
            None,
            None,
            empty_results_figure(),
            [],
            [{"name": c, "id": c} for c in CORE_OUTPUT_COLUMNS],
            [],
            html.Pre(
                message,
                style={
                    "backgroundColor": "#f8d7da",
                    "padding": "12px",
                    "borderRadius": "5px",
                    "color": "#111827",
                    "whiteSpace": "pre-wrap",
                    "marginBottom": "10px",
                },
            ),
            "Unable to score uploaded spectra CSV.",
        )


@callback(
    Output("download-ftir-wide-template", "data"),
    Input("download-wide-template-btn", "n_clicks"),
    prevent_initial_call=True,
)
def download_wide_template(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    df = make_wide_template(include_example=True)
    return dcc.send_data_frame(df.to_csv, "ftir_example_upload.csv", index=False)


@callback(
    Output("download-ftir-long-template", "data"),
    Input("download-long-template-btn", "n_clicks"),
    prevent_initial_call=True,
)
def download_long_template(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    df = make_long_template()
    return dcc.send_data_frame(df.to_csv, "ftir_long_template.csv", index=False)


@callback(
    Output("download-ftir-results", "data"),
    Input("download-ftir-results-btn", "n_clicks"),
    State("ftir-results-store", "data"),
    prevent_initial_call=True,
)
def download_ftir_results(n_clicks, rows):
    if not n_clicks or not rows:
        raise PreventUpdate
    df = pd.DataFrame(rows)
    return dcc.send_data_frame(df.to_csv, "ftir_spectroscopy_results.csv", index=False)