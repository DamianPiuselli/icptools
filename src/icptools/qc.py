"""
Quality Control (QA/QC) module for ICP-MS and ICP-OES analysis under ISO 17025 / EPA guidelines.
Evaluates % ISTD recovery, CCV/ICV/CRM recovery %, duplicate RPD %, and matrix spike recovery %.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

from .models import Batch, Sample, SampleType, SampleMatrix


@dataclass
class QCEvaluationResult:
    sample_id: str
    sample_name: str
    qc_type: str  # 'ISTD', 'CCV', 'CRM', 'DUP', 'SPIKE'
    parameter: str  # analyte or internal standard name
    found_value: float
    target_value: Optional[float]
    recovery_or_rpd: float  # % recovery or % RPD
    lower_limit: float
    upper_limit: float
    status: str  # 'PASS' or 'FAIL'
    details: str = ""


class QCEvaluator:
    """
    Evaluates analytical quality controls for a Batch according to ISO 17025 / EPA criteria.
    """
    def __init__(
        self,
        batch: Batch,
        is_recovery_limits: Tuple[float, float] = (70.0, 120.0),
        ccv_limits: Tuple[float, float] = (90.0, 110.0),
        crm_limits: Tuple[float, float] = (80.0, 120.0),
        spike_limits: Tuple[float, float] = (75.0, 125.0),
        dup_rpd_max: float = 20.0,
    ):
        self.batch = batch
        self.is_min, self.is_max = is_recovery_limits
        self.ccv_min, self.ccv_max = ccv_limits
        self.crm_min, self.crm_max = crm_limits
        self.spike_min, self.spike_max = spike_limits
        self.dup_rpd_max = dup_rpd_max

    def evaluate_is_recoveries(self) -> List[QCEvaluationResult]:
        """Evaluates internal standard recoveries for all samples."""
        results = []
        for sample in self.batch.samples:
            for is_name, rec in sample.is_recovery.items():
                status = "PASS" if (self.is_min <= rec <= self.is_max) else "FAIL"
                results.append(QCEvaluationResult(
                    sample_id=sample.sample_id,
                    sample_name=sample.sample_name or sample.sample_id,
                    qc_type="ISTD",
                    parameter=is_name,
                    found_value=sample.raw_intensities.get(is_name, 0.0),
                    target_value=None,
                    recovery_or_rpd=rec,
                    lower_limit=self.is_min,
                    upper_limit=self.is_max,
                    status=status,
                    details=f"% ISTD = {rec:.1f}% (Limits: {self.is_min:.0f}-{self.is_max:.0f}%)"
                ))
        return results

    def evaluate_check_standards(self) -> List[QCEvaluationResult]:
        """Evaluates QC check standards (CCV, ICV, CRM) against expected concentrations."""
        results = []
        for sample in self.batch.samples:
            if sample.sample_type != SampleType.QC:
                continue

            is_crm = "crm" in (sample.sample_name or "").lower() or "crm" in (sample.sample_id).lower()
            low_lim = self.crm_min if is_crm else self.ccv_min
            high_lim = self.crm_max if is_crm else self.ccv_max
            qc_label = "CRM" if is_crm else "CCV"

            # Check expected_concentrations or known_concentrations
            targets = sample.expected_concentrations or sample.known_concentrations
            for analyte, target in targets.items():
                if target <= 0:
                    continue
                found = sample.instrument_concentrations.get(analyte, 0.0)
                rec = (found / target) * 100.0 if target > 0 else 0.0
                status = "PASS" if (low_lim <= rec <= high_lim) else "FAIL"
                results.append(QCEvaluationResult(
                    sample_id=sample.sample_id,
                    sample_name=sample.sample_name or sample.sample_id,
                    qc_type=qc_label,
                    parameter=analyte,
                    found_value=found,
                    target_value=target,
                    recovery_or_rpd=rec,
                    lower_limit=low_lim,
                    upper_limit=high_lim,
                    status=status,
                    details=f"% Rec = {rec:.1f}% (Found: {found:.2f}, Target: {target:.2f})"
                ))
        return results

    def evaluate_duplicates(self) -> List[QCEvaluationResult]:
        """Evaluates analytical or field duplicates (DUP) calculating % RPD."""
        results = []
        for sample in self.batch.samples:
            is_dup = sample.sample_type == SampleType.DUPLICATE or "dup" in (sample.sample_name or "").lower() or (sample.sample_id.endswith("_BETA"))
            if not is_dup:
                continue

            # Determine parent sample
            parent = None
            if sample.parent_sample_id:
                parent = self.batch.get_sample(sample.parent_sample_id)
            else:
                # Infer parent (e.g. 'LUJ004 BETA' -> 'LUJ004 ALPHA' or 'LUJ004')
                name = sample.sample_name or sample.sample_id
                if " beta" in name.lower():
                    alpha_name = name.lower().replace(" beta", " alpha")
                    parent = next((s for s in self.batch.samples if (s.sample_name or "").lower() == alpha_name), None)
                elif "_dup" in sample.sample_id.lower():
                    base_id = sample.sample_id.lower().replace("_dup", "")
                    parent = self.batch.get_sample(base_id)

            if parent is None:
                continue

            for analyte in self.batch.analytes.keys():
                if self.batch.analytes[analyte].is_internal_standard:
                    continue
                c1 = parent.instrument_concentrations.get(analyte, 0.0)
                c2 = sample.instrument_concentrations.get(analyte, 0.0)
                mean_c = (c1 + c2) / 2.0
                if mean_c <= 0:
                    continue
                rpd = (abs(c1 - c2) / mean_c) * 100.0
                status = "PASS" if rpd <= self.dup_rpd_max else "FAIL"
                results.append(QCEvaluationResult(
                    sample_id=sample.sample_id,
                    sample_name=sample.sample_name or sample.sample_id,
                    qc_type="DUP",
                    parameter=analyte,
                    found_value=c2,
                    target_value=c1,
                    recovery_or_rpd=rpd,
                    lower_limit=0.0,
                    upper_limit=self.dup_rpd_max,
                    status=status,
                    details=f"RPD = {rpd:.1f}% (Parent: {c1:.2f}, Dup: {c2:.2f}, Max: {self.dup_rpd_max:.0f}%)"
                ))
        return results

    def evaluate_matrix_spikes(self) -> List[QCEvaluationResult]:
        """Evaluates matrix spikes (SPIKE / MS) calculating % Spike Recovery."""
        results = []
        for sample in self.batch.samples:
            if sample.sample_type != SampleType.SPIKE and not sample.spike_concentrations:
                continue

            parent = self.batch.get_sample(sample.parent_sample_id) if sample.parent_sample_id else None
            for analyte, added in sample.spike_concentrations.items():
                if added <= 0:
                    continue
                c_spiked = sample.instrument_concentrations.get(analyte, 0.0)
                c_parent = parent.instrument_concentrations.get(analyte, 0.0) if parent else 0.0
                rec = ((c_spiked - c_parent) / added) * 100.0
                status = "PASS" if (self.spike_min <= rec <= self.spike_max) else "FAIL"
                results.append(QCEvaluationResult(
                    sample_id=sample.sample_id,
                    sample_name=sample.sample_name or sample.sample_id,
                    qc_type="SPIKE",
                    parameter=analyte,
                    found_value=c_spiked,
                    target_value=c_parent + added,
                    recovery_or_rpd=rec,
                    lower_limit=self.spike_min,
                    upper_limit=self.spike_max,
                    status=status,
                    details=f"% Rec = {rec:.1f}% (Spiked: {c_spiked:.2f}, Parent: {c_parent:.2f}, Added: {added:.2f})"
                ))
        return results

    def evaluate_all(self) -> List[QCEvaluationResult]:
        """Runs all QA/QC evaluations and returns the combined list of results."""
        return (
            self.evaluate_is_recoveries()
            + self.evaluate_check_standards()
            + self.evaluate_duplicates()
            + self.evaluate_matrix_spikes()
        )


def get_qc_summary(
    batch_or_processor: Any,
    include_is: bool = True,
    is_limits: Tuple[float, float] = (70.0, 120.0),
    ccv_limits: Tuple[float, float] = (90.0, 110.0),
    crm_limits: Tuple[float, float] = (80.0, 120.0),
    spike_limits: Tuple[float, float] = (75.0, 125.0),
    dup_rpd_max: float = 20.0,
) -> pd.DataFrame:
    """
    Returns a structured QA/QC summary DataFrame for the batch.
    """
    batch = getattr(batch_or_processor, "batch", batch_or_processor)
    evaluator = QCEvaluator(
        batch=batch,
        is_recovery_limits=is_limits,
        ccv_limits=ccv_limits,
        crm_limits=crm_limits,
        spike_limits=spike_limits,
        dup_rpd_max=dup_rpd_max,
    )
    
    results = []
    if include_is:
        results.extend(evaluator.evaluate_is_recoveries())
    results.extend(evaluator.evaluate_check_standards())
    results.extend(evaluator.evaluate_duplicates())
    results.extend(evaluator.evaluate_matrix_spikes())

    data = []
    for r in results:
        data.append({
            "Sample ID": r.sample_id,
            "Sample Name": r.sample_name,
            "QC Type": r.qc_type,
            "Parameter": r.parameter,
            "Found": r.found_value,
            "Target": r.target_value,
            "% Rec / RPD": r.recovery_or_rpd,
            "Lower Limit": r.lower_limit,
            "Upper Limit": r.upper_limit,
            "Status": r.status,
            "Details": r.details,
        })

    return pd.DataFrame(data)
