required <- c(
  "shiny", "dplyr", "lavaan", "MASS", "readr", "tibble", "jsonlite"
)
optional <- c("DT")

required_ok <- setNames(
  vapply(required, requireNamespace, logical(1), quietly = TRUE),
  required
)
optional_ok <- setNames(
  vapply(optional, requireNamespace, logical(1), quietly = TRUE),
  optional
)

print(required_ok)
print(optional_ok)

if (!all(required_ok)) {
  stop(
    "Missing required package(s): ",
    paste(names(required_ok)[!required_ok], collapse = ", "),
    call. = FALSE
  )
}

cat("Required R dependencies are available.\n")
