import pandas as pd
from typing import Dict, Any, List
from .models import Batch
from .pipeline import Processor

def get_results_dataframe(batch: Batch, include_raw: bool = False) -> pd.DataFrame:
    """
    Converts the processed batch results into a Pandas DataFrame.
    """
    data = []
    
    for sample in batch.samples:
        row: Dict[str, Any] = {
            "Sample ID": sample.sample_id,
            "Type": sample.sample_type.value,
            "Mass (g)": sample.mass,
            "Final Volume (mL)": sample.final_volume,
            "Dilution Factor": sample.dilution_factor
        }
        
        for analyte_name in batch.analytes.keys():
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
