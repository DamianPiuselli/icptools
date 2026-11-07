#!/usr/bin/env python3
"""
Environmental Water Study — Automated Batch Processing and Auditable Report Generation

This script processes an Agilent MassHunter ICP-MS batch measuring river and estuary water:
1. Major cations (Na, Mg, K, Ca) measured at 1:100 dilution and reported in mg/L.
2. Trace metals (Cr, Mn, Fe, Ni, Cu, Zn, As, Cd, Pb) measured undiluted and reported in ug/L.
3. Generates an auditable 3-sheet Excel report with live formulas directly in this folder.

NOTE FOR DEVELOPERS & AGENTS:
Following icptools best practices, this processing script is co-located with the raw data files
(CAL.xlsx and FQ_COUNTS.xlsx) to serve as reproducible documentation of analytical data provenance.
"""
from pathlib import Path
from icptools import (
    parse_agilent_counts,
    parse_agilent_calibration,
    apply_calibration_table,
    Processor,
    export_split_dilution_report,
    get_calibration_summary,
)

# 1. Define folder path (co-located script pattern)
DATA_DIR = Path(__file__).resolve().parent

COUNTS_FILE = DATA_DIR / "FQ_COUNTS.xlsx"
CAL_FILE = DATA_DIR / "CAL.xlsx"
OUTPUT_REPORT = DATA_DIR / "Reporte_Consolidado_3_Pestanias.xlsx"


def main():
    print(f"=== Procesando Corrida Ambiental en: {DATA_DIR.name} ===")

    # 2. Ingest raw instrument counts and calibration table
    print(f"Cargando cuentas instrumentales: {COUNTS_FILE.name}")
    batch = parse_agilent_counts(COUNTS_FILE)

    print(f"Cargando tabla de calibración: {CAL_FILE.name}")
    cal_data = parse_agilent_calibration(CAL_FILE)
    apply_calibration_table(batch, cal_data)

    # 3. Process analytical run
    print("Ejecutando pipeline analítico (normalización de ISTD y calibración)...")
    proc = Processor(batch)
    proc.process()

    # 4. Calibration quality check
    cal_summary = get_calibration_summary(proc)
    print("\n--- Resumen de Curvas de Calibración ---")
    for _, row in cal_summary.iterrows():
        r2 = row["R-squared"]
        status = "OK" if r2 >= 0.995 else "REVISAR"
        print(f"  {row['Analyte']:<10} | R² = {r2:.5f} [{status}]")

    # 5. Define analyte groups
    # High cations measured at 1:100 dilution (reported in mg/L)
    altos = ["Na23", "Mg24", "K39", "Ca44"]
    # Trace elements measured undiluted (reported in ug/L)
    bajos = ["Cr52", "Mn55", "Fe56", "Ni60", "Cu63", "Zn66", "As75", "Cd111", "Pb208"]

    # Typical instrument LoQs (ug/L)
    loqs = {
        "Na23": 0.05,
        "Mg24": 0.05,
        "K39": 0.10,
        "Ca44": 0.10,
        "Cr52": 0.05,
        "Mn55": 0.10,
        "Fe56": 0.50,
        "Ni60": 0.10,
        "Cu63": 0.10,
        "Zn66": 0.50,
        "As75": 0.20,
        "Cd111": 0.01,
        "Pb208": 0.05,
    }

    # 6. Export 3-sheet live formula Excel report
    print(f"\nExportando reporte de 3 pestañas a: {OUTPUT_REPORT.name}")
    export_split_dilution_report(
        batch=batch,
        output_path=OUTPUT_REPORT,
        high_analytes=altos,
        low_analytes=bajos,
        high_units="mg/L",
        low_units="ug/L",
        instrument_loqs=loqs,
        report_title="Monitoreo de Calidad de Agua - Cuenca Ambiental",
        exclude_washes=True,
    )

    print(f"Reporte generado exitosamente con fórmulas nativas vivas en:")
    print(f"  {OUTPUT_REPORT.resolve()}")


if __name__ == "__main__":
    main()
