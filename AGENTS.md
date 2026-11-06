# AGENTS.md — Guía de Uso de `icptools` para Agentes de IA y Desarrolladores

Esta guía define las mejores prácticas, la arquitectura del dominio y los flujos analíticos estándar de ICP-MS e ICP-OES implementados en `icptools`. Está optimizada para que agentes autónomos de IA y desarrolladores humanos puedan interactuar con la biblioteca de forma idiomática, robusta y reproducible.

---

## 1. Filosofía y Principios Clave

1. **Modelos de Dominio Orientados a Objetos (`models.py`)**:
   * Todos los datos analíticos se encapsulan en `Batch`, `Sample` y `Analyte`.
   * Los cálculos nunca modifican estructuras crudas `dict` o `DataFrame` a mano; se utiliza `Processor(batch)`.
2. **El Excel con Fórmulas es el Entregable Analítico Primario**:
   * Los clientes y laboratorios bajo norma ISO 17025 auditan las celdas de Excel buscando fórmulas nativas (`SLOPE`, `INTERCEPT`, `RSQ`, cocientes de estándar interno, dilución y evaluación condicional contra el LoQ).
   * La biblioteca implementa el motor [`export_excel_formula_report`](file:///home/damm/Projects/icptools/src/icptools/reporting.py) para este fin.
3. **Manejo Estricto de Unidades**:
   * Concentración Instrumental en vial: **$\mu\text{g/L}$**.
   * Muestra Líquida: **$\mu\text{g/L}$** o **$\text{mg/L}$** ($\text{Conc. Final} = \text{Conc. Inst.} \times \text{Factor Dilución}$).
   * Muestra Sólida (Base Seca): **$\text{mg/kg}$** ($\text{Conc. Final} = \frac{\text{Conc. Inst.} \times (\text{Volumen [mL]} / 1000) \times \text{Factor Dilución}}{\text{Masa Húmeda [g]} \times (1 - \%\text{Humedad} / 100)}$).
4. **Prevención de Errores `#VALUE!` en Excel**:
   * Cuando una concentración es inferior al límite de cuantificación ($\text{Conc} < \text{LoQ}$), el reporte de cliente evalúa una cadena de texto (ej. `"< 0.10"`).
   * **Regla para agentes**: Para cambiar unidades de $\mu\text{g/L}$ a $\text{mg/L}$, **nunca** dividas una celda de texto en Excel (`="< 0.10" / 1000`). En su lugar, usa el parámetro nativo `unit="mg/L"` en el exportador para que la conversión se aplique sobre las celdas numéricas de la Sección 2.

---

## 2. Mapa Rápido de Componentes

| Módulo / Clase | Propósito | Cuándo usarlo |
| :--- | :--- | :--- |
| `Batch` | Contenedor principal de la corrida analítica | Siempre: agrupa analitos, estándares internos y muestras |
| `Sample` | Entidad de muestra individual | Representa calibradores, blancos, QCs y muestras desconocidas |
| `Analyte` | Definición de elemento/isótopo ($\text{Cr}^{52}$, $\text{Sc}^{45}$, etc.) | Configuración de elementos y designación de ISTD |
| `parse_agilent_counts` | Parser de Excel exportado por Agilent MassHunter | Para importar cuentas CPS y metadatos de corridas reales |
| `parse_agilent_calibration` | Parser de tabla `CAL.xlsx` de Agilent | Para extraer niveles de concentración y mapeo de ISTD |
| `apply_calibration_table` | Asigna concentraciones conocidas a los calibradores | Vincula `CAL.xlsx` con el `Batch` |
| `parse_sample_prep` / `apply_sample_prep` | Ingesta de pesadas, humedades y dilución | Para cargar planillas de preparación (.xlsx/.csv) en el `Batch` |
| `Processor` | Motor del pipeline de cálculo | IS-correction $\rightarrow$ Calibración $\rightarrow$ Blancos $\rightarrow$ Prep Math |
| `export_excel_formula_report` | Exportador nativo de Excel con fórmulas | Para generar la hoja analítica completa con fórmulas vivas |
| `export_split_dilution_report` | Generador del reporte de 3 pestañas | Cuando se miden mayoritarios diluidos y trazas sin diluir |

---

## 3. Recetas Típicas de Laboratorio (ICP-MS)

### Receta 1: Muestras de Agua / Líquidas Directas con Calibración Agilent

Este es el caso más común: aguas superficiales, subterráneas o de consumo procesadas a partir de archivos de MassHunter.

```python
from pathlib import Path
from icptools import (
    parse_agilent_counts,
    parse_agilent_calibration,
    apply_calibration_table,
    Processor,
    export_excel_formula_report,
)

# 1. Cargar datos del instrumento y tabla de calibración
batch = parse_agilent_counts("datos/FQ_COUNTS.xlsx")
cal_data = parse_agilent_calibration("datos/CAL.xlsx")
apply_calibration_table(batch, cal_data)

# 2. Ejecutar procesamiento con blank_offset (ideal para trazas cerca de cero)
proc = Processor(batch, weighting="blank_offset")
proc.process()

# 3. Exportar Excel nativo con fórmulas
export_excel_formula_report(
    batch=batch,
    output_path="reportes/Reporte_Aguas.xlsx",
    instrument_loqs={"Cr52": 0.2, "As75": 0.5, "Pb208": 0.1},
    report_title="Monitoreo de Aguas Superficiales",
)
```

---

### Receta 2: Doble Dilución (3 Pestañas: Altos Diluidos + Bajos Sin Diluir + Unificado)

En matrices ambientales (ej. cuencas fluviales), los cationes mayoritarios ($\text{Na}$, $\text{Mg}$, $\text{K}$, $\text{Ca}$) saturan el detector sin diluir, mientras que las trazas ($\text{Cr}$, $\text{Ni}$, $\text{Cu}$, $\text{As}$, $\text{Pb}$) caen bajo el LoQ si se diluyen. Se miden ambas y se consolida un reporte en 3 pestañas.

```python
from icptools import (
    parse_agilent_counts,
    apply_calibration_table,
    Processor,
    export_split_dilution_report,
)

# 1. Cargar y calibrar
batch = parse_agilent_counts("datos/FQ_COUNTS.xlsx")
apply_calibration_table(batch, "datos/CAL.xlsx")

# 2. Procesar
proc = Processor(batch, weighting="blank_offset")
proc.process()

# 3. Definir grupos de analitos
altos = ["Na23", "Mg24", "K39", "Ca44"]
bajos = ["Cr52", "Mn55", "Fe56", "Ni60", "Cu63", "Zn66", "As75", "Cd111", "Pb208"]

# 4. Exportar reporte de 3 pestañas
# Pestaña 1: Altos (mg/L, DF=100)
# Pestaña 2: Bajos (ug/L, DF=1)
# Pestaña 3: Unificado (enlace vivo a las pestañas 1 y 2 sin errores #VALUE!)
export_split_dilution_report(
    batch=batch,
    output_path="reportes/REPORTE_CONSOLIDADO_3_PESTANIAS.xlsx",
    high_analytes=altos,
    low_analytes=bajos,
    high_units="mg/L",
    low_units="ug/L",
    instrument_loqs={"Cr52": 0.2, "As75": 0.5, "Pb208": 0.1, "Na23": 0.05},
    report_title="Monitoreo Ambiental - Cuenca Fluvial",
)
```

---

### Receta 3: Digestión de Muestras Sólidas (Suelo/Sedimento/Lodo) con Humedad y Blanco de Método

Muestras sólidas digeridas por microondas (ej. $0.5\text{ g}$ llevados a $50\text{ mL}$).
Se resta el blanco de método (`MBLK`) correspondiente al lote de digestión (`prep_group`) y se corrige por porcentaje de humedad para reportar en base seca.

```python
from icptools.models import Batch, Sample, Analyte, SampleType, SampleMatrix
from icptools.pipeline import Processor
from icptools.reporting import export_excel_formula_report

batch = Batch(name="Soil_Digestion_Run")
batch.add_analyte(Analyte("Pb208", "Pb", 208))
batch.add_analyte(Analyte("Rh103", "Rh", 103, is_internal_standard=True))
batch.analyte_to_is["Pb208"] = "Rh103"

# 1. Estándares de calibración (Líquidos, ug/L)
for level, cps in [(0.0, 50.0), (10.0, 5000.0), (100.0, 50000.0)]:
    s = Sample(f"STD_{level}", SampleType.BLANK if level == 0 else SampleType.STANDARD)
    s.known_concentrations["Pb208"] = level
    s.raw_intensities = {"Pb208": cps, "Rh103": 50000.0}
    batch.add_sample(s)

# 2. Blanco de Método (digestado junto con el lote "LOTE_SUELOS_01")
mblk = Sample("MBLK_01", SampleType.METHOD_BLANK, prep_group="LOTE_SUELOS_01", matrix=SampleMatrix.SOLID)
mblk.mass = 0.5000       # 0.5 g
mblk.final_volume = 50.0 # 50 mL
mblk.raw_intensities = {"Pb208": 500.0, "Rh103": 50000.0} # Contaminación ~ 1 ug/L
batch.add_sample(mblk)

# 3. Muestra de Suelo con 20% de humedad (Masa húmeda 0.50 g -> Masa seca 0.40 g)
soil = Sample("SUELO_01", SampleType.UNKNOWN, prep_group="LOTE_SUELOS_01", matrix=SampleMatrix.SOLID)
soil.mass = 0.5000
soil.percent_humidity = 20.0
soil.final_volume = 50.0
soil.dilution_factor = 1.0
soil.raw_intensities = {"Pb208": 15000.0, "Rh103": 50000.0}
batch.add_sample(soil)

# 4. Procesar y Exportar
proc = Processor(batch)
proc.process()

export_excel_formula_report(
    batch=batch,
    output_path="reportes/Reporte_Suelos_Auditables.xlsx",
    analytes=["Pb208"],
    instrument_loqs={"Pb208": 0.1},
    report_title="Control de Metales en Suelos",
)
```

En la hoja generada:
* La Sección 2 contendrá la fórmula nativa:
  `=(((InstrConc - MBLK) * (Vol/1000) * Dilution) / (Mass * (1 - Hum/100)))`
* El resultado final en la Sección 3 estará auditado en $\text{mg/kg}$ sobre base seca.

---

### Receta 4: Batch Mixto (Efluentes Líquidos + Sólidos en una misma corrida)

En una misma secuencia de ICP-MS se miden efluentes (líquidos directos o diluidos) junto con muestras sólidas de lodo digerido:

```python
# Muestra líquida (no tiene masa ni volumen de digestión; usa Conc * Dilution)
effluent = Sample("EFLUENTE_01", SampleType.UNKNOWN, matrix=SampleMatrix.LIQUID)
effluent.dilution_factor = 5.0 # Diluido 1:5
effluent.raw_intensities = {"Cu63": 12000.0, "Sc45": 50000.0}
batch.add_sample(effluent)

# Muestra sólida (utiliza masa, volumen y % humedad)
sludge = Sample("LODO_01", SampleType.UNKNOWN, matrix=SampleMatrix.SOLID, prep_group="BATCH_LODOS")
sludge.mass = 0.5200
sludge.final_volume = 50.0
sludge.percent_humidity = 15.0
sludge.raw_intensities = {"Cu63": 25000.0, "Sc45": 50000.0}
batch.add_sample(sludge)

proc = Processor(batch)
proc.process()
export_excel_formula_report(batch, "reportes/Batch_Mixto.xlsx")
```

El motor exportador activa automáticamente las columnas de preparación (`Mass`, `% Humidity`, `Vol`) y aplica la fórmula de líquido a las filas líquidas y la de sólido a las filas sólidas.

---

### Receta 5: Carga Automatizada de Planilla de Preparación (Pesadas y Humedades)

En lugar de cargar masas y volúmenes muestra por muestra en código, se utiliza una planilla Excel o CSV de preparación de laboratorio (con columnas en español o inglés como `Muestra`, `Masa (g)`, `Volumen (mL)`, `% Humedad`, `Factor Dilución`, `Lote`, `Tipo Muestra`):

```python
from icptools import (
    parse_agilent_counts,
    parse_agilent_calibration,
    apply_calibration_table,
    apply_sample_prep,
    Processor,
    export_excel_formula_report,
)

# 1. Cargar datos del equipo y calibración
batch = parse_agilent_counts("datos/FQ_COUNTS.xlsx")
apply_calibration_table(batch, "datos/CAL.xlsx")

# 2. Inyectar pesadas y preparación desde la planilla del laboratorio
apply_sample_prep(batch, "datos/PLANILLA_PREPARACION.xlsx")

# 3. Procesar y generar reporte
proc = Processor(batch)
proc.process()

export_excel_formula_report(
    batch=batch,
    output_path="reportes/Reporte_Suelos_Automatizado.xlsx",
    report_title="Control de Metales en Suelos y Sedimentos",
)
```

---

## 4. Opciones de Ponderación de Calibración (`weighting`)

Al instanciar `Processor(batch, weighting=...)`:

* `"none"`: Regresión lineal por mínimos cuadrados ordinarios ($y = mx + b$). Útil cuando el rango es estrecho (menos de 2 órdenes de magnitud).
* `"1/x"`: Ponderación inversa a la concentración ($w_i = 1/x_i$). Reduce la influencia de los puntos altos sobre el intercepto.
* `"blank_offset"`: **Recomendado para ICP-MS en trazas**. Fija el intercepto exactamente en la respuesta del blanco de calibración ($x=0$) y calcula la pendiente óptima $m = \frac{\sum x(y - b)}{\sum x^2}$. Garantiza que el blanco dé exactamente $0.0\ \mu\text{g/L}$ y previene concentraciones negativas artificiales en trazas.

---

## 5. Reglas de Validación para Agentes Autónomos

Antes de considerar una tarea analítica como completada:

1. **Verificar $R^2$ de Calibración**:
   ```python
   from icptools import get_calibration_summary
   cal_sum = get_calibration_summary(proc)
   for _, row in cal_sum.iterrows():
       assert row["Fit Successful"] is True
       assert row["R-squared"] >= 0.995, f"R2 bajo para {row['Analyte']}: {row['R-squared']}"
   ```
2. **Verificar Ausencia de Errores en Fórmulas de Excel**:
   ```python
   import openpyxl
   wb = openpyxl.load_workbook(archivo_salida, data_only=False)
   for ws in wb.worksheets:
       for row in ws.iter_rows(values_only=True):
           for cell in row:
               val = str(cell or "")
               assert not any(err in val for err in ["#VALUE!", "#REF!", "#DIV/0!", "#NAME?"])
   ```
3. **Comprobar Réplicas de Campo y Duplicados**:
   Calcular el RPD (Relative Percent Difference) entre réplicas (como `ALPHA` y `BETA`). Para elementos mayoritarios, el RPD esperado es $< 10\%$.
