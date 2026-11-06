import pytest
import openpyxl
from pathlib import Path
from icptools import (
    Batch,
    Sample,
    Analyte,
    SampleType,
    SampleMatrix,
    Processor,
    export_excel_formula_report,
    export_split_dilution_report,
    generate_split_dilution_report,
)

def _build_calibration_standards(batch: Batch, analyte_names: list, conc_levels: list = None):
    """Helper to add standard samples S0, S1, S2, etc."""
    levels = conc_levels or [0.0, 10.0, 50.0, 100.0]
    for idx, lvl in enumerate(levels):
        stype = SampleType.BLANK if lvl == 0.0 else SampleType.STANDARD
        s = Sample(
            sample_id=f"S{idx}",
            sample_type=stype,
            sample_name=f"S{idx}",
            level=float(idx + 1),
        )
        for aname in analyte_names:
            s.known_concentrations[aname] = float(lvl)
            # Simulated counts: IS = 50,000; slope = 0.05
            is_name = batch.analyte_to_is.get(aname)
            is_cps = 50000.0
            if is_name:
                s.raw_intensities[is_name] = is_cps
            cps = (0.05 * lvl + 0.001) * is_cps
            s.raw_intensities[aname] = cps
        batch.add_sample(s)


def test_excel_formulas_liquid_direct(tmp_path):
    """TC-01: Direct liquid analysis without dilution (DF = 1.0)."""
    batch = Batch(name="LiquidDirectBatch")
    batch.add_analyte(Analyte("Cr52", "Cr", 52))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Cr52"] = "Sc45"

    _build_calibration_standards(batch, ["Cr52"], [0.0, 10.0, 50.0, 100.0])

    # Add unknown liquid sample
    u1 = Sample(
        sample_id="WATER_01",
        sample_type=SampleType.UNKNOWN,
        sample_name="WATER_01",
        matrix=SampleMatrix.LIQUID,
        dilution_factor=1.0,
        raw_intensities={"Cr52": 1250.0, "Sc45": 50000.0}, # ratio = 0.025 -> ~24 ug/L
    )
    batch.add_sample(u1)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "liquid_direct.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["Cr52"],
        instrument_loqs={"Cr52": 0.5},
    )

    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws = wb.active

    # 1. Verify Calibration formulas
    # Slope, Intercept, RSQ in parameter rows (rows 10, 11, 12)
    slope_cell = ws.cell(row=10, column=4).value
    intercept_cell = ws.cell(row=11, column=4).value
    rsq_cell = ws.cell(row=12, column=4).value
    assert str(slope_cell).startswith("=SLOPE(")
    assert str(intercept_cell).startswith("=INTERCEPT(")
    assert str(rsq_cell).startswith("=RSQ(")

    # 2. Verify Sample Measurements formulas (Sample row 16)
    # Col 1: ID, Col 2: Type, Col 3: Matrix, Col 4: Dilution, Col 5: Ratio, Col 6: Instr Conc, Col 7: Sample LoQ, Col 8: Final Conc
    r_sample = 16
    assert ws.cell(row=r_sample, column=1).value == "WATER_01"
    assert ws.cell(row=r_sample, column=4).value == 1.0

    instr_formula = str(ws.cell(row=r_sample, column=6).value)
    loq_formula = str(ws.cell(row=r_sample, column=7).value)
    final_formula = str(ws.cell(row=r_sample, column=8).value)

    assert instr_formula.startswith("=(") and "/$D$10" in instr_formula
    assert loq_formula == "=$D$13*D16"
    assert final_formula == "=F16*D16"

    # 3. Verify Client Report (Row 20)
    assert ws.cell(row=20, column=1).value == "WATER_01"
    client_formula = str(ws.cell(row=20, column=2).value)
    assert client_formula.startswith("=IF(H16<G16")


