#!/usr/bin/env python3
"""Preprocess raw FTIR spectra and run exported HSH FTIR models."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.signal import savgol_filter


UNIFIED_BUNDLE_FILE = "bundle_unified_ftir_models.joblib"

REGRESSION_MODEL_KEYS = {
    "co2_burst": "gpr_co2_burst_identity_on_regression_pls",
    "toc": "gpr_toc_identity_on_regression_pls",
    "pmn": "gpr_pmn_identity_on_regression_pls",
    "wsa_mega": "gpr_wsa_mega_identity_on_regression_pls",
    "SH": "gpr_SH_identity_on_regression_pls",
}

CLASSIFIER_MODEL_KEYS = {
    "minerals": ("plsr_minerals_snvsg", "rf_minerals_on_minerals_pls"),
    "PIAL": ("plsr_pial_snvsg", "rf_pial_on_pial_pls"),
}

def expected_spectral_columns() -> list[str]:
    high = list(range(3990, 2388, -2))
    low = list(range(2266, 628, -2))
    return [f"X{x}" for x in high + low]


def raw_spectral_numbers() -> list[int]:
    return list(range(4000, 398, -2))


def parse_wavenumber(column: object) -> int | None:
    text = str(column).strip()
    if text.startswith("X"):
        text = text[1:]
    try:
        value = float(text)
    except ValueError:
        return None
    if value.is_integer():
        return int(value)
    return None


def spectral_column_map(columns: list[object]) -> dict[int, object]:
    out: dict[int, object] = {}
    for col in columns:
        wn = parse_wavenumber(col)
        if wn is not None:
            out[wn] = col
    return out


def normalize_metadata_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {}
    for col in df.columns:
        key = str(col).strip().lower().replace("-", "_").replace(" ", "_")
        if key in {"sample_id", "sampleid", "sample", "id", "sh_1"}:
            renamed[col] = "sample_id"
        elif key in {"minerals", "mineral", "mineral_class", "mineralogy"}:
            renamed[col] = "minerals"
        elif key in {"wavenumber", "wave_number", "wn", "cm_1", "cm1"}:
            renamed[col] = "wavenumber"
        elif key in {"absorbance", "abs", "intensity", "signal", "value"}:
            renamed[col] = "absorbance"
    if renamed:
        df = df.rename(columns=renamed)
    return df


def long_to_wide_spectra(df: pd.DataFrame) -> pd.DataFrame:
    if "sample_id" not in df.columns:
        raise ValueError("Long-form FTIR CSV must include a sample_id column.")

    long_df = df.copy()
    long_df["wavenumber"] = pd.to_numeric(long_df["wavenumber"], errors="coerce")
    long_df["absorbance"] = pd.to_numeric(long_df["absorbance"], errors="coerce")
    long_df = long_df.dropna(subset=["sample_id", "wavenumber", "absorbance"])
    long_df["wavenumber"] = long_df["wavenumber"].round().astype(int)
    if long_df.empty:
        raise ValueError("Long-form FTIR CSV has no valid sample_id, wavenumber, absorbance rows.")

    wide = long_df.pivot_table(
        index="sample_id",
        columns="wavenumber",
        values="absorbance",
        aggfunc="mean",
    ).reset_index()
    wide.columns = [str(col) if col != "sample_id" else col for col in wide.columns]

    if "minerals" in long_df.columns:
        minerals = (
            long_df[["sample_id", "minerals"]]
            .dropna(subset=["minerals"])
            .drop_duplicates(subset=["sample_id"])
        )
        wide = wide.merge(minerals, on="sample_id", how="left")
    return wide


def load_model_bundle(model_dir: Path) -> dict[str, object]:
    path = model_dir / UNIFIED_BUNDLE_FILE
    if not path.exists():
        raise FileNotFoundError(f"Missing unified FTIR model bundle: {path}")
    # Bundles exported under NumPy 2.x can reference numpy._core. The
    # production Shiny server currently runs NumPy 1.x, where the same modules
    # live under numpy.core.
    if not hasattr(np, "_core") and hasattr(np, "core"):
        sys.modules.setdefault("numpy._core", np.core)
        for module_name in ["multiarray", "numeric", "overrides", "_dtype_ctypes"]:
            module = getattr(np.core, module_name, None)
            if module is not None:
                sys.modules.setdefault(f"numpy._core.{module_name}", module)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bundle = joblib.load(path)

    missing = [
        key
        for key in ["plsr_regression_snvsg", *REGRESSION_MODEL_KEYS.values()]
        if key not in bundle.get("models", {})
    ]
    if missing:
        raise ValueError("Unified FTIR model bundle is missing model key(s): " + ", ".join(missing))
    if "plsr_regression_snvsg" not in bundle.get("metadata", {}):
        raise ValueError("Unified FTIR model bundle is missing plsr_regression_snvsg metadata.")
    return bundle


def row_snv(x: np.ndarray) -> np.ndarray:
    mean = np.nanmean(x, axis=1, keepdims=True)
    sd = np.nanstd(x, axis=1, ddof=1, keepdims=True)
    sd[sd == 0] = np.nan
    return (x - mean) / sd


def preprocess_raw_spectra(df: pd.DataFrame) -> pd.DataFrame:
    colmap = spectral_column_map(list(df.columns))
    raw_numbers = [
        wn
        for wn in raw_spectral_numbers()
        if wn in colmap
    ]
    required_numbers = [
        wn
        for wn in range(4000, 618, -2)
        if not (2268 <= wn <= 2388)
    ]
    missing_required = [wn for wn in required_numbers if wn not in colmap]

    if missing_required:
        shown = ", ".join(str(wn) for wn in missing_required[:8])
        suffix = "" if len(missing_required) <= 8 else f", ... ({len(missing_required)} total)"
        raise ValueError(
            "Raw FTIR upload must include at least the model-supported spectral "
            "region from 4000 to 620 cm-1 at 2 cm-1 spacing. Wider uploads, "
            "such as 4000 to 400 cm-1, are accepted and cropped internally. "
            f"Missing required wavenumber column(s): {shown}{suffix}. "
            "Columns may be named like 4000 or X4000."
        )

    raw = df[[colmap[wn] for wn in raw_numbers]].apply(pd.to_numeric, errors="coerce")
    required_raw = raw[[colmap[wn] for wn in required_numbers]]
    bad_rows = required_raw.isna().any(axis=1)
    x = raw.to_numpy(dtype=float)
    x_snv = row_snv(x)
    sg = savgol_filter(
        x_snv,
        window_length=11,
        polyorder=2,
        deriv=1,
        delta=1.0,
        axis=1,
        mode="interp",
    )[:, 5:-5]
    sg_numbers = raw_numbers[5:-5]

    keep = [
        i
        for i, wn in enumerate(sg_numbers)
        if wn >= 630 and not (2268 <= wn <= 2388)
    ]
    processed = pd.DataFrame(
        sg[:, keep],
        columns=[f"X{sg_numbers[i]}" for i in keep],
        index=df.index,
    )
    processed.insert(0, "sample_id", df["sample_id"].astype(str).to_numpy())
    if "minerals" in df.columns:
        processed["minerals"] = df["minerals"].astype(str).to_numpy()
    processed["_raw_bad_row"] = bad_rows.to_numpy()
    return processed


def coerce_model_ready_spectra(df: pd.DataFrame) -> pd.DataFrame:
    colmap = spectral_column_map(list(df.columns))
    spectral_cols = expected_spectral_columns()
    missing = [col for col in spectral_cols if int(col[1:]) not in colmap]
    if missing:
        shown = ", ".join(missing[:8])
        suffix = "" if len(missing) <= 8 else f", ... ({len(missing)} total)"
        raise ValueError(f"FTIR upload is missing spectral column(s): {shown}{suffix}")

    spectra = pd.DataFrame(
        {
            col: pd.to_numeric(df[colmap[int(col[1:])]], errors="coerce")
            for col in spectral_cols
        },
        index=df.index,
    )
    out = pd.concat(
        [pd.DataFrame({"sample_id": df["sample_id"].astype(str)}, index=df.index), spectra],
        axis=1,
    )
    if "minerals" in df.columns:
        out["minerals"] = df["minerals"].astype(str)
    out["_raw_bad_row"] = False
    return out


def read_spectra(input_csv: Path) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    df = pd.read_csv(input_csv)
    df.columns = [str(col).strip() for col in df.columns]
    df = normalize_metadata_columns(df)
    if {"wavenumber", "absorbance"}.issubset(df.columns):
        df = long_to_wide_spectra(df)
    if "sample_id" not in df.columns:
        raise ValueError("FTIR upload must include a sample_id column.")

    colmap = spectral_column_map(list(df.columns))
    spectral_cols = expected_spectral_columns()
    has_raw_range = 4000 in colmap and 620 in colmap
    has_exact_model_cols = all(int(col[1:]) in colmap for col in spectral_cols)

    if has_raw_range:
        df = preprocess_raw_spectra(df)
    elif has_exact_model_cols:
        df = coerce_model_ready_spectra(df)
    else:
        raise ValueError(
            "FTIR upload must include raw spectra covering at least 4000 to 620 cm-1, "
            "with wider ranges such as 4000 to 400 cm-1 accepted, "
            "or already processed model-ready columns X3990 through X630."
        )

    df[spectral_cols] = df[spectral_cols].apply(pd.to_numeric, errors="coerce")
    bad_rows = df[spectral_cols].isna().any(axis=1)
    if "_raw_bad_row" in df.columns:
        bad_rows = bad_rows | df["_raw_bad_row"].astype(bool)
    if bad_rows.all():
        raise ValueError("No spectra have complete numeric values across the expected FTIR columns.")

    dropped = df.loc[bad_rows, ["sample_id"]].copy()
    if not dropped.empty:
        dropped["drop_reason"] = "Missing or non-numeric spectral value"

    valid = df.loc[~bad_rows].drop(columns=["_raw_bad_row"], errors="ignore").copy()
    return valid, dropped.to_dict(orient="records")


def predict(input_csv: Path, output_csv: Path, model_dir: Path) -> None:
    bundle = load_model_bundle(model_dir)
    models = bundle["models"]
    metadata = bundle["metadata"]
    df, dropped = read_spectra(input_csv)

    spectral_cols = metadata["plsr_regression_snvsg"]["feature_cols"]
    missing_spectral_cols = [col for col in spectral_cols if col not in df.columns]
    if missing_spectral_cols:
        shown = ", ".join(missing_spectral_cols[:8])
        suffix = "" if len(missing_spectral_cols) <= 8 else f", ... ({len(missing_spectral_cols)} total)"
        raise ValueError(f"FTIR upload is missing model spectral column(s): {shown}{suffix}")

    x = df[spectral_cols].to_numpy(dtype=float)
    regression_scores = models["plsr_regression_snvsg"].transform(x)

    co2_mean, co2_sd = models[REGRESSION_MODEL_KEYS["co2_burst"]].predict(
        regression_scores, return_std=True
    )
    toc_mean, toc_sd = models[REGRESSION_MODEL_KEYS["toc"]].predict(
        regression_scores, return_std=True
    )
    pmn_mean, pmn_sd = models[REGRESSION_MODEL_KEYS["pmn"]].predict(
        regression_scores, return_std=True
    )
    wsa_mean, wsa_sd = models[REGRESSION_MODEL_KEYS["wsa_mega"]].predict(
        regression_scores, return_std=True
    )
    sh_mean, sh_sd = models[REGRESSION_MODEL_KEYS["SH"]].predict(
        regression_scores, return_std=True
    )

    out = pd.DataFrame(
        {
            "sample_id": df["sample_id"].astype(str).to_numpy(),
            "ftir_toc": np.maximum(toc_mean, 0),
            "ftir_toc_sd": toc_sd,
            "ftir_co2_burst": np.maximum(co2_mean, 0),
            "ftir_co2_burst_sd": co2_sd,
            "ftir_pmn": pmn_mean,
            "ftir_pmn_sd": pmn_sd,
            "ftir_wsa_mega": wsa_mean,
            "ftir_wsa_mega_sd": wsa_sd,
            "ftir_direct_SH": sh_mean,
            "ftir_direct_SH_sd": sh_sd,
        }
    )

    if "minerals" in df.columns:
        out["minerals"] = df["minerals"].astype(str).to_numpy()

    for label, (plsr_key, classifier_key) in CLASSIFIER_MODEL_KEYS.items():
        if plsr_key not in models or classifier_key not in models:
            continue
        classifier_feature_cols = metadata[plsr_key]["feature_cols"]
        if not all(col in df.columns for col in classifier_feature_cols):
            continue
        classifier_scores = models[plsr_key].transform(
            df[classifier_feature_cols].to_numpy(dtype=float)
        )
        classifier = models[classifier_key]
        predictions = classifier.predict(classifier_scores)
        out[f"ftir_predicted_{label}"] = predictions
        if hasattr(classifier, "predict_proba"):
            probabilities = classifier.predict_proba(classifier_scores)
            out[f"ftir_predicted_{label}_prob"] = probabilities.max(axis=1)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_csv, index=False)
    if dropped:
        output_csv.with_suffix(".dropped.json").write_text(json.dumps(dropped, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    args = parser.parse_args()
    predict(args.input, args.output, args.model_dir)


if __name__ == "__main__":
    main()
