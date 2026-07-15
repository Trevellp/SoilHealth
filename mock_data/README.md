# Mock Aggregate Data

`aggregate_dashboard_demo.csv` is synthetic and contains no real provider,
sample, project, or location information.

It is intended to exercise:

- reporting-period filters
- broad management categories
- mineral-class summaries
- score and indicator metrics
- missing or unscored observations
- small-group suppression

`display_allowed` is `FALSE` when `sample_count` is below five. Dashboard code
must not render those rows as distinct public groups.

This file is not a schema for granular owner data.
