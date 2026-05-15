from icptools.models import Batch, Analyte, Sample, SampleType, SampleMatrix
from icptools.pipeline import Processor
from icptools.reporting import generate_reports

def run_complex_lab_example():
    """
    Showcase of a realistic laboratory scenario:
    - Shared calibration for all samples.
    - Group A: Solid samples (Microwave Digestion) with its own Method Blank.
    - Group B: Liquid samples (Diluted only) with no blank subtraction.
    - Specific analytes requested per group.
    """
    
    # 1. Initialize Batch and Analytes
    batch = Batch(name="Lab_Run_2026-05-14")
    
    # Setup Analytes (Rh as Internal Standard for Pb and Cd)
    rh = Analyte("Rh103", "Rh", 103, is_internal_standard=True)
    pb = Analyte("Pb208", "Pb", 208)
    cd = Analyte("Cd111", "Cd", 111)
    
    batch.add_analyte(rh)
    batch.add_analyte(pb, internal_standard_name="Rh103")
    batch.add_analyte(cd, internal_standard_name="Rh103")

    # 2. Add Calibration Standards (Liquid)
    # Standard 1: 10 ug/L, Standard 2: 100 ug/L
    for level in [10.0, 100.0]:
        std = Sample(f"STD_{level}", SampleType.STANDARD)
        std.known_concentrations = {"Pb208": level, "Cd111": level}
        # Simulate some raw counts (Ratio = 0.05 * conc)
        # Assuming IS is 500,000 CPS
        std.raw_intensities = {
            "Rh103": 500000.0,
            "Pb208": (0.05 * level) * 500000.0,
            "Cd111": (0.02 * level) * 500000.0
        }
        batch.add_sample(std)

    # 3. Add GROUP A: Solid Samples (Soil Digestion)
    # Prep Group: "SOIL_BATCH_01"
    # Logic: Method Blank subtraction will be applied here.
    # Unit: mg/kg
    
    # Method Blank for Soil
    mblk_soil = Sample("MBLK_SOIL_01", SampleType.METHOD_BLANK, prep_group="SOIL_BATCH_01", matrix=SampleMatrix.SOLID)
    mblk_soil.raw_intensities = {"Rh103": 510000.0, "Pb208": 15000.0, "Cd111": 5000.0} # Contamination
    mblk_soil.mass = 0.5  # 0.5g digested
    mblk_soil.final_volume = 50.0 # to 50mL
    batch.add_sample(mblk_soil)
    
    # Unknown Soil Sample
    soil_sample = Sample("SOIL_SAMPLE_01", SampleType.UNKNOWN, prep_group="SOIL_BATCH_01", matrix=SampleMatrix.SOLID)
    soil_sample.raw_intensities = {"Rh103": 490000.0, "Pb208": 500000.0, "Cd111": 80000.0}
    soil_sample.mass = 0.52
    soil_sample.final_volume = 50.0
    soil_sample.dilution_factor = 10.0 # Extra 1:10 dilution because it was "hot"
    soil_sample.requested_analytes = ["Pb208", "Cd111"] # We want both
    batch.add_sample(soil_sample)

    # 4. Add GROUP B: Liquid Samples (Waste Water)
    # Prep Group: None (Direct analysis)
    # Logic: No blank subtraction.
    # Unit: ug/L
    water_sample = Sample("WASTEWATER_01", SampleType.UNKNOWN, matrix=SampleMatrix.LIQUID)
    water_sample.raw_intensities = {"Rh103": 505000.0, "Pb208": 120000.0, "Cd111": 2000.0}
    water_sample.dilution_factor = 2.0 # 1:2 dilution
    water_sample.requested_analytes = ["Pb208"] # Client only paid for Lead!
    batch.add_sample(water_sample)

    # 5. EXECUTE PIPELINE
    processor = Processor(batch)
    processor.process()

    # 6. GENERATE REPORTS
    # This returns a dict of DataFrames split by context
    reports = generate_reports(batch)

    print("--- REPORT LISTING ---")
    for report_name in reports.keys():
        print(f"Report Generated: {report_name}")

    # Display the Solid report (mg/kg)
    print("\n--- SOLID SAMPLE REPORT (SOIL) ---")
    # Columns will include units like [Final Conc (mg/kg)]
    soil_report = reports["Solid_SOIL_BATCH_01"]
    print(soil_report[["Sample ID", "Pb208 [Final Conc (mg/kg)]", "Cd111 [Final Conc (mg/kg)]"]])

    # Display the Liquid report (ug/L)
    print("\n--- LIQUID SAMPLE REPORT (WASTEWATER) ---")
    # Note: Cd111 should be missing/None because it wasn't requested
    liquid_report = reports["Liquid_Direct"]
    # We filter for only our wastewater sample (ignoring standards)
    ww_row = liquid_report[liquid_report["Sample ID"] == "WASTEWATER_01"]
    print(ww_row[["Sample ID", "Pb208 [Final Conc (ug/L)]", "Cd111 [Final Conc (ug/L)]"]])

if __name__ == "__main__":
    run_complex_lab_example()
