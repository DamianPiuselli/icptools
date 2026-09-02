import pandas as pd
from typing import Dict, Any, List
from .models import Batch, SampleMatrix
from .pipeline import Processor

def generate_reports(batch: Batch, include_raw: bool = False) -> Dict[str, pd.DataFrame]:
    """
    Generates multiple DataFrames, grouping samples by their SampleMatrix and Prep Group.
    Returns a dictionary mapping a report name (e.g., 'Liquid_None', 'Solid_Digestion_A') to its DataFrame.
    """
    reports = {}
    
    # Group samples by (Matrix, Prep Group)
    groups: Dict[tuple, list] = {}
    for sample in batch.samples:
        key = (sample.matrix, sample.prep_group)
        if key not in groups:
            groups[key] = []
        groups[key].append(sample)
        
    for (matrix, prep_group), samples in groups.items():
        data = []
        # Determine the appropriate unit string based on matrix
        final_unit = "ug/L" if matrix == SampleMatrix.LIQUID else "mg/kg"
        
        for sample in samples:
            row: Dict[str, Any] = {
                "Sample ID": sample.sample_id,
                "Type": sample.sample_type.value,
                "Prep Group": sample.prep_group if sample.prep_group else "N/A"
            }
            
            if matrix == SampleMatrix.SOLID:
                row["Mass (g)"] = sample.mass
                row["Final Volume (mL)"] = sample.final_volume
            
            row["Dilution Factor"] = sample.dilution_factor
            
            # Use requested_analytes if available, otherwise all non-ISTD analytes
            if sample.requested_analytes:
                analytes_to_report = sample.requested_analytes
            else:
                analytes_to_report = [
                    name for name, a in batch.analytes.items() if not a.is_internal_standard
                ]
            
            for analyte_name in analytes_to_report:
                if include_raw:
                    row[f"{analyte_name} [Raw CPS]"] = sample.raw_intensities.get(analyte_name, None)
                    row[f"{analyte_name} [IS Ratio]"] = sample.is_corrected_intensities.get(analyte_name, None)
                    
                row[f"{analyte_name} [Instr Conc (ug/L)]"] = sample.instrument_concentrations.get(analyte_name, None)
                
                # Check if we successfully calculated a final concentration for this analyte
                if analyte_name in sample.final_concentrations:
                    row[f"{analyte_name} [Final Conc ({final_unit})]"] = sample.final_concentrations[analyte_name]
                else:
                    row[f"{analyte_name} [Final Conc ({final_unit})]"] = None
                
            data.append(row)
            
        group_name = f"{matrix.value}_{prep_group if prep_group else 'Direct'}"
        reports[group_name] = pd.DataFrame(data)
        
    return reports

def get_results_dataframe(batch: Batch, include_raw: bool = False) -> pd.DataFrame:
    """
    Convenience method to return a single combined DataFrame for the entire batch.
    Will lack specific unit annotations in the headers because matrix can vary.
    """
    data = []
    
    for sample in batch.samples:
        row: Dict[str, Any] = {
            "Sample ID": sample.sample_id,
            "Type": sample.sample_type.value,
            "Matrix": sample.matrix.value,
            "Prep Group": sample.prep_group,
            "Mass (g)": sample.mass,
            "Final Volume (mL)": sample.final_volume,
            "Dilution Factor": sample.dilution_factor
        }
        
        for analyte_name, analyte in batch.analytes.items():
            if analyte.is_internal_standard and not include_raw:
                continue
            if include_raw:
                row[f"{analyte_name} [Raw CPS]"] = sample.raw_intensities.get(analyte_name, None)
                row[f"{analyte_name} [IS Ratio]"] = sample.is_corrected_intensities.get(analyte_name, None)
                
            row[f"{analyte_name} [Instr Conc]"] = sample.instrument_concentrations.get(analyte_name, None)
            row[f"{analyte_name} [Final Conc]"] = sample.final_concentrations.get(analyte_name, None)
            
        data.append(row)
        
    return pd.DataFrame(data)

def get_calibration_summary(processor: Processor) -> pd.DataFrame:
    """
    Returns a DataFrame summarizing the calibration curves for the batch.
    """
    data = []
    for analyte_name, model in processor.calibration_models.items():
        data.append({
            "Analyte": analyte_name,
            "Weighting": model.weighting,
            "Slope": model.slope,
            "Intercept": model.intercept,
            "R-squared": model.r_squared,
            "Fit Successful": model.fit_successful
        })
        
    return pd.DataFrame(data)
