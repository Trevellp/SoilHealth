# Import libraries used for data handling, dashboard creation, and plotting
import pandas as pd
from dash import Dash, html, dcc, Input, Output
import plotly.express as px

# Load the synthetic soil health dataset
# header=1 tells pandas that the actual column names start on the second row
df = pd.read_csv("data/hsh_mock_synthetic_database_for_sql.csv", header=1)

# Keep only the fields that are important for the MVP dashboard
# These are the factors discussed for explaining Soil Health Score (SHS)
important_cols = [
    "shs", "latitude", "longitude",
    "plot_name", "minerals", "order", "suborder",
    "great_group", "PIAL_none", "management_category",
    "current_land_use", "most_previous_land_use"
]

# Create a copy containing only the selected columns
df = df[important_cols].copy()

# Convert numeric fields to numbers
# Invalid values are turned into missing values (NaN)
for col in ["shs", "latitude", "longitude"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# Remove rows missing key information needed for visualization
df = df.dropna(subset=["plot_name", "shs", "latitude", "longitude"])

# Initialize the Dash application
app = Dash(__name__)

# Create a 3D scatter plot
# Each point represents a plot from the dataset
fig = px.scatter_3d(
    df,
    x="longitude",     # Geographic location
    y="latitude",      # Geographic location
    z="shs",           # Soil Health Score shown as height
    color="shs",       # Soil Health Score shown as color
    size="shs",        # Soil Health Score shown as bubble size
    hover_name="plot_name",  # Main label shown when hovering
    hover_data=[
        "minerals",
        "order",
        "suborder",
        "great_group",
        "PIAL_none",
        "management_category",
        "current_land_use",
        "most_previous_land_use"
    ],
    title="3D Soil Health Score by Plot",
    color_continuous_scale="Viridis"
)

# Customize the appearance of the 3D plot
fig.update_layout(
    height=700,
    paper_bgcolor="#0f172a",
    plot_bgcolor="#0f172a",
    font=dict(color="white"),
    scene=dict(
        xaxis_title="Longitude",
        yaxis_title="Latitude",
        zaxis_title="SHS",
        bgcolor="#0f172a"
    )
)

# Build the dashboard layout
app.layout = html.Div(
    style={
        "backgroundColor": "#0f172a",
        "color": "white",
        "fontFamily": "Arial",
        "padding": "25px"
    },
    children=[

        # Dashboard title
        html.H1("Soil Health Score Dashboard"),

        # Dropdown used to select a specific plot
        html.Div([
            html.H3("Select Plot Name"),
            dcc.Dropdown(
                id="plot-dropdown",

                # Create dropdown options from all unique plot names
                options=[
                    {"label": name, "value": name}
                    for name in sorted(df["plot_name"].unique())
                ],

                # Default selection is the first plot alphabetically
                value=sorted(df["plot_name"].unique())[0],

                style={"color": "black"}
            )
        ]),

        html.Br(),

        # Section that will display information about the selected plot
        html.Div(
            id="plot-details",
            style={
                "backgroundColor": "#1e293b",
                "padding": "20px",
                "borderRadius": "12px",
                "marginBottom": "25px"
            }
        ),

        # Display the interactive 3D Soil Health visualization
        html.Div(
            style={
                "backgroundColor": "#1e293b",
                "padding": "20px",
                "borderRadius": "12px"
            },
            children=[
                dcc.Graph(figure=fig)
            ]
        )
    ]
)

# Callback updates plot information whenever a user selects a different plot
@app.callback(
    Output("plot-details", "children"),
    Input("plot-dropdown", "value")
)
def update_plot_details(selected_plot):

    # Find the row corresponding to the selected plot
    row = df[df["plot_name"] == selected_plot].iloc[0]

    # Display Soil Health Score and associated factors
    return html.Div([
        html.H2(f"Plot: {row['plot_name']}"),
        html.H1(f"Soil Health Score: {round(row['shs'], 2)}"),

        html.P(f"Minerals: {row['minerals']}"),
        html.P(f"Order: {row['order']}"),
        html.P(f"Suborder: {row['suborder']}"),
        html.P(f"Great Group: {row['great_group']}"),
        html.P(f"PIAL: {row['PIAL_none']}"),
        html.P(f"Management Category: {row['management_category']}"),
        html.P(f"Current Land Use: {row['current_land_use']}"),
        html.P(f"Most Previous Land Use: {row['most_previous_land_use']}")
    ])

# Run the dashboard locally
if __name__ == "__main__":
    app.run(debug=True)