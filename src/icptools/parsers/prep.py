"""
Parser and loader for sample preparation logs and weight sheets (CSV / Excel).
"""
import re
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd

from ..models import Batch, Sample, SampleMatrix, SampleType

COLUMN_SYNONYMS = {
    "sample_id": [
        "sample id", "sample_id", "sample", "muestra", "id", "identificador", "codigo", "código"
    ],
    "matrix": [
        "matrix", "matriz", "sample matrix", "tipo matriz", "tipo de matriz"
    ],
    "mass": [
        "mass (g)", "mass", "masa (g)", "masa", "peso (g)", "peso", "weight (g)", "weight"
    ],
    "percent_humidity": [
        "% humidity", "humidity (%)", "humidity", "% humedad", "humedad (%)", "humedad", "moisture", "% moisture"
    ],
    "final_volume": [
        "final volume (ml)", "volume (ml)", "volumen (ml)", "vol (ml)", "final volume", "volume", "volumen"
    ],
    "dilution_factor": [
        "dilution factor", "dilution", "factor dilucion", "factor dilución", "dilución", "dilucion", "df"
    ],
    "prep_group": [
        "prep group", "prepgroup", "lote", "batch digestión", "grupo prep", "lote digestión", "digestion batch"
    ],
    "sample_type": [
        "sample type", "type", "tipo", "tipo muestra"
    ],
    "requested_analytes": [
        "requested analytes", "analitos", "analytes", "elements", "elementos"
    ]
}


def parse_sample_prep(
    file_path_or_df: Union[str, Path, pd.DataFrame],
    sheet_name: Union[str, int] = 0
) -> pd.DataFrame:
    """
    Parses a sample preparation sheet (Excel or CSV) into a normalized DataFrame.
    
    Args:
        file_path_or_df: Path to .xlsx/.csv file or an existing DataFrame.
        sheet_name: Sheet index or name if Excel (default: 0).
        
    Returns:
        DataFrame with canonical column names: sample_id, mass, percent_humidity,
        final_volume, dilution_factor, prep_group, matrix, sample_type, requested_analytes.
    """
    if isinstance(file_path_or_df, pd.DataFrame):
        df = file_path_or_df.copy()
    else:
        path = Path(file_path_or_df)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
                df = pd.read_excel(path, sheet_name=sheet_name)
        else:
            # CSV or TSV
            df = pd.read_csv(path, sep=None, engine="python")

    # Map column headers to canonical names
    matched_cols = {}
    for col in df.columns:
        norm_col = str(col).strip().lower()
        for canon, syns in COLUMN_SYNONYMS.items():
            if canon not in matched_cols and norm_col in syns:
                matched_cols[canon] = col
                break

    if "sample_id" not in matched_cols:
        raise ValueError(
            f"No sample identification column found in prep file. "
            f"Columns available: {list(df.columns)}"
        )

    # Build clean DataFrame
    clean_data = []
    for _, row in df.iterrows():
        sid = row[matched_cols["sample_id"]]
        if pd.isna(sid):
            continue
        entry = {"sample_id": str(sid).strip()}

        for canon, orig_col in matched_cols.items():
            if canon == "sample_id":
                continue
            val = row[orig_col]
            if pd.notna(val):
                entry[canon] = val

        clean_data.append(entry)

    return pd.DataFrame(clean_data)


def apply_sample_prep(
    batch: Batch,
    prep_data: Union[str, Path, pd.DataFrame],
    id_column: Optional[str] = None,
    sheet_name: Union[str, int] = 0,
) -> Batch:
    """
    Applies sample preparation parameters (mass, volume, humidity, matrix, dilution, prep group)
    from a preparation sheet (Excel, CSV, or DataFrame) onto matching samples in a Batch.
    
    Args:
        batch: The target Batch instance.
        prep_data: Path to prep file (.xlsx/.csv) or DataFrame.
        id_column: Optional explicit ID column name if prep_data is a custom DataFrame.
        sheet_name: Sheet index or name if Excel.
        
    Returns:
        The updated Batch instance.
    """
    if isinstance(prep_data, pd.DataFrame) and id_column:
        df = prep_data.rename(columns={id_column: "sample_id"})
    else:
        df = parse_sample_prep(prep_data, sheet_name=sheet_name)

    applied_count = 0
    for _, row in df.iterrows():
        sid = str(row["sample_id"]).strip()
        sample = batch.get_sample(sid)
        if sample is None:
            continue

        applied_count += 1

        if "mass" in row and pd.notna(row["mass"]):
            try:
                m_val = float(row["mass"])
                if m_val > 0:
                    sample.mass = m_val
            except (ValueError, TypeError):
                pass

        if "percent_humidity" in row and pd.notna(row["percent_humidity"]):
            try:
                h_val = float(row["percent_humidity"])
                if 0.0 <= h_val < 100.0:
                    sample.percent_humidity = h_val
            except (ValueError, TypeError):
                pass

        if "final_volume" in row and pd.notna(row["final_volume"]):
            try:
                v_val = float(row["final_volume"])
                if v_val > 0:
                    sample.final_volume = v_val
            except (ValueError, TypeError):
                pass

        if "dilution_factor" in row and pd.notna(row["dilution_factor"]):
            try:
                d_val = float(row["dilution_factor"])
                if d_val > 0:
                    sample.dilution_factor = d_val
            except (ValueError, TypeError):
                pass

        if "prep_group" in row and pd.notna(row["prep_group"]):
            sample.prep_group = str(row["prep_group"]).strip()

        if "matrix" in row and pd.notna(row["matrix"]):
            mat_str = str(row["matrix"]).strip().lower()
            if "sol" in mat_str:
                sample.matrix = SampleMatrix.SOLID
            elif "liq" in mat_str:
                sample.matrix = SampleMatrix.LIQUID

        if "sample_type" in row and pd.notna(row["sample_type"]):
            st_str = str(row["sample_type"]).strip().lower()
            if any(term in st_str for term in ("mblk", "blanco met", "blanco dig", "method")):
                sample.sample_type = SampleType.METHOD_BLANK
            elif any(term in st_str for term in ("qc", "crm", "ccv")):
                sample.sample_type = SampleType.QC

        if "requested_analytes" in row and pd.notna(row["requested_analytes"]):
            val = row["requested_analytes"]
            if isinstance(val, list):
                sample.requested_analytes = [str(a).strip() for a in val]
            elif isinstance(val, str):
                sample.requested_analytes = [a.strip() for a in re.split(r"[,;]+", val) if a.strip()]

    return batch
