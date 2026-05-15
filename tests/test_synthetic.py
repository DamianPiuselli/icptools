import pytest
from icptools.synthetic import generate_synthetic_batch
from icptools.models import SampleType

def test_generate_synthetic_batch():
    batch, true_concs = generate_synthetic_batch(
        num_standards=5,
        num_liquid_unknowns=5,
        num_solid_unknowns=5,
        num_blanks=2
    )
    
    assert batch.name == "Synthetic_Mixed_Batch_001"
    assert "Pb208" in batch.analytes
    assert "Rh103" in batch.analytes
    assert batch.analytes["Rh103"].is_internal_standard
    
    # 5 STD + 5 LIQ_UNK + 5 SOL_UNK + 2 BLK + 1 MBLK = 18 samples
    assert len(batch.samples) == 18
    
    # Check that known_concentrations are set for standards
    standards = [s for s in batch.samples if s.sample_type == SampleType.STANDARD]
    assert len(standards) == 5
    for std in standards:
        assert len(std.known_concentrations) > 0
        assert "Pb208" in std.known_concentrations
        
    # Check that counts were generated
    for s in batch.samples:
        assert "Pb208" in s.raw_intensities
        assert "Rh103" in s.raw_intensities
        assert s.raw_intensities["Rh103"] > 0
