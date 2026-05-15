from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

class SampleType(Enum):
    STANDARD = "STD"
    BLANK = "BLK"  # Calibration Blank
    QC = "QC"
    UNKNOWN = "UNK"
    METHOD_BLANK = "MBLK"  # Digestion/Method Blank

@dataclass
class Analyte:
    name: str  # e.g., 'Pb208'
    element: str  # e.g., 'Pb'
    mass: int  # e.g., 208
    is_internal_standard: bool = False

@dataclass
class Sample:
    sample_id: str
    sample_type: SampleType
    
    # Raw intensities in counts per second (CPS) for each analyte
    # Key: Analyte name (str), Value: CPS (float)
    raw_intensities: Dict[str, float] = field(default_factory=dict)
    
    # Sample preparation metadata
    mass: float = 1.0  # Sample mass (e.g., grams)
    final_volume: float = 1.0  # Final volume after digestion (e.g., mL)
    dilution_factor: float = 1.0  # Additional dilution prior to analysis
    
    # Processed Results state
    is_corrected_intensities: Dict[str, float] = field(default_factory=dict)
    instrument_concentrations: Dict[str, float] = field(default_factory=dict) # e.g., ug/L
    final_concentrations: Dict[str, float] = field(default_factory=dict) # e.g., mg/kg
    
    # Calibration true concentrations (used for standard samples)
    known_concentrations: Dict[str, float] = field(default_factory=dict)

@dataclass
class Batch:
    name: str
    samples: List[Sample] = field(default_factory=list)
    analytes: Dict[str, Analyte] = field(default_factory=dict)
    
    # Maps an analyte name to its assigned Internal Standard's name
    analyte_to_is: Dict[str, str] = field(default_factory=dict)

    def add_sample(self, sample: Sample):
        self.samples.append(sample)
        
    def add_analyte(self, analyte: Analyte, internal_standard_name: Optional[str] = None):
        self.analytes[analyte.name] = analyte
        if internal_standard_name:
            self.analyte_to_is[analyte.name] = internal_standard_name
