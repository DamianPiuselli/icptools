from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

class SampleType(Enum):
    STANDARD = "STD"
    BLANK = "BLK"  # Calibration Blank
    QC = "QC"
    UNKNOWN = "UNK"
    METHOD_BLANK = "MBLK"  # Digestion/Method Blank

class SampleMatrix(Enum):
    LIQUID = "Liquid"
    SOLID = "Solid"

@dataclass
class Analyte:
    name: str  # e.g., 'Pb208'
    element: str  # e.g., 'Pb'
    mass: int  # e.g., 208
    is_internal_standard: bool = False
    gas_mode: Optional[str] = None  # e.g., 'He', 'No Gas'
    raw_name: Optional[str] = None  # Original column name from instrument export

@dataclass
class Sample:
    sample_id: str
    sample_type: SampleType
    
    # Raw intensities in counts per second (CPS) for each analyte
    # Key: Analyte name (str), Value: CPS (float)
    raw_intensities: Dict[str, float] = field(default_factory=dict)
    
    # Sample preparation metadata
    matrix: SampleMatrix = SampleMatrix.LIQUID
    prep_group: Optional[str] = None  # e.g., "Digestion_Batch_A"
    requested_analytes: Optional[List[str]] = None  # e.g., ["Pb208", "Cd111"]
    
    mass: float = 1.0  # Sample mass (e.g., grams)
    final_volume: float = 1.0  # Final volume after digestion (e.g., mL)
    dilution_factor: float = 1.0  # Additional dilution prior to analysis
    
    # Processed Results state
    is_corrected_intensities: Dict[str, float] = field(default_factory=dict)
    instrument_concentrations: Dict[str, float] = field(default_factory=dict) # e.g., ug/L
    final_concentrations: Dict[str, float] = field(default_factory=dict) # e.g., mg/kg
    
    # Calibration true concentrations (used for standard samples)
    known_concentrations: Dict[str, float] = field(default_factory=dict)

    # Instrument metadata
    sample_name: Optional[str] = None
    data_file: Optional[str] = None
    comment: Optional[str] = None
    level: Optional[float] = None

@dataclass
class StandardMix:
    """
    Represents a multi-element certified stock solution (e.g., Merck Certipur VI).
    stock_concentrations maps element (or analyte name) to its stock concentration (e.g. mg/L).
    reference_element is an element used to scale the mix when nominal dilution levels are given.
    """
    name: str
    stock_concentrations: Dict[str, float]
    reference_element: Optional[str] = None

@dataclass
class Batch:
    name: str
    samples: List[Sample] = field(default_factory=list)
    analytes: Dict[str, Analyte] = field(default_factory=dict)
    
    # Maps an analyte name to its assigned Internal Standard's name
    analyte_to_is: Dict[str, str] = field(default_factory=dict)

    # Maps an analyte name to a list of specific sample identifiers used as calibration standards
    analyte_calibration_standards: Dict[str, List[str]] = field(default_factory=dict)

    # Optional mapping for analyte-specific regression weighting (e.g. 'none', '1/x')
    analyte_weightings: Dict[str, str] = field(default_factory=dict)

    def add_sample(self, sample: Sample):
        self.samples.append(sample)
        
    def add_analyte(self, analyte: Analyte, internal_standard_name: Optional[str] = None):
        self.analytes[analyte.name] = analyte
        if internal_standard_name:
            self.analyte_to_is[analyte.name] = internal_standard_name

    def get_sample(self, identifier: str) -> Optional[Sample]:
        """Finds a sample by sample_id, sample_name, or data_file."""
        for s in self.samples:
            if s.sample_id == identifier or s.sample_name == identifier or s.data_file == identifier:
                return s
        return None

    def assign_calibration(
        self,
        analyte: str,
        standards: Dict[str, float],
        internal_standard: Optional[str] = None
    ):
        """
        Assigns known concentrations to specific standard samples for an analyte.
        Allows piecewise / ad-hoc calibration curves (e.g. Hg calibrated on separate vials).
        `standards` is a dict of {sample_identifier: concentration}.
        """
        if internal_standard:
            self.analyte_to_is[analyte] = internal_standard

        matched_ids = []
        for ident, conc in standards.items():
            sample = self.get_sample(ident)
            if sample is not None:
                sample.known_concentrations[analyte] = float(conc)
                # If currently unknown or unclassified, mark appropriately
                if sample.sample_type in (SampleType.UNKNOWN, SampleType.QC):
                    sample.sample_type = SampleType.BLANK if conc == 0.0 else SampleType.STANDARD
                matched_ids.append(sample.sample_id)
            else:
                # If sample not yet in batch, still register identifier
                matched_ids.append(ident)

        self.analyte_calibration_standards[analyte] = matched_ids

    def apply_standard_mix(
        self,
        mix: StandardMix,
        levels: Dict[str, float],
        reference_element: Optional[str] = None
    ):
        """
        Applies a multi-element stock solution across standard levels (e.g. S0 through S9).
        `levels` maps standard identifier (sample_name, sample_id, or str(level)) to nominal concentration.
        If reference_element is specified (or configured on mix), concentrations scale according to:
            conc = nominal_level * (stock[element] / stock[ref_element])
        """
        ref_elem = reference_element or mix.reference_element
        ref_stock = 1.0
        if ref_elem:
            # Look up reference element stock
            ref_stock = mix.stock_concentrations.get(
                ref_elem,
                mix.stock_concentrations.get(f"{ref_elem}52", 1.0) # fallback
            )

        for ident, nominal_val in levels.items():
            sample = self.get_sample(str(ident))
            if sample is None:
                # Try finding by level attribute
                try:
                    lvl_num = float(ident)
                    sample = next((s for s in self.samples if s.level == lvl_num), None)
                except ValueError:
                    pass

            if sample is None:
                continue

            for analyte in self.analytes.values():
                if analyte.is_internal_standard:
                    continue

                # Match by element or analyte name
                stock_val = mix.stock_concentrations.get(analyte.element)
                if stock_val is None:
                    stock_val = mix.stock_concentrations.get(analyte.name)

                if stock_val is not None:
                    if ref_elem:
                        conc = nominal_val * (stock_val / ref_stock)
                    else:
                        conc = nominal_val * stock_val
                    sample.known_concentrations[analyte.name] = float(conc)

            # Ensure standard samples are classified as STANDARD/BLANK
            if sample.sample_type == SampleType.UNKNOWN:
                sample.sample_type = SampleType.BLANK if nominal_val == 0.0 else SampleType.STANDARD
