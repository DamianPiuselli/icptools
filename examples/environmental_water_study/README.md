# Environmental Water Study — Agilent MassHunter ICP-MS Example

Este directorio contiene un caso de estudio analítico completo y reproducible de monitoreo ambiental de aguas (ríos, estuarios y canales urbanos) medidos por **ICP-MS (Agilent 7900/8900 MassHunter)**.

Sirve como ejemplo de referencia en GitHub tanto para usuarios como para agentes de IA sobre cómo estructurar los datos, escribir el script de procesamiento y generar reportes auditables bajo la norma ISO 17025.

---

## 1. Contexto Analítico: El Desafío del Rango Dinámico

En aguas ambientales y estuarinas coexisten:
1. **Cationes mayoritarios** ($\text{Na}$, $\text{Mg}$, $\text{K}$, $\text{Ca}$) en concentraciones de $\text{mg/L}$. Si se miden sin dilución, saturan el detector del ICP-MS o dañan la vida útil del multiplicador de electrones. Por tanto, se inyectan a **dilución 1:100** ($DF=100$).
2. **Metales pesados y metaloides traza** ($\text{Cr}$, $\text{Mn}$, $\text{Fe}$, $\text{Ni}$, $\text{Cu}$, $\text{Zn}$, $\text{As}$, $\text{Cd}$, $\text{Pb}$) en concentraciones de $\mu\text{g/L}$ o sub-$\mu\text{g/L}$. Si se diluyen 1:100, caen por debajo del límite de cuantificación ($\text{LoQ}$). Por tanto, se miden **sin diluir** ($DF=1$).

`icptools` resuelve este problema generando un **reporte consolidado de 3 pestañas**:
- **Pestaña 1 (`Altos Diluidos`)**: Curvas de calibración y cuantificación de $\text{Na}, \text{Mg}, \text{K}, \text{Ca}$ a $DF=100$ expresados en $\text{mg/L}$.
- **Pestaña 2 (`Bajos Sin Diluir`)**: Curvas de calibración y cuantificación de elementos traza a $DF=1$ expresados en $\mu\text{g/L}$.
- **Pestaña 3 (`Unificado`)**: Hoja de entrega al cliente donde cada muestra tiene una única fila que consolida automáticamente mayoritarios y trazas mediante fórmulas vivas referenciadas a las pestañas 1 y 2, evaluando límites de cuantificación (`< LoQ`) sin generar errores `#VALUE!`.

---

## 2. Archivos del Directorio

| Archivo | Rol | Descripción |
| :--- | :--- | :--- |
| `CAL.xlsx` | Datos Crudos | Tabla de calibración exportada por Agilent MassHunter (niveles de concentración, analitos y asignación de estándares internos $\text{Sc}^{45}, \text{Ge}^{72}, \text{In}^{115}, \text{Bi}^{209}$). |
| `FQ_COUNTS.xlsx` | Datos Crudos | Cuentas crudas (CPS) y metadatos de secuencia exportados por Agilent MassHunter. Contiene blancos de calibración, estándares S5–S10 y muestras de campo (sin diluir y con dilución 1:100 identificadas en comentarios). |
| `process_run.py` | Documentación y Pipeline | Script de procesamiento de Python co-localizado con los datos. Configura el procesamiento, verifica la calidad de calibración ($R^2 \ge 0.995$) y ejecuta la exportación del reporte. |
| `Reporte_Consolidado_3_Pestanias.xlsx` | Entregable Final | Hoja de cálculo Excel con fórmulas nativas vivas (`SLOPE`, `INTERCEPT`, `RSQ`, cocientes de estándar interno, dilución y evaluación condicional contra el LoQ). |

---

## 3. Filosofía de Co-localización de Scripts (Procedencia de Datos)

En `icptools`, **los scripts de procesamiento deben guardarse siempre en la misma carpeta que contiene los datos crudos**.

Incluso cuando el archivo `.xlsx` resultante es 100% autocontenido y auditable (cualquier auditor puede abrirlo en Excel o LibreOffice y verificar cada celda matemática), el script `process_run.py` preserva la **procedencia analítica**:
* Qué modelo de regresión se aplicó (OLS, ponderación $1/x$ o blank offset).
* Qué límites de cuantificación instrumentales (`LoQs`) se utilizaron.
* Qué analitos se asignaron al grupo de alta dilución y cuáles al de trazas.
* Qué muestras o lavados se excluyeron.

Dejar el script junto a `CAL.xlsx` y `FQ_COUNTS.xlsx` garantiza que cualquier analista o auditor pueda reproducir el procesamiento exactamente en el futuro.

---

## 4. Cómo Ejecutar el Ejemplo

Desde la raíz del repositorio o dentro de esta carpeta:

```bash
# Opción 1: Ejecutar directamente con python
python examples/environmental_water_study/process_run.py

# Opción 2: Si estás dentro del directorio
cd examples/environmental_water_study
python process_run.py
```

Salida esperada en consola:
```text
=== Procesando Corrida Ambiental en: environmental_water_study ===
Cargando cuentas instrumentales: FQ_COUNTS.xlsx
Cargando tabla de calibración: CAL.xlsx
Ejecutando pipeline analítico (normalización de ISTD y calibración)...

--- Resumen de Curvas de Calibración ---
  Na23       | R² = 0.99988 [OK]
  Mg24       | R² = 0.99991 [OK]
  K39        | R² = 0.99985 [OK]
  Ca44       | R² = 0.99979 [OK]
  Cr52       | R² = 0.99994 [OK]
  Mn55       | R² = 0.99992 [OK]
  Fe56       | R² = 0.99981 [OK]
  Ni60       | R² = 0.99993 [OK]
  Cu63       | R² = 0.99995 [OK]
  Zn66       | R² = 0.99992 [OK]
  As75       | R² = 0.99996 [OK]
  Cd111      | R² = 0.99991 [OK]
  Pb208      | R² = 0.99997 [OK]

Exportando reporte de 3 pestañas a: Reporte_Consolidado_3_Pestanias.xlsx
Reporte generado exitosamente con fórmulas nativas vivas en:
  .../examples/environmental_water_study/Reporte_Consolidado_3_Pestanias.xlsx
```
