# Hawaii Soil Health Portal

This directory is the stand-up-ready Shiny app source for the soil health scoring tool intended for `soilhealth.ctahr.hawaii.edu`.

## What I found

- No deployable Shiny app entry point existed in the repository: no `app.R`, `ui.R`, `server.R`, `shinyApp()`, `fluidPage()`, `fileInput()`, or `downloadHandler()` signatures were found.
- The scoring logic lives mostly in `soil_health_scoring/scripts/`, especially:
  - `Webtool_code.R`
  - `Webtool_code_v4.R`
  - `V4_scoring_function.R`
  - `V4_mini_suite_scoring_function.R`
- `web/hawaii_soil_health_portal/` previously contained only CTAHR VPN instructions, so this app has been added there as the deployment source.
- `project_management/notes/` exists but is empty. The update notes below come from the pasted goals.

## Implemented update notes

- Add downloadable template for data formatting.
- Add introduction and links to CTAHR soil/publication resources.
- Remove unnecessary column requirements by using the reduced v4 mini-suite input: `sample_id`, `minerals`, `toc`, `co2_burst`, `pmn`, `wsa_mega`.
- Add color-coded scoring results.
- Add progress/status feedback while scoring.
- Require consent before using the tool.
- Force numeric parsing and report dropped samples.
- Show user-facing error codes and write server-side error logs.
- Add a summarized, non-location-specific demo dashboard.
- Separate granular data tables into a demo data-owner portal with placeholder login and editable data-use preferences.
- Add an FTIR spectroscopy scoring page using exported HSH-spec models.

## Live scoring reconciliation

The lab-indicator page now uses the serialized model and preprocessing objects exported from the live Shiny app on June 12, 2026. The broader portal retains the summarized dashboard, data-owner portal scaffold, and FTIR page while matching the live scorer's core behavior:

- full nine-indicator model rather than the reduced four-indicator approximation
- overall `SH` score plus `f1_items`, `f2_items`, and `f3_items`
- reference percentiles for overall SH and all three factors
- separate `Scores` and `Core Dataset` result views
- compatibility with live headers such as `SH.`, `Plot.name`, `Minerals`, and `PIAL.none`
- two-significant-figure display and result downloads

The lab upload is intentionally permissive. It accepts the full master-database export, automatically detects and skips a units/preamble row, normalizes spacing and punctuation in headers, and ignores columns that are not needed for scoring. The minimum required fields are:

- a sample ID supplied as `sample_id`, `SH_1`, `HSH_id`, or `Intake_number`
- `minerals`
- `toc`, `co2_burst`, `ph`, `beta_glucosidase`, `beta_glucosaminidase`, `pmn`, `whc`, `hwec`, and `wsa_mega`

`plot_name`, `PIAL_none`, and `bd` are accepted but optional because the serialized live model does not require them for prediction.

The live model assets are stored in `live_model/`. The reduced cached scoring bundle remains only for passing FTIR-predicted indicators through the reduced standard-score bridge.

## Dashboard and data-owner portal

The public demo dashboard should only show summarized, non-location-specific information. It intentionally avoids sample-level rows, farms, islands, coordinates, or other location fields.

Granular sample data belongs behind a real login wall. The current `Data owner portal` tab is a local demo scaffold only:

- demo username: `owner@example.org`
- demo password: `demo-only`
- owner-scoped table filters records by `owner_id`
- preferences include research-use permission, allowed data types, follow-up contact preference, external collaborator review, and revocation-style options

Before production deployment, replace the placeholder login with production authentication and authorization, encrypted preference storage, audit logs, password reset/account lifecycle handling, and a server-side data model that enforces owner-level access on every request.

## FTIR spectroscopy scoring

The FTIR tab accepts either Bruker OPUS replicate files or raw wide-format FTIR absorbance spectra CSVs.

For OPUS uploads:

- upload one or more `.0` or `.opus` files
- upload a manifest CSV with `file_name` and `sample_id`
- every uploaded OPUS file must appear exactly once in the manifest
- replicate files are grouped by manifest `sample_id`, resampled to 4000-400 cm-1, averaged, then scored

Example manifest:

```csv
file_name,sample_id,replicate_id,minerals
Soil_PLATE-003_2019-158_A2.0,2019-158,A2,HAC
Soil_PLATE-003_2019-158_B2.0,2019-158,B2,HAC
Soil_PLATE-003_2019-158_C2.0,2019-158,C2,HAC
Soil_PLATE-003_2019-158_D2.0,2019-158,D2,HAC
```

