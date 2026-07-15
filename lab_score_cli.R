#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(tibble)
  library(jsonlite)
  library(lavaan)
})

args <- commandArgs(trailingOnly = TRUE)

if (length(args) < 4 || args[1] != "--input" || args[3] != "--outdir") {
  stop("Usage: Rscript lab_score_cli.R --input input.csv --outdir output_dir", call. = FALSE)
}

input_path <- args[2]
outdir <- args[4]

# Optional:
# Rscript lab_score_cli.R --input input.csv --outdir output_dir --appdir app
app_dir <- if (length(args) >= 6 && args[5] == "--appdir") args[6] else file.path(getwd(), "app")

dir.create(outdir, showWarnings = FALSE, recursive = TRUE)

live_required_columns <- c(
  "sample_id", "minerals", "toc", "co2_burst", "ph",
  "beta_glucosidase", "beta_glucosaminidase", "pmn", "whc", "hwec", "wsa_mega"
)

live_numeric_columns <- c(
  "toc", "co2_burst", "ph", "beta_glucosidase", "beta_glucosaminidase",
  "pmn", "whc", "hwec", "wsa_mega"
)

live_optional_columns <- c("plot_name", "pial_none", "bd")

normalize_names <- function(x) {
  x <- tolower(trimws(x))
  x <- gsub("[^a-z0-9]+", "_", x)
  gsub("^_|_$", "", x)
}

read_csv_with_header_detection <- function(path) {
  preview <- suppressWarnings(read_csv(
    path,
    col_names = FALSE,
    n_max = 8,
    show_col_types = FALSE,
    name_repair = "minimal",
    na = character()
  ))

  header_markers <- c(
    "sample_id", "sh_1", "hsh_id", "intake_number", "minerals",
    "toc", "co2_burst", "beta_glucosidase", "beta_glucosaminidase",
    "pmn", "ph", "hwec", "whc", "wsa_mega"
  )

  header_scores <- apply(
    preview,
    1,
    function(row) {
      sum(normalize_names(as.character(row)) %in% header_markers, na.rm = TRUE)
    }
  )

  header_row <- which.max(header_scores)
  skip_rows <- if (length(header_row) == 0 || header_scores[header_row] < 4) {
    0
  } else {
    header_row - 1
  }

  suppressWarnings(read_csv(
    path,
    skip = skip_rows,
    show_col_types = FALSE,
    na = c("", "NA", "#N/A", "#REF!", "None")
  ))
}

boxcox_transform <- function(x, lambda) {
  if (abs(lambda) < .Machine$double.eps^0.5) {
    log(x)
  } else {
    (x^lambda - 1) / lambda
  }
}

score_band <- function(shs) {
  case_when(
    is.na(shs) ~ NA_character_,
    shs < 0.25 ~ "Low",
    shs < 0.50 ~ "Moderate-low",
    shs < 0.75 ~ "Moderate-high",
    TRUE ~ "High"
  )
}

load_live_model_bundle <- function(app_dir) {
  model_dir <- file.path(app_dir, "live_model")

  paths <- c(
    fit = file.path(model_dir, "trained_model.rds"),
    preproc = file.path(model_dir, "preproc_values.rds"),
    prob_sh = file.path(model_dir, "probSH.rds"),
    prob_factor1 = file.path(model_dir, "probFactor1.rds"),
    prob_factor2 = file.path(model_dir, "probFactor2.rds"),
    prob_factor3 = file.path(model_dir, "probFactor3.rds")
  )

  missing <- paths[!file.exists(paths)]

  if (length(missing) > 0) {
    stop(
      "Missing live model asset(s): ",
      paste(basename(missing), collapse = ", "),
      ". Looking in: ",
      model_dir
    )
  }

  list(
    fit = readRDS(paths[["fit"]]),
    preproc = readRDS(paths[["preproc"]]),
    prob_sh = readRDS(paths[["prob_sh"]]),
    prob_factor1 = readRDS(paths[["prob_factor1"]]),
    prob_factor2 = readRDS(paths[["prob_factor2"]]),
    prob_factor3 = readRDS(paths[["prob_factor3"]])
  )
}