def test_excel_formulas_liquid_unit_conversion(tmp_path):
    """TC-02 & TC-03: Liquid samples with dilution and unit conversion (ug/L vs mg/L)."""
    batch = Batch(name="LiquidUnitBatch")
    batch.add_analyte(Analyte("Na23", "Na", 23))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Na23"] = "Sc45"

    _build_calibration_standards(batch, ["Na23"], [0.0, 100.0, 250.0, 500.0])

    u = Sample(
        sample_id="EFFLUENT_100X",
        sample_type=SampleType.UNKNOWN,
        sample_name="EFFLUENT_100X",
        matrix=SampleMatrix.LIQUID,
        dilution_factor=100.0,
        raw_intensities={"Na23": 5000.0, "Sc45": 50000.0},
    )
    batch.add_sample(u)

    proc = Processor(batch)
    proc.process()

    # Case A: Export in ug/L
    out_ug = tmp_path / "liquid_ug.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_ug,
        analytes=["Na23"],
        instrument_loqs={"Na23": 1.0},
        unit="ug/L",
    )
    wb_ug = openpyxl.load_workbook(out_ug, data_only=False)
    ws_ug = wb_ug.active
    # In ug/L, Final Conc is =Conc * Dilution
    assert ws_ug.cell(row=16, column=8).value == "=F16*D16"
    assert ws_ug.cell(row=16, column=7).value == "=$D$13*D16"

    # Case B: Export in mg/L
    out_mg = tmp_path / "liquid_mg.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_mg,
        analytes=["Na23"],
        instrument_loqs={"Na23": 1.0},
        unit="mg/L",
    )
    wb_mg = openpyxl.load_workbook(out_mg, data_only=False)
    ws_mg = wb_mg.active
    # In mg/L, Final Conc and LoQ formulas must include /1000 natively on numeric cells
    assert ws_mg.cell(row=16, column=8).value == "=F16*D16/1000"
    assert ws_mg.cell(row=16, column=7).value == "=$D$13*D16/1000"
    # Client report formula references those mg/L cells directly
    assert ws_mg.cell(row=20, column=2).value == '=IF(H16<G16, "< " & TEXT(G16, "0.00"), ROUND(H16, 2))'