For CSV uploads:

- `sample_id`
- optional `minerals` (`HAC`, `LAC`, `PNCM`, `HIST`) for indicator-based SEM scoring
- wide format: one row per sample with wavenumber columns named like `4000`, `3998`, `3996`, down to at least `620`
- long format: `sample_id`, `wavenumber`, and `absorbance` columns
- wider spectral ranges, such as `4000` to `400`, are accepted and cropped internally

The app handles preprocessing internally, following the R scripts in `ftir/scripts/02-Opus-to-SNVSG-csv.Rmd` and `ftir/scripts/ftir_processing.R`:

- uses the model-supported portion of raw spectra after derivative edge trimming, producing final model columns from 3990-630 cm-1
- accepts wider uploads such as 4000-400 cm-1 without using the extra lower-wavenumber region in the current models
- applies row-wise standard normal variate (SNV)
- applies Savitzky-Golay first derivative preprocessing with polynomial order 2, window 11, derivative 1
- trims derivative edge columns below the model range
- removes the 2388-2268 cm-1 CO2-sensitive region after SNV+SG preprocessing
- maps the processed spectra to the exported `X3990` through `X630` model columns

The user-facing flow is raw spectra upload. Already processed model-ready columns are still accepted only as a developer compatibility path. The exported models are stored in `ftir_models/` and are called by `ftir_predict.py`.

Compatibility note: direct OPUS file reading depends on the R `opusreader2` and `simplerspec` packages and is aimed at Bruker OPUS exports. Other instrument/software ecosystems should export a raw absorbance CSV with one row per sample and numeric wavenumber columns. Add dedicated converters later for any recurring vendor formats that cannot export that CSV shape.

The spectroscopy scorer produces:

- FTIR-predicted `toc`, `co2_burst`, `pmn`, and `wsa_mega` in original units
- direct FTIR latent soil-health prediction and percentile
- indicator-based soil-health score when `minerals` is supplied

## Deferred operational notes

- Email alerts are implemented as optional server behavior. Set `SOIL_HEALTH_ALERT_EMAIL` and ensure the server has a working `mail` command.
- Maintenance schedule still needs an owner and cadence. Suggested minimum: monthly smoke test, quarterly dependency check, and model-data review whenever the master database changes.
- FTIR should probably be a separate page or tab because the upload format, model assumptions, and error modes differ from the lab-indicator scoring flow.

## Local run

From the repository root:

```sh
Rscript -e "shiny::runApp('web/hawaii_soil_health_portal', host='127.0.0.1', port=3838)"
```

Required R packages:

```r
install.packages(c(
  "shiny", "dplyr", "lavaan", "MASS", "readr", "tibble", "jsonlite"
))
```

`DT` is optional. When it is unavailable, the app falls back to standard
Shiny tables. The app intentionally does not depend on the `tidyverse`
metapackage; component packages are checked explicitly at startup.

Required Python packages for the FTIR tab:

```sh
python -m pip install pandas numpy scipy joblib scikit-learn
```

If the web server needs a specific Python environment, set:

```sh
export SOIL_HEALTH_PYTHON=/path/to/python
```

## Deployment notes

Deploy the complete contents of this directory to:

```text
/srv/shiny-server/soil_health_app
```

The production bundle must include `scoring_bundle.rds`, `live_model/`,
`ftir_models/`, `ftir_predict.py`, `opus_to_raw_csv.R`, and `www/`.
When `scoring_bundle.rds` is present, the repository master database is not
required at runtime.

Before deployment, verify the server dependencies as the `shiny` user:

```sh
sudo -u shiny Rscript -e 'p <- c(
  "shiny","dplyr","lavaan","MASS","readr","tibble","jsonlite"
); print(setNames(vapply(p, requireNamespace, logical(1), quietly=TRUE), p))'

sudo -u shiny python3 -c \
  'import pandas,numpy,scipy,joblib,sklearn; print("FTIR Python dependencies OK")'
```

For direct OPUS uploads, also verify:

```sh
sudo -u shiny Rscript -e 'p <- c("opusreader2","simplerspec"); print(setNames(vapply(p, requireNamespace, logical(1), quietly=TRUE), p))'
```

The Shiny backend path is:

```text
http://10.224.6.98:3838/soil_health_app/
```

The preferred public configuration maps the domain root
`https://soilhealth.ctahr.hawaii.edu/` to that backend while preserving Shiny
WebSocket support and rewriting the public root to the backend
`/soil_health_app/` path.