prepare_live_upload <- function(path) {
  uploaded <- read_csv_with_header_detection(path)
  names(uploaded) <- normalize_names(names(uploaded))

  id_alias <- intersect(
    c("sample_id", "sh_1", "hsh_id", "intake_number", "sh"),
    names(uploaded)
  )

  if (!"sample_id" %in% names(uploaded) && length(id_alias) > 0) {
    uploaded <- uploaded %>% rename(sample_id = all_of(id_alias[1]))
  }

  if (!"minerals" %in% names(uploaded) && "mineral" %in% names(uploaded)) {
    uploaded <- uploaded %>% rename(minerals = mineral)
  }

  aliases <- c(
    beta_glucosidase = "bg",
    beta_glucosaminidase = "nag",
    co2_burst = "co2",
    wsa_mega = "wsa"
  )

  for (target in names(aliases)) {
    source <- aliases[[target]]

    if (!target %in% names(uploaded) && source %in% names(uploaded)) {
      uploaded <- uploaded %>% rename(!!target := all_of(source))
    }
  }

  missing_columns <- setdiff(live_required_columns, names(uploaded))

  if (length(missing_columns) > 0) {
    stop("Missing required column(s): ", paste(missing_columns, collapse = ", "))
  }

  if (!"plot_name" %in% names(uploaded)) {
    uploaded$plot_name <- uploaded$sample_id
  }

  if (!"pial_none" %in% names(uploaded)) {
    uploaded$pial_none <- "None"
  }

  if (!"bd" %in% names(uploaded)) {
    uploaded$bd <- NA_real_
  }

  uploaded %>%
    mutate(
      .row_number = row_number(),
      sample_id = as.character(sample_id),
      plot_name = as.character(plot_name),
      pial_none = as.character(pial_none),
      minerals = toupper(trimws(as.character(minerals))),
      across(all_of(live_numeric_columns), \(x) parse_number(as.character(x))),
      bd = parse_number(as.character(bd))
    ) %>%
    select(.row_number, all_of(live_required_columns), all_of(live_optional_columns))
}