def test_excel_formulas_solid_digestion_and_moisture(tmp_path):
    """TC-04 & TC-05 & TC-06: Solid samples with digestion math, humidity correction, and dilution."""
    batch = Batch(name="SoilBatch")
    batch.add_analyte(Analyte("Pb208", "Pb", 208))
    batch.add_analyte(Analyte("Rh103", "Rh", 103, is_internal_standard=True))
    batch.analyte_to_is["Pb208"] = "Rh103"

    _build_calibration_standards(batch, ["Pb208"], [0.0, 10.0, 50.0, 100.0])

    # Solid 1: Digestion simple (mass 0.5g, vol 50mL, hum 0%, dilution 1.0)
    s1 = Sample(
        sample_id="SOIL_DRY",
        sample_type=SampleType.UNKNOWN,
        sample_name="SOIL_DRY",
        matrix=SampleMatrix.SOLID,
        mass=0.5,
        final_volume=50.0,
        percent_humidity=0.0,
        dilution_factor=1.0,
        raw_intensities={"Pb208": 2500.0, "Rh103": 50000.0},
    )
    # Solid 2: With moisture (mass 1.0g, vol 50mL, hum 25%, dilution 1.0 -> dry mass 0.75g)
    s2 = Sample(
        sample_id="SOIL_WET",
        sample_type=SampleType.UNKNOWN,
        sample_name="SOIL_WET",
        matrix=SampleMatrix.SOLID,
        mass=1.0,
        final_volume=50.0,
        percent_humidity=25.0,
        dilution_factor=1.0,
        raw_intensities={"Pb208": 2500.0, "Rh103": 50000.0},
    )
    # Solid 3: With digestion + extra dilution 1:10 (DF = 10.0)
    s3 = Sample(
        sample_id="SOIL_HOT_DIL",
        sample_type=SampleType.UNKNOWN,
        sample_name="SOIL_HOT_DIL",
        matrix=SampleMatrix.SOLID,
        mass=0.5,
        final_volume=50.0,
        percent_humidity=0.0,
        dilution_factor=10.0,
        raw_intensities={"Pb208": 2500.0, "Rh103": 50000.0},
    )
    batch.add_sample(s1)
    batch.add_sample(s2)
    batch.add_sample(s3)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "solid_report.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["Pb208"],
        instrument_loqs={"Pb208": 0.1},
    )

    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws = wb.active

    # Check solid metadata columns:
    # Col 1: ID, Col 2: Type, Col 3: Matrix, Col 4: Dilution, Col 5: Mass (g), Col 6: % Humidity, Col 7: Vol (mL)
    assert ws.cell(row=15, column=5).value == "Mass (g)"
    assert ws.cell(row=15, column=6).value == "% Humidity"
    assert ws.cell(row=15, column=7).value == "Vol (mL)"

    # Check formulas for sample 1 (Row 16):
    # Col 8: Ratio, Col 9: Instr Conc, Col 10: Sample LoQ, Col 11: Final Conc
    r1 = 16
    assert ws.cell(row=r1, column=4).value == 1.0 # Dilution
    assert ws.cell(row=r1, column=5).value == 0.5 # Mass
    assert ws.cell(row=r1, column=6).value == 0.0 # Humidity
    assert ws.cell(row=r1, column=7).value == 50.0 # Volume

    loq_f1 = str(ws.cell(row=r1, column=10).value)
    final_f1 = str(ws.cell(row=r1, column=11).value)
    # Expected formula pattern: =((Conc)*(G16/1000)*D16)/(E16*(1-F16/100))
    assert "(G16/1000)" in final_f1
    assert "*D16" in final_f1
    assert "/(E16*(1-F16/100))" in final_f1

    # Check sample 2 (Row 17): % Humidity is 25.0
    r2 = 17
    assert ws.cell(row=r2, column=6).value == 25.0
    final_f2 = str(ws.cell(row=r2, column=11).value)
    assert "/(E17*(1-F17/100))" in final_f2

    # Check sample 3 (Row 18): Dilution is 10.0
    r3 = 18
    assert ws.cell(row=r3, column=4).value == 10.0
    final_f3 = str(ws.cell(row=r3, column=11).value)
    assert "*D18" in final_f3


def test_excel_formulas_method_blank_subtraction(tmp_path):
    """TC-07: Selective method blank subtraction by prep_group."""
    batch = Batch(name="MblkBatch")
    batch.add_analyte(Analyte("Cd111", "Cd", 111))
    batch.add_analyte(Analyte("Y89", "Y", 89, is_internal_standard=True))
    batch.analyte_to_is["Cd111"] = "Y89"

    _build_calibration_standards(batch, ["Cd111"], [0.0, 10.0, 50.0, 100.0])

    # Method blank for Batch A (contamination: 1.0 ug/L -> ratio = 0.051)
    mblk = Sample(
        sample_id="MBLK_A",
        sample_type=SampleType.METHOD_BLANK,
        prep_group="BATCH_A",
        matrix=SampleMatrix.SOLID,
        mass=0.5,
        final_volume=50.0,
        raw_intensities={"Cd111": 2550.0, "Y89": 50000.0},
    )
    # Unknown in Batch A (should subtract MBLK_A)
    u_a = Sample(
        sample_id="SAMPLE_A",
        sample_type=SampleType.UNKNOWN,
        prep_group="BATCH_A",
        matrix=SampleMatrix.SOLID,
        mass=0.5,
        final_volume=50.0,
        raw_intensities={"Cd111": 5000.0, "Y89": 50000.0},
    )
    # Direct Liquid sample without prep_group (should NOT subtract MBLK)
    u_dir = Sample(
        sample_id="WATER_DIRECT",
        sample_type=SampleType.UNKNOWN,
        prep_group=None,
        matrix=SampleMatrix.LIQUID,
        raw_intensities={"Cd111": 3000.0, "Y89": 50000.0},
    )
    batch.add_sample(mblk)
    batch.add_sample(u_a)
    batch.add_sample(u_dir)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "mblk_report.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["Cd111"],
    )

    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws = wb.active

    # When method blank is present, a Blank-Corr column is inserted
    # MBLK_A is at row 16, SAMPLE_A at row 17, WATER_DIRECT at row 18
    # Ratio is Col 8, Instr Conc is Col 9, Blank-Corr is Col 10
    assert ws.cell(row=15, column=10).value == "Cd111 Blank-Corr (ug/L)"

    # MBLK row itself does not subtract
    assert ws.cell(row=16, column=10).value == "=I16"

    # SAMPLE_A subtracts MBLK_A: =I17-$I$16
    assert ws.cell(row=17, column=10).value == "=I17-$I$16"

    # WATER_DIRECT does not have matching blank, so it evaluates =I18
    assert ws.cell(row=18, column=10).value == "=I18"


def test_excel_formulas_loq_evaluation_logic(tmp_path):
    """TC-08: Logical evaluation of < LoQ in client report."""
    batch = Batch(name="LoqLogicBatch")
    batch.add_analyte(Analyte("As75", "As", 75))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["As75"] = "Sc45"

    _build_calibration_standards(batch, ["As75"], [0.0, 10.0, 50.0, 100.0])

    # Sample below LoQ: raw ratio ~ 0.001 -> Conc ~ 0.0 ug/L
    s_low = Sample(
        sample_id="SAMPLE_BELOW_LOQ",
        sample_type=SampleType.UNKNOWN,
        sample_name="SAMPLE_BELOW_LOQ",
        matrix=SampleMatrix.LIQUID,
        raw_intensities={"As75": 50.0, "Sc45": 50000.0},
    )
    # Sample above LoQ: raw ratio ~ 0.50 -> Conc ~ 10.0 ug/L
    s_high = Sample(
        sample_id="SAMPLE_ABOVE_LOQ",
        sample_type=SampleType.UNKNOWN,
        sample_name="SAMPLE_ABOVE_LOQ",
        matrix=SampleMatrix.LIQUID,
        raw_intensities={"As75": 25000.0, "Sc45": 50000.0},
    )
    batch.add_sample(s_low)
    batch.add_sample(s_high)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "loq_report.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["As75"],
        instrument_loqs={"As75": 1.0}, # LoQ = 1.0 ug/L
    )

    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws = wb.active

    # Check Client Report formulas
    # Client rows at row 21 and 22
    f_low = ws.cell(row=21, column=2).value
    f_high = ws.cell(row=22, column=2).value
    assert str(f_low).startswith("=IF(")
    assert str(f_high).startswith("=IF(")
    assert '< " & TEXT(' in str(f_low)
    assert 'ROUND(' in str(f_high)


def test_excel_formulas_split_dilution_three_sheets(tmp_path):
    """TC-10: Three-sheet split dilution workbook with active links and no text division errors."""
    batch = Batch(name="SplitBatch")
    batch.add_analyte(Analyte("Na23", "Na", 23))
    batch.add_analyte(Analyte("Pb208", "Pb", 208))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.add_analyte(Analyte("Rh103", "Rh", 103, is_internal_standard=True))
    batch.analyte_to_is["Na23"] = "Sc45"
    batch.analyte_to_is["Pb208"] = "Rh103"

    _build_calibration_standards(batch, ["Na23", "Pb208"], [0.0, 10.0, 100.0])

    # Diluted sample (for Na)
    s_dil = Sample(
        sample_id="RIVER_DIL",
        sample_name="RIVER_SAMPLE",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.LIQUID,
        dilution_factor=100.0,
        raw_intensities={"Na23": 50000.0, "Pb208": 50.0, "Sc45": 50000.0, "Rh103": 50000.0},
    )
    # Undiluted sample (for Pb)
    s_undil = Sample(
        sample_id="RIVER_UNDIL",
        sample_name="RIVER_SAMPLE",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.LIQUID,
        dilution_factor=1.0,
        raw_intensities={"Na23": 500000.0, "Pb208": 2500.0, "Sc45": 50000.0, "Rh103": 50000.0},
    )
    batch.add_sample(s_dil)
    batch.add_sample(s_undil)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "split_dilution_3_sheets.xlsx"
    export_split_dilution_report(
        batch=batch,
        output_path=out_xlsx,
        high_analytes=["Na23"],
        low_analytes=["Pb208"],
        high_units="mg/L",
        low_units="ug/L",
        instrument_loqs={"Na23": 0.5, "Pb208": 0.1},
    )

    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    assert wb.sheetnames == ["Analitos Altos", "Analitos Bajos", "Reporte Unificado"]

    # Check Sheet 1 (Analitos Altos):
    # In mg/L, the Final Conc and LoQ must have /1000 in Section 2, and Section 3 must have unit (mg/L)
    ws_high = wb["Analitos Altos"]
    assert ws_high.cell(row=18, column=2).value == "Na (mg/L)"
    final_conc_f = str(ws_high.cell(row=15, column=8).value)
    assert "/1000" in final_conc_f

    # Check Sheet 3 (Reporte Unificado):
    # Must link to Section 3 without any '/ 1000' arithmetic that would fail on '< LoQ'
    ws_unif = wb["Reporte Unificado"]
    assert ws_unif.cell(row=4, column=1).value == "Sample ID"
    assert ws_unif.cell(row=4, column=2).value == "Na (mg/L)"
    assert ws_unif.cell(row=4, column=3).value == "Pb (ug/L)"

    # Sample row 5
    assert ws_unif.cell(row=5, column=1).value == "RIVER_SAMPLE"
    link_high = str(ws_unif.cell(row=5, column=2).value)
    link_low = str(ws_unif.cell(row=5, column=3).value)

    assert link_high.startswith("='Analitos Altos'!")
    assert "/ 1000" not in link_high # Critical check: no division on string!
    assert link_low.startswith("='Analitos Bajos'!")


def test_excel_formulas_mixed_batch(tmp_path):
    """TC-09: Mixed batch containing both Liquid and Solid samples in the same Excel report."""
    batch = Batch(name="MixedBatch")
    batch.add_analyte(Analyte("Cu63", "Cu", 63))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Cu63"] = "Sc45"

    _build_calibration_standards(batch, ["Cu63"], [0.0, 10.0, 50.0])

    # Liquid sample (direct, DF=1)
    s_liq = Sample(
        sample_id="EFFLUENT",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.LIQUID,
        dilution_factor=1.0,
        raw_intensities={"Cu63": 2500.0, "Sc45": 50000.0},
    )
    # Solid sample (digested: 0.5g, 50mL, 10% hum, DF=2.0)
    s_sol = Sample(
        sample_id="SLUDGE",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.SOLID,
        mass=0.5,
        final_volume=50.0,
        percent_humidity=10.0,
        dilution_factor=2.0,
        raw_intensities={"Cu63": 5000.0, "Sc45": 50000.0},
    )
    batch.add_sample(s_liq)
    batch.add_sample(s_sol)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "mixed_batch.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["Cu63"],
    )

    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws = wb.active

    # When solid matrix is present in target samples, Mass/Hum/Vol columns are present
    assert ws.cell(row=14, column=5).value == "Mass (g)"
    assert ws.cell(row=14, column=6).value == "% Humidity"
    assert ws.cell(row=14, column=7).value == "Vol (mL)"

    # Liquid row 15: Liquid formula =Conc * Dilution
    r_liq = 15
    assert ws.cell(row=r_liq, column=3).value == "Liquid"
    f_liq = str(ws.cell(row=r_liq, column=11).value)
    assert f_liq == "=I15*D15"

    # Solid row 16: Solid formula includes prep math
    r_sol = 16
    assert ws.cell(row=r_sol, column=3).value == "Solid"
    f_sol = str(ws.cell(row=r_sol, column=11).value)
    assert "(G16/1000)" in f_sol
    assert "/(E16*(1-F16/100))" in f_sol


def test_excel_formulas_piecewise_calibration(tmp_path):
    """TC-11: Piecewise calibration curves with specific standard subsets per analyte."""
    batch = Batch(name="PiecewiseBatch")
    batch.add_analyte(Analyte("Cr52", "Cr", 52))
    batch.add_analyte(Analyte("Pb208", "Pb", 208))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Cr52"] = "Sc45"
    batch.analyte_to_is["Pb208"] = "Sc45"

    # Standards for Cr: S_Cr_0, S_Cr_1, S_Cr_2
    for idx, lvl in enumerate([0.0, 10.0, 50.0]):
        s = Sample(
            sample_id=f"S_Cr_{idx}",
            sample_type=SampleType.BLANK if lvl == 0 else SampleType.STANDARD,
            known_concentrations={"Cr52": float(lvl)},
            raw_intensities={"Cr52": (0.05 * lvl + 0.001) * 50000.0, "Sc45": 50000.0},
        )
        batch.add_sample(s)

    # Standards for Pb: S_Pb_0, S_Pb_1
    for idx, lvl in enumerate([0.0, 20.0]):
        s = Sample(
            sample_id=f"S_Pb_{idx}",
            sample_type=SampleType.BLANK if lvl == 0 else SampleType.STANDARD,
            known_concentrations={"Pb208": float(lvl)},
            raw_intensities={"Pb208": (0.03 * lvl + 0.001) * 50000.0, "Sc45": 50000.0},
        )
        batch.add_sample(s)

    u = Sample(
        sample_id="SAMPLE_X",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.LIQUID,
        raw_intensities={"Cr52": 2500.0, "Pb208": 1500.0, "Sc45": 50000.0},
    )
    batch.add_sample(u)

    out_xlsx = tmp_path / "piecewise_report.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["Cr52", "Pb208"],
    )

    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws = wb.active

    # Cr standards are in rows 6, 7, 8
    # Pb standards are in rows 9, 10
    # Slope for Cr should reference rows 6:8
    # Slope for Pb should reference rows 9:10
    slope_row = 11
    cr_slope_f = str(ws.cell(row=slope_row, column=4).value)
    pb_slope_f = str(ws.cell(row=slope_row, column=6).value)

    assert "6:D8" in cr_slope_f
    assert "9:F10" in pb_slope_f


