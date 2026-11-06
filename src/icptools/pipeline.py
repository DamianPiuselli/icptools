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
        self.calculate_is_recoveries()
        self.perform_is_correction()
        self.calibrate()
        self.apply_calibration()
        self.perform_blank_subtraction()
        self.calculate_final_concentrations()

    def calculate_is_recoveries(self):
        """
        Calculates % ISTD recovery for each sample and each internal standard
        relative to the mean intensity of the calibration blank(s) (CalBlk).
        """
        # Find all internal standards in batch
        istd_names = [name for name, a in self.batch.analytes.items() if a.is_internal_standard]
        if not istd_names:
            return

        # Calculate baseline CPS from calibration blanks
        cal_blks = [
            s for s in self.batch.samples
            if s.sample_type == SampleType.BLANK
            or "calblk" in (s.sample_name or "").lower()
            or "calblk" in (s.data_file or "").lower()
        ]

        baseline_is: Dict[str, float] = {}
        for is_name in istd_names:
            cps_list = [s.raw_intensities[is_name] for s in cal_blks if is_name in s.raw_intensities and s.raw_intensities[is_name] > 0]
            if cps_list:
                baseline_is[is_name] = sum(cps_list) / len(cps_list)
            else:
                # Fallback: first sample that has this ISTD
                first_cps = next((s.raw_intensities[is_name] for s in self.batch.samples if is_name in s.raw_intensities and s.raw_intensities[is_name] > 0), None)
                baseline_is[is_name] = first_cps if first_cps else 1.0

        for sample in self.batch.samples:
            for is_name in istd_names:
                base = baseline_is.get(is_name, 0.0)
                curr = sample.raw_intensities.get(is_name, 0.0)
                if base > 0:
                    sample.is_recovery[is_name] = (curr / base) * 100.0
                else:
                    sample.is_recovery[is_name] = 100.0

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
                
        # Subtract from unknowns into blank_corrected_concentrations without mutating instrument_concentrations
        for sample in self.batch.samples:
            if sample.sample_type == SampleType.UNKNOWN:
                pg = sample.prep_group
                blank_vals = final_blank_concs.get(pg, {})
                for analyte_name, instr_conc in sample.instrument_concentrations.items():
                    blank_conc = blank_vals.get(analyte_name, 0.0)
                    sample.blank_corrected_concentrations[analyte_name] = instr_conc - blank_conc
            else:
                for analyte_name, instr_conc in sample.instrument_concentrations.items():
                    sample.blank_corrected_concentrations[analyte_name] = instr_conc

    def calculate_final_concentrations(self):
        """Step 5: Applies dilution factor, final volume, and mass to get sample concentration."""
        from .models import SampleMatrix
        for sample in self.batch.samples:
            for analyte_name in sample.instrument_concentrations.keys():
                
                # If requested_analytes is specified, skip others
                if sample.requested_analytes is not None and analyte_name not in sample.requested_analytes:
                    continue
                
                # Use blank-corrected concentration if available, else instrument concentration
                active_conc = sample.blank_corrected_concentrations.get(
                    analyte_name, sample.instrument_concentrations.get(analyte_name, 0.0)
                )

                if sample.matrix == SampleMatrix.LIQUID:
                    # Final Conc (ug/L) = Instr Conc * Dilution Factor (ignore mass and volume)
                    final_conc = active_conc * sample.dilution_factor
                else:
                    # Solid: Final Conc (mg/kg) = (Instr Conc (ug/L) * (Final Volume (mL) / 1000) * Dilution Factor) / Dry Mass (g)
                    dry_m = sample.dry_mass
                    if dry_m > 0:
                        final_conc = (active_conc * (sample.final_volume / 1000.0) * sample.dilution_factor) / dry_m
                    else:
                        final_conc = 0.0
                        
                sample.final_concentrations[analyte_name] = final_conc
