#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(simplerspec)
  library(opusreader2)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 5 || args[1] != "--manifest" || args[3] != "--output") {
  stop("Usage: opus_to_raw_csv.R --manifest manifest.csv --output output.csv file1.0 file2.0 ...", call. = FALSE)
}

manifest_path <- args[2]
output <- args[4]
files <- args[-c(1, 2, 3, 4)]
missing <- files[!file.exists(files)]
if (length(missing) > 0) {
  stop("Missing OPUS file(s): ", paste(missing, collapse = ", "), call. = FALSE)
}
if (!file.exists(manifest_path)) {
  stop("Missing OPUS manifest: ", manifest_path, call. = FALSE)
}

normalize_names <- function(x) {
  x <- tolower(trimws(x))
  x <- gsub("[^a-z0-9]+", "_", x)
  gsub("^_|_$", "", x)
}

manifest <- read_csv(manifest_path, show_col_types = FALSE, na = c("", "NA", "#N/A"))
names(manifest) <- normalize_names(names(manifest))
if (!all(c("file_name", "sample_id") %in% names(manifest))) {
  stop("OPUS manifest must include file_name and sample_id columns.", call. = FALSE)
}

manifest <- manifest %>%
  transmute(
    file_name = basename(as.character(file_name)),
    sample_id = trimws(as.character(sample_id))
  )

if (any(is.na(manifest$file_name) | manifest$file_name == "") || any(is.na(manifest$sample_id) | manifest$sample_id == "")) {
  stop("OPUS manifest has blank file_name or sample_id values.", call. = FALSE)
}
if (any(duplicated(manifest$file_name))) {
  duplicated_files <- unique(manifest$file_name[duplicated(manifest$file_name)])
  stop("OPUS manifest has duplicate file_name row(s): ", paste(duplicated_files, collapse = ", "), call. = FALSE)
}

uploaded <- tibble::tibble(file_path = files, file_name = basename(files))
missing_manifest <- setdiff(uploaded$file_name, manifest$file_name)
extra_manifest <- setdiff(manifest$file_name, uploaded$file_name)
if (length(missing_manifest) > 0) {
  stop("OPUS file(s) missing from manifest: ", paste(missing_manifest, collapse = ", "), call. = FALSE)
}
if (length(extra_manifest) > 0) {
  stop("Manifest file_name value(s) were not uploaded: ", paste(extra_manifest, collapse = ", "), call. = FALSE)
}

file_map <- uploaded %>%
  left_join(manifest, by = "file_name")

spc_list <- read_opus_univ(fnames = files, extract = c("spc"))

raw <- spc_list %>%
  gather_spc() %>%
  mutate(source_file = basename(files), sample_id = file_map$sample_id) %>%
  resample_spc(wn_lower = 400, wn_upper = 4000, wn_interval = 2)

spc_matrix <- do.call(rbind, raw$spc_rs)
colnames(spc_matrix) <- colnames(raw$spc_rs[[1]])

raw_df <- tibble::as_tibble(spc_matrix) %>%
  mutate(sample_id = raw$sample_id, .before = 1) %>%
  group_by(sample_id) %>%
  summarise(across(everything(), \(x) mean(as.numeric(x), na.rm = TRUE)), .groups = "drop")

write_csv(raw_df, output)