def _evaluate_with_libreoffice(xlsx_path: Path) -> openpyxl.Workbook:
    """Evaluates formulas in an Excel file using headless LibreOffice."""
    import subprocess
    import shutil

    if not shutil.which("libreoffice"):
        pytest.skip("libreoffice not available for headless formula evaluation")

    td = xlsx_path.parent / f"eval_{xlsx_path.stem}"
    td.mkdir(exist_ok=True)
    ods_path = td / (xlsx_path.stem + ".ods")

    subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "ods", "--outdir", str(td), str(xlsx_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "xlsx", str(ods_path), "--outdir", str(td)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return openpyxl.load_workbook(td / xlsx_path.name, data_only=True)


def test_sample_invariants_validation():
    """Verify that Sample raises ValueError on invalid physical parameters."""
    with pytest.raises(ValueError, match="mass must be positive"):
        Sample("S", SampleType.UNKNOWN, mass=0)

    with pytest.raises(ValueError, match="mass must be positive"):
        Sample("S", SampleType.UNKNOWN, mass=-0.5)

    with pytest.raises(ValueError, match="Final volume must be positive"):
        Sample("S", SampleType.UNKNOWN, final_volume=0)

    with pytest.raises(ValueError, match="Dilution factor must be positive"):
        Sample("S", SampleType.UNKNOWN, dilution_factor=0)

    with pytest.raises(ValueError, match="Percent humidity must be in range"):
        Sample("S", SampleType.UNKNOWN, percent_humidity=-1.0)

    with pytest.raises(ValueError, match="Percent humidity must be in range"):
        Sample("S", SampleType.UNKNOWN, percent_humidity=100.0)


def test_excel_formulas_blank_offset_numerical_parity(tmp_path):
    """Verify blank_offset formula generation and exact numerical parity with Processor."""
    batch = Batch(name="BlankOffsetBatch")
    batch.add_analyte(Analyte("Cr52", "Cr", 52))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Cr52"] = "Sc45"

    _build_calibration_standards(batch, ["Cr52"], [0.0, 10.0, 50.0, 100.0])

    u = Sample(
        sample_id="SAMPLE_BO",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.LIQUID,
        dilution_factor=2.0,
        raw_intensities={"Cr52": 1500.0, "Sc45": 50000.0},
    )
    batch.add_sample(u)

    proc = Processor(batch, weighting="blank_offset")
    proc.process()

    out_xlsx = tmp_path / "blank_offset_report.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["Cr52"],
        weighting="blank_offset",
    )

    wb_raw = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws_raw = wb_raw.active

    # Row 10: Slope, Row 11: Intercept, Row 12: R2
    slope_f = str(ws_raw.cell(row=10, column=4).value)
    int_f = str(ws_raw.cell(row=11, column=4).value)
    rsq_f = str(ws_raw.cell(row=12, column=4).value)

    assert "SUMPRODUCT" in slope_f
    assert "SUMSQ" in slope_f
    assert int_f == "=D6"  # Row 6 is S0 (blank)
    assert "DEVSQ" in rsq_f

    # Evaluate with LibreOffice Calc and verify exact parity
    wb_eval = _evaluate_with_libreoffice(out_xlsx)
    ws_eval = wb_eval.active

    model = proc.calibration_models["Cr52"]
    eval_slope = float(ws_eval.cell(row=10, column=4).value)
    eval_intercept = float(ws_eval.cell(row=11, column=4).value)
    eval_rsq = float(ws_eval.cell(row=12, column=4).value)

    assert eval_slope == pytest.approx(model.slope, rel=1e-5)
    assert eval_intercept == pytest.approx(model.intercept, rel=1e-5)
    assert eval_rsq == pytest.approx(model.r_squared, rel=1e-4)

    # Check evaluated final concentration
    eval_final = float(ws_eval.cell(row=16, column=8).value)
    assert eval_final == pytest.approx(u.final_concentrations["Cr52"], rel=1e-4)


