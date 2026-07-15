required_r_packages <- c(
  "shiny", "dplyr", "lavaan", "MASS", "readr", "tibble", "jsonlite"
)
missing_r_packages <- required_r_packages[
  !vapply(required_r_packages, requireNamespace, logical(1), quietly = TRUE)
]
if (length(missing_r_packages) > 0) {
  stop(
    "Missing required R package(s): ",
    paste(missing_r_packages, collapse = ", "),
    call. = FALSE
  )
}

library(shiny)
library(dplyr)

has_dt <- requireNamespace("DT", quietly = TRUE)
preview_tabs_enabled <- identical(
  tolower(Sys.getenv("SOIL_HEALTH_ENABLE_PREVIEW_TABS", unset = "false")),
  "true"
)

configure_lavaan_ncpus <- function() {
  cores <- suppressWarnings(parallel::detectCores())
  if (!is.na(cores)) {
    return(invisible(TRUE))
  }

  opt <- suppressWarnings(lavaan:::lav_options_default())
  chk <- get("opt.check", envir = lavaan:::lavaan_cache_env)
  opt$ncpus <- 1L
  chk$ncpus$nm$bounds <- c(1, 1)
  assign("opt.default", opt, envir = lavaan:::lavaan_cache_env)
  assign("opt.check", chk, envir = lavaan:::lavaan_cache_env)
  invisible(TRUE)
}

configure_lavaan_ncpus()

accepted_minerals <- c("HAC", "LAC", "PNCM", "HIST")
live_required_columns <- c(
  "sample_id", "toc", "co2_burst", "ph", "beta_glucosidase",
  "beta_glucosaminidase", "pmn", "whc", "hwec", "wsa_mega", "minerals"
)
live_numeric_columns <- c(
  "toc", "co2_burst", "ph", "beta_glucosidase",
  "beta_glucosaminidase", "pmn", "whc", "hwec", "wsa_mega"
)
live_optional_columns <- c("plot_name", "pial_none", "bd")

find_repo_root <- function(start = getwd()) {
  current <- normalizePath(start, mustWork = TRUE)
  repeat {
    candidate <- file.path(
      current,
      "soil_health_scoring",
      "raw_data",
      "HSH_MASTER_DATABASEallsamples - Master Database (15).csv"
    )
    if (file.exists(candidate)) {
      return(current)
    }
    parent <- dirname(current)
    if (identical(parent, current)) {
      stop("Could not find repository root containing soil_health_scoring/raw_data.")
    }
    current <- parent
  }
}

find_portal_dir <- function() {
  candidates <- c(
    getwd(),
    file.path(getwd(), "web", "hawaii_soil_health_portal")
  )
  repo_candidate <- tryCatch(
    file.path(find_repo_root(), "web", "hawaii_soil_health_portal"),
    error = function(e) NULL
  )
  candidates <- c(candidates, repo_candidate)
  for (candidate in candidates) {
    if (file.exists(file.path(candidate, "ftir_predict.py"))) {
      return(normalizePath(candidate, mustWork = TRUE))
    }
  }
  stop("Could not find hawaii_soil_health_portal app assets.")
}

normalize_names <- function(x) {
  x <- tolower(trimws(x))
  x <- gsub("[^a-z0-9]+", "_", x)
  gsub("^_|_$", "", x)
}