score_live_samples <- function(input_data, bundle) {
  checked <- input_data %>%
    mutate(
      drop_reason = case_when(
        is.na(sample_id) | sample_id == "" ~ "Missing sample_id",
        minerals == "SAND" ~ "Sand is not supported by the live scoring model",
        minerals == "HIST" ~ "Histosol scoring is not available in the live model",
        !minerals %in% c("HAC", "LAC", "PNCM") ~ "Unsupported minerals value",
        if_any(all_of(live_numeric_columns), is.na) ~ "Missing or non-numeric required value",
        toc <= 0 | co2_burst <= 0 | ph <= 0 | hwec <= 0 | whc <= 0 ~ "Positive indicator value required",
        beta_glucosidase <= -10 | beta_glucosaminidase <= -10 ~ "Enzyme value must be greater than -10",
        pmn <= -22 ~ "pmn must be greater than -22",
        wsa_mega <= -1 ~ "wsa_mega must be greater than -1",
        TRUE ~ NA_character_
      )
    )

  dropped <- checked %>% filter(!is.na(drop_reason))
  ingest <- checked %>% filter(is.na(drop_reason))

  if (nrow(ingest) == 0) {
    stop("No valid samples remained after validation.")
  }

  p <- bundle$preproc

  ingest <- ingest %>%
    mutate(
      toc_tr = boxcox_transform(toc, p$lamba1),
      co2_burst_tr = boxcox_transform(co2_burst, p$lamba2),
      beta_glucosidase_tr = boxcox_transform(beta_glucosidase + 10, p$lamba3),
      beta_glucosaminidase_tr = boxcox_transform(beta_glucosaminidase + 10, p$lamba4),
      pmn_tr = boxcox_transform(pmn + 22, p$lamba5),
      acidity_tr = -1 * boxcox_transform(ph, p$lamba6),
      hwec_tr = boxcox_transform(hwec, p$lamba8),
      whc_tr = boxcox_transform(whc, p$lamba9),
      wsa_mega_tr = boxcox_transform(wsa_mega + 1, p$lamba10),

      toc_tr_s = (toc_tr - p$tocmean) / p$tocsd,
      co2_burst_tr_s = (co2_burst_tr - p$co2_burstmean) / p$co2_burstsd,
      beta_glucosidase_tr_s = (beta_glucosidase_tr - p$beta_glucosidasemean) / p$beta_glucosidasesd,
      beta_glucosaminidase_tr_s = (beta_glucosaminidase_tr - p$beta_glucosaminidasemean) / p$beta_glucosaminidasesd,
      pmn_tr_s = (pmn_tr - p$pmnmean) / p$pmnsd,
      acidity_tr_s = (acidity_tr - p$aciditymean) / p$aciditysd,
      hwec_tr_s = (hwec_tr - p$hwecmean) / p$hwecsd,
      whc_tr_s = (whc_tr - p$whcmean) / p$whcsd,
      wsa_mega_tr_s = (wsa_mega_tr - p$wsa_megamean) / p$wsa_megasd,

      PIAL = if_else(tolower(trimws(pial_none)) == "none", 0, 1),
      Combined = paste(minerals, PIAL),

      HAC = if_else(minerals == "HAC", 1, 0),
      LAC = if_else(minerals == "LAC", 1, 0),
      PNCM = if_else(minerals == "PNCM", 1, 0),

      HAC_PIAL = if_else(Combined == "HAC 1", 1, 0),
      HAC_none = if_else(Combined == "HAC 0", 1, 0),
      LAC_PIAL = if_else(Combined == "LAC 1", 1, 0),
      LAC_none = if_else(Combined == "LAC 0", 1, 0),
      PNCM_PIAL = if_else(Combined == "PNCM 1", 1, 0),
      PNCM_none = if_else(Combined == "PNCM 0", 1, 0)
    )

  scores <- lavaan::lavPredict(bundle$fit, level = 1L, newdata = ingest)

  scored <- bind_cols(ingest, as_tibble(scores)) %>%
    mutate(
      across(any_of(c("SH", "f1_items", "f2_items", "f3_items")), as.numeric),
      cdf_SHS = bundle$prob_sh(SH),
      cdf_Factor1 = bundle$prob_factor1(f1_items),
      cdf_Factor2 = bundle$prob_factor2(f2_items),
      cdf_Factor3 = bundle$prob_factor3(f3_items),
      score_percentile = cdf_SHS * 100,
      score_band = score_band(cdf_SHS)
    )

  scores_view <- scored %>%
    select(
      sample_id, plot_name, SH, f1_items, f2_items, f3_items,
      cdf_SHS, cdf_Factor1, cdf_Factor2, cdf_Factor3,
      score_percentile, score_band
    )

  core_view <- scored %>%
    select(
      sample_id, plot_name, toc, co2_burst, ph, beta_glucosidase,
      beta_glucosaminidase, pmn, whc, hwec, wsa_mega, bd,
      minerals, cdf_SHS, cdf_Factor1, cdf_Factor2, cdf_Factor3
    )

  list(
    scores = scores_view,
    core = core_view,
    dropped = dropped
  )
}

tryCatch({
  bundle <- load_live_model_bundle(app_dir)
  input_data <- prepare_live_upload(input_path)
  scored <- score_live_samples(input_data, bundle)

  write_csv(scored$scores, file.path(outdir, "scores.csv"))
  write_csv(scored$core, file.path(outdir, "core.csv"))
  write_csv(scored$dropped, file.path(outdir, "dropped.csv"))

  # Also write the filenames your Python callback originally expected.
  write_csv(scored$scores, file.path(outdir, "lab_scored_results.csv"))
  write_csv(scored$core, file.path(outdir, "lab_core_results.csv"))
  write_csv(scored$dropped, file.path(outdir, "lab_dropped_samples.csv"))

  write_json(
    list(
      ok = TRUE,
      scores_file = "scores.csv",
      core_file = "core.csv",
      dropped_file = "dropped.csv"
    ),
    file.path(outdir, "status.json"),
    auto_unbox = TRUE
  )
}, error = function(e) {
  write_json(
    list(
      ok = FALSE,
      error = conditionMessage(e)
    ),
    file.path(outdir, "status.json"),
    auto_unbox = TRUE
  )

  stop(conditionMessage(e), call. = FALSE)
}
)