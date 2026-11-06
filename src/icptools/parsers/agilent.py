import re
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Union
import numpy as np
import pandas as pd

from ..models import Batch, Sample, Analyte, SampleType, SampleMatrix

def _parse_analyte_header(col_str: str):
    """
    Parses column header string such as '52  Cr  [ He ] ' or '45  Sc ( ISTD )  [ He ] '.
    Returns (name, element, mass, is_istd, gas_mode) or None.
    """
    is_istd = "( ISTD )" in col_str or "(ISTD)" in col_str or "ISTD" in col_str
    
    # Extract gas mode in brackets [ ... ]
    gas_match = re.search(r"\[\s*(.*?)\s*\]", col_str)
    gas_mode = gas_match.group(1).strip() if gas_match else None
    
    # Clean out parenthetical (ISTD) and brackets
    cleaned = re.sub(r"\(.*?\)", "", col_str)
    cleaned = re.sub(r"\[.*?\]", "", cleaned).strip()
    
    # Match mass (digits) and element symbol (letters)
    m = re.match(r"(\d+)\s*([A-Za-z]+)", cleaned)
    if m:
        mass = int(m.group(1))
        element = m.group(2)
        name = f"{element}{mass}"
        return name, element, mass, is_istd, gas_mode
    return None

def parse_agilent_counts(
    file_path: Union[str, Path],
    sheet_name: Union[str, int] = "Sheet1",
    batch_name: Optional[str] = None,
    is_mapping: Optional[Dict[str, str]] = None
) -> Batch:
    """
    Parses an Agilent MassHunter exported Excel counts file into a Batch.
    
    Args:
        file_path: Path to the .xlsx file.
        sheet_name: Sheet containing the counts table (default: 'Sheet1').
        batch_name: Optional batch name. Defaults to filename stem.
        is_mapping: Optional dictionary mapping analyte names (e.g. 'Cr52' or 'Cr')
                    to internal standard names (e.g. 'Sc45'). If not provided,
                    each analyte is paired to the internal standard with the nearest mass.
                    
    Returns:
        A populated Batch instance.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    # Suppress benign openpyxl data validation extension warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        df = pd.read_excel(path, sheet_name=sheet_name)

    if df.empty:
        raise ValueError(f"Spreadsheet at {path} is empty.")

    row0 = df.iloc[0]

    # 1. Identify metadata columns
    meta_indices: Dict[str, int] = {}
    for i, col in enumerate(df.columns):
        lbl = str(row0.iloc[i]).strip() if pd.notna(row0.iloc[i]) else ""
        if lbl in ("Rjct", "Data File", "Type", "Level", "Sample Name", "Comment", "Acq. Date-Time"):
            meta_indices[lbl] = i

    # 2. Identify Analyte / ISTD columns (Row 0 must be 'CPS')
    analyte_cols: Dict[int, tuple] = {}
    for i, col in enumerate(df.columns):
        lbl = str(row0.iloc[i]).strip() if pd.notna(row0.iloc[i]) else ""
        if lbl == "CPS":
            parsed = _parse_analyte_header(str(col))
            if parsed:
                analyte_cols[i] = parsed

    if not analyte_cols:
        raise ValueError(f"No valid CPS analyte columns detected in {path}.")

    batch = Batch(name=batch_name or path.stem)

    # 3. Add Analyte objects
    istd_analytes = []
    quant_analytes = []
    for col_idx, (name, element, mass, is_istd, gas_mode) in analyte_cols.items():
        analyte = Analyte(
            name=name,
            element=element,
            mass=mass,
            is_internal_standard=is_istd,
            gas_mode=gas_mode,
            raw_name=str(df.columns[col_idx])
        )
        batch.add_analyte(analyte)
        if is_istd:
            istd_analytes.append(analyte)
        else:
            quant_analytes.append(analyte)

    # 4. Pair Internal Standards
    for analyte in quant_analytes:
        if is_mapping:
            target_is = is_mapping.get(analyte.name) or is_mapping.get(analyte.element)
            if target_is and target_is in batch.analytes:
                batch.analyte_to_is[analyte.name] = target_is
                continue

        # Fallback: assign to nearest ISTD by mass
        if istd_analytes:
            nearest_is = min(istd_analytes, key=lambda a: abs(a.mass - analyte.mass))
            batch.analyte_to_is[analyte.name] = nearest_is.name

    # 5. Extract Sample rows
    seen_ids = set()
    for row_idx in range(1, len(df)):
        row = df.iloc[row_idx]

        # Check rejection flag
        if "Rjct" in meta_indices:
            rjct_val = row.iloc[meta_indices["Rjct"]]
            if pd.notna(rjct_val) and bool(rjct_val) is True:
                continue

        data_file = str(row.iloc[meta_indices["Data File"]]).strip() if "Data File" in meta_indices and pd.notna(row.iloc[meta_indices["Data File"]]) else f"ROW_{row_idx}"
        sample_name = str(row.iloc[meta_indices["Sample Name"]]).strip() if "Sample Name" in meta_indices and pd.notna(row.iloc[meta_indices["Sample Name"]]) else ""
        type_str = str(row.iloc[meta_indices["Type"]]).strip() if "Type" in meta_indices and pd.notna(row.iloc[meta_indices["Type"]]) else "Sample"
        comment = str(row.iloc[meta_indices["Comment"]]).strip() if "Comment" in meta_indices and pd.notna(row.iloc[meta_indices["Comment"]]) else None
        
        level_val = None
        if "Level" in meta_indices and pd.notna(row.iloc[meta_indices["Level"]]):
            try:
                level_val = float(row.iloc[meta_indices["Level"]])
            except ValueError:
                pass

        # Determine SampleType
        if type_str == "CalBlk":
            stype = SampleType.BLANK
        elif type_str == "CalStd":
            stype = SampleType.STANDARD
        elif type_str.startswith("QC"):
            stype = SampleType.QC
        else:
            stype = SampleType.UNKNOWN

        # Determine a unique, descriptive sample_id
        base_id = sample_name if sample_name else data_file
        if base_id not in seen_ids:
            sample_id = base_id
        else:
            clean_df = data_file.replace(".d", "")
            sample_id = f"{base_id}_{clean_df}"
        seen_ids.add(sample_id)

        # Determine dilution factor from comment if present (e.g. 'DIL 1.100' or 'DIL 1:100')
        dil_factor = 1.0
        if comment:
            m_dil = re.search(r"DIL\s*1[.:/](\d+)", comment, re.IGNORECASE)
            if m_dil:
                try:
                    dil_factor = float(m_dil.group(1))
                except ValueError:
                    dil_factor = 1.0

        sample = Sample(
            sample_id=sample_id,
            sample_type=stype,
            sample_name=sample_name or sample_id,
            data_file=data_file,
            comment=comment,
            level=level_val,
            dilution_factor=dil_factor
        )

        # Extract CPS counts
        for col_idx, (name, element, mass, is_istd, gas_mode) in analyte_cols.items():
            val = row.iloc[col_idx]
            try:
                cps = float(val) if pd.notna(val) else 0.0
            except (ValueError, TypeError):
                cps = 0.0
            sample.raw_intensities[name] = max(0.0, cps)

        batch.add_sample(sample)

    return batch

def parse_agilent_calibration(
    file_path: Union[str, Path],
    sheet_name: Union[str, int] = "Sheet1"
) -> Dict[str, dict]:
    """
    Parses an Agilent MassHunter exported Calibration table Excel file (e.g. CAL.xlsx).
    
    Returns a dict mapping element/analyte symbol to:
        {
            'istd': str or None,
            'units': str,
            'levels': {level_num (int): conc (float)}
        }
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        df = pd.read_excel(path, sheet_name=sheet_name)

    if df.empty:
        raise ValueError(f"Calibration spreadsheet at {path} is empty.")

    # Identify header columns from row 0
    row0 = df.iloc[0]
    analyte_col = 0
    istd_col = 1
    units_col = None
    level_cols: Dict[int, int] = {}
    
    for i, val in enumerate(row0):
        val_str = str(val).strip()
        if val_str.lower() == "name":
            analyte_col = i
        elif val_str.lower() == "istd":
            istd_col = i
        elif val_str.lower() == "units":
            units_col = i
        elif val_str.lower().startswith("level"):
            parts = val_str.split()
            if len(parts) >= 2 and parts[1].isdigit():
                level_cols[int(parts[1])] = i

    cal_data: Dict[str, dict] = {}
    for r in range(1, len(df)):
        elem = str(df.iloc[r, analyte_col]).strip()
        if not elem or elem.lower() == "nan":
            continue
        istd = str(df.iloc[r, istd_col]).strip() if pd.notna(df.iloc[r, istd_col]) else None
        units = str(df.iloc[r, units_col]).strip() if units_col is not None and pd.notna(df.iloc[r, units_col]) else "ug/L"
        
        levels: Dict[int, float] = {}
        for lvl_num, c_idx in level_cols.items():
            val = df.iloc[r, c_idx]
            try:
                if pd.notna(val):
                    levels[lvl_num] = float(val)
            except (ValueError, TypeError):
                pass
                
        cal_data[elem] = {
            "istd": istd,
            "units": units,
            "levels": levels
        }

    return cal_data

