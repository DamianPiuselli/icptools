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
    is_mapping: Optional[Dict[str, str]] = None,
    include_gas_mode: bool = False,
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
        include_gas_mode: If True, forces gas mode suffix in analyte names (e.g. 'Fe56_He').
                          If False (default), gas mode suffix is added only when necessary
                          to disambiguate collisions (e.g. same isotope in 'He' and 'No Gas').
                    
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
        if lbl in (
            "Rjct", "Data File", "Type", "Level", "Sample Name", "Comment", "Acq. Date-Time",
            "Dilution", "Total Dil.", "Dil. Factor", "Dil"
        ):
            meta_indices[lbl] = i

    # 2. Identify Analyte / ISTD columns (Row 0 must be 'CPS') and adjacent CPS RSD
    raw_analyte_cols: Dict[int, tuple] = {}
    rsd_cols: Dict[int, int] = {}
    for i, col in enumerate(df.columns):
        lbl = str(row0.iloc[i]).strip() if pd.notna(row0.iloc[i]) else ""
        if lbl == "CPS":
            parsed = _parse_analyte_header(str(col))
            if parsed:
                raw_analyte_cols[i] = parsed
                if i + 1 < len(df.columns):
                    next_lbl = str(row0.iloc[i + 1]).strip() if pd.notna(row0.iloc[i + 1]) else ""
                    if "rsd" in next_lbl.lower():
                        rsd_cols[i] = i + 1

    if not raw_analyte_cols:
        raise ValueError(f"No valid CPS analyte columns detected in {path}.")

    # Disambiguate names when multi-gas collisions occur
    from collections import Counter
    name_counts = Counter(parsed[0] for parsed in raw_analyte_cols.values())

    analyte_cols: Dict[int, tuple] = {}
    for col_idx, (base_name, element, mass, is_istd, gas_mode) in raw_analyte_cols.items():
        if (name_counts[base_name] > 1 or include_gas_mode) and gas_mode:
            clean_gas = re.sub(r"\s+", "", gas_mode)
            final_name = f"{base_name}_{clean_gas}"
        else:
            final_name = base_name
        analyte_cols[col_idx] = (final_name, element, mass, is_istd, gas_mode)

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

        # Fallback: if analyte has a gas_mode, prefer ISTDs with the same gas_mode
        matching_istds = [a for a in istd_analytes if a.gas_mode == analyte.gas_mode] if analyte.gas_mode else []
        candidate_istds = matching_istds if matching_istds else istd_analytes

        if candidate_istds:
            nearest_is = min(candidate_istds, key=lambda a: abs(a.mass - analyte.mass))
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

        # Determine dilution factor: check explicit metadata column, then comment
        dil_factor = 1.0
        for dil_key in ("Dilution", "Total Dil.", "Dil. Factor", "Dil"):
            if dil_key in meta_indices and pd.notna(row.iloc[meta_indices[dil_key]]):
                try:
                    val = float(row.iloc[meta_indices[dil_key]])
                    if val > 0:
                        dil_factor = val
                        break
                except (ValueError, TypeError):
                    pass

        if dil_factor == 1.0 and comment:
            # Matches: DIL 1.100, DIL 1:100, DIL 1/100, DIL 100, 1:100, 1/100, x100, DF 100
            m_dil = re.search(r"(?:DIL\s*(?:1[.:/])?|1\s*[:/]|[xX]\s*|DF\s*)(\d+(?:\.\d+)?)", comment, re.IGNORECASE)
            if m_dil:
                try:
                    val = float(m_dil.group(1))
                    if val > 0:
                        dil_factor = val
                except ValueError:
                    pass

        sample = Sample(
            sample_id=sample_id,
            sample_type=stype,
            sample_name=sample_name or sample_id,
            data_file=data_file,
            comment=comment,
            level=level_val,
            dilution_factor=dil_factor
        )

        # Extract CPS counts and CPS RSDs
        for col_idx, (name, element, mass, is_istd, gas_mode) in analyte_cols.items():
            val = row.iloc[col_idx]
            try:
                cps = float(val) if pd.notna(val) else 0.0
            except (ValueError, TypeError):
                cps = 0.0
            sample.raw_intensities[name] = max(0.0, cps)

            if col_idx in rsd_cols:
                rsd_val = row.iloc[rsd_cols[col_idx]]
                try:
                    rsd = float(rsd_val) if pd.notna(rsd_val) else 0.0
                except (ValueError, TypeError):
                    rsd = 0.0
                sample.raw_rsds[name] = max(0.0, rsd)

        batch.add_sample(sample)

    return batch

def parse_agilent_calibration(
    file_path: Union[str, Path],
    sheet_name: Union[str, int] = "Sheet1"
) -> Dict[str, dict]:
    """
    Parses an Agilent MassHunter exported Calibration table Excel file (e.g. CAL.xlsx).
    Normalizes known concentration levels to ug/L regardless of original unit in Excel (ppm, ppb, etc.).
    
    Returns a dict mapping element/analyte symbol to:
        {
            'istd': str or None,
            'units': str,
            'levels': {level_num (int): conc_ug_per_L (float)}
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
        elem_raw = str(df.iloc[r, analyte_col]).strip()
        if not elem_raw or elem_raw.lower() == "nan":
            continue

        # Extract element or isotope name: e.g. 'Cr', '52 Cr', 'Pb', '208 Pb'
        m_elem = re.match(r"(?:(\d+)\s*)?([A-Za-z]+)", elem_raw)
        if m_elem:
            mass_str = m_elem.group(1)
            elem_sym = m_elem.group(2)
            elem_key = f"{elem_sym}{mass_str}" if mass_str else elem_sym
        else:
            elem_key = elem_raw
            elem_sym = elem_raw

        istd = str(df.iloc[r, istd_col]).strip() if pd.notna(df.iloc[r, istd_col]) else None
        units_raw = str(df.iloc[r, units_col]).strip() if units_col is not None and pd.notna(df.iloc[r, units_col]) else "ug/L"
        
        # Unit normalization factor to ug/L
        unit_clean = units_raw.lower().replace(" ", "")
        if unit_clean in ("ppm", "mg/l"):
            unit_factor = 1000.0
        elif unit_clean in ("ppb", "ug/l", "µg/l"):
            unit_factor = 1.0
        elif unit_clean in ("ppt", "ng/l"):
            unit_factor = 0.001
        elif unit_clean in ("%", "wt%"):
            unit_factor = 10000000.0
        else:
            unit_factor = 1.0

        levels: Dict[int, float] = {}
        for lvl_num, c_idx in level_cols.items():
            val = df.iloc[r, c_idx]
            try:
                if pd.notna(val):
                    levels[lvl_num] = float(val) * unit_factor
            except (ValueError, TypeError):
                pass
                
        cal_entry = {
            "istd": istd,
            "units": units_raw,
            "levels": levels
        }
        cal_data[elem_key] = cal_entry
        if elem_sym != elem_key:
            cal_data[elem_sym] = cal_entry

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

    def get_cal_entry(analyte: Analyte):
        if analyte.name in cal_data:
            return cal_data[analyte.name]
        base = analyte.name.split("_")[0]
        if base in cal_data:
            return cal_data[base]
        if analyte.element in cal_data:
            return cal_data[analyte.element]
        return None

    # 1. Update internal standards mapping if requested
    if override_is:
        for aname, analyte in batch.analytes.items():
            if analyte.is_internal_standard:
                continue
            entry = get_cal_entry(analyte)
            if entry and entry["istd"]:
                istd_elem = entry["istd"]
                matching = [
                    is_name for is_name, is_a in batch.analytes.items()
                    if is_a.is_internal_standard and is_a.element == istd_elem
                ]
                if matching:
                    same_gas = [m for m in matching if batch.analytes[m].gas_mode == analyte.gas_mode]
                    batch.analyte_to_is[aname] = same_gas[0] if same_gas else matching[0]

    # 2. Populate known_concentrations for standard and blank samples
    for sample in batch.samples:
        is_cal_blk = (
            sample.sample_type == SampleType.BLANK
            or "calblk" in (sample.sample_name or "").lower()
            or "calblk" in (sample.data_file or "").lower()
        )

        if sample.level is not None:
            lvl_num = int(sample.level)
            for aname, analyte in batch.analytes.items():
                if analyte.is_internal_standard:
                    continue
                entry = get_cal_entry(analyte)
                if entry and lvl_num in entry["levels"]:
                    conc = entry["levels"][lvl_num]
                    sample.known_concentrations[aname] = conc

            # Set sample type based on whether known concentrations are 0.0 or > 0.0
            if sample.sample_type in (SampleType.UNKNOWN, SampleType.STANDARD, SampleType.BLANK):
                has_positive = any(c > 0.0 for c in sample.known_concentrations.values())
                sample.sample_type = SampleType.STANDARD if has_positive else SampleType.BLANK

        elif is_cal_blk:
            # CalBlk without level number: set known conc to 0.0 for all analytes
            sample.sample_type = SampleType.BLANK
            for aname, analyte in batch.analytes.items():
                if not analyte.is_internal_standard:
                    sample.known_concentrations[aname] = 0.0

    return batch
