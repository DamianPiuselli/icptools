import pytest
import pandas as pd
from icptools.synthetic import generate_synthetic_batch
from icptools.pipeline import Processor
from icptools.reporting import get_results_dataframe, get_calibration_summary

def test_full_pipeline():
    # 1. Generate Synthetic Data
    batch, true_concs = generate_synthetic_batch(
        num_standards=5,
        num_unknowns=10,
        num_blanks=2,
        num_method_blanks=1,
        noise_level=0.01, # low noise for tighter test bounds
        random_seed=42
    )
    
    # 2. Process Data
    processor = Processor(batch)
    processor.process()
    
    # 3. Check Calibration Models
    cal_summary = get_calibration_summary(processor)
    assert len(cal_summary) == 2 # Pb208 and Zn66
    
    # R-squared should be very close to 1 due to low noise
    for r2 in cal_summary["R-squared"]:
        assert r2 > 0.99
        
    # 4. Check Results against True Concentrations
    results_df = get_results_dataframe(batch)
    
    # Check a few unknowns
    unknowns = results_df[results_df["Type"] == "UNK"]
    assert len(unknowns) == 10
    
    for idx, row in unknowns.iterrows():
        sample_id = row["Sample ID"]
        true_pb = true_concs[sample_id]["Pb208"]
        true_zn = true_concs[sample_id]["Zn66"]
        
        # True concentrations were in instrument units (ug/L) before processing.
        # But for unknowns we set mass=0.5, vol=50, df=10.
        # So final = instr * 50 * 10 / 0.5 = instr * 1000
        # Wait, the synthetic generator just uses the true instrument concentration
        # to generate CPS. So the instr_conc calculated by pipeline should match `true_pb`.
        # However, we also added method blank subtraction. True MBLK is Pb:0.5, Zn:1.0.
        # So expected_instr = true_pb - 0.5
        expected_instr_pb = max(0.0, true_pb - 0.5)
        expected_instr_zn = max(0.0, true_zn - 1.0)
        
        calc_instr_pb = row["Pb208 [Instr Conc]"]
        calc_instr_zn = row["Zn66 [Instr Conc]"]
        
        # Check within 5% tolerance (due to noise and calibration fitting variation)
        assert abs(calc_instr_pb - expected_instr_pb) / expected_instr_pb < 0.05
        assert abs(calc_instr_zn - expected_instr_zn) / expected_instr_zn < 0.05
        
        # Check final concentrations calculation arithmetic
        calc_final_pb = row["Pb208 [Final Conc]"]
        expected_final_pb = calc_instr_pb * 50.0 * 10.0 / 0.5
        assert pytest.approx(calc_final_pb, 1e-4) == expected_final_pb
