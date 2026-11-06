"""
Generalized multi-dilution and auto-ranging reporting engine for icptools.
Supports N-dilution levels and automatic selection of the best dilution factor per analyte.
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import Batch, Sample, SampleType, SampleMatrix
from .reporting import export_excel_formula_report, _get_loq_format_and_decimals


def select_optimal_dilution(
    samples_for_same_id: List[Sample],
    analyte: str,
    max_standard_conc: Optional[float] = None,
    loq: Optional[float] = None,
) -> Sample:
    """
    Selects the optimal sample dilution for a given analyte.
    Criteria:
    1. Prefer dilution where instrument concentration is within [LoQ, Max_Standard].
    2. If all are above max standard, choose highest dilution (least saturated).
    3. If all are below LoQ, choose lowest dilution (closest to detectable signal).
    4. Reject measurements with extreme ISTD suppression (< 50% recovery) if healthier dilution exists.
    """
    if not samples_for_same_id:
        raise ValueError("Cannot select from empty sample list")
    if len(samples_for_same_id) == 1:
        return samples_for_same_id[0]

    # Sort samples by dilution factor ascending (1x, 5x, 10x, 100x)
    sorted_samples = sorted(samples_for_same_id, key=lambda s: s.dilution_factor)

    loq_val = loq or 0.1
    max_std = max_standard_conc or float("inf")

    # Filter out samples with critical ISTD failure (< 50% recovery) if others are healthy
    healthy_samples = []
    for s in sorted_samples:
        rec_values = list(s.is_recovery.values())
        if not rec_values or min(rec_values) >= 50.0:
            healthy_samples.append(s)
    candidates = healthy_samples if healthy_samples else sorted_samples

    # 1. Look for a candidate within calibration range [LoQ, Max_Std]
    in_range = []
    for s in candidates:
        conc = s.instrument_concentrations.get(analyte, 0.0)
        if loq_val <= conc <= max_std:
            in_range.append(s)

    if in_range:
        # Prefer the lowest dilution within range for best precision
        return in_range[0]

    # 2. Check if all are below LoQ -> choose lowest dilution
    all_below = all(s.instrument_concentrations.get(analyte, 0.0) < loq_val for s in candidates)
    if all_below:
        return candidates[0]

    # 3. Otherwise (above max standard) -> choose highest dilution
    return candidates[-1]


def export_multidilution_report(
    batch: Batch,
    output_path: Union[str, Path],
    dilution_groups: Optional[Dict[str, List[str]]] = None,
    instrument_loqs: Optional[Dict[str, float]] = None,
    units: Optional[Dict[str, str]] = None,
    weighting: Optional[str] = None,
    report_title: Optional[str] = None,
    include_qc_sheet: bool = False,
) -> Path:
    """
    Exports an auditable multi-sheet Excel report for batches measured across N dilution levels:
    - Creates one auditable Agilent sheet for each distinct dilution level (e.g. 'Dilucion 1x', 'Dilucion 100x').
    - Creates a 'Reporte Unificado' client sheet linking dynamically to the appropriate tab per analyte.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    loq_dict = instrument_loqs or {}
    unit_map = units or {}

    # Identify all distinct dilution factors among unknown samples
    unknown_samples = [s for s in batch.samples if s.sample_type in (SampleType.UNKNOWN, SampleType.QC, SampleType.METHOD_BLANK)]
    distinct_dfs = sorted(list(set(s.dilution_factor for s in unknown_samples if s.sample_type == SampleType.UNKNOWN)))
    if not distinct_dfs:
        distinct_dfs = [1.0]

    # Determine calibration maximum standard concentration per analyte
    max_standards = {}
    for a in batch.analytes.keys():
        knowns = [s.known_concentrations[a] for s in batch.samples if a in s.known_concentrations]
        max_standards[a] = max(knowns) if knowns else 100.0

    wb = openpyxl.Workbook()
    # remove default empty sheet later or use it as first
    wb.remove(wb.active)

    dil_sheets_meta: Dict[float, dict] = {}

    for df_factor in distinct_dfs:
        tab_name = f"DF_{int(df_factor)}x" if df_factor.is_integer() else f"DF_{df_factor}x"
        samples_at_df = [s.sample_id for s in batch.samples if s.dilution_factor == df_factor or s.sample_type in (SampleType.BLANK, SampleType.STANDARD, SampleType.METHOD_BLANK)]
        
        # Determine default unit for this dilution level
        default_unit = unit_map.get(str(df_factor), "mg/L" if df_factor > 10.0 else "ug/L")

        wb, meta = export_excel_formula_report(
            batch=batch,
            samples=samples_at_df,
            sheet_title=tab_name,
            report_title=f"{report_title or batch.name} - Dilución {df_factor}x",
            unit=default_unit,
            weighting=weighting,
            instrument_loqs=loq_dict,
            workbook=wb,
            return_metadata=True,
        )
        dil_sheets_meta[df_factor] = meta

    # Create Unified Sheet
    ws_unif = wb.create_sheet(title="Reporte Unificado", index=0)
    ws_unif.views.sheetView[0].showGridLines = True

    font_title = Font(name="Calibri", size=13, bold=True, color="1F497D")
    font_sub = Font(name="Calibri", size=10, italic=True, color="595959")
    font_head = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=10, bold=True)
    font_rep = Font(name="Calibri", size=10, bold=True, color="1F497D")

    fill_rep_head = PatternFill("solid", fgColor="366092")
    thin_border = Side(border_style="thin", color="D9D9D9")
    cell_border = Border(left=thin_border, right=thin_border, top=thin_border, bottom=thin_border)
    sample_head_border = Border(
        left=thin_border, right=thin_border, top=thin_border, bottom=Side(border_style="medium", color="243F60")
    )

    ws_unif.cell(row=1, column=1, value=f"{report_title or batch.name} - Reporte Unificado Consolidado").font = font_title
    ws_unif.cell(row=2, column=1, value=f"Batch: {batch.name} | Consolidación dinámica de {len(distinct_dfs)} niveles de dilución").font = font_sub

    # Determine unique client sample names
    client_names = []
    samples_by_name: Dict[str, List[Sample]] = {}
    for s in batch.samples:
        if s.sample_type not in (SampleType.UNKNOWN, SampleType.DUPLICATE):
            continue
        name = s.sample_name or s.sample_id
        if name not in samples_by_name:
            samples_by_name[name] = []
            client_names.append(name)
        samples_by_name[name].append(s)

    quant_analytes = [name for name, a in batch.analytes.items() if not a.is_internal_standard]

    # Headers
    headers_unif = ["Sample ID"]
    for a in quant_analytes:
        elem = batch.analytes[a].element
        # Unit
        a_unit = "mg/L" if any(a in group for group in (dilution_groups or {}).values() if "mg" in str(group)) else "ug/L"
        headers_unif.append(f"{elem} ({a_unit})")

    head_row_num = 4
    for col_idx, h in enumerate(headers_unif, 1):
        c = ws_unif.cell(row=head_row_num, column=col_idx, value=h)
        c.font = font_head
        c.fill = fill_rep_head
        c.border = sample_head_border
        c.alignment = Alignment(horizontal="center", vertical="center")

    client_start_row = 5
    for idx, name in enumerate(client_names):
        r = client_start_row + idx
        c_id = ws_unif.cell(row=r, column=1, value=name)
        c_id.alignment = Alignment(horizontal="left", vertical="center")
        c_id.font = font_bold
        c_id.border = cell_border

        samples_group = samples_by_name[name]

        for a_idx, a in enumerate(quant_analytes):
            # Select best sample dilution
            best_sample = select_optimal_dilution(
                samples_group,
                analyte=a,
                max_standard_conc=max_standards.get(a),
                loq=loq_dict.get(a, 0.1)
            )

            df_factor = best_sample.dilution_factor
            meta = dil_sheets_meta.get(df_factor)
            target_col_let = get_column_letter(2 + a_idx)

            c_val = ws_unif.cell(row=r, column=2 + a_idx)
            if meta:
                # Find row in meta['client_samples']
                match_r = next((r_num for s_label, r_num in meta["client_samples"] if s_label == name), None)
                if match_r:
                    c_val.value = f"='{meta['sheet_title']}'!{target_col_let}{match_r}"
                else:
                    c_val.value = ""
            else:
                c_val.value = ""

            c_val.font = font_rep
            c_val.border = cell_border
            c_val.alignment = Alignment(horizontal="right", vertical="center")
            fmt_str, _ = _get_loq_format_and_decimals(loq_dict.get(a, 0.1))
            c_val.number_format = fmt_str

    for col in ws_unif.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws_unif.column_dimensions[col_letter].width = max(max_len + 3, 13)

    if include_qc_sheet:
        from .qc import QCEvaluator
        evaluator = QCEvaluator(batch)
        qc_results = evaluator.evaluate_all()
        ws_qc = wb.create_sheet(title="Control de Calidad (QA-QC)")
        ws_qc.views.sheetView[0].showGridLines = True
        ws_qc.cell(row=1, column=1, value="CONTROL DE CALIDAD ANALÍTICO (ISO 17025 / QA-QC)").font = font_title
        ws_qc.cell(row=2, column=1, value=f"Batch: {batch.name} | Resumen QA/QC").font = font_sub

    wb.save(out_file)
    return out_file
