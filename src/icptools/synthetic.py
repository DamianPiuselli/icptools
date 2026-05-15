import random
from typing import Dict, Tuple
from .models import Batch, Sample, Analyte, SampleType

def generate_synthetic_batch(
    num_standards: int = 5,
    num_unknowns: int = 10,
    num_blanks: int = 2,
    num_method_blanks: int = 1,
    noise_level: float = 0.05,
    random_seed: int = 42
) -> Tuple[Batch, Dict[str, Dict[str, float]]]:
    """
    Generates a mock Batch with synthetic count data.
    Returns the batch and a dictionary of true concentrations for verification.
    """
    random.seed(random_seed)
    batch = Batch(name="Synthetic_Batch_001")
    
    # Setup Analytes
    rh = Analyte("Rh103", "Rh", 103, is_internal_standard=True)
    pb = Analyte("Pb208", "Pb", 208)
    zn = Analyte("Zn66", "Zn", 66)
    
    batch.add_analyte(rh)
    batch.add_analyte(pb, internal_standard_name="Rh103")
    batch.add_analyte(zn, internal_standard_name="Rh103")
    
    # True calibration curves (ratio = slope * conc + intercept)
    curves = {
        "Pb208": {"slope": 0.05, "intercept": 0.001},
        "Zn66": {"slope": 0.02, "intercept": 0.005}
    }
    
    # Baseline IS CPS
    baseline_is_cps = 500000.0
    
    true_concentrations = {}
    
    def add_sample(sample_id: str, stype: SampleType, true_concs: Dict[str, float], mass=1.0, vol=1.0, df=1.0):
        sample = Sample(sample_id=sample_id, sample_type=stype, mass=mass, final_volume=vol, dilution_factor=df)
        
        # Simulate IS CPS with drift/noise
        is_cps = baseline_is_cps * random.uniform(0.8, 1.2)
        sample.raw_intensities["Rh103"] = is_cps
        
        true_concentrations[sample_id] = true_concs
        
        for analyte_name, conc in true_concs.items():
            if analyte_name not in curves:
                continue
                
            slope = curves[analyte_name]["slope"]
            intercept = curves[analyte_name]["intercept"]
            
            # True ratio
            true_ratio = slope * conc + intercept
            
            # Expected Raw CPS
            expected_cps = true_ratio * is_cps
            
            # Apply Gaussian noise
            noise = random.gauss(0, expected_cps * noise_level) if expected_cps > 0 else random.gauss(0, 10)
            final_cps = max(0.0, expected_cps + noise)
            
            sample.raw_intensities[analyte_name] = final_cps
            
        batch.add_sample(sample)
        
    # Generate Blanks (Calibration Blank)
    for i in range(num_blanks):
        add_sample(f"BLK_{i+1}", SampleType.BLANK, {"Pb208": 0.0, "Zn66": 0.0})
        
    # Generate Standards (using true concentrations directly)
    # The actual standard concentrations need to be stored somewhere to perform calibration!
    # In reality, this would be read from a calibration table. We will store it in the Sample object
    # by adding an attribute to Sample or using a separate calibration config. For now, true_concentrations
    # acts as our reference. We should probably add `known_concentrations` to Sample for STANDARD type.
    std_levels = [1, 10, 50, 100, 500][:num_standards]
    for i, level in enumerate(std_levels):
        sample_id = f"STD_{level}"
        concs = {"Pb208": float(level), "Zn66": float(level)}
        add_sample(sample_id, SampleType.STANDARD, concs)
        # We need to inject these knowns into the sample for calibration
        batch.samples[-1].known_concentrations = concs
        
    # Generate Method Blanks
    for i in range(num_method_blanks):
        add_sample(f"MBLK_{i+1}", SampleType.METHOD_BLANK, {"Pb208": 0.5, "Zn66": 1.0})
        
    # Generate Unknowns
    for i in range(num_unknowns):
        pb_conc = random.uniform(5, 200)
        zn_conc = random.uniform(5, 200)
        add_sample(f"UNK_{i+1}", SampleType.UNKNOWN, {"Pb208": pb_conc, "Zn66": zn_conc}, mass=0.5, vol=50.0, df=10.0)
        
    return batch, true_concentrations