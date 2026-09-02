from typing import Dict, Optional
from .models import Batch, SampleType, Sample
from .calibration import CalibrationModel

class Processor:
    """
    Executes the data processing pipeline on a Batch.
    """
    def __init__(self, batch: Batch, weighting: str = "none"):
        self.batch = batch
        self.weighting = weighting
        self.calibration_models: Dict[str, CalibrationModel] = {}

    def process(self):
        """Runs the complete data processing pipeline."""
        self.perform_is_correction()
        self.calibrate()
        self.apply_calibration()
        self.perform_blank_subtraction()
        self.calculate_final_concentrations()

    def perform_is_correction(self):
        """Step 1: Normalizes analyte raw intensities by their assigned internal standard."""
        for sample in self.batch.samples:
            for analyte_name, raw_cps in sample.raw_intensities.items():
                if analyte_name not in self.batch.analytes:
                    continue
                
                analyte = self.batch.analytes[analyte_name]
                if analyte.is_internal_standard:
                    # IS is not corrected against itself here
                    sample.is_corrected_intensities[analyte_name] = raw_cps
                    continue
                
                is_name = self.batch.analyte_to_is.get(analyte_name)
                if is_name and is_name in sample.raw_intensities:
                    is_cps = sample.raw_intensities[is_name]
                    # Avoid division by zero
                    ratio = raw_cps / is_cps if is_cps > 0 else 0.0
                    sample.is_corrected_intensities[analyte_name] = ratio
                else:
                    # If no IS assigned, raw CPS is the "corrected" intensity
                    sample.is_corrected_intensities[analyte_name] = raw_cps

    def calibrate(self, weighting: Optional[str] = None):
        """Step 2: Fits calibration curves for each analyte."""
        default_wt = weighting or self.weighting
        for analyte_name, analyte in self.batch.analytes.items():
            if analyte.is_internal_standard:
                continue
                
            wt = getattr(self.batch, "analyte_weightings", {}).get(analyte_name, default_wt)
            model = CalibrationModel(analyte_name, self.batch, weighting=wt)
            model.fit()
            self.calibration_models[analyte_name] = model

    def apply_calibration(self):
        """Step 3: Converts IS-corrected intensities to instrument concentrations."""
        for sample in self.batch.samples:
            for analyte_name, model in self.calibration_models.items():
                if analyte_name in sample.is_corrected_intensities:
                    intensity = sample.is_corrected_intensities[analyte_name]
                    conc = model.calculate_concentration(intensity)
                    sample.instrument_concentrations[analyte_name] = conc

    def perform_blank_subtraction(self):
        """Step 4: Subtracts the average method blank from unknown samples by prep_group."""
        # Calculate average method blank concentrations by prep_group
        avg_blank_concs: Dict[str, Dict[str, list]] = {}
        
        for sample in self.batch.samples:
            if sample.sample_type == SampleType.METHOD_BLANK:
                pg = sample.prep_group
                if pg not in avg_blank_concs:
                    avg_blank_concs[pg] = {analyte: [] for analyte in self.calibration_models.keys()}
                
                for analyte_name in self.calibration_models.keys():
                    conc = sample.instrument_concentrations.get(analyte_name, 0.0)
                    avg_blank_concs[pg][analyte_name].append(conc)
                    
        # Average them out
        final_blank_concs: Dict[str, Dict[str, float]] = {}
        for pg, analyte_data in avg_blank_concs.items():
            final_blank_concs[pg] = {}
            for analyte, concs in analyte_data.items():
                final_blank_concs[pg][analyte] = sum(concs) / len(concs) if concs else 0.0
                
        # Subtract from unknowns
        for sample in self.batch.samples:
            if sample.sample_type == SampleType.UNKNOWN:
                pg = sample.prep_group
                # If there are method blanks for this exact prep_group, apply them
                if pg in final_blank_concs:
                    blank_vals = final_blank_concs[pg]
                    for analyte_name, instr_conc in sample.instrument_concentrations.items():
                        blank_conc = blank_vals.get(analyte_name, 0.0)
                        corrected_conc = instr_conc - blank_conc
                        sample.instrument_concentrations[analyte_name] = corrected_conc

    def calculate_final_concentrations(self):
        """Step 5: Applies dilution factor, final volume, and mass to get sample concentration."""
        from .models import SampleMatrix
        for sample in self.batch.samples:
            for analyte_name, instr_conc in sample.instrument_concentrations.items():
                
                # If requested_analytes is specified, skip others
                if sample.requested_analytes is not None and analyte_name not in sample.requested_analytes:
                    continue
                
                if sample.matrix == SampleMatrix.LIQUID:
                    # Final Conc = Instr Conc * Dilution Factor (ignore mass and volume)
                    final_conc = instr_conc * sample.dilution_factor
                else:
                    # Solid: Final Conc = (Instr Conc * Final Volume * Dilution Factor) / Dry Mass
                    dry_m = sample.dry_mass
                    if dry_m > 0:
                        final_conc = (instr_conc * sample.final_volume * sample.dilution_factor) / dry_m
                    else:
                        final_conc = 0.0
                        
                sample.final_concentrations[analyte_name] = final_conc
