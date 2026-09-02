import pytest
from pathlib import Path
from icptools import (
    parse_agilent_counts,
    StandardMix,
    Processor,
    get_calibration_summary,
    generate_reports,
    SampleMatrix,
    SampleType,
)

REAL_DATA_PATH = Path("local_data/20 y 22 -2026   pellets y lodos/fq count.xlsx")

@pytest.mark.skipif(not REAL_DATA_PATH.exists(), reason="Real test data not found in local_data")
def test_parse_agilent_counts_real_batch():
    batch = parse_agilent_counts(REAL_DATA_PATH)
    
    # Check Analytes and ISTDs
    assert "Cr52" in batch.analytes
    assert "Fe56" in batch.analytes
    assert "Cu63" in batch.analytes
    assert "Zn66" in batch.analytes
    assert "Cd111" in batch.analytes
    assert "Hg201" in batch.analytes
    assert "Pb208" in batch.analytes
    
    assert "Sc45" in batch.analytes
    assert batch.analytes["Sc45"].is_internal_standard is True
    assert "Tb159" in batch.analytes
    assert batch.analytes["Tb159"].is_internal_standard is True

    # Check sample extraction
    assert len(batch.samples) > 20
    s1 = batch.get_sample("S1")
    assert s1 is not None
    assert s1.sample_type == SampleType.STANDARD
    assert "Cr52" in s1.raw_intensities
    assert s1.raw_intensities["Cr52"] > 0

    # Test StandardMix application (Certipur VI)
    certipur_vi = StandardMix(
        name="Certipur_VI",
        stock_concentrations={
            "Cr": 10.0, "Cu": 10.0, "Cd": 10.0, "Pb": 10.0,
            "Fe": 100.0, "Zn": 100.0
        },
        reference_element="Cr"
    )
    batch.apply_standard_mix(
        certipur_vi,
        levels={
            "S0": 0.0, "S1": 0.1, "S2": 0.3, "S3": 1.0, "S4": 5.0,
            "S5": 10.0, "S6": 20.0, "S7": 50.0, "S8": 100.0, "S9": 250.0
        }
    )

    assert s1.known_concentrations["Cr52"] == pytest.approx(0.1)
    assert s1.known_concentrations["Fe56"] == pytest.approx(1.0) # 10x higher
    s9 = batch.get_sample("S9")
    assert s9.known_concentrations["Cr52"] == pytest.approx(250.0)
    assert s9.known_concentrations["Fe56"] == pytest.approx(2500.0)

    # Test piecewise calibration for Hg
    batch.assign_calibration(
        analyte="Hg201",
        standards={"hg bco": 0.0, "hg 1": 1.0, "hg 10": 10.0, "hg 20": 20.0},
        internal_standard="Tb159"
    )
    
    # Process
    proc = Processor(batch)
    proc.process()
    
    # Check calibration fits
    cal_summary = get_calibration_summary(proc)
    assert len(cal_summary) == 7 # 7 analytes
    for _, row in cal_summary.iterrows():
        assert row["Fit Successful"] is True
        assert row["R-squared"] > 0.99

def test_parse_agilent_counts_synthetic(tmp_path):
    import pandas as pd
    excel_file = tmp_path / "mock_counts.xlsx"
    
    # Construct mock Agilent MassHunter layout
    headers = [
        "Sample", "Unnamed: 1", "Unnamed: 2", "Unnamed: 3", "Unnamed: 4", "Unnamed: 5", "Unnamed: 6", "Unnamed: 7",
        "52  Cr  [ He ] ", "Unnamed: 9", "45  Sc ( ISTD )  [ He ] ", "Unnamed: 11"
    ]
    row0 = [
        None, "Rjct", "Data File", "Acq. Date-Time", "Type", "Level", "Sample Name", "ISTD Conc.",
        "CPS", "CPS RSD", "CPS", "CPS RSD"
    ]
    row1 = [None, False, "001CALB.d", "2026-01-01", "CalBlk", 1.0, "S0", "Level1", 100.0, 1.0, 50000.0, 1.0]
    row2 = [None, False, "002CALS.d", "2026-01-01", "CalStd", 2.0, "S1", "Level2", 5000.0, 1.0, 50000.0, 1.0]
    row3 = [None, False, "003SMPL.d", "2026-01-01", "Sample", None, "Sample1", "Level1", 2500.0, 1.0, 50000.0, 1.0]
    
    df = pd.DataFrame([row0, row1, row2, row3], columns=headers)
    df.to_excel(excel_file, index=False)
    
    batch = parse_agilent_counts(excel_file)
    assert "Cr52" in batch.analytes
    assert "Sc45" in batch.analytes
    assert batch.analytes["Sc45"].is_internal_standard is True
    assert len(batch.samples) == 3
    assert batch.get_sample("S0").sample_type == SampleType.BLANK
    assert batch.get_sample("S1").sample_type == SampleType.STANDARD
    assert batch.get_sample("Sample1").sample_type == SampleType.UNKNOWN

def test_export_excel_formula_report(tmp_path):
    import openpyxl
    from icptools import Batch, Sample, Analyte, SampleType, SampleMatrix, export_excel_formula_report
    
    batch = Batch(name="TestBatch")
    batch.add_analyte(Analyte("Cr52", "Cr", 52))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Cr52"] = "Sc45"
    
    # Add 2 standards
    s0 = Sample("S0", SampleType.BLANK, raw_intensities={"Cr52": 100.0, "Sc45": 50000.0}, is_corrected_intensities={"Cr52": 0.002})
    s0.known_concentrations["Cr52"] = 0.0
    s1 = Sample("S1", SampleType.STANDARD, raw_intensities={"Cr52": 5000.0, "Sc45": 50000.0}, is_corrected_intensities={"Cr52": 0.100})
    s1.known_concentrations["Cr52"] = 10.0
    batch.add_sample(s0)
    batch.add_sample(s1)
    
    # Add unknown sample
    u1 = Sample("UNK1", SampleType.UNKNOWN, matrix=SampleMatrix.LIQUID, raw_intensities={"Cr52": 2500.0, "Sc45": 50000.0}, dilution_factor=2.0)
    batch.add_sample(u1)
    
    out_xlsx = tmp_path / "formula_report.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        instrument_loqs={"Cr52": 0.5},
        analytes=["Cr52"]
    )
    
    assert out_xlsx.exists()
    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws = wb.active
    
    # Verify formulas exist
    formulas_found = [cell.value for row in ws.iter_rows() for cell in row if str(cell.value or "").startswith("=")]
    assert any("SLOPE" in str(f) for f in formulas_found)
    assert any("INTERCEPT" in str(f) for f in formulas_found)
    assert any("RSQ" in str(f) for f in formulas_found)
    assert any("IF" in str(f) for f in formulas_found)


