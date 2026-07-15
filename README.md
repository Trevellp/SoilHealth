# Hawaii Soil Health Portal Dashboard Handoff

This bundle is a development copy of the existing Hawaii Soil Health Portal.
It includes the production-aligned Shiny application, model assets required to
start the app, and synthetic aggregate data for dashboard development.

## Start Here

1. Install the required R packages:

```r
install.packages(c(
  "shiny", "dplyr", "lavaan", "MASS", "readr", "tibble", "jsonlite"
))
```

`DT` is optional. The app uses standard Shiny tables when it is unavailable.

2. From the bundle directory, run:

```sh
./run_dashboard_preview.sh
```

3. Open:

```text
http://127.0.0.1:3838
```

The preview command enables the otherwise disabled `Data Dashboard` and
`Data owner portal` tabs. Production leaves both tabs disabled by default.

## Directory Layout

```text
app/                         Standalone Shiny portal
mock_data/                   Synthetic, non-location dashboard inputs
README.md                    This file
DASHBOARD_SPEC.md            Scope, privacy rules, and implementation map
check_dependencies.R         Local R dependency check
run_dashboard_preview.sh     Local development launcher
```

## Development Boundary

Work inside the existing application structure. The dashboard currently lives
in `app/app.R`; its relevant blocks are listed in `DASHBOARD_SPEC.md`.

Do not add real provider records, sample-level data, farms, coordinates,
islands, site names, owner identifiers, or credentials to this bundle.

The public dashboard is for summarized, non-location-specific information.
Granular records and data-use preferences belong behind authenticated,
owner-scoped access. The current owner portal is only a UI scaffold and is not
production authentication.

## Recommended Workflow

1. Keep the FTIR, laboratory scoring, About Us, and Resources tabs working.
2. Develop with `SOIL_HEALTH_ENABLE_PREVIEW_TABS=true`.
3. Use only `mock_data/aggregate_dashboard_demo.csv` until a reviewed
   aggregate-data contract is available.
   From `app/app.R`, its relative path is
   `../mock_data/aggregate_dashboard_demo.csv`.
4. Test at desktop and mobile widths.
5. Return changed source files plus screenshots and a short data-contract note.

Do not deploy directly to the production server. Christian will reconcile and
deploy reviewed changes.
