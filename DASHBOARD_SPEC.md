# Dashboard Development Specification

## Purpose

Build a clear public dashboard for summarized Hawaii soil-health information
without exposing locations, owners, farms, projects, or individual samples.
The dashboard should help farmers, researchers, and extension users understand
the distribution of soil-health scores and broad indicator patterns.

## Existing Implementation Map

All current portal code is in `app/app.R`.

- `demo_dashboard_data`: temporary in-memory demo records
- CSS classes beginning with `.dashboard-` and `.metric-`: dashboard styling
- `tabPanel(... value = "demo_dashboard")`: dashboard UI
- outputs beginning with `demo_`: dashboard server calculations and plots
- `SOIL_HEALTH_ENABLE_PREVIEW_TABS`: development-only tab enablement
- `owner_login_panel` and `owner_portal_panel`: placeholder owner-access UI

Search with:

```sh
rg -n "demo_dashboard|dashboard-grid|demo_|owner_portal" app/app.R
```

## Initial Metrics

The established placeholder dashboard includes:

- records scored
- median Soil Health Score percentile
- count or percentage in moderate-high and high bands
- lowest broad indicator group
- distribution across score bands
- carbon-storage index
- biological-activity index
- physical-structure index

Useful additions that remain aggregate:

- number of observations contributing to each summary
- percentage of records successfully scored
- median and interquartile range for major indicators
- score-band change across broad reporting periods
- mineral-class comparison only when each group passes suppression rules
- plain-language notes explaining what each metric represents

## Data Contract

Use `mock_data/aggregate_dashboard_demo.csv` as the initial interface.
Because Shiny runs with `app/` as its working directory, dashboard code can
read it from `../mock_data/aggregate_dashboard_demo.csv`.

Each row represents an already aggregated group, not a soil sample.

Required fields:

- `reporting_period`
- `management_category`
- `mineral_class`
- `sample_count`
- `scored_count`
- `median_score_percentile`
- `percent_moderate_high_or_high`
- `carbon_storage_index`
- `biological_activity_index`
- `physical_structure_index`
- `display_allowed`

The production aggregation layer may later replace this CSV with a database
view or API response while preserving the same conceptual fields.

## Privacy Rules

- Never display latitude, longitude, island, farm, site, plot, barcode,
  intake number, project name, owner ID, or sample ID.
- Do not expose row-level records in the public dashboard.
- Suppress or combine groups with fewer than five contributing records.
- Do not allow filter combinations that reveal a small hidden group.
- Treat free-text management notes as private unless separately reviewed.
- Aggregate data-use permission must be checked before including provider data.
- Public downloads must contain only the reviewed aggregate fields.

The mock field `display_allowed` demonstrates the suppression decision.
Rows where it is `FALSE` must not be rendered as individual groups.

## Owner Portal Boundary

The Data owner portal will eventually require:

- real authentication
- authorization on every data query
- owner-scoped records
- encrypted preference storage
- audit logs
- account recovery and lifecycle controls
- consent and revocation workflows

Do not implement production security by extending the current hard-coded demo
login. It is a visual prototype only.

## Design Constraints

- Keep the interface work-focused and easy to scan.
- Keep cards at 8px radius or less.
- Avoid maps and location-derived visualizations.
- Use the established score-band colors consistently.
- Do not make page sections look like cards.
- Ensure labels and values fit at mobile widths.
- Provide loading, empty, suppressed, and error states.
- Avoid dependencies that are not already available on the production server
  unless they are reviewed and bundled for offline installation.

## Completion Checklist

- Dashboard works with the synthetic aggregate CSV.
- No location or owner fields are introduced.
- Groups below the suppression threshold are hidden or combined.
- Existing FTIR and lab scoring workflows still load.
- Preview tabs remain disabled when the environment switch is absent.
- Desktop and mobile screenshots are included with the handoff.
- New package dependencies are documented.