read_csv_with_header_detection <- function(path) {
  preview <- suppressWarnings(readr::read_csv(
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
    function(row) sum(normalize_names(as.character(row)) %in% header_markers, na.rm = TRUE)
  )
  header_row <- which.max(header_scores)
  skip_rows <- if (length(header_row) == 0 || header_scores[header_row] < 4) 0 else header_row - 1

  suppressWarnings(readr::read_csv(
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

build_model_bundle <- function() {
  repo_root <- find_repo_root()
  training_path <- file.path(
    repo_root,
    "soil_health_scoring",
    "raw_data",
    "HSH_MASTER_DATABASEallsamples - Master Database (15).csv"
  )

  raw <- readr::read_csv(
    training_path,
    show_col_types = FALSE,
    na = c("", "NA", "#N/A", "#REF!", "None")
  )
  names(raw) <- normalize_names(names(raw))

  training <- raw %>%
    mutate(
      across(
        c(toc, co2_burst, beta_glucosidase, beta_glucosaminidase, pmn, ph, hwec, whc, wsa_mega),
        \(x) readr::parse_number(as.character(x))
      ),
      minerals = toupper(trimws(minerals))
    ) %>%
    filter(complete.cases(toc, co2_burst, beta_glucosidase, beta_glucosaminidase, pmn, ph, hwec, whc, wsa_mega))

  transform_source <- raw %>%
    transmute(
      toc = readr::parse_number(as.character(toc)),
      co2_burst = readr::parse_number(as.character(co2_burst)),
      beta_glucosidase = readr::parse_number(as.character(beta_glucosidase)),
      beta_glucosaminidase = readr::parse_number(as.character(beta_glucosaminidase)),
      doc_don = readr::parse_number(as.character(doc_don)),
      pmn = readr::parse_number(as.character(pmn)),
      ph = readr::parse_number(as.character(ph)),
      hwec = readr::parse_number(as.character(hwec)),
      whc = readr::parse_number(as.character(whc)),
      wsa_mega = readr::parse_number(as.character(wsa_mega))
    ) %>%
    filter(if_all(everything(), \(x) !is.na(x)))

  best_lambda <- function(formula, data) {
    bc <- MASS::boxcox(formula, data = data, plotit = FALSE)
    bc$x[which.max(bc$y)]
  }

  lambdas <- list(
    toc = best_lambda(toc ~ 1, transform_source),
    co2_burst = best_lambda(co2_burst ~ 1, transform_source),
    pmn = best_lambda((pmn + 22) ~ 1, transform_source),
    wsa_mega = best_lambda((wsa_mega + 1) ~ 1, transform_source)
  )

  transformed <- training %>%
    mutate(
      toc_tr = boxcox_transform(toc, lambdas$toc),
      co2_burst_tr = boxcox_transform(co2_burst, lambdas$co2_burst),
      pmn_tr = boxcox_transform(pmn + 22, lambdas$pmn),
      wsa_mega_tr = boxcox_transform(wsa_mega + 1, lambdas$wsa_mega)
    )

  centers <- transformed %>%
    summarise(across(c(toc_tr, co2_burst_tr, pmn_tr, wsa_mega_tr), \(x) mean(x, na.rm = TRUE)))
  scales <- transformed %>%
    summarise(across(c(toc_tr, co2_burst_tr, pmn_tr, wsa_mega_tr), \(x) sd(x, na.rm = TRUE)))

  if (!"plot_name" %in% names(transformed)) {
    transformed$plot_name <- as.character(seq_len(nrow(transformed)))
  }

  model_data <- transformed %>%
    mutate(
      toc_tr_s = (toc_tr - centers$toc_tr) / scales$toc_tr,
      co2_burst_tr_s = (co2_burst_tr - centers$co2_burst_tr) / scales$co2_burst_tr,
      pmn_tr_s = (pmn_tr - centers$pmn_tr) / scales$pmn_tr,
      wsa_mega_tr_s = (wsa_mega_tr - centers$wsa_mega_tr) / scales$wsa_mega_tr,
      HAC = if_else(minerals == "HAC", 1, 0),
      LAC = if_else(minerals == "LAC", 1, 0),
      PNCM = if_else(minerals == "PNCM", 1, 0),
      HIST = if_else(minerals == "HIST", 1, 0),
      plot_name = coalesce(as.character(plot_name), as.character(row_number()))
    ) %>%
    filter(
      minerals != "SAND",
      minerals != "",
      complete.cases(toc_tr_s, co2_burst_tr_s, pmn_tr_s, wsa_mega_tr_s, minerals, plot_name)
    )

  model_spec <- "
    SH =~ co2_burst_tr_s + pmn_tr_s + toc_tr_s + wsa_mega_tr_s
    co2_burst_tr_s + pmn_tr_s + toc_tr_s + wsa_mega_tr_s ~ LAC + PNCM + HIST
  "

  fit <- lavaan::cfa(model_spec, estimator = "MLR", data = model_data, ncpus = 1)
  reference_scores <- cbind(model_data, lavaan::lavPredict(fit, level = 1L)) %>%
    mutate(shs = ecdf(SH)(SH))

  list(
    fit = fit,
    lambdas = lambdas,
    centers = centers,
    scales = scales,
    sh_ecdf = ecdf(reference_scores$SH),
    training_path = training_path
  )
}

load_or_build_model_bundle <- function() {
  bundle_path <- file.path(find_portal_dir(), "scoring_bundle.rds")
  if (file.exists(bundle_path)) {
    return(readRDS(bundle_path))
  }
  bundle <- build_model_bundle()
  saveRDS(bundle, bundle_path)
  bundle
}

load_live_model_bundle <- function() {
  model_dir <- file.path(find_portal_dir(), "live_model")
  files <- c(
    fit = "trained_model.rds",
    preproc = "preproc_values.rds",
    prob_sh = "probSH.rds",
    prob_factor1 = "probFactor1.rds",
    prob_factor2 = "probFactor2.rds",
    prob_factor3 = "probFactor3.rds"
  )
  paths <- stats::setNames(file.path(model_dir, unname(files)), names(files))
  missing <- paths[!file.exists(paths)]
  if (length(missing) > 0) {
    stop("Missing live scoring model asset(s): ", paste(basename(missing), collapse = ", "))
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

score_band <- function(shs) {
  case_when(
    is.na(shs) ~ NA_character_,
    shs < 0.25 ~ "Low",
    shs < 0.50 ~ "Moderate-low",
    shs < 0.75 ~ "Moderate-high",
    TRUE ~ "High"
  )
}

two_sig_figs <- function(data) {
  data %>% mutate(across(where(is.numeric), \(x) signif(x, 2)))
}

estimate_with_se <- function(estimate, se, digits = 2) {
  ifelse(
    is.na(estimate),
    NA_character_,
    paste0(signif(estimate, digits), " +/- ", signif(se, digits), " SE")
  )
}

ftir_display_results <- function(results) {
  out <- results %>%
    transmute(
      sample_id,
      `FTIR SH estimate` = estimate_with_se(ftir_direct_SH, ftir_direct_SH_sd),
      `FTIR SHS percentile` = paste0(
        signif(direct_score_percentile, 3),
        "% (95% approx. ",
        signif(direct_score_percentile_low95, 3),
        "-",
        signif(direct_score_percentile_high95, 3),
        "%)"
      ),
      `FTIR SHS band` = direct_score_band,
      `TOC estimate` = estimate_with_se(ftir_toc, ftir_toc_sd),
      `CO2 burst estimate` = estimate_with_se(ftir_co2_burst, ftir_co2_burst_sd),
      `PMN estimate` = estimate_with_se(ftir_pmn, ftir_pmn_sd),
      `WSA estimate` = estimate_with_se(ftir_wsa_mega, ftir_wsa_mega_sd),
      `Predicted minerals` = if ("ftir_predicted_minerals" %in% names(results)) ftir_predicted_minerals else NA_character_,
      `Minerals confidence` = if ("ftir_predicted_minerals_prob" %in% names(results)) signif(ftir_predicted_minerals_prob, 2) else NA_real_,
      `Predicted PIAL` = if ("ftir_predicted_PIAL" %in% names(results)) ftir_predicted_PIAL else NA_character_,
      `PIAL confidence` = if ("ftir_predicted_PIAL_prob" %in% names(results)) signif(ftir_predicted_PIAL_prob, 2) else NA_real_
    )

  if ("minerals" %in% names(results)) {
    out <- out %>% mutate(`User minerals` = results$minerals, .after = sample_id)
  }
  if ("indicator_score_percentile" %in% names(results)) {
    out <- out %>%
      mutate(
        `Indicator SEM SHS percentile` = indicator_score_percentile,
        `Indicator SEM band` = indicator_score_band
      )
  }
  out
}

prepare_live_upload <- function(path) {
  uploaded <- read_csv_with_header_detection(path)
  names(uploaded) <- normalize_names(names(uploaded))

  id_alias <- intersect(c("sample_id", "sh_1", "hsh_id", "intake_number", "sh"), names(uploaded))
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
      across(all_of(live_numeric_columns), \(x) readr::parse_number(as.character(x))),
      bd = readr::parse_number(as.character(bd))
    ) %>%
    dplyr::select(.row_number, all_of(live_required_columns), all_of(live_optional_columns))
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
  scored <- bind_cols(ingest, tibble::as_tibble(scores)) %>%
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
    dplyr::select(
      sample_id, plot_name, SH, f1_items, f2_items, f3_items,
      cdf_SHS, cdf_Factor1, cdf_Factor2, cdf_Factor3,
      score_percentile, score_band
    )
  core_view <- scored %>%
    dplyr::select(
      sample_id, plot_name, toc, co2_burst, ph, beta_glucosidase,
      beta_glucosaminidase, pmn, whc, hwec, wsa_mega, bd,
      minerals, cdf_SHS, cdf_Factor1, cdf_Factor2, cdf_Factor3
    )

  list(results = scored, scores = scores_view, core = core_view, dropped = dropped)
}

prepare_upload <- function(path) {
  uploaded <- readr::read_csv(path, show_col_types = FALSE, na = c("", "NA", "#N/A", "#REF!"))
  names(uploaded) <- normalize_names(names(uploaded))

  if (!"sample_id" %in% names(uploaded) && "sh_1" %in% names(uploaded)) {
    uploaded <- uploaded %>% rename(sample_id = sh_1)
  }

  missing_columns <- setdiff(required_columns, names(uploaded))
  if (length(missing_columns) > 0) {
    stop("Missing required column(s): ", paste(missing_columns, collapse = ", "))
  }

  uploaded %>%
    mutate(.row_number = row_number()) %>%
    transmute(
      .row_number,
      sample_id = as.character(sample_id),
      minerals = toupper(trimws(as.character(minerals))),
      toc = readr::parse_number(as.character(toc)),
      co2_burst = readr::parse_number(as.character(co2_burst)),
      pmn = readr::parse_number(as.character(pmn)),
      wsa_mega = readr::parse_number(as.character(wsa_mega))
    )
}

score_samples <- function(input_data, bundle) {
  checked <- input_data %>%
    mutate(
      drop_reason = case_when(
        is.na(sample_id) | sample_id == "" ~ "Missing sample_id",
        !minerals %in% accepted_minerals ~ "Unsupported minerals value",
        is.na(toc) | is.na(co2_burst) | is.na(pmn) | is.na(wsa_mega) ~ "Missing or non-numeric required value",
        toc <= 0 ~ "toc must be greater than 0",
        co2_burst <= 0 ~ "co2_burst must be greater than 0",
        pmn <= -22 ~ "pmn must be greater than -22",
        wsa_mega <= -1 ~ "wsa_mega must be greater than -1",
        TRUE ~ NA_character_
      )
    )

  dropped <- checked %>% filter(!is.na(drop_reason))
  scoring_data <- checked %>% filter(is.na(drop_reason))

  if (nrow(scoring_data) == 0) {
    stop("No valid samples remained after validation.")
  }

  transformed <- scoring_data %>%
    mutate(
      toc_tr = boxcox_transform(toc, bundle$lambdas$toc),
      co2_burst_tr = boxcox_transform(co2_burst, bundle$lambdas$co2_burst),
      pmn_tr = boxcox_transform(pmn + 22, bundle$lambdas$pmn),
      wsa_mega_tr = boxcox_transform(wsa_mega + 1, bundle$lambdas$wsa_mega),
      toc_tr_s = (toc_tr - bundle$centers$toc_tr) / bundle$scales$toc_tr,
      co2_burst_tr_s = (co2_burst_tr - bundle$centers$co2_burst_tr) / bundle$scales$co2_burst_tr,
      pmn_tr_s = (pmn_tr - bundle$centers$pmn_tr) / bundle$scales$pmn_tr,
      wsa_mega_tr_s = (wsa_mega_tr - bundle$centers$wsa_mega_tr) / bundle$scales$wsa_mega_tr,
      HAC = if_else(minerals == "HAC", 1, 0),
      LAC = if_else(minerals == "LAC", 1, 0),
      PNCM = if_else(minerals == "PNCM", 1, 0),
      HIST = if_else(minerals == "HIST", 1, 0)
    )

  scores <- lavaan::lavPredict(bundle$fit, level = 1L, newdata = transformed)
  results <- bind_cols(transformed, tibble::as_tibble(scores)) %>%
    mutate(
      shs = bundle$sh_ecdf(SH),
      score_percentile = round(shs * 100, 1),
      score_band = score_band(shs)
    ) %>%
    dplyr::select(sample_id, minerals, toc, co2_burst, pmn, wsa_mega, SH, shs, score_percentile, score_band)

  list(results = results, dropped = dropped)
}

log_error <- function(error_id, err) {
  log_dir <- file.path(getwd(), "logs")
  dir.create(log_dir, showWarnings = FALSE, recursive = TRUE)
  msg <- paste0(
    format(Sys.time(), "%Y-%m-%d %H:%M:%S %Z"),
    " | ",
    error_id,
    " | ",
    conditionMessage(err),
    "\n"
  )
  cat(msg, file = file.path(log_dir, "errors.log"), append = TRUE)

  alert_to <- Sys.getenv("SOIL_HEALTH_ALERT_EMAIL", unset = "")
  if (nzchar(alert_to) && nzchar(Sys.which("mail"))) {
    system2(
      "mail",
      args = c("-s", paste("Soil health portal error", error_id), alert_to),
      input = msg,
      stdout = FALSE,
      stderr = FALSE
    )
  }
}

ftir_spectral_columns <- function() {
  paste0("X", c(seq(3990, 2390, by = -2), seq(2266, 630, by = -2)))
}

ftir_raw_template_columns <- function() {
  as.character(seq(4000, 400, by = -2))
}

python_executable <- function() {
  configured <- Sys.getenv("SOIL_HEALTH_PYTHON", unset = "")
  candidates <- unique(c(
    configured,
    "/opt/soil-health-python/bin/python",
    Sys.which("python"),
    Sys.which("python3")
  ))
  candidates <- candidates[nzchar(candidates)]

  for (candidate in candidates) {
    status <- suppressWarnings(system2(
      candidate,
      args = c("-c", shQuote("import joblib, numpy, pandas, scipy, sklearn")),
      stdout = FALSE,
      stderr = FALSE
    ))
    if (identical(status, 0L)) {
      return(candidate)
    }
  }
  stop(
    "No compatible Python environment was found. Set SOIL_HEALTH_PYTHON to a Python executable with pandas, numpy, scipy, joblib, and scikit-learn."
  )
}

r_executable <- function() {
  configured <- Sys.getenv("SOIL_HEALTH_RSCRIPT", unset = "")
  if (nzchar(configured)) {
    return(configured)
  }
  rscript <- Sys.which("Rscript")
  if (nzchar(rscript)) {
    return(rscript)
  }
  stop("Rscript was not found. Set SOIL_HEALTH_RSCRIPT to the Rscript executable with simplerspec and opusreader2.")
}

prepare_ftir_input <- function(upload_info, manifest_info, app_dir) {
  input_paths <- upload_info$datapath
  original_names <- upload_info$name
  extensions <- tolower(tools::file_ext(original_names))

  if (length(input_paths) == 1 && extensions[1] == "csv") {
    return(input_paths[1])
  }

  if (all(extensions %in% c("0", "opus"))) {
    if (is.null(manifest_info) || is.null(manifest_info$datapath)) {
      stop("OPUS uploads require a manifest CSV with file_name and sample_id columns.")
    }
    safe_names <- basename(original_names)
    if (any(safe_names == "") || any(duplicated(safe_names))) {
      stop("Uploaded OPUS filenames must be non-empty and unique.")
    }
    staging_dir <- tempfile("opus_upload_")
    dir.create(staging_dir, recursive = TRUE)
    staged_paths <- file.path(staging_dir, safe_names)
    copied <- file.copy(input_paths, staged_paths, overwrite = FALSE)
    if (!all(copied)) {
      stop("Could not stage uploaded OPUS files using their original filenames.")
    }

    converter <- file.path(app_dir, "opus_to_raw_csv.R")
    out_csv <- tempfile(fileext = ".csv")
    status <- system2(
      r_executable(),
      args = c(converter, "--manifest", manifest_info$datapath, "--output", out_csv, staged_paths),
      stdout = TRUE,
      stderr = TRUE
    )
    exit_code <- attr(status, "status")
    if (!is.null(exit_code) && exit_code != 0) {
      stop(paste(status, collapse = "\n"))
    }
    return(out_csv)
  }

  stop("FTIR upload must be either one raw absorbance CSV or one or more Bruker OPUS files with .0 or .opus extensions.")
}

run_ftir_prediction <- function(upload_info, manifest_info, bundle) {
  app_dir <- find_portal_dir()
  script <- file.path(app_dir, "ftir_predict.py")
  model_dir <- file.path(app_dir, "ftir_models")
  input_path <- prepare_ftir_input(upload_info, manifest_info, app_dir)
  out_csv <- tempfile(fileext = ".csv")
  dropped_json <- sub("\\.csv$", ".dropped.json", out_csv)

  status <- system2(
    python_executable(),
    args = c(
      script,
      "--input", input_path,
      "--output", out_csv,
      "--model-dir", model_dir
    ),
    stdout = TRUE,
    stderr = TRUE
  )
  exit_code <- attr(status, "status")
  if (!is.null(exit_code) && exit_code != 0) {
    stop(paste(status, collapse = "\n"))
  }

  predictions <- readr::read_csv(out_csv, show_col_types = FALSE)
  dropped <- tibble::tibble()
  if (file.exists(dropped_json)) {
    dropped <- jsonlite::fromJSON(dropped_json) %>% tibble::as_tibble()
  }

  predictions <- predictions %>%
    mutate(
      ftir_toc_low95 = pmax(0, ftir_toc - 1.96 * ftir_toc_sd),
      ftir_toc_high95 = ftir_toc + 1.96 * ftir_toc_sd,
      ftir_co2_burst_low95 = pmax(0, ftir_co2_burst - 1.96 * ftir_co2_burst_sd),
      ftir_co2_burst_high95 = ftir_co2_burst + 1.96 * ftir_co2_burst_sd,
      ftir_pmn_low95 = ftir_pmn - 1.96 * ftir_pmn_sd,
      ftir_pmn_high95 = ftir_pmn + 1.96 * ftir_pmn_sd,
      ftir_wsa_mega_low95 = pmax(0, ftir_wsa_mega - 1.96 * ftir_wsa_mega_sd),
      ftir_wsa_mega_high95 = ftir_wsa_mega + 1.96 * ftir_wsa_mega_sd,
      ftir_direct_SH_low95 = ftir_direct_SH - 1.96 * ftir_direct_SH_sd,
      ftir_direct_SH_high95 = ftir_direct_SH + 1.96 * ftir_direct_SH_sd,
      direct_shs = bundle$sh_ecdf(ftir_direct_SH),
      direct_shs_low95 = bundle$sh_ecdf(ftir_direct_SH_low95),
      direct_shs_high95 = bundle$sh_ecdf(ftir_direct_SH_high95),
      direct_score_percentile = round(direct_shs * 100, 1),
      direct_score_percentile_low95 = round(direct_shs_low95 * 100, 1),
      direct_score_percentile_high95 = round(direct_shs_high95 * 100, 1),
      direct_score_band = score_band(direct_shs)
    )

  if ("minerals" %in% names(predictions)) {
    indicator_input <- predictions %>%
      transmute(
        .row_number = row_number(),
        sample_id,
        minerals = toupper(trimws(as.character(minerals))),
        toc = ftir_toc,
        co2_burst = ftir_co2_burst,
        pmn = ftir_pmn,
        wsa_mega = ftir_wsa_mega
      )
    indicator_scores <- score_samples(indicator_input, bundle)
    predictions <- predictions %>%
      left_join(
        indicator_scores$results %>%
          mutate(indicator_SH = as.numeric(SH)) %>%
          dplyr::select(sample_id, indicator_SH, indicator_shs = shs, indicator_score_percentile = score_percentile, indicator_score_band = score_band),
        by = "sample_id"
      )
    dropped <- bind_rows(dropped, indicator_scores$dropped)
  }

  list(results = predictions, dropped = dropped)
}

demo_dashboard_data <- tibble::tribble(
  ~owner_id, ~sample_id, ~plot, ~minerals, ~score_percentile, ~toc, ~co2_burst, ~pmn, ~wsa_mega, ~status,
  "owner-demo", "DEMO-001", "Orchard A", "HAC", 82, 4.8, 112, 78, 68, "Scored",
  "owner-demo", "DEMO-002", "Block 3", "HAC", 74, 4.1, 96, 64, 61, "Scored",
  "owner-demo", "DEMO-003", "Vegetable 1", "LAC", 58, 2.9, 71, 45, 54, "Scored",
  "owner-demo", "DEMO-004", "Tomato 2", "LAC", 43, 2.3, 49, 38, 47, "Scored",
  "owner-demo", "DEMO-005", "Pasture 7", "PNCM", 67, 3.6, 84, 59, 63, "Scored",
  "owner-demo", "DEMO-006", "Pasture 2", "PNCM", 51, 3.0, 66, 42, 57, "Scored",
  "owner-demo", "DEMO-007", "Agroforest", "HAC", 89, 5.3, 124, 86, 72, "Scored",
  "owner-demo", "DEMO-008", "Field 4", "LAC", 36, 1.8, 38, 27, 41, "Scored",
  "owner-demo", "DEMO-009", "Taro 1", "HIST", NA, 9.4, 134, 92, 38, "Pending Histosol scoring",
  "owner-other", "OTHER-001", "Demo Plot", "LAC", 61, 3.2, 76, 48, 56, "Scored"
) %>%
  mutate(
    score_band = score_band(score_percentile / 100),
    carbon_storage = pmin(100, round((toc / max(toc, na.rm = TRUE)) * 100)),
    biological_activity = pmin(100, round(((co2_burst / max(co2_burst, na.rm = TRUE)) * 0.55 + (pmn / max(pmn, na.rm = TRUE)) * 0.45) * 100)),
    physical_structure = pmin(100, round((wsa_mega / max(wsa_mega, na.rm = TRUE)) * 100))
  )

demo_owner_credentials <- tibble::tribble(
  ~username, ~password, ~owner_id, ~display_name,
  "owner@example.org", "demo-only", "owner-demo", "Demo Data Owner"
)

model_bundle <- load_or_build_model_bundle()
live_model_bundle <- load_live_model_bundle()

ui <- fluidPage(
  tags$head(
    tags$title("Hawaii Soil Health Portal"),
    tags$style(HTML(paste0("
      body { background: #f7f7f4; color: #1f2a24; }
      .container-fluid { max-width: 1180px; }
      .page-title { margin: 22px 0 6px; font-weight: 700; }
      .site-header { display: flex; align-items: center; gap: 16px; margin: 18px 0 8px; }
      .site-logo { width: 76px; height: 76px; object-fit: cover; border-radius: 50%; border: 1px solid #d9ded8; }
      .site-header .page-title { margin: 0 0 3px; }
      .site-subtitle { color: #526158; margin: 0; }
      .intro { max-width: 1000px; font-size: 1.16rem; line-height: 1.62; }
      .intro p { margin-bottom: 8px; }
      .panel { background: #ffffff; border: 1px solid #d9ded8; border-radius: 6px; padding: 16px; margin: 14px 0; }
      .dashboard-grid { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 10px; margin: 14px 0; }
      .metric-card { background: #ffffff; border: 1px solid #d9ded8; border-radius: 6px; padding: 13px 14px; min-height: 98px; }
      .metric-label { color: #5a665e; font-size: 0.86rem; text-transform: uppercase; letter-spacing: 0; }
      .metric-value { color: #19251e; font-size: 2.05rem; font-weight: 700; line-height: 1.05; margin-top: 6px; }
      .metric-note { color: #5a665e; font-size: 0.92rem; margin-top: 4px; }
      .demo-ribbon { display: inline-block; background: #e8f0e4; border: 1px solid #c8d6c2; border-radius: 4px; padding: 4px 8px; font-weight: 600; color: #2d442f; margin-bottom: 8px; }
      .login-box { max-width: 460px; }
      .owner-pref-grid { display: grid; grid-template-columns: minmax(240px, 1fr) minmax(240px, 1fr); gap: 14px; }
      .preference-summary { background: #eef3ec; border: 1px solid #c8d6c2; border-radius: 4px; padding: 10px 12px; color: #26382b; }
      .band-legend { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 10px 0 4px; width: 100%; }
      .band { border-radius: 4px; padding: 9px 10px; font-weight: 600; color: #18221d; }
      .band-low { background: #e57373; }
      .band-ml { background: #ffb74d; }
      .band-mh { background: #fff176; }
      .band-high { background: #81c784; }
      .status { color: #4b5b51; font-size: 0.95rem; }
      .error-code { font-family: monospace; background: #f4dddd; padding: 8px; border-radius: 4px; }
      .about-lead { max-width: 980px; font-size: 1.28rem; line-height: 1.68; color: #34443a; }
      .team-heading { margin: 26px 0 4px; }
      .team-note { color: #5a665e; margin-bottom: 14px; }
      .people-grid { display: grid; grid-template-columns: repeat(2, minmax(260px, 1fr)); gap: 12px; }
      .person-card { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 14px; align-items: start; background: #ffffff; border: 1px solid #d9ded8; border-radius: 6px; padding: 15px; min-height: 190px; }
      .person-photo, .person-avatar { width: 88px; height: 88px; border-radius: 50%; border: 1px solid #cbd3cd; }
      .person-photo { object-fit: cover; background: #edf1ed; }
      .person-avatar { display: flex; align-items: center; justify-content: center; color: #ffffff; font-size: 1.35rem; font-weight: 700; background: #496b55; }
      .avatar-earth { background: #87633f; }
      .avatar-blue { background: #42687a; }
      .avatar-gold { background: #8a702b; }
      .avatar-plum { background: #73576e; }
      .person-name { font-size: 1.12rem; font-weight: 700; margin: 1px 0 2px; }
      .person-role { color: #376246; font-weight: 600; margin-bottom: 7px; }
      .person-bio { color: #48564d; line-height: 1.45; margin: 0; }
      .nav-tabs { display: flex; flex-wrap: wrap; }
      .nav-tabs > li { float: none; }
      .nav-tabs > li:has(a[data-value='ftir']) { order: 1; }
      .nav-tabs > li:has(a[data-value='lab']) { order: 2; }
      .nav-tabs > li:has(a[data-value='resources']) { order: 3; }
      .nav-tabs > li:has(a[data-value='about']) { order: 4; }
      .nav-tabs > li:has(a[data-value='demo_dashboard']) { order: 5; }
      .nav-tabs > li:has(a[data-value='owner_portal']) { order: 6; }
      .nav-tabs > li > a[data-value='demo_dashboard'],
      .nav-tabs > li > a[data-value='owner_portal'] {
        pointer-events: none;
        color: #8b928e;
        background: #eceeed;
        border-color: #d8dcda;
        cursor: not-allowed;
        opacity: 0.82;
      }
      .coming-soon-label { margin-left: 5px; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; color: #737b77; }
      .resource-list { display: grid; grid-template-columns: repeat(2, minmax(260px, 1fr)); gap: 12px; margin-top: 14px; }
      .resource-card { background: #ffffff; border: 1px solid #d9ded8; border-radius: 6px; padding: 16px; min-height: 170px; }
      .resource-card h3 { margin: 0 0 8px; font-size: 1.12rem; }
      .resource-card p { color: #4b5b51; line-height: 1.5; min-height: 66px; }
      .resource-link { color: #294f36; font-weight: 600; }
      .resource-link:hover, .resource-link:focus { color: #183c25; }
      ",
      if (preview_tabs_enabled) "
      .nav-tabs > li > a[data-value='demo_dashboard'],
      .nav-tabs > li > a[data-value='owner_portal'] {
        pointer-events: auto;
        color: #294f36;
        background: transparent;
        border-color: transparent;
        cursor: pointer;
        opacity: 1;
      }
      " else "",
      "
      @media (max-width: 900px) { .dashboard-grid { grid-template-columns: repeat(2, minmax(150px, 1fr)); } }
      @media (max-width: 700px) {
        .owner-pref-grid, .people-grid, .resource-list { grid-template-columns: 1fr; }
      }
      @media (max-width: 560px) {
        .dashboard-grid, .band-legend { grid-template-columns: 1fr; }
        .site-header { align-items: flex-start; }
        .site-logo { width: 58px; height: 58px; }
        .person-card { grid-template-columns: 68px minmax(0, 1fr); gap: 11px; }
        .person-photo, .person-avatar { width: 64px; height: 64px; }
      }
    ")))
    ,
    if (!preview_tabs_enabled) tags$script(HTML("
      $(document).on('click keydown', \"a[data-value='demo_dashboard'], a[data-value='owner_portal']\", function(event) {
        event.preventDefault();
        event.stopImmediatePropagation();
      });
      $(function() {
        $(\"a[data-value='demo_dashboard'], a[data-value='owner_portal']\")
          .attr('aria-disabled', 'true')
          .attr('tabindex', '-1')
          .attr('title', 'Coming soon');
      });
    ")) else NULL
  ),
  div(
    class = "site-header",
    tags$img(src = "soil_logo.jpg", alt = "Hawaii Soil Health Portal", class = "site-logo"),
    div(
      h1("Hawaii Soil Health Portal", class = "page-title"),
      p("Scoring tools, summarized reporting, and data-provider access", class = "site-subtitle")
    )
  ),
  div(
    class = "intro",
    p("Soil health is a soil's capacity to support plants, cycle nutrients, store water and carbon, and remain resilient. Understanding these functions is especially important in Hawaii, where soils, climates, crops, and management systems vary greatly across short distances."),
    p("Use this portal to estimate soil indicators and soil-health scores from raw FTIR spectra, or use the laboratory indicator workflow. Scores are interpreted relative to the reference database bundled with this application.")
  ),
  tabsetPanel(
    selected = "ftir",
    tabPanel(
      title = tagList(
        icon("clock"),
        " Data Dashboard",
        tags$span("Coming soon", class = "coming-soon-label")
      ),
      value = "demo_dashboard",
      div(
        class = "panel",
        span("Demo placeholders", class = "demo-ribbon"),
        h3("Farm Soil Health Summary"),
        p("This dashboard is populated with placeholder values for demonstration. It shows summarized, non-location-specific soil-health patterns only. Granular sample records belong in the login-gated data owner portal.")
      ),
      div(
        class = "dashboard-grid",
        div(class = "metric-card",
          div(class = "metric-label", "Records scored"),
          div(class = "metric-value", textOutput("demo_samples_scored", inline = TRUE)),
          div(class = "metric-note", "1 pending or excluded")
        ),
        div(class = "metric-card",
          div(class = "metric-label", "Median SHS"),
          div(class = "metric-value", textOutput("demo_median_shs", inline = TRUE)),
          div(class = "metric-note", "Percentile of reference database")
        ),
        div(class = "metric-card",
          div(class = "metric-label", "High-scoring records"),
          div(class = "metric-value", textOutput("demo_high_count", inline = TRUE)),
          div(class = "metric-note", "Moderate-high or High")
        ),
        div(class = "metric-card",
          div(class = "metric-label", "Primary constraint"),
          div(class = "metric-value", textOutput("demo_constraint", inline = TRUE)),
          div(class = "metric-note", "Lowest indicator group")
        )
      ),
      fluidRow(
        column(
          width = 7,
          div(
            class = "panel",
            h3("Score Band Summary"),
            plotOutput("demo_score_distribution", height = 275)
          )
        ),
        column(
          width = 5,
          div(
            class = "panel",
            h3("Indicator Group Snapshot"),
            plotOutput("demo_indicator_snapshot", height = 275)
          )
        )
      )
    ),
    tabPanel(
      title = tagList(
        icon("lock"),
        " Data owner portal",
        tags$span("Coming soon", class = "coming-soon-label")
      ),
      value = "owner_portal",
      uiOutput("owner_login_panel"),
      uiOutput("owner_portal_panel")
    ),
    tabPanel(
      "Lab indicators",
      value = "lab",
      fluidRow(
        column(
          width = 4,
          div(
            class = "panel",
            h3("Upload"),
            downloadButton("template", "Download live CSV template"),
            br(), br(),
            checkboxInput(
              "consent",
              "I understand uploaded data may be stored in server logs or temporary files for tool operation, troubleshooting, and maintenance.",
              value = FALSE
            ),
            fileInput("upload", "CSV file", accept = c(".csv", "text/csv")),
            actionButton("score", "Score samples", class = "btn-primary"),
            br(), br(),
            div(textOutput("status"), class = "status")
          ),
          div(
            class = "panel",
            h3("Score Bands"),
            div(class = "band-legend",
              div(class = "band band-low", "Low: 0-24%"),
              div(class = "band band-ml", "Moderate-low: 25-49%"),
              div(class = "band band-mh", "Moderate-high: 50-74%"),
              div(class = "band band-high", "High: 75-100%")
            )
          ),
          div(
            class = "panel",
            h3("Live Input"),
            p("The minimum scoring input is a sample ID, mineral class, and nine indicators: toc, co2_burst, ph, beta_glucosidase, beta_glucosaminidase, pmn, whc, hwec, and wsa_mega. Additional master-database columns are accepted and ignored when they are not needed. plot_name, PIAL_none, and bd are optional. Sample IDs may be supplied as sample_id, SH_1, HSH_id, or Intake_number.")
          )
        ),
        column(
          width = 8,
          div(
            class = "panel",
            h3("Results"),
            uiOutput("error_box"),
            plotOutput("score_plot", height = 260),
            tabsetPanel(
              tabPanel(
                "Scores",
                if (has_dt) DT::DTOutput("results_table") else tableOutput("results_table")
              ),
              tabPanel(
                "Core Dataset",
                if (has_dt) DT::DTOutput("core_results_table") else tableOutput("core_results_table")
              )
            ),
            br(),
            downloadButton("download_results", "Download scored results")
          ),
          div(
            class = "panel",
            h3("Dropped Samples"),
            if (has_dt) DT::DTOutput("dropped_table") else tableOutput("dropped_table")
          )
        )
      )
    ),
    tabPanel(
      "FTIR spectroscopy",
      value = "ftir",
      fluidRow(
        column(
          width = 4,
          div(
            class = "panel",
            h3("Upload Spectra"),
            radioButtons(
              "ftir_upload_mode",
              "Upload type",
              choices = c(
                "Spectra CSV" = "csv",
                "Raw OPUS files" = "opus"
              ),
              selected = "csv",
              inline = TRUE
            ),
            conditionalPanel(
              condition = "input.ftir_upload_mode == 'csv'",
              downloadButton("ftir_template", "Download wide CSV template"),
              downloadButton("ftir_long_template", "Download long CSV template"),
              br(), br(),
              fileInput(
                "ftir_csv_upload",
                "Raw absorbance CSV",
                accept = c(".csv", "text/csv"),
                multiple = FALSE
              )
            ),
            conditionalPanel(
              condition = "input.ftir_upload_mode == 'opus'",
              downloadButton("opus_manifest_template", "Download OPUS manifest template"),
              br(), br(),
              fileInput(
                "opus_upload",
                "Raw OPUS replicate files",
                accept = c(".0", ".opus"),
                multiple = TRUE
              ),
              fileInput(
                "opus_manifest",
                "OPUS manifest CSV",
                accept = c(".csv", "text/csv")
              )
            ),
            checkboxInput(
              "ftir_consent",
              "I understand uploaded spectra may be stored in server logs or temporary files for tool operation, troubleshooting, and maintenance.",
              value = FALSE
            ),
            actionButton("score_ftir", "Score spectra", class = "btn-primary"),
            br(), br(),
            div(textOutput("ftir_status"), class = "status")
          ),
          div(
            class = "panel",
            h3("Expected Format"),
            p("Upload either one raw absorbance CSV or one or more Bruker OPUS replicate files with .0 or .opus extensions. CSVs may be wide format with one row per sample and numeric wavenumber columns, or long format with sample_id, wavenumber, and absorbance columns. Spectra must cover 4000 to at least 620 cm-1 at 2 cm-1 spacing; wider ranges such as 4000 to 400 are accepted and cropped internally. OPUS uploads require a manifest CSV with file_name and sample_id; replicates are grouped and averaged by manifest sample_id before scoring.")
          )
        ),
        column(
          width = 8,
          div(
            class = "panel",
            h3("Spectroscopy Results"),
            uiOutput("ftir_error_box"),
            plotOutput("ftir_score_plot", height = 260),
            if (has_dt) DT::DTOutput("ftir_results_table") else tableOutput("ftir_results_table"),
            br(),
            downloadButton("download_ftir_results", "Download spectroscopy results")
          ),
          div(
            class = "panel",
            h3("Dropped Spectra"),
            if (has_dt) DT::DTOutput("ftir_dropped_table") else tableOutput("ftir_dropped_table")
          )
        )
      )
    ),
    tabPanel(
      "About Us",
      value = "about",
      div(
        class = "panel",
        h2("About the Hawaii Soil Health Portal"),
        p(
          class = "about-lead",
          "These tools were built to make soil health assessment more accessible to farmers, land managers, and researchers. Soil health describes a soil's capacity to function as a living ecosystem that supports plants, cycles nutrients, stores water and carbon, and remains resilient under changing conditions. In Hawaii, understanding these functions is especially important because the islands contain highly diverse soils, climates, crops, and management systems within a limited land base. The portal brings together field and laboratory methods, soil-health scoring, spectroscopy, data stewardship, and web development to support practical soil management across Hawaii."
        )
      ),
      h3("Web Team", class = "team-heading"),
      p(
        "Current and foundational contributors to the application, website, and supporting data systems.",
        class = "team-note"
      ),
      div(
        class = "people-grid",
        div(
          class = "person-card",
          div("TM", class = "person-avatar"),
          div(
            div("Dr. Tai Maaz", class = "person-name"),
            div("Professor of Soil Science and project leadership", class = "person-role"),
            p(
              "A professor in UH Manoa's Department of Tropical Plant and Soil Sciences, she leads research on soil fertility, nutrient cycling, crop productivity, and practical soil-health assessment. Her graduate research at Washington State University examined crop nitrogen uptake and nitrogen-use efficiency. She provides scientific leadership for the Hawaii Soil Health Project and guides how its research becomes useful tools and extension resources.",
              class = "person-bio"
            )
          )
        ),
        div(
          class = "person-card",
          tags$img(
            src = "christian_fullmer.png",
            alt = "Christian Sanoja Fullmer",
            class = "person-photo"
          ),
          div(
            div("Christian Sanoja Fullmer", class = "person-name"),
            div("Staff Data Analyst and portal developer", class = "person-role"),
            p(
              "A staff data analyst with an M.S. in Soil Science, he builds and manages the current portal and supports the project's data systems, reporting, bioinformatics, and reproducible analyses. He is passionate about data science, science communication, reproducibility, and creating practical tools that serve farmers. In his free time, he is starting a farm cooperative with friends on the North Shore of Oahu.",
              class = "person-bio"
            )
          )
        ),
        div(
          class = "person-card",
          tags$img(
            src = "trevell_pruitt.png",
            alt = "Trevell Pruitt",
            class = "person-photo"
          ),
          div(
            div("Trevell Pruitt", class = "person-name"),
            div("UH Manoa Computer Science student", class = "person-role"),
            p(
              "Develops the portal's aggregate-data dashboard and is helping design data-provider access, privacy controls, consent preferences, and security safeguards for more granular records.",
              class = "person-bio"
            )
          )
        ),
        div(
          class = "person-card",
          div("JG", class = "person-avatar avatar-blue"),
          div(
            div("Joe Gan", class = "person-name"),
            div("UH Manoa Computer Science graduate student", class = "person-role"),
            p(
              "Built the first version of the soil health Shiny application, establishing the upload, scoring, results, and download workflow that the current portal expands.",
              class = "person-bio"
            )
          )
        )
      ),
      h3("Alumni & Contributors", class = "team-heading"),
      p(
        "Researchers and staff whose field, laboratory, analytical, and extension work supports the broader soil health project.",
        class = "team-note"
      ),
      div(
        class = "people-grid",
        div(
          class = "person-card",
          div("CT", class = "person-avatar avatar-earth"),
          div(
            div("Christine Tallamy", class = "person-name"),
            div("Laboratory and field data quality", class = "person-role"),
            p(
              "As the Crow Lab manager, supported consistent field operations, laboratory workflows, and quality assurance for the data underlying the soil health project.",
              class = "person-bio"
            )
          )
        ),
        div(
          class = "person-card",
          div("TB", class = "person-avatar avatar-gold"),
          div(
            div("Dr. Tanner Beckstrom", class = "person-name"),
            div("Soil scientist and FTIR researcher", class = "person-role"),
            p(
              "Recently completed a Ph.D. in Soil Science through UH Manoa's Department of Natural Resources and Environmental Management. He led FTIR prediction research connecting raw mid-infrared spectra with soil indicators and soil health scores, including the modeling foundation used by the portal's spectroscopy workflow.",
              class = "person-bio"
            )
          )
        ),
        div(
          class = "person-card",
          div("AB", class = "person-avatar avatar-plum"),
          div(
            div("Arianna Bunnell", class = "person-name"),
            div("Computer Science Ph.D. candidate and contributor", class = "person-role"),
            p(
              "A UH Manoa Computer Science Ph.D. candidate whose research focuses on interpretable deep learning and responsible artificial intelligence. She contributed computing and data-science expertise to the broader Hawaii soil health assessment effort. ",
              tags$a(
                "View professional portfolio",
                href = "https://aribunnell.github.io/",
                target = "_blank",
                rel = "noopener noreferrer"
              ),
              class = "person-bio"
            )
          )
        ),
        div(
          class = "person-card",
          div("JC", class = "person-avatar avatar-blue"),
          div(
            div("Jubin Choi", class = "person-name"),
            div("Data and research contributor", class = "person-role"),
            p(
              "Supported project data, analysis, and operational workflows that helped move soil health measurements toward consistent scoring and reporting.",
              class = "person-bio"
            )
          )
        ),
        div(
          class = "person-card",
          div("SC", class = "person-avatar avatar-earth"),
          div(
            div("Dr. Susan Crow", class = "person-name"),
            div("Soil carbon and ecosystem science", class = "person-role"),
            p(
              "Provided scientific leadership and research contributions linking soil health assessment with soil carbon, ecosystem function, and sustainable land management in Hawaii.",
              class = "person-bio"
            )
          )
        ),
        div(
          class = "person-card",
          div("JD", class = "person-avatar avatar-gold"),
          div(
            div("Dr. Jonathan Deenik", class = "person-name"),
            div("Soil fertility and extension", class = "person-role"),
            p(
              "Contributed soil science and extension expertise, helping connect soil health indicators and interpretation with the practical needs of farmers and land managers.",
              class = "person-bio"
            )
          )
        )
      )
    ),
    tabPanel(
      "Resources",
      value = "resources",
      div(
        class = "panel",
        h2("Soil Health Resources"),
        p(
          class = "about-lead",
          "Extension materials, publications, and supporting information for interpreting soil properties and applying soil-health assessment in Hawaii."
        ),
        div(
          class = "resource-list",
          div(
            class = "resource-card",
            h3("CTAHR Hawaii Soils"),
            p("Extension information about Hawaii's soils, soil properties, management, and related educational materials for growers and land managers."),
            tags$a(
              icon("external-link-alt"),
              " Visit Hawaii Soils resources",
              href = "https://www.ctahr.hawaii.edu/site/extsl.aspx",
              target = "_blank",
              rel = "noopener noreferrer",
              class = "resource-link"
            )
          ),
          div(
            class = "resource-card",
            h3("CTAHR Publications"),
            p("Search extension bulletins and technical publications covering soil and crop management, nutrient management, production practices, and other agricultural topics."),
            tags$a(
              icon("book"),
              " Search CTAHR publications",
              href = "https://www.ctahr.hawaii.edu/site/PubList.aspx?key=Soil+and+Crop+Management",
              target = "_blank",
              rel = "noopener noreferrer",
              class = "resource-link"
            )
          ),
          div(
            class = "resource-card",
            h3("Agricultural Diagnostic Service Center"),
            p("ADSC provides soil nutrient and plant tissue analysis, plant disease diagnostics, insect identification, and other testing services for Hawaii's farmers and agricultural professionals."),
            tags$a(
              icon("flask"),
              " Visit ADSC services",
              href = "https://cms.ctahr.hawaii.edu/adsc/Services",
              target = "_blank",
              rel = "noopener noreferrer",
              class = "resource-link"
            )
          ),
          div(
            class = "resource-card",
            h3("GoFarm Hawaii"),
            p("GoFarm Hawaii offers hands-on beginning-farmer training, agribusiness support, workshops, and practical resources for new and established agricultural producers."),
            tags$a(
              icon("seedling"),
              " Visit GoFarm Hawaii",
              href = "https://gofarmhawaii.org/",
              target = "_blank",
              rel = "noopener noreferrer",
              class = "resource-link"
            )
          )
        )
      )
    )
  )
)

server <- function(input, output, session) {
  scored <- reactiveVal(NULL)
  last_error <- reactiveVal(NULL)
  ftir_scored <- reactiveVal(NULL)
  ftir_last_error <- reactiveVal(NULL)
  owner_session <- reactiveVal(NULL)
  owner_login_error <- reactiveVal(NULL)
  owner_preferences_saved <- reactiveVal(FALSE)

  active_ftir_upload <- reactive({
    if (identical(input$ftir_upload_mode, "opus")) {
      input$opus_upload
    } else {
      input$ftir_csv_upload
    }
  })

  observeEvent(input$ftir_upload_mode, {
    ftir_scored(NULL)
    ftir_last_error(NULL)
  }, ignoreInit = TRUE)

  output$demo_samples_scored <- renderText({
    sum(demo_dashboard_data$status == "Scored")
  })

  output$demo_median_shs <- renderText({
    paste0(round(median(demo_dashboard_data$score_percentile, na.rm = TRUE)), "%")
  })

  output$demo_high_count <- renderText({
    sum(demo_dashboard_data$score_percentile >= 50, na.rm = TRUE)
  })

  output$demo_constraint <- renderText({
    group_means <- demo_dashboard_data %>%
      summarise(
        Carbon = mean(carbon_storage, na.rm = TRUE),
        Biology = mean(biological_activity, na.rm = TRUE),
        Structure = mean(physical_structure, na.rm = TRUE)
      )
    names(group_means)[which.min(as.numeric(group_means[1, ]))]
  })

  output$demo_score_distribution <- renderPlot({
    levels <- c("Low", "Moderate-low", "Moderate-high", "High")
    counts <- table(factor(demo_dashboard_data$score_band, levels = levels))
    barplot(
      counts,
      col = c("#e57373", "#ffb74d", "#fff176", "#81c784"),
      border = NA,
      ylab = "Records",
      las = 2
    )
  })

  output$demo_indicator_snapshot <- renderPlot({
    values <- c(
      "Carbon storage" = mean(demo_dashboard_data$carbon_storage, na.rm = TRUE),
      "Biological activity" = mean(demo_dashboard_data$biological_activity, na.rm = TRUE),
      "Physical structure" = mean(demo_dashboard_data$physical_structure, na.rm = TRUE)
    )
    barplot(
      values,
      horiz = TRUE,
      xlim = c(0, 100),
      col = c("#5b8c5a", "#4f7cac", "#c17c3a"),
      border = NA,
      xlab = "Demo relative index",
      las = 1
    )
  })

  output$owner_login_panel <- renderUI({
    if (!is.null(owner_session())) {
      return(NULL)
    }
    div(
      class = "panel login-box",
      span("Demo login wall", class = "demo-ribbon"),
      h3("Data Owner Login"),
      p("Data tables and data-use preferences are separated from the public dashboard. This demo uses a local placeholder login only; production deployment needs real authentication, authorization, audit logging, and encrypted storage."),
      textInput("owner_username", "Email", value = "owner@example.org"),
      passwordInput("owner_password", "Password", value = "demo-only"),
      actionButton("owner_login", "Sign in", class = "btn-primary"),
      br(), br(),
      uiOutput("owner_login_error")
    )
  })

  output$owner_login_error <- renderUI({
    msg <- owner_login_error()
    if (is.null(msg)) return(NULL)
    div(class = "error-code", msg)
  })

  observeEvent(input$owner_login, {
    owner_login_error(NULL)
    match <- demo_owner_credentials %>%
      filter(username == input$owner_username, password == input$owner_password)
    if (nrow(match) != 1) {
      owner_login_error("Invalid demo login.")
      return()
    }
    owner_session(as.list(match[1, ]))
    owner_preferences_saved(FALSE)
  })

  observeEvent(input$owner_logout, {
    owner_session(NULL)
    owner_login_error(NULL)
    owner_preferences_saved(FALSE)
  })

  owner_data <- reactive({
    req(owner_session())
    demo_dashboard_data %>%
      filter(owner_id == owner_session()$owner_id) %>%
      transmute(
        sample_id,
        plot,
        minerals,
        score_percentile,
        score_band,
        toc,
        co2_burst,
        pmn,
        wsa_mega,
        status
      )
  })

  output$owner_portal_panel <- renderUI({
    session_info <- owner_session()
    if (is.null(session_info)) {
      return(NULL)
    }
    tagList(
      div(
        class = "panel",
        span("Owner-scoped demo", class = "demo-ribbon"),
        h3(paste("Welcome,", session_info$display_name)),
        p("Only records assigned to this data owner are shown here. The preferences below are placeholders for the consent and governance workflow."),
        actionButton("owner_logout", "Sign out")
      ),
      fluidRow(
        column(
          width = 5,
          div(
            class = "panel",
            h3("Data Use Preferences"),
            radioButtons(
              "research_permission",
              "Research use permission",
              choices = c(
                "Allow approved de-identified HSH research use" = "allow_approved",
                "Ask before each new research project" = "ask_project",
                "Ask every time for every use" = "ask_every_time",
                "Revoke research use permission" = "revoke"
              ),
              selected = "ask_project"
            ),
            checkboxGroupInput(
              "allowed_data_types",
              "Data types allowed for approved use",
              choices = c(
                "Lab indicator results" = "lab_indicators",
                "FTIR spectra and FTIR predictions" = "ftir",
                "Management notes or survey responses" = "management_notes",
                "De-identified aggregate summaries" = "aggregate_summaries"
              ),
              selected = c("lab_indicators", "aggregate_summaries")
            ),
            radioButtons(
              "contact_preference",
              "Questions about data interpretation",
              choices = c(
                "You may contact me with research questions" = "may_contact",
                "Contact me only when required for a specific use" = "limited_contact",
                "Do not contact me for follow-up questions" = "no_contact"
              ),
              selected = "limited_contact"
            ),
            checkboxInput(
              "ask_external_use",
              "Ask before external collaborators use my data, even when de-identified.",
              value = TRUE
            ),
            actionButton("save_owner_preferences", "Save preferences", class = "btn-primary"),
            br(), br(),
            uiOutput("owner_preference_status")
          )
        ),
        column(
          width = 7,
          div(
            class = "panel",
            h3("My Data Table"),
            if (has_dt) DT::DTOutput("owner_data_table") else tableOutput("owner_data_table")
          )
        )
      )
    )
  })

  observeEvent(input$save_owner_preferences, {
    req(owner_session())
    owner_preferences_saved(TRUE)
  })

  output$owner_preference_status <- renderUI({
    req(owner_session())
    if (!isTRUE(owner_preferences_saved())) {
      return(div(class = "status", "Preferences are editable in this demo session."))
    }
    div(
      class = "preference-summary",
      strong("Saved for demo session."),
      br(),
      "Research permission: ", input$research_permission,
      br(),
      "Allowed data types: ", paste(input$allowed_data_types, collapse = ", "),
      br(),
      "Contact preference: ", input$contact_preference,
      br(),
      "External collaborator review: ", ifelse(isTRUE(input$ask_external_use), "required", "not required")
    )
  })

  if (has_dt) {
    output$owner_data_table <- DT::renderDT({
      req(owner_session())
      DT::datatable(owner_data(), options = list(pageLength = 8, scrollX = TRUE), rownames = FALSE)
    })
  } else {
    output$owner_data_table <- renderTable({
      req(owner_session())
      owner_data()
    })
  }

  output$template <- downloadHandler(
    filename = function() "hawaii_soil_health_template.csv",
    content = function(file) {
      template <- tibble::tibble(
        sample_id = character(),
        plot_name = character(),
        toc = numeric(),
        co2_burst = numeric(),
        ph = numeric(),
        beta_glucosidase = numeric(),
        beta_glucosaminidase = numeric(),
        pmn = numeric(),
        whc = numeric(),
        hwec = numeric(),
        wsa_mega = numeric(),
        bd = numeric(),
        minerals = character(),
        pial_none = character()
      )
      readr::write_csv(template, file)
    }
  )

  output$ftir_template <- downloadHandler(
    filename = function() "hawaii_soil_health_ftir_template.csv",
    content = function(file) {
      template <- tibble::as_tibble(setNames(rep(list(numeric()), length(ftir_raw_template_columns())), ftir_raw_template_columns())) %>%
        mutate(sample_id = character(), minerals = character(), .before = 1)
      readr::write_csv(template, file)
    }
  )

  output$ftir_long_template <- downloadHandler(
    filename = function() "hawaii_soil_health_ftir_long_template.csv",
    content = function(file) {
      template <- tibble::tibble(
        sample_id = c("example-1", "example-1", "example-1"),
        wavenumber = c(4000, 3998, 3996),
        absorbance = c(NA_real_, NA_real_, NA_real_),
        minerals = c("HAC", "HAC", "HAC")
      )
      readr::write_csv(template, file)
    }
  )

  output$opus_manifest_template <- downloadHandler(
    filename = function() "hawaii_soil_health_opus_manifest_template.csv",
    content = function(file) {
      template <- tibble::tibble(
        file_name = c(
          "Soil_PLATE-003_2019-158_A2.0",
          "Soil_PLATE-003_2019-158_B2.0",
          "Soil_PLATE-003_2019-158_C2.0",
          "Soil_PLATE-003_2019-158_D2.0"
        ),
        sample_id = rep("2019-158", 4),
        replicate_id = c("A2", "B2", "C2", "D2"),
        minerals = rep("", 4)
      )
      readr::write_csv(template, file)
    }
  )

  output$status <- renderText({
    req(input$upload)
    if (!isTRUE(input$consent)) {
      "Consent is required before scoring."
    } else if (is.null(scored())) {
      "Ready to score uploaded data."
    } else {
      paste0("Scored ", nrow(scored()$results), " sample(s); dropped ", nrow(scored()$dropped), ".")
    }
  })

  output$ftir_status <- renderText({
    req(active_ftir_upload())
    if (!isTRUE(input$ftir_consent)) {
      "Consent is required before scoring spectra."
    } else if (is.null(ftir_scored())) {
      if (identical(input$ftir_upload_mode, "opus")) {
        if (is.null(input$opus_manifest)) {
          "Add the OPUS manifest before scoring."
        } else {
          paste0("Ready to score ", nrow(active_ftir_upload()), " OPUS file(s).")
        }
      } else {
        "Ready to score the uploaded spectra CSV."
      }
    } else {
      paste0("Scored ", nrow(ftir_scored()$results), " spectrum/spectra; dropped ", nrow(ftir_scored()$dropped), ".")
    }
  })

  observeEvent(input$score, {
    last_error(NULL)
    scored(NULL)
    req(input$upload)

    if (!isTRUE(input$consent)) {
      last_error(list(code = "CONSENT-REQUIRED", message = "Please confirm consent before using the tool."))
      return()
    }

    tryCatch(
      {
        withProgress(message = "Scoring samples", value = 0, {
          incProgress(0.25, detail = "Reading uploaded CSV")
          uploaded <- prepare_live_upload(input$upload$datapath)
          incProgress(0.35, detail = "Validating and transforming indicators")
          result <- score_live_samples(uploaded, live_model_bundle)
          incProgress(0.30, detail = "Preparing results")
          scored(result)
          incProgress(0.10, detail = "Done")
        })
      },
      error = function(err) {
        error_id <- paste0("HSH-", format(Sys.time(), "%Y%m%d-%H%M%S"), "-", sample(1000:9999, 1))
        log_error(error_id, err)
        last_error(list(code = error_id, message = conditionMessage(err)))
      }
    )
  })

  observeEvent(input$score_ftir, {
    ftir_last_error(NULL)
    ftir_scored(NULL)
    upload_info <- active_ftir_upload()
    req(upload_info)

    if (!isTRUE(input$ftir_consent)) {
      ftir_last_error(list(code = "CONSENT-REQUIRED", message = "Please confirm consent before using the spectroscopy tool."))
      return()
    }
    if (identical(input$ftir_upload_mode, "opus") && is.null(input$opus_manifest)) {
      ftir_last_error(list(code = "MANIFEST-REQUIRED", message = "Raw OPUS uploads require an OPUS manifest CSV."))
      return()
    }

    tryCatch(
      {
        withProgress(message = "Scoring spectra", value = 0, {
          incProgress(0.20, detail = "Loading FTIR models")
          incProgress(0.30, detail = "Predicting indicators from spectra")
          manifest_info <- if (identical(input$ftir_upload_mode, "opus")) input$opus_manifest else NULL
          result <- run_ftir_prediction(upload_info, manifest_info, model_bundle)
          incProgress(0.35, detail = "Calculating score percentiles")
          ftir_scored(result)
          incProgress(0.15, detail = "Done")
        })
      },
      error = function(err) {
        error_id <- paste0("FTIR-", format(Sys.time(), "%Y%m%d-%H%M%S"), "-", sample(1000:9999, 1))
        log_error(error_id, err)
        ftir_last_error(list(code = error_id, message = conditionMessage(err)))
      }
    )
  })

  output$error_box <- renderUI({
    err <- last_error()
    if (is.null(err)) return(NULL)
    div(
      class = "error-code",
      strong("Error code: "),
      err$code,
      br(),
      err$message
    )
  })

  output$ftir_error_box <- renderUI({
    err <- ftir_last_error()
    if (is.null(err)) return(NULL)
    div(
      class = "error-code",
      strong("Error code: "),
      err$code,
      br(),
      err$message
    )
  })

  output$score_plot <- renderPlot({
    req(scored())
    results <- scored()$results
    order_index <- order(results$score_percentile)
    colors <- c(
      "Low" = "#e57373",
      "Moderate-low" = "#ffb74d",
      "Moderate-high" = "#fff176",
      "High" = "#81c784"
    )
    barplot(
      results$score_percentile[order_index],
      names.arg = results$sample_id[order_index],
      horiz = TRUE,
      xlim = c(0, 100),
      col = unname(colors[results$score_band[order_index]]),
      border = NA,
      xlab = "Score percentile",
      las = 1
    )
  })

  output$ftir_score_plot <- renderPlot({
    req(ftir_scored())
    results <- ftir_scored()$results
    order_index <- order(results$direct_score_percentile)
    colors <- c(
      "Low" = "#e57373",
      "Moderate-low" = "#ffb74d",
      "Moderate-high" = "#fff176",
      "High" = "#81c784"
    )
    barplot(
      results$direct_score_percentile[order_index],
      names.arg = results$sample_id[order_index],
      horiz = TRUE,
      xlim = c(0, 100),
      col = unname(colors[results$direct_score_band[order_index]]),
      border = NA,
      xlab = "Direct FTIR score percentile",
      las = 1
    )
  })

  if (has_dt) {
    output$results_table <- DT::renderDT({
      req(scored())
      DT::datatable(two_sig_figs(scored()$scores), options = list(pageLength = 10, scrollX = TRUE), rownames = FALSE)
    })
    output$core_results_table <- DT::renderDT({
      req(scored())
      DT::datatable(two_sig_figs(scored()$core), options = list(pageLength = 10, scrollX = TRUE), rownames = FALSE)
    })
    output$dropped_table <- DT::renderDT({
      req(scored())
      DT::datatable(scored()$dropped, options = list(pageLength = 10, scrollX = TRUE), rownames = FALSE)
    })
    output$ftir_results_table <- DT::renderDT({
      req(ftir_scored())
      DT::datatable(two_sig_figs(ftir_scored()$results), options = list(pageLength = 10, scrollX = TRUE), rownames = FALSE)
    })
    output$ftir_dropped_table <- DT::renderDT({
      req(ftir_scored())
      DT::datatable(ftir_scored()$dropped, options = list(pageLength = 10, scrollX = TRUE), rownames = FALSE)
    })
  } else {
    output$results_table <- renderTable({
      req(scored())
      two_sig_figs(scored()$scores)
    })
    output$core_results_table <- renderTable({
      req(scored())
      two_sig_figs(scored()$core)
    })
    output$dropped_table <- renderTable({
      req(scored())
      scored()$dropped
    })
    output$ftir_results_table <- renderTable({
      req(ftir_scored())
      two_sig_figs(ftir_scored()$results)
    })
    output$ftir_dropped_table <- renderTable({
      req(ftir_scored())
      ftir_scored()$dropped
    })
  }

  output$download_results <- downloadHandler(
    filename = function() paste0("hawaii_soil_health_scores_", Sys.Date(), ".csv"),
    content = function(file) {
      req(scored())
      readr::write_csv(two_sig_figs(scored()$results), file)
    }
  )

  output$download_ftir_results <- downloadHandler(
    filename = function() paste0("hawaii_soil_health_ftir_scores_", Sys.Date(), ".csv"),
    content = function(file) {
      req(ftir_scored())
      readr::write_csv(two_sig_figs(ftir_scored()$results), file)
    }
  )
}

shinyApp(ui, server)
