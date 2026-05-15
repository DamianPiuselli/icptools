# GEMINI.md - Project Context & Implementation Details

## Project Overview
`icptools` is a batch-centric Python library for processing ICP-MS and ICP-OES analytical data. It handles the transition from raw instrument counts (CPS) to final sample concentrations (e.g., mg/kg or ug/L) using an Object-Oriented architecture.

## Core Mandates & Architecture
- **Object-Oriented Domain Models**: All data is encapsulated in `Batch`, `Sample`, and `Analyte` objects found in `src/icptools/models.py`.
- **Pipeline Segregation**: The processing logic is decoupled from data storage, residing in `src/icptools/pipeline.py`.
- **Unit Management**: 
  - `LIQUID` matrix: Final units are `ug/L`. Formula: `Instrument Conc * Dilution Factor`.
  - `SOLID` matrix: Final units are `mg/kg`. Formula: `(Instrument Conc * Volume * Dilution) / Mass`.
- **Prep Groups**: Method blanks (`MBLK`) are grouped by `prep_group`. Subtraction only occurs within matching groups.

## Current Implementation State
- [x] **Core Models**: Dataclasses with support for matrices, preparation groups, and requested analytes.
- [x] **Calibration Engine**: Linear regression with optional weighting (1/x) and R² tracking.
- [x] **Processing Pipeline**: Sequential steps for IS-correction, calibration, selective blanking, and sample prep math.
- [x] **Synthetic Data**: A robust generator (`synthetic.py`) for testing pipeline logic without external files.
- [x] **Reporting**: Grouped DataFrame generation in `reporting.py` with dynamic unit headers.

## Future Development Steps
1. **Data Parsers**: Need to implement parsers for `.xlsx` files.
   - **Calibration Table Parser**: Should extract concentration levels for each analyte.
   - **Batch Data Parser**: Should extract raw counts and sample metadata (Mass, Volume, Dilution).
2. **Simplified Batch Configuration**: Parsers should ideally automate the creation of the `Batch` and `Sample` objects based on file headers/formats.
3. **QC Validation**: Future support for checking QC recovery percentages and calibration drift standards.

## Development Environment
- **Layout**: `src` layout.
- **Testing**: `pytest` in the `tests/` directory.
- **Dependencies**: `pandas`, `numpy`, `scipy`.
- **Install**: `pip install -e .`

## Usage Hint
Refer to `example_usage.py` for a realistic laboratory workflow involving mixed solid/liquid samples and prep groups.
