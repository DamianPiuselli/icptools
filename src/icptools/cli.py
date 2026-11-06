"""
Command-line interface (CLI) for icptools.
Provides commands to process ICP-MS/OES batches and generate auditable Excel reports directly from the terminal.
"""
import argparse
import sys
from pathlib import Path
import json

from .parsers import (
    parse_agilent_counts,
    parse_agilent_calibration,
    apply_calibration_table,
    apply_sample_prep,
)
from .pipeline import Processor
from .reporting import export_excel_formula_report
from .qc import get_qc_summary


def main():
    parser = argparse.ArgumentParser(
        prog="icptools",
        description="icptools: Analytical processing and Excel formula report engine for ICP-MS and ICP-OES."
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Command: process
    proc_parser = subparsers.add_parser("process", help="Process an analytical batch and export Excel report.")
    proc_parser.add_argument("counts", type=str, help="Path to instrument counts file (.xlsx)")
    proc_parser.add_argument("-c", "--cal", type=str, default=None, help="Path to Agilent CAL.xlsx calibration table")
    proc_parser.add_argument("-p", "--prep", type=str, default=None, help="Path to sample preparation table (.csv/.xlsx)")
    proc_parser.add_argument("-o", "--output", type=str, default="Reporte_Analitico.xlsx", help="Output Excel file path")
    proc_parser.add_argument("-w", "--weighting", type=str, default="none", choices=["none", "blank_offset", "1/x"], help="Calibration weighting model")
    proc_parser.add_argument("-u", "--unit", type=str, default=None, help="Reported unit (e.g. ug/L or mg/L)")
    proc_parser.add_argument("--qc", action="store_true", help="Include QA/QC evaluation worksheet in output Excel")

    # Command: qc
    qc_parser = subparsers.add_parser("qc", help="Display QA/QC summary table on the console.")
    qc_parser.add_argument("counts", type=str, help="Path to instrument counts file (.xlsx)")
    qc_parser.add_argument("-c", "--cal", type=str, default=None, help="Path to Agilent CAL.xlsx")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "process":
        print(f"Loading counts from: {args.counts}")
        batch = parse_agilent_counts(args.counts)

        if args.cal:
            print(f"Applying calibration from: {args.cal}")
            apply_calibration_table(batch, args.cal)

        if args.prep:
            print(f"Applying sample prep from: {args.prep}")
            apply_sample_prep(batch, args.prep)

        print(f"Processing batch with weighting='{args.weighting}'...")
        proc = Processor(batch, weighting=args.weighting)
        proc.process()

        print(f"Generating formula Excel report: {args.output}")
        export_excel_formula_report(
            batch=batch,
            output_path=args.output,
            unit=args.unit,
            weighting=args.weighting,
            include_qc_sheet=args.qc,
        )
        print("Done successfully.")

    elif args.command == "qc":
        batch = parse_agilent_counts(args.counts)
        if args.cal:
            apply_calibration_table(batch, args.cal)
        proc = Processor(batch)
        proc.process()
        df_qc = get_qc_summary(batch)
        print(df_qc.to_string(index=False))


if __name__ == "__main__":
    main()
