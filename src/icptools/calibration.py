import numpy as np
from typing import Optional
from .models import Batch, SampleType

class CalibrationModel:
    """
    Handles linear calibration for a single analyte.
    """
    def __init__(self, analyte_name: str, batch: Batch, weighting: str = "none"):
        self.analyte_name = analyte_name
        self.batch = batch
        self.weighting = weighting
        self.slope = 0.0
        self.intercept = 0.0
        self.r_squared = 0.0
        self.fit_successful = False

    def fit(self):
        """Fits the calibration curve using the Standard samples in the batch."""
        standard_ids = self.batch.analyte_calibration_standards.get(self.analyte_name)
        
        x = []
        y = []
        
        for sample in self.batch.samples:
            if standard_ids is not None:
                # If specific standards are assigned to this analyte, only consider them
                is_match = (
                    sample.sample_id in standard_ids
                    or (sample.sample_name is not None and sample.sample_name in standard_ids)
                    or (sample.data_file is not None and sample.data_file in standard_ids)
                )
                if not is_match:
                    continue
            else:
                # Default: use samples marked STANDARD or BLANK that have known_concentrations
                if sample.sample_type not in (SampleType.STANDARD, SampleType.BLANK):
                    continue
                
            if self.analyte_name in sample.known_concentrations and self.analyte_name in sample.is_corrected_intensities:
                x.append(sample.known_concentrations[self.analyte_name])
                y.append(sample.is_corrected_intensities[self.analyte_name])
                
        if len(x) < 2:
            return # Not enough points
            
        x = np.array(x)
        y = np.array(y)
        
        weights = None
        if self.weighting == "1/x":
            # np.polyfit's `w` parameter represents weights applied to the y-coordinates.
            # To weight by 1/variance where variance ~ x^2, w should be 1/x. 
            # If variance ~ x, w should be 1/sqrt(x).
            # Often analytical chemistry 1/x weighting means w_i = 1/x_i.
            weights = 1.0 / np.maximum(x, 1e-6)
            
        if weights is not None:
            coeffs = np.polyfit(x, y, deg=1, w=weights)
        else:
            coeffs = np.polyfit(x, y, deg=1)
            
        self.slope = coeffs[0]
        self.intercept = coeffs[1]
        
        # Calculate R^2
        y_fit = self.slope * x + self.intercept
        ss_res = np.sum((y - y_fit)**2)
        ss_tot = np.sum((y - np.mean(y))**2)
        self.r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
        
        self.fit_successful = True
        
    def calculate_concentration(self, is_corrected_intensity: float) -> float:
        """Converts an IS-corrected intensity back to an instrument concentration."""
        if not self.fit_successful or self.slope == 0:
            return 0.0
        return (is_corrected_intensity - self.intercept) / self.slope
