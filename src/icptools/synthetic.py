import random
from typing import Dict, Tuple, List
from .models import Batch, Sample, Analyte, SampleType, SampleMatrix

def generate_synthetic_batch(
    num_standards: int = 5,
    num_liquid_unknowns: int = 5,
    num_solid_unknowns: int = 5,
    num_blanks: int = 2,
    noise_level: float = 0.05,
    random_seed: int = 42
) -> Tuple[Batch, Dict[str, Dict[str, float]]]:
    """
    Generates a mock Batch with synthetic count data, including mixed matrices and prep groups.
    Returns the batch and a dictionary of true concentrations for verification.
    """
    random.seed(random_seed)
    batch = Batch(name="Synthetic_Mixed_Batch_001")
    
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
    
    baseline_is_cps = 500000.0
    true_concentrations = {}
    
    def add_sample(
        sample_id: str, 
        stype: SampleType, 
        true_concs: Dict[str, float], 
        matrix: SampleMatrix = SampleMatrix.LIQUID,
        prep_group: str = None,
        requested_analytes: List[str] = None,
        mass=1.0, 
        vol=1.0, 
        df=1.0
    ):
        sample = Sample(
            sample_id=sample_id, 
            sample_type=stype,
            matrix=matrix,
            prep_group=prep_group,
            requested_analytes=requested_analytes,
            mass=mass, 
            final_volume=vol, 
            dilution_factor=df
        )
        
        is_cps = baseline_is_cps * random.uniform(0.8, 1.2)
        sample.raw_intensities["Rh103"] = is_cps
        true_concentrations[sample_id] = true_concs
        
        for analyte_name, conc in true_concs.items():
            if analyte_name not in curves:
                continue
            slope = curves[analyte_name]["slope"]
            intercept = curves[analyte_name]["intercept"]
            true_ratio = slope * conc + intercept
            expected_cps = true_ratio * is_cps
            noise = random.gauss(0, expected_cps * noise_level) if expected_cps > 0 else random.gauss(0, 10)
            sample.raw_intensities[analyte_name] = max(0.0, expected_cps + noise)
            
        batch.add_sample(sample)

    # 1. Calibration Blanks
    for i in range(num_blanks):
        add_sample(f"BLK_{i+1}", SampleType.BLANK, {"Pb208": 0.0, "Zn66": 0.0})
        
    # 2. Standards (Liquid)
    std_levels = [1, 10, 50, 100, 500][:num_standards]
    for i, level in enumerate(std_levels):
        concs = {"Pb208": float(level), "Zn66": float(level)}
        add_sample(f"STD_{level}", SampleType.STANDARD, concs)
        batch.samples[-1].known_concentrations = concs

    # 3. Direct Liquid Group
    # No method blank for this group, direct analysis
    for i in range(num_liquid_unknowns):
        add_sample(
            f"LIQ_UNK_{i+1}", 
            SampleType.UNKNOWN, 
            {"Pb208": random.uniform(5, 50), "Zn66": random.uniform(5, 50)},
            matrix=SampleMatrix.LIQUID,
            prep_group=None,
            requested_analytes=["Pb208"],  # Only request Pb for liquids
            df=2.0 # Just a dilution
        )

    # 4. Solid Digestion Group (Prep Group A)
    prep_group_a = "Digestion_A"
    
    # Method blank for Group A
    add_sample(
        "MBLK_A_1", 
        SampleType.METHOD_BLANK, 
        {"Pb208": 0.5, "Zn66": 1.0},
        matrix=SampleMatrix.SOLID,
        prep_group=prep_group_a,
        mass=0.5, vol=50.0 # Blanks usually follow same prep config
    )

    # Unknowns for Group A
    for i in range(num_solid_unknowns):
        add_sample(
            f"SOL_UNK_{i+1}", 
            SampleType.UNKNOWN, 
            {"Pb208": random.uniform(50, 200), "Zn66": random.uniform(50, 200)},
            matrix=SampleMatrix.SOLID,
            prep_group=prep_group_a,
            mass=0.5, vol=50.0, df=10.0
        )
        
    return batch, true_concentrations
