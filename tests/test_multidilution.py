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
    select_optimal_dilution,
    export_multidilution_report,
)


def test_select_optimal_dilution():
    """Verify auto-ranging logic selects the best dilution factor."""
    # Create 3 dilutions for the same sample: 1x, 10x, 100x
    s1 = Sample("WATER_1X", SampleType.UNKNOWN, sample_name="WATER", dilution_factor=1.0)
    s10 = Sample("WATER_10X", SampleType.UNKNOWN, sample_name="WATER", dilution_factor=10.0)
    s100 = Sample("WATER_100X", SampleType.UNKNOWN, sample_name="WATER", dilution_factor=100.0)

    # Analyte Pb: trace element, in 1x conc is 2.5 ug/L, in 100x drops < LoQ (0.02)
    s1.instrument_concentrations["Pb208"] = 2.5
    s10.instrument_concentrations["Pb208"] = 0.25
    s100.instrument_concentrations["Pb208"] = 0.02

    # Analyte Na: major element, in 1x conc is 500 ug/L (saturates std curve max 100), in 100x conc is 5.0 ug/L
    s1.instrument_concentrations["Na23"] = 500.0
    s10.instrument_concentrations["Na23"] = 50.0
    s100.instrument_concentrations["Na23"] = 5.0

    samples = [s1, s10, s100]

    # For Pb (trace): should pick 1x (DF=1.0) because 2.5 is well within range [0.1, 100]
    best_pb = select_optimal_dilution(samples, analyte="Pb208", max_standard_conc=100.0, loq=0.1)
    assert best_pb.dilution_factor == 1.0

    # For Na (major): 10x is 50.0 (in range [0.1, 100]), 100x is 5.0 (in range [0.1, 100]).
    # 10x is preferred as the lowest in-range dilution for highest precision
    best_na = select_optimal_dilution(samples, analyte="Na23", max_standard_conc=100.0, loq=0.1)
    assert best_na.dilution_factor == 10.0


def test_export_multidilution_report(tmp_path):
    """Verify export of N-dilution report with dynamic unified client sheet."""
    batch = Batch(name="MultiDilBatch")
    batch.add_analyte(Analyte("Na23", "Na", 23))
    batch.add_analyte(Analyte("Pb208", "Pb", 208))
    batch.add_analyte(Analyte("Sc45", "Sc", 45, is_internal_standard=True))
    batch.analyte_to_is["Na23"] = "Sc45"
    batch.analyte_to_is["Pb208"] = "Sc45"

    # Calibration standards
    s0 = Sample("S0", SampleType.BLANK, raw_intensities={"Na23": 100.0, "Pb208": 50.0, "Sc45": 50000.0}, known_concentrations={"Na23": 0.0, "Pb208": 0.0})
    s1 = Sample("S1", SampleType.STANDARD, raw_intensities={"Na23": 5000.0, "Pb208": 5000.0, "Sc45": 50000.0}, known_concentrations={"Na23": 100.0, "Pb208": 100.0})
    batch.add_sample(s0)
    batch.add_sample(s1)

    # 3 dilution levels: 1x, 10x, 100x
    for df in [1.0, 10.0, 100.0]:
        s = Sample(
            f"RIVER_{int(df)}X",
            SampleType.UNKNOWN,
            sample_name="RIVER_A",
            dilution_factor=df,
            raw_intensities={"Na23": 2500.0, "Pb208": 2500.0, "Sc45": 50000.0},
        )
        batch.add_sample(s)

    proc = Processor(batch)
    proc.process()

    out_xlsx = tmp_path / "multidilution_report.xlsx"
    export_multidilution_report(
        batch=batch,
        output_path=out_xlsx,
        instrument_loqs={"Na23": 0.5, "Pb208": 0.1},
    )

    assert out_xlsx.exists()
    wb = openpyxl.load_workbook(out_xlsx, data_only=False)
    assert "Reporte Unificado" in wb.sheetnames
    assert "DF_1x" in wb.sheetnames
    assert "DF_10x" in wb.sheetnames
    assert "DF_100x" in wb.sheetnames

    ws_unif = wb["Reporte Unificado"]
    assert ws_unif.cell(row=4, column=1).value == "Sample ID"
    # Row 5 is RIVER_A
    assert ws_unif.cell(row=5, column=1).value == "RIVER_A"
    formula_na = str(ws_unif.cell(row=5, column=2).value)
    assert formula_na.startswith("='DF_")