def apply_calibration_table(
    batch: Batch,
    calibration_data_or_file: Union[str, Path, Dict[str, dict]],
    override_is: bool = True
) -> Batch:
    """
    Applies parsed calibration concentrations and internal standards to a Batch.
    
    Args:
        batch: The Batch instance to calibrate.
        calibration_data_or_file: A path to a CAL.xlsx file or the dictionary from parse_agilent_calibration.
        override_is: If True, updates batch.analyte_to_is matching the ISTD in the cal table.
        
    Returns:
        The updated Batch instance.
    """
    if isinstance(calibration_data_or_file, (str, Path)):
        cal_data = parse_agilent_calibration(calibration_data_or_file)
    else:
        cal_data = calibration_data_or_file

    # 1. Update internal standards mapping if requested
    if override_is:
        for aname, analyte in batch.analytes.items():
            if analyte.is_internal_standard:
                continue
            elem = analyte.element
            if elem in cal_data and cal_data[elem]["istd"]:
                istd_elem = cal_data[elem]["istd"]
                # Find matching internal standard analyte in batch
                for is_name, is_analyte in batch.analytes.items():
                    if is_analyte.is_internal_standard and is_analyte.element == istd_elem:
                        batch.analyte_to_is[aname] = is_name
                        break

    # 2. Populate known_concentrations for standard samples
    for sample in batch.samples:
        if sample.level is not None:
            lvl_num = int(sample.level)
            for aname, analyte in batch.analytes.items():
                if analyte.is_internal_standard:
                    continue
                elem = analyte.element
                if elem in cal_data and lvl_num in cal_data[elem]["levels"]:
                    conc = cal_data[elem]["levels"][lvl_num]
                    sample.known_concentrations[aname] = conc
            
            # Update sample type if needed
            if sample.sample_type == SampleType.UNKNOWN:
                sample.sample_type = SampleType.BLANK if lvl_num == 1 else SampleType.STANDARD

    return batch
