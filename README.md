# icptools

A batch-centric Python library and CLI for processing **ICP-MS** and **ICP-OES** analytical data, generating audit-ready Excel workbooks with live native formulas.

---

## Key Features

- **Object-Oriented Domain Models**: Represents analytical batches (`Batch`), samples (`Sample`), and elements/isotopes (`Analyte`).
- **Complete Analytical Pipeline**:
  - Internal Standard (IS) normalization and % ISTD recovery tracking.
  - Linear regression calibration with unweighted OLS (`none`), inverse weighting (`1/x`), or anchored blank offset (`blank_offset`).
  - Selective digestion/method blank (`MBLK`) subtraction by preparation group (`prep_group`).
  - Physical preparation scaling: sample mass, moisture/humidity correction (% moisture to dry weight basis), digestion volume, and dilution factors.
- **Audit-Ready Excel Reports with Live Native Formulas**:
  - Generates formulas (`SLOPE`, `INTERCEPT`, `RSQ`, `SUMPRODUCT`, `SUMSQ`, `AVERAGE`, `IF`, `ROUND`, `TEXT`) in Excel.
  - Dynamically evaluates sample limits of quantification (`< LoQ`) without producing `#VALUE!` errors upon unit conversion.
  - Multi-sheet reporting for split dilutions (`export_split_dilution_report` / `export_multidilution_report`).
- **ISO 17025 / EPA QA-QC Module**:
  - Continuous calibration verification (`CCV`, `ICV`) and certified reference materials (`CRM`) recovery %.
  - Duplicate analysis (% RPD).
  - Matrix spike recovery % (`MS`).
  - Optional auditable `Control de Calidad (QA-QC)` worksheet with `PASS`/`FAIL` conditional formatting.
- **Instrument Parsers & Laboratory Preparation Logs**:
  - Agilent MassHunter Excel counts (`FQ COUNTS.xlsx`) with multi-gas collision disambiguation (`Fe56_NoGas` vs `Fe56_He`) and `CPS RSD` extraction.
  - Agilent calibration table (`CAL.xlsx`) with automated unit normalization (`ppm`, `ppb`, `ppt` to $\mu\text{g/L}$).
  - Ingestion of laboratory weighing sheets (`apply_sample_prep`) from CSV or Excel (mass, humidity, volume, dilution, prep group).
- **Command-Line Interface (CLI)**: Process runs and generate Excel reports directly with `icptools process`.

---

## Installation

```bash
git clone https://github.com/DamianPiuselli/icptools.git
cd icptools
pip install -e .
```

---

## Quick Start (Python)

```python
from icptools import (
    parse_agilent_counts,
    parse_agilent_calibration,
    apply_calibration_table,
    apply_sample_prep,
    Processor,
    export_excel_formula_report,
)

# 1. Load instrument run and calibration table
batch = parse_agilent_counts("datos/FQ_COUNTS.xlsx")
apply_calibration_table(batch, "datos/CAL.xlsx")

# 2. Ingest laboratory preparation sheet (mass, moisture, digestion volume)
apply_sample_prep(batch, "datos/PLANILLA_PREPARACION.xlsx")

# 3. Process analytical batch
proc = Processor(batch)
proc.process()

# 4. Export audit-ready Excel formula report with QA/QC sheet
export_excel_formula_report(
    batch=batch,
    output_path="reportes/Reporte_Final.xlsx",
    instrument_loqs={"Cr52": 0.2, "As75": 0.5, "Pb208": 0.1},
    include_qc_sheet=True,
    report_title="Monitoreo Ambiental 2026",
)
```

---

## Command-Line Interface (CLI)

```bash
# Process a run with Agilent counts, calibration, and prep log:
icptools process FQ_COUNTS.xlsx -c CAL.xlsx -p PREP.xlsx -o Reporte.xlsx --qc

# Check QA/QC status in terminal:
icptools qc FQ_COUNTS.xlsx -c CAL.xlsx
```

---

## Documentation for AI Agents & Developers

See [AGENTS.md](AGENTS.md) for canonical recipes, unit handling conventions, and validation guidelines.

---

## Running Tests

```bash
pytest
```

---

## License

MIT
