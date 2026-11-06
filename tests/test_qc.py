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
    QCEvaluator,
    get_qc_summary,
    export_excel_formula_report,
)


def test_is_recovery_calculation_and_limits():
    """Verify % ISTD recovery calculation relative to CalBlk."""
    batch = Batch(name="ISTD_Batch")
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.add_analyte(Analyte("Cr52", "Cr", 52), internal_standard_name="Sc45")

    # Initial CalBlk with 50,000 CPS
    b0 = Sample("BLK", SampleType.BLANK, raw_intensities={"Sc45": 50000.0, "Cr52": 100.0})
    # Sample with normal ISTD (45,000 CPS -> 90% recovery)
    s_norm = Sample("NORM", SampleType.UNKNOWN, raw_intensities={"Sc45": 45000.0, "Cr52": 2500.0})
    # Sample with suppressed ISTD (25,000 CPS -> 50% recovery -> Out of limits)
    s_supp = Sample("SUPP", SampleType.UNKNOWN, raw_intensities={"Sc45": 25000.0, "Cr52": 2500.0})

    batch.add_sample(b0)
    batch.add_sample(s_norm)
    batch.add_sample(s_supp)

    proc = Processor(batch)
    proc.process()

    assert s_norm.is_recovery["Sc45"] == pytest.approx(90.0)
    assert s_supp.is_recovery["Sc45"] == pytest.approx(50.0)

    evaluator = QCEvaluator(batch, is_recovery_limits=(70.0, 120.0))
    results = evaluator.evaluate_is_recoveries()
    res_map = {r.sample_id: r for r in results}

    assert res_map["NORM"].status == "PASS"
    assert res_map["SUPP"].status == "FAIL"


def test_ccv_and_crm_evaluation():
    """Verify check standard (CCV and CRM) recovery evaluation."""
    batch = Batch(name="QC_Batch")
    batch.add_analyte(Analyte("Pb208", "Pb", 208))
    batch.add_analyte(Analyte("Rh103", "Rh", 103, is_internal_standard=True))
    batch.analyte_to_is["Pb208"] = "Rh103"

    # Standards S0 (0) and S1 (10 ug/L)
    s0 = Sample("S0", SampleType.BLANK, raw_intensities={"Pb208": 50.0, "Rh103": 50000.0}, known_concentrations={"Pb208": 0.0})
    s1 = Sample("S1", SampleType.STANDARD, raw_intensities={"Pb208": 5050.0, "Rh103": 50000.0}, known_concentrations={"Pb208": 10.0})
    batch.add_sample(s0)
    batch.add_sample(s1)

    # CCV: target 10.0 ug/L, measured ~ 9.5 ug/L -> 95% recovery (PASS)
    ccv = Sample(
        "CCV_1",
        SampleType.QC,
        sample_name="CCV_1",
        raw_intensities={"Pb208": 4800.0, "Rh103": 50000.0},
        expected_concentrations={"Pb208": 10.0},
    )
    # CRM: target 50.0 ug/L, measured ~ 35.0 ug/L -> 70% recovery (FAIL, limit 80-120%)
    crm = Sample(
        "CRM_SOIL",
        SampleType.QC,
        sample_name="CRM_SOIL",
        raw_intensities={"Pb208": 17550.0, "Rh103": 50000.0},
        expected_concentrations={"Pb208": 50.0},
    )
    batch.add_sample(ccv)
    batch.add_sample(crm)

    proc = Processor(batch)
    proc.process()

    evaluator = QCEvaluator(batch)
    results = evaluator.evaluate_check_standards()
    res_map = {r.sample_id: r for r in results}

    assert res_map["CCV_1"].status == "PASS"
    assert pytest.approx(res_map["CCV_1"].recovery_or_rpd, 0.5) == 95.0

    assert res_map["CRM_SOIL"].status == "FAIL"
    assert pytest.approx(res_map["CRM_SOIL"].recovery_or_rpd, 0.5) == 70.0


def test_duplicates_rpd_evaluation():
    """Verify duplicate RPD calculation."""
    batch = Batch(name="DupBatch")
    batch.add_analyte(Analyte("Cu63", "Cu", 63))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Cu63"] = "Sc45"

    s0 = Sample("S0", SampleType.BLANK, raw_intensities={"Cu63": 50.0, "Sc45": 50000.0}, known_concentrations={"Cu63": 0.0})
    s1 = Sample("S1", SampleType.STANDARD, raw_intensities={"Cu63": 5050.0, "Sc45": 50000.0}, known_concentrations={"Cu63": 10.0})
    batch.add_sample(s0)
    batch.add_sample(s1)

    # Parent sample: ~ 10 ug/L
    parent = Sample("WATER_01", SampleType.UNKNOWN, raw_intensities={"Cu63": 5050.0, "Sc45": 50000.0})
    # Good duplicate: ~ 10.5 ug/L -> RPD ~ 4.9% (PASS)
    dup_good = Sample(
        "WATER_01_DUP",
        SampleType.DUPLICATE,
        parent_sample_id="WATER_01",
        raw_intensities={"Cu63": 5300.0, "Sc45": 50000.0},
    )
    batch.add_sample(parent)
    batch.add_sample(dup_good)

    proc = Processor(batch)
    proc.process()

    evaluator = QCEvaluator(batch, dup_rpd_max=10.0)
    results = evaluator.evaluate_duplicates()
    assert len(results) == 1
    assert results[0].status == "PASS"
    assert results[0].recovery_or_rpd < 6.0


def test_matrix_spike_evaluation():
    """Verify matrix spike recovery calculation."""
    batch = Batch(name="SpikeBatch")
    batch.add_analyte(Analyte("As75", "As", 75))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["As75"] = "Sc45"

    s0 = Sample("S0", SampleType.BLANK, raw_intensities={"As75": 50.0, "Sc45": 50000.0}, known_concentrations={"As75": 0.0})
    s1 = Sample("S1", SampleType.STANDARD, raw_intensities={"As75": 5050.0, "Sc45": 50000.0}, known_concentrations={"As75": 10.0})
    batch.add_sample(s0)
    batch.add_sample(s1)

    # Unspiked parent: ~ 5 ug/L
    parent = Sample("RIVER_01", SampleType.UNKNOWN, raw_intensities={"As75": 2550.0, "Sc45": 50000.0})
    # Spiked: added 10 ug/L, measured ~ 15.2 ug/L -> Net added = 10.2 -> Rec = 102% (PASS)
    spiked = Sample(
        "RIVER_01_MS",
        SampleType.SPIKE,
        parent_sample_id="RIVER_01",
        raw_intensities={"As75": 7650.0, "Sc45": 50000.0},
        spike_concentrations={"As75": 10.0},
    )
    batch.add_sample(parent)
    batch.add_sample(spiked)

    proc = Processor(batch)
    proc.process()

    evaluator = QCEvaluator(batch)
    results = evaluator.evaluate_matrix_spikes()
    assert len(results) == 1
    assert results[0].status == "PASS"
    assert pytest.approx(results[0].recovery_or_rpd, 1.0) == 102.0

    df_qc = get_qc_summary(batch)
    assert not df_qc.empty
    assert "SPIKE" in df_qc["QC Type"].values


def test_export_excel_with_qc_sheet(tmp_path):
    """Verify generation of the 'Control de Calidad (QA-QC)' worksheet in Excel."""
    batch = Batch(name="BatchWithQC")
    batch.add_analyte(Analyte("Cr52", "Cr", 52))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Cr52"] = "Sc45"

    s0 = Sample("S0", SampleType.BLANK, raw_intensities={"Cr52": 50.0, "Sc45": 50000.0}, known_concentrations={"Cr52": 0.0})
    s1 = Sample("S1", SampleType.STANDARD, raw_intensities={"Cr52": 5050.0, "Sc45": 50000.0}, known_concentrations={"Cr52": 10.0})
    ccv = Sample("CCV", SampleType.QC, raw_intensities={"Cr52": 5100.0, "Sc45": 50000.0}, expected_concentrations={"Cr52": 10.0})
    u = Sample("UNK", SampleType.UNKNOWN, raw_intensities={"Cr52": 2500.0, "Sc45": 50000.0})

    batch.add_sample(s0)
    batch.add_sample(s1)
    batch.add_sample(ccv)
    batch.add_sample(u)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "report_with_qc.xlsx"
    export_excel_formula_report(
        batch=batch,
        output_path=out_xlsx,
        include_qc_sheet=True,
    )

    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    assert "Control de Calidad (QA-QC)" in wb.sheetnames

    ws_qc = wb["Control de Calidad (QA-QC)"]
    assert ws_qc.cell(row=1, column=1).value == "CONTROL DE CALIDAD ANALÍTICO (ISO 17025 / QA-QC)"
    # Row 4 is header
    assert ws_qc.cell(row=4, column=1).value == "Sample ID"
    assert ws_qc.cell(row=4, column=10).value == "Status"

    # Status column contains PASS
    statuses = [ws_qc.cell(row=r, column=10).value for r in range(5, ws_qc.max_row + 1)]
    assert "PASS" in statuses
