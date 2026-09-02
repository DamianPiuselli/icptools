import pytest
import pandas as pd
from icptools.synthetic import generate_synthetic_batch
from icptools.pipeline import Processor
from icptools.reporting import get_results_dataframe, generate_reports

def test_full_pipeline():
    # 1. Generate Synthetic Data
    batch, true_concs = generate_synthetic_batch(
        num_standards=5,
        num_liquid_unknowns=5,
        num_solid_unknowns=5,
        num_blanks=2,
        noise_level=0.01, # low noise for tighter test bounds
        random_seed=42
    )
    
    # 2. Process Data
    processor = Processor(batch)
    processor.process()
    
    # 3. Test generate_reports grouping
    reports = generate_reports(batch)
    
    # We expect several reports: 'Liquid_Direct' (or 'Liquid_None') for standards and liquid unknowns, 
    # 'Solid_Digestion_A' for the solid blanks and unknowns, and maybe 'Liquid_N/A' depending on blank prep groups.
    # Let's just check the data.
    
    results_df = get_results_dataframe(batch)
    
    # Check Solid Unknowns
    solid_unknowns = results_df[(results_df["Type"] == "UNK") & (results_df["Prep Group"] == "Digestion_A")]
    assert len(solid_unknowns) == 5
    
    for idx, row in solid_unknowns.iterrows():
        sample_id = row["Sample ID"]
        true_pb = true_concs[sample_id]["Pb208"]
        
        # MBLK for Digestion_A is Pb:0.5
        expected_instr_pb = max(0.0, true_pb - 0.5)
        calc_instr_pb = row["Pb208 [Instr Conc]"]
        
        # Check within 5% tolerance
        assert abs(calc_instr_pb - expected_instr_pb) / expected_instr_pb < 0.05
        
        # Solid formula: Instr * 50 * 10 / 0.5
        calc_final_pb = row["Pb208 [Final Conc]"]
        expected_final_pb = calc_instr_pb * 50.0 * 10.0 / 0.5
        assert pytest.approx(calc_final_pb, 1e-4) == expected_final_pb
        
    # Check Liquid Unknowns
    liquid_unknowns = results_df[(results_df["Type"] == "UNK") & (results_df["Matrix"] == "Liquid")]
    assert len(liquid_unknowns) == 5
    
    for idx, row in liquid_unknowns.iterrows():
        sample_id = row["Sample ID"]
        true_pb = true_concs[sample_id]["Pb208"]
        
        # No MBLK applied to this prep group (it's None)
        expected_instr_pb = true_pb
        calc_instr_pb = row["Pb208 [Instr Conc]"]
        
        # Increase tolerance to 10% because true_pb can be low (e.g. 5 ug/L), making noise relatively higher
        assert abs(calc_instr_pb - expected_instr_pb) / expected_instr_pb < 0.10
        
        # Liquid formula: Instr * Dilution Factor (2.0)
        calc_final_pb = row["Pb208 [Final Conc]"]
        expected_final_pb = calc_instr_pb * 2.0
        assert pytest.approx(calc_final_pb, 1e-4) == expected_final_pb
        
        # Check that Zn66 Final Conc is None because requested_analytes was only ["Pb208"]
        # In Pandas, it might be NaN
        assert pd.isna(row["Zn66 [Final Conc]"]) or row["Zn66 [Final Conc]"] is None

def test_humidity_correction():
    from icptools.models import Batch, Sample, Analyte, SampleType, SampleMatrix
    from icptools.pipeline import Processor

    batch = Batch(name="HumidityBatch")
    batch.add_analyte(Analyte("Pb208", "Pb", 208))

    # Standard
    s1 = Sample("S1", SampleType.STANDARD, raw_intensities={"Pb208": 1000.0})
    s1.known_concentrations["Pb208"] = 10.0
    s0 = Sample("S0", SampleType.BLANK, raw_intensities={"Pb208": 0.0})
    s0.known_concentrations["Pb208"] = 0.0
    batch.add_sample(s0)
    batch.add_sample(s1)

    # Solid sample with 20% humidity: 1.0g wet mass -> 0.8g dry mass
    # Digestion: 100 mL (0.1 L), Dilution: 1.0
    # Expected Instr Conc = 10.0 ug/L
    # Final Conc (dry basis) = (10.0 * 0.1 * 1.0) / 0.8 = 1.25 mg/kg
    # (Without humidity correction it would be 10.0 * 0.1 / 1.0 = 1.00 mg/kg)
    u = Sample(
        sample_id="SoilSample",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.SOLID,
        mass=1.0,
        percent_humidity=20.0,
        final_volume=0.1,
        dilution_factor=1.0,
        raw_intensities={"Pb208": 1000.0}
    )
    batch.add_sample(u)

    proc = Processor(batch)
    proc.process()

    assert u.dry_mass == pytest.approx(0.8)
    assert u.final_concentrations["Pb208"] == pytest.approx(1.25)

