from typing import Dict
from .models import Batch, SampleType, Sample
from .calibration import CalibrationModel

class Processor:
    """
    Executes the data processing pipeline on a Batch.
    """
    def __init__(self, batch: Batch):
        self.batch = batch
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

    def calibrate(self):
        """Step 2: Fits calibration curves for each analyte."""
        for analyte_name, analyte in self.batch.analytes.items():
            if analyte.is_internal_standard:
                continue
                
            model = CalibrationModel(analyte_name, self.batch)
            model.fit()
            self.calibration_models[analyte_name] = model

    def apply_calibration(self):
        """Step 3: Converts IS-corrected intensities to instrument concentrations."""
        for sample in self.batch.samples:
            for analyte_name, model in self.calibration_models.items():
                if analyte_name in sample.is_corrected_intensities:
                    ratio = sample.is_corrected_intensities[analyte_name]
                    conc = model.calculate_concentration(ratio)
                    sample.instrument_concentrations[analyte_name] = max(0.0, conc) # Assume no negative concentrations

    def perform_blank_subtraction(self):
        """Step 4: Subtracts the average method blank from unknown samples."""
        method_blanks = [s for s in self.batch.samples if s.sample_type == SampleType.METHOD_BLANK]
        
        # Calculate average method blank concentrations
        avg_blank_conc = {}
        for analyte_name in self.calibration_models.keys():
            concs = [mblk.instrument_concentrations.get(analyte_name, 0.0) for mblk in method_blanks]
            if concs:
                avg_blank_conc[analyte_name] = sum(concs) / len(concs)
            else:
                avg_blank_conc[analyte_name] = 0.0
                
        # Subtract from unknowns
        for sample in self.batch.samples:
            if sample.sample_type == SampleType.UNKNOWN:
                for analyte_name, instr_conc in sample.instrument_concentrations.items():
                    blank_conc = avg_blank_conc.get(analyte_name, 0.0)
                    # Subtract and ensure it doesn't go below zero
                    corrected_conc = max(0.0, instr_conc - blank_conc)
                    # We store this back in instrument_concentrations, or we can use final_concentrations
                    # It's cleaner to update instrument_concentrations for intermediate step
                    sample.instrument_concentrations[analyte_name] = corrected_conc

    def calculate_final_concentrations(self):
        """Step 5: Applies dilution factor, final volume, and mass to get sample concentration."""
        for sample in self.batch.samples:
            for analyte_name, instr_conc in sample.instrument_concentrations.items():
                # Formula: Final Conc = (Instr Conc * Final Volume * Dilution Factor) / Mass
                if sample.mass > 0:
                    final_conc = (instr_conc * sample.final_volume * sample.dilution_factor) / sample.mass
                    sample.final_concentrations[analyte_name] = final_conc
                else:
                    sample.final_concentrations[analyte_name] = 0.0