def test_excel_formulas_multiple_method_blanks_averaging(tmp_path):
    """Verify that multiple method blanks in the same prep_group are averaged in Excel."""
    batch = Batch(name="MultiMblkBatch")
    batch.add_analyte(Analyte("Pb208", "Pb", 208))
    batch.add_analyte(Analyte("Rh103", "Rh", 103, is_internal_standard=True))
    batch.analyte_to_is["Pb208"] = "Rh103"

    _build_calibration_standards(batch, ["Pb208"], [0.0, 10.0, 50.0])

    # Two method blanks in BATCH_M
    # MBLK 1: ratio = 0.005 -> conc ~ 0.08 ug/L
    mb1 = Sample(
        sample_id="MBLK_1",
        sample_type=SampleType.METHOD_BLANK,
        prep_group="BATCH_M",
        matrix=SampleMatrix.SOLID,
        mass=0.5,
        final_volume=50.0,
        raw_intensities={"Pb208": 250.0, "Rh103": 50000.0},
    )
    # MBLK 2: ratio = 0.010 -> conc ~ 0.18 ug/L
    mb2 = Sample(
        sample_id="MBLK_2",
        sample_type=SampleType.METHOD_BLANK,
        prep_group="BATCH_M",
        matrix=SampleMatrix.SOLID,
        mass=0.5,
        final_volume=50.0,
        raw_intensities={"Pb208": 500.0, "Rh103": 50000.0},
    )
    # Unknown in BATCH_M
    unk = Sample(
        sample_id="SAMPLE_SOLID",
        sample_type=SampleType.UNKNOWN,
        prep_group="BATCH_M",
        matrix=SampleMatrix.SOLID,
        mass=0.5,
        final_volume=50.0,
        dilution_factor=2.0,
        raw_intensities={"Pb208": 5000.0, "Rh103": 50000.0},
    )
    batch.add_sample(mb1)
    batch.add_sample(mb2)
    batch.add_sample(unk)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "multi_mblk_report.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["Pb208"],
    )

    wb_raw = openpyxl.load_workbook(out_xlsx, data_only=False)
    ws_raw = wb_raw.active

    # Sample is at row 17. Blank-Corr formula must contain AVERAGE of both MBLK rows
    bcorr_formula = str(ws_raw.cell(row=17, column=10).value)
    assert "AVERAGE(" in bcorr_formula
    assert "$I$15" in bcorr_formula
    assert "$I$16" in bcorr_formula

    # Numerical verification via LibreOffice
    wb_eval = _evaluate_with_libreoffice(out_xlsx)
    ws_eval = wb_eval.active

    eval_final = float(ws_eval.cell(row=17, column=12).value)
    assert eval_final == pytest.approx(unk.final_concentrations["Pb208"], rel=1e-4)


def test_excel_formulas_numerical_ground_truth_parity(tmp_path):
    """Full end-to-end numerical check: verify 0 Excel errors and full parity with Python."""
    batch = Batch(name="ParityBatch")
    batch.add_analyte(Analyte("Cu63", "Cu", 63))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Cu63"] = "Sc45"

    _build_calibration_standards(batch, ["Cu63"], [0.0, 10.0, 50.0, 100.0])

    s_liq = Sample(
        sample_id="LIQ_SAMPLE",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.LIQUID,
        dilution_factor=5.0,
        raw_intensities={"Cu63": 3000.0, "Sc45": 50000.0},
    )
    s_sol = Sample(
        sample_id="SOL_SAMPLE",
        sample_type=SampleType.UNKNOWN,
        matrix=SampleMatrix.SOLID,
        mass=0.5000,
        final_volume=50.0,
        percent_humidity=15.0,
        dilution_factor=2.0,
        raw_intensities={"Cu63": 8000.0, "Sc45": 50000.0},
    )
    batch.add_sample(s_liq)
    batch.add_sample(s_sol)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "parity_report.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        analytes=["Cu63"],
        instrument_loqs={"Cu63": 0.05},
    )

    wb_eval = _evaluate_with_libreoffice(out_xlsx)
    ws_eval = wb_eval.active

    # 1. Ensure NO error codes exist in any cell
    for row in ws_eval.iter_rows(values_only=True):
        for cell_val in row:
            val_str = str(cell_val or "")
            for err_tag in ["#VALUE!", "#REF!", "#DIV/0!", "#NAME?", "#N/A", "Err:"]:
                assert err_tag not in val_str, f"Found Excel error {err_tag} in cell value: {val_str}"

    # 2. Check parity of final concentrations
    # Row 16: Liquid sample -> Col 11
    eval_liq = float(ws_eval.cell(row=16, column=11).value)
    assert eval_liq == pytest.approx(s_liq.final_concentrations["Cu63"], rel=1e-4)

    # Row 17: Solid sample -> Col 11
    eval_sol = float(ws_eval.cell(row=17, column=11).value)
    assert eval_sol == pytest.approx(s_sol.final_concentrations["Cu63"], rel=1e-4)


