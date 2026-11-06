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

def test_parse_calibration_and_blank_offset(tmp_path):
    import pandas as pd
    from icptools import (
        parse_agilent_counts,
        parse_agilent_calibration,
        apply_calibration_table,
        Processor,
        SampleMatrix,
    )

    counts_file = tmp_path / "counts.xlsx"
    cal_file = tmp_path / "cal.xlsx"

    # 1. Mock CAL.xlsx
    cal_cols = ["Analyte", "Unnamed: 1", "Unnamed: 2", "Unnamed: 3", "Level", "Unnamed: 5"]
    row0_c = ["Name", "ISTD", "Min Conc.", "Units", "Level 1", "Level 2"]
    row1_c = ["Cr", "Sc", 0, "ug/L", 0.0, 10.0]
    df_cal = pd.DataFrame([row0_c, row1_c], columns=cal_cols)
    df_cal.to_excel(cal_file, index=False)

    # 2. Mock FQ COUNTS.xlsx
    cnt_cols = [
        "Sample", "Unnamed: 1", "Unnamed: 2", "Unnamed: 3", "Unnamed: 4", "Unnamed: 5", "Unnamed: 6", "Unnamed: 7", "Unnamed: 8",
        "52  Cr  [ He ] ", "Unnamed: 10", "45  Sc ( ISTD )  [ He ] ", "Unnamed: 12"
    ]
    row0_cnt = [None, "Rjct", "Data File", "Acq. Date-Time", "Type", "Level", "Sample Name", "ISTD Conc.", "Comment", "CPS", "CPS RSD", "CPS", "CPS RSD"]
    row1_cnt = [None, False, "001CALB.d", "2026-01-01", "CalBlk", 1.0, "S0", "Level1", None, 100.0, 1.0, 10000.0, 1.0] # ratio = 0.01
    row2_cnt = [None, False, "002CALS.d", "2026-01-01", "CalStd", 2.0, "S1", "Level2", None, 1100.0, 1.0, 10000.0, 1.0] # ratio = 0.11 (slope = 0.01)
    row3_cnt = [None, False, "003SMPL.d", "2026-01-01", "Sample", None, "Sample1", "Level1", "DIL 1.100", 600.0, 1.0, 10000.0, 1.0] # ratio = 0.06 -> net ratio = 0.05 -> conc = 5.0 -> diluted = 500.0
    df_cnt = pd.DataFrame([row0_cnt, row1_cnt, row2_cnt, row3_cnt], columns=cnt_cols)
    df_cnt.to_excel(counts_file, index=False)

    cal_data = parse_agilent_calibration(cal_file)
    assert "Cr" in cal_data
    assert cal_data["Cr"]["levels"][1] == 0.0
    assert cal_data["Cr"]["levels"][2] == 10.0

    batch = parse_agilent_counts(counts_file)
    apply_calibration_table(batch, cal_data)

    s_unk = batch.get_sample("Sample1")
    assert s_unk.dilution_factor == 100.0
    assert batch.analyte_to_is["Cr52"] == "Sc45"

    proc = Processor(batch, weighting="blank_offset")
    proc.process()

    model = proc.calibration_models["Cr52"]
    assert model.fit_successful
    assert model.intercept == pytest.approx(0.01)
    assert model.slope == pytest.approx(0.01)
    assert s_unk.instrument_concentrations["Cr52"] == pytest.approx(5.0)
    assert s_unk.final_concentrations["Cr52"] == pytest.approx(500.0)

def test_export_split_dilution_report(tmp_path):
    import openpyxl
    from icptools import (
        Batch,
        Sample,
        Analyte,
        SampleType,
        export_split_dilution_report,
        generate_split_dilution_report,
    )

    batch = Batch(name="TestSplit")
    batch.add_analyte(Analyte("Na23", "Na", 23))
    batch.add_analyte(Analyte("Cr52", "Cr", 52))

    # Add high-dilution sample
    s_high = Sample(
        sample_id="SMPL1_dil",
        sample_type=SampleType.UNKNOWN,
        sample_name="SMPL1",
        data_file="001SMPL.d",
        dilution_factor=100.0,
        instrument_concentrations={"Na23": 200.0, "Cr52": 0.0},
        final_concentrations={"Na23": 20000.0, "Cr52": 0.0},
    )
    # Add undiluted sample
    s_low = Sample(
        sample_id="SMPL1_undil",
        sample_type=SampleType.UNKNOWN,
        sample_name="SMPL1",
        data_file="002SMPL.d",
        dilution_factor=1.0,
        instrument_concentrations={"Na23": 20000.0, "Cr52": 1.5},
        final_concentrations={"Na23": 20000.0, "Cr52": 1.5},
    )
    batch.add_sample(s_high)
    batch.add_sample(s_low)

    rep_dfs = generate_split_dilution_report(
        batch=batch,
        high_analytes=["Na23"],
        low_analytes=["Cr52"],
        high_units="mg/L",
        low_units="ug/L",
    )
    assert "Analitos Altos" in rep_dfs
    assert "Analitos Bajos" in rep_dfs
    assert "Reporte Unificado" in rep_dfs
    assert len(rep_dfs["Reporte Unificado"]) == 1
    assert rep_dfs["Reporte Unificado"]["Na [mg/L]"].iloc[0] == pytest.approx(20.0)
    assert rep_dfs["Reporte Unificado"]["Cr [ug/L]"].iloc[0] == pytest.approx(1.5)

    out_xlsx = tmp_path / "split_report.xlsx"
    export_split_dilution_report(
        batch=batch,
        output_path=out_xlsx,
        high_analytes=["Na23"],
        low_analytes=["Cr52"],
        high_units="mg/L",
        low_units="ug/L",
    )
    assert out_xlsx.exists()
    wb = openpyxl.load_workbook(out_xlsx)
    assert "Analitos Altos" in wb.sheetnames
    assert "Analitos Bajos" in wb.sheetnames
    assert "Reporte Unificado" in wb.sheetnames

    ws_u = wb["Reporte Unificado"]
    # Verify linking formula exists in unified table
    formula_val = ws_u.cell(row=5, column=2).value
    assert str(formula_val).startswith("='Analitos Altos'!")




