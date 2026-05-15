# icptools

A batch-centric Python library for processing ICP-MS and ICP-OES data.

## Features

- **Object-Oriented Domain Models**: Represents analytical concepts like `Batch`, `Sample`, and `Analyte`.
- **Automated Processing Pipeline**:
  - Internal Standard (IS) correction.
  - Linear calibration fitting with optional weighting (e.g., 1/x).
  - Method/Digestion blank subtraction.
  - Sample preparation corrections (Mass, Final Volume, Dilution Factor).
- **Synthetic Data Generation**: Built-in tools to simulate realistic analytical runs with noise and drift for testing logic without raw files.
- **Flexible Reporting**: Export results and calibration summaries directly to Pandas DataFrames.

## Project Structure

```text
icptools/
├── src/
│   └── icptools/          # Core package
│       ├── models.py      # Dataclasses for Batch, Sample, Analyte
│       ├── pipeline.py    # Processing logic
│       ├── calibration.py # Curve fitting
│       ├── reporting.py   # DataFrame export tools
│       └── synthetic.py   # Data simulation
├── tests/                 # Unit and integration tests
├── pyproject.toml         # Project metadata and dependencies
└── requirements.txt       # Local development dependencies
```

## Installation

### For Development

1. Clone the repository.
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -e .
   ```

## Usage Example

```python
from icptools.synthetic import generate_synthetic_batch
from icptools.pipeline import Processor
from icptools.reporting import get_results_dataframe

# 1. Generate a synthetic batch with known properties
batch, true_values = generate_synthetic_batch(num_unknowns=5)

# 2. Initialize the processor and run the pipeline
processor = Processor(batch)
processor.process()

# 3. Get results as a Pandas DataFrame
df = get_results_dataframe(batch)
print(df.head())
```

## Running Tests

```bash
pytest
```

## License

MIT
