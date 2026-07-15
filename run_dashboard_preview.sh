#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
Rscript check_dependencies.R

SOIL_HEALTH_ENABLE_PREVIEW_TABS=true \
  Rscript -e "shiny::runApp('app', host='127.0.0.1', port=3838)"
