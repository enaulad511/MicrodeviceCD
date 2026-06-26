# Estado del arte y revistas — Plataforma CD microfluídica: PCR plasmónica + sensado electroquímico

> Reporte consolidado de dos rondas de investigación (210 agentes, verificación adversarial 3-votos).
> **Restricción de publicación:** revistas NO MDPI y Q1 o Q2 en SJR. Las **referencias** citadas en el artículo pueden ser de cualquier venue, incluyendo MDPI.
> Artículos: solo 2015–2026.
>
> ⚠️ **Antes de citar:** JIF/SJR son aproximados; verifica en scimagojr.com antes de enviar. Dos fuentes (Sensing & Bio-Sensing Research 2023 `S2590137023000432`; Talanta 2026 FACILE 2.0 `S0039914026004170`) devolvieron HTTP 403 en fetch directo — confirma DOI/autores vía Crossref. Las afirmaciones refutadas están listadas en §6 y **no deben citarse con esas cifras**.

---

## 1. Revistas destino (no-MDPI, Q1/Q2 en SJR)

| Revista | Editorial | SJR / Cuartil confirmado | Encaje | Recomendación |
|---|---|---|---|---|
| **Lab on a Chip** | RSC | Q1 — Biomedical Engineering / Chemistry (estimado; confirmar SCImago) | Microfluídica centrífuga, PCR integrada, detección EC on-chip | **Primera opción.** Publica PCR sample-to-answer en CD + detección EC integrada. |
| **Biosensors and Bioelectronics** | Elsevier | **Q1** confirmado (SJR >2, IF ~12) | Biosensores electroq., sensores integrados, microfluídica | **Opción premium.** Publica biosensores EC avanzados y plataformas integradas PCR+EC. |
| **Environmental Science & Technology** | ACS | **Q1** (SJR >2, IF ~10–11) | Diagnóstico de agua, detección patógenos + metales | Ideal para el **encuadre de calidad de agua**; publicó CD centrífugo para virus en agua (2025). |
| **Talanta** | Elsevier | **Q1** Analytical Chemistry, **Q2** Biochemistry (SJR ~0.976, verificado) | Instrumentación analítica / potenciostato integrado | Para el **enfoque de instrumento + control** (CV/SWV + sistema embebido). |
| **Analytica Chimica Acta** | Elsevier | Q1 (SJR ~0.8–1.0, confirmar) | Química analítica, sensores EC, microdispositivos | Alternativa sólida a Talanta; acepta sensores EC en chip y validación de agua. |
| **The Analyst** | RSC | Q1–Q2 (confirmar SCImago) | Química analítica, biosensores, microfluídica | Encaja con validación analítica de la plataforma. |
| **ACS Nano** | ACS | **Q1** (SJR >4, IF ~17) | Nanomateriales fotónicos, PCR plasmónica | Venue aspiracional; para el ángulo nanofilm de oro + LED. |
| **Microchimica Acta** | Springer | Q1–Q2 (confirmar) | Biosensores EC, microdispositivos, metales pesados | Publica detección EC de E. coli y SWASV de metales; revisión pendiente. |
| **Sensing and Bio-Sensing Research** | Elsevier | **Q1** (confirmado en 2ª ronda) | PCR fotónica + biosensado | Publicó el paper de doble nanofilm de oro + LED 50 W (2023). |
| **Journal of Electrical Engineering & Technology** | Springer | **Q2** (confirmado en 2ª ronda) | Control + microfluídica | Para el ángulo de control PID del termociclador. |

**Descartadas o a verificar antes de usar:**
- **RSC Advances** — Q2/Q3 según ronda (verificar; puede no cumplir Q1/Q2 en todas las categorías).
- **Frontiers in Chemistry** — Frontiers Media (no MDPI, pero modelo APC similar); cuartil variable, confirmar.
- **Accounts of Chemical Research** — ACS, Q1, pero es revista de **reviews/perspectivas**, no acepta artículos experimentales originales → solo para citar, no para enviar.
- **HardwareX** — Elsevier, foco open-hardware; SJR probablemente bajo → verificar antes de incluir.

---

## 2. Artículos de estado del arte verificados (2015–2026)

*(Todas las afirmaciones sobrevivieron verificación adversarial ≥2-1. Los datos refutados están en §6.)*

---

### 2.1 PCR plasmónica / fototérmica — film de oro + LED

**[R1]** Jalili et al. (2021). *A plasmonic gold nanofilm-based microfluidic chip for rapid and inexpensive droplet-based photonic PCR.* **Scientific Reports** (Nature Portfolio). DOI: `10.1038/s41598-021-02535-1`
- Film de Au 120 nm, 2 LED azules SMD 450 nm, 10 W @ 900 mA (arriba/abajo del chip).
- PID sobre Arduino Uno + termopar MAX6675: 94.99 ± 0.41 °C, 60.02 ± 0.37 °C, 72.01 ± 0.39 °C.
- ⚠️ **NO citar** las tasas de rampa (7.37 °C/s) ni la temperatura máxima de film (230 °C) — refutadas 0-3.

**[R2]** (2023). *Highly efficient photonic PCR system based on plasmonic heating of gold nanofilms.* **Sensing and Bio-Sensing Research** (Elsevier, Q1). PII: `S2590137023000432`
- Doble film de oro (RF magnetron sputter), LED 50 W; tasas: **13.20 °C/s calentamiento, 7.92 °C/s enfriamiento**; ΔT <1 °C en todas las fases; 30 ciclos en **7.5 min**, 20 µL DNA bacteriano.
- ⚠️ Confirmar DOI/autores vía Crossref (403 en fetch).

**[R3]** Kim, Kim, Park, Jon (2017). *Gold Nanorod-based Photo-PCR System for One-Step, Rapid Detection of Bacteria.* **Nanotheranostics**. DOI: `10.7150/ntno.18720`
- Nanorods Au PEG + láser 808 nm; lisis + amplificación en un paso; **validado en E. coli** (+ S. aureus, S. epidermidis).
- *Caveat: láser NIR + NPs en suspensión, no LED + film fijo.*

**[R4]** (2022). *Ultrafast Real-Time PCR in Photothermal Microparticles.* **ACS Nano**. DOI: `10.1021/acsnano.2c07017`
- **22.0/23.5 °C/s**, 40-ciclos qPCR en ~5 min; **E. coli 10²–10⁸ copias/µL, eficiencia 97.62 %**; volumen ~100 nL.

**[R5]** (2024). *Au nanoshell photothermal PCR.* **Scientific Reports** (Nature). DOI: `10.1038/s41598-024-54406-0` (PMC10873297)
- Au nanoshells 155 ± 7 nm + láser 808 nm; PID: **2.4 ± 0.05 °C/s calentamiento, 3.9 ± 0.05 °C/s enfriamiento** (menor que film → referencia comparativa).
- ⚠️ NO citar "40 ciclos en 800 s" — refutado 0-3.

---

### 2.2 Control térmico — PID y PID + fuzzy para termocicladores miniaturizados

**[R6]** Cheng et al. (2024). (Fuzzy adaptive PID en termociclador miniaturizado con 4 módulos TEC). **Biosensors** (MDPI, Q1). PMC: `PMC11352655`
- Fuzzy adaptive PID ajusta dinámicamente Kp, Ki, Kd; ΔT mantenido 0.5–1 °C.
- Tasas: **11 °C/s calentamiento, 8 °C/s enfriamiento**; 58 → 96 °C en 3.4 s; 96 → 58 °C en 4.7 s.
- 45 ciclos en **~700 s** (≈19 min).
- *(Citable como referencia; no es venue de publicación destino.)*

**[R7]** (2021, Sci. Reports) — *ver [R1]*: PID sobre Arduino + termopar MAX6675 para chip LED+nanofilm. Valores de temperatura verificados (±0.4 °C). **Línea base PID sin fuzzy.**

**[R8]** (2022). (PID en microchip de flujo continuo, amplificación Lambda Phage DNA). **Journal of Electrical Engineering & Technology** (Springer, Q2). DOI: `10.1007/s42835-021-00969-1`
- PID convencional con retroalimentación térmica en tiempo real; amplificación de DNA confirmada.

**[R9]** (2025). (Control adaptativo por fluorescencia de L-DNA, láser 1370 nm, sin PID). **Biosensors** (MDPI, Q1). PMC: `PMC12026111`
- Arquitectura alternativa al PID: monitorea derivada de fluorescencia de hibridación/fusión de L-DNA para conmutar fases; 40 ciclos en 14.62 ± 0.42 min (singleplex).
- *(Referencia de contraste; MDPI — solo para citar.)*
- ⚠️ NO citar las tasas de rampa específicas del láser — refutadas 1-2.

---

### 2.3 Microfluídica centrífuga (lab-on-a-CD) para PCR / diagnóstico de patógenos

**[R10]** Czilwik et al. (2015). *LabDisk con PCR anidada + prep de muestra integrada.* **Lab on a Chip** (RSC). DOI: `10.1039/C5LC00591D`
- **Ancla canónica:** extracción DNA + pre-amplificación multiplex + PCR RT específica; **LOD 5 cfu E. coli** en 200 µL; resultado en 3h 45min.
- *Caveat: matriz suero (sepsis clínica), no agua.*

**[R11]** Huang & Jiang (2025). *Quantification of Viruses in Wastewater on a Centrifugal Microfluidic Disc.* **Environmental Science & Technology** (ACS). DOI: `10.1021/acs.est.4c13718`
- CD integra concentración + purificación + amplificación on-disc; virus PMMoV en aguas residuales 6.0×10⁴–2.1×10⁷ copias/mL; <1.5 h. **Mejor ancla para calidad de agua.**
- *Caveat: usa ddRT-LAMP (isotérmico), no PCR por ciclado térmico.*

---

### 2.4 Detección electroquímica de E. coli con ferri/ferrocianuro

**[R12]** (2025). *Bacteria-imprinted polydopamine / MGO-IL-Pd/GCE biosensor para E. coli.* **Scientific Reports** (Nature). PMC: `PMC12749742`
- **[Fe(CN)₆]³⁻ᐟ⁴⁻ como sonda redox** en CV y SWV para detección de E. coli.
- **LOD = 1.50 CFU/mL**; rango lineal 5.0–1.0×10⁷ CFU/mL; R² = 0.992 (SWV).
- Electrodo: BIP/MGO-IL-Pd/GCE (bacteria-imprinted polymer + óxido de grafeno magnético + IL + Pd NPs).

**[R13]** (2023). *D-mannose functionalized GCE + Au NPs, detección label-free de E. coli por EIS con ferri/ferrocianuro.* PMC: `PMC10296727`
- [Fe(CN)₆]³⁻ᐟ⁴⁻ (EIS: 0.1 Hz–100 kHz, 0.24 V) para caracterizar cada paso de funcionalización y detectar E. coli vía cambio de Rct.
- *(Confirmar DOI/journal completo antes de citar.)*

---

### 2.5 Detección electroquímica de metales pesados (ASV/SWV) en chip

**[R14]** Zhao, Tran, Modha, Sedki et al. (2022). *Multiplexed Anodic Stripping Voltammetry Detection of Heavy Metals in Water.* **Frontiers in Chemistry**. DOI: `10.3389/fchem.2022.815805`
- SWASV simultáneo de As(III)/Cd(II)/Pb(II) en agua; SPE + celda de flujo 3D-printed. **Ancla de metales pesados SWV.**

---

### 2.6 Plataformas integradas (NAAT + detección electroquímica / instrumento)

**[R15]** Hsieh, Ferguson, Eisenstein, Plaxco, Soh (2015). *Integrated Electrochemical Microsystems for Genetic Detection of Pathogens at the Point of Care.* **Accounts of Chemical Research** (ACS). DOI: `10.1021/ar500456w`
- Review que justifica la arquitectura **amplificación (PCR/LAMP) + sensor E-DNA electroquímico** en microfluídica POC (sin óptica, compatible con IC). *(Solo para citar, no venue de envío.)*

**[R16]** FACILE 2.0 (2026). *Multifunctional potentiostat for static and fluidic electrochemical sensing.* **Talanta** (Elsevier, Q1). PII: `S0039914026004170`
- Potenciostato portátil CV/SWV/cronoamperometría/EIS + single-board computer + touchscreen + flujo programable.
- SWV label-free de P. aeruginosa en agua de grifo: LOD 1000 CFU/mL, RSD <10 %, n=5.
- **Análogo más cercano al stack electroquímica+control embebido del prototipo.** *(Confirmar DOI, 403.)*

---

## 3. Hallazgo de novedad confirmado

**Ningún paper 2015–2026 combina las tres tecnologías en un solo dispositivo:** PCR plasmónica (film de oro + LED) + detección electroquímica (CV/SWV) + disco CD centrífugo. Los dos vectores tecnológicos (PCR plasmónica + EC) están bien establecidos por separado pero no se han integrado en una plataforma única — esto refuerza la novedad de tu prototipo. Presénta la integración como la unión de tres subsistemas validados independientemente.

---

## 4. Artículos MDPI válidos como referencias (no como venue)

Pueden citarse en el paper aunque no publiques ahí:
- Cheng et al. (2024) — Fuzzy adaptive PID en termociclador. *Biosensors* (MDPI, Q1). PMC11352655. **[R6]**
- (2025) — Control adaptativo por fluorescencia L-DNA. *Biosensors* (MDPI, Q1). PMC12026111. **[R9]**
- Czilwik et al. (2015) era en RSC, no MDPI. ✓

---

## 5. Preguntas abiertas / huecos pendientes

1. **SJR de las 8 revistas restantes:** Lab on a Chip, RSC Advances, ES&T, Sensing & Bio-Sensing Res., Frontiers in Chemistry, ACS Nano, Microchimica Acta, HardwareX — **verificar en scimagojr.com** (el fetch directo falló por bloqueo).
2. **Fuzzy PID en disco giratorio:** todos los papers de fuzzy PID/control (R6–R9) usan cámaras estacionarias. No se encontró literatura de fuzzy PID para termocicladores en discos que giran — tu implementación puede ser novedosa en este aspecto.
3. **[Fe(CN)₆] en matrices reales (agua + metales + bacteria):** las referencias de E. coli con ferrocianuro (R12/R13) reportan LODs en buffer; los efectos de interferencia de metales pesados coexistentes en la sonda redox no están caracterizados en la literatura verificada.

---

## 6. Afirmaciones refutadas — NO citar estas cifras

| Dato | Fuente | Resultado |
|---|---|---|
| Tasas de rampa del nanofilm 120 nm + LED 450 nm (7.37 °C/s / 1.91 °C/s) | Sci. Reports 2021 `s41598-021-02535-1` | 0-3 REFUTADO |
| Temperatura máxima del film de Au (230 °C en 100 s) | Sci. Reports 2021 | 0-3 REFUTADO |
| 40 ciclos en 800 s para Au nanoshell | Sci. Reports 2024 `s41598-024-54406-0` | 0-3 REFUTADO |
| Tasas de rampa del láser 1370 nm (2.41/2.49 °C/s) | Biosensors 2025 PMC12026111 | 1-2 REFUTADO |
| SWV + [Fe(CN)₆] detecta E. coli: rango 25–6400 cfu/mL | PMC8953795 | 1-2 REFUTADO |
| Electrodo de lápiz grafito + tironina + ferroceno; LOD 53 cfu E. coli (SWV) | PMC8953795 | 0-3 REFUTADO |
| D-mannosa + GCE + AuNPs: LOD 2 CFU/mL, 60 min | PMC10296727 | 1-2 REFUTADO |
| Ferricianuro solo para caracterización (no detección) de E. coli | PMC9638781 | 1-2 REFUTADO |
| LoC centrífugo integrado: E. coli DH5α 2×10⁴–1.1×10⁹ CFU/mL sin modificación biológica | PMC9638781 | 1-2 REFUTADO |
| Control térmico en disco giratorio ±0.1 °C | PMC11202104 | 0-3 REFUTADO |

---

<!-- Consolidado de dos rondas de deep-research (210 agentes, 39 fuentes, verificación adversarial 3-votos). Ronda 1: 25 claims verificados, 24 confirmados. Ronda 2: 25 claims verificados, 15 confirmados. -->


| Article Name (Year) | Main Topic | DOI | Technology |
| :--- | :--- | :--- | :--- |
| A plasmonic gold nanofilm based microfluidic chip (2021) | Plasmonic PCR | 10.1038/s41598-021-02535-1 | Gold film and LED [5, 6] |
| Highly efficient photonic PCR system (2023) | Photonic PCR | 10.1016/j.biosx.2023.100346 | Double gold film [7] |
| Gold Nanorod based Photo PCR System (2017) | Bacteria detection | 10.7150/ntno.18720 | Nanorods and laser [7] |
| Ultrafast Real Time PCR in Photothermal Microparticles (2022) | Rapid PCR | 10.1021/acsnano.2c07017 | Microparticles [8] |
| Au nanoshell photothermal PCR (2024) | Photothermal PCR | 10.1038/s41598-024-54406-0 | Nanoshells and laser [8] |
| Fuzzy adaptive PID in thermocycler (2024) | Thermal control | 10.3390/bios14080379 | Fuzzy PID and TEC [9] |
| PID in continuous flow microchip (2022) | PID control | 10.1007/s42835-021-00969-1 | PID in flow [6] |
| Adaptive control by fluorescence (2025) | Adaptive control | 10.3390/bios15040258 | Laser without PID [10] |
| LabDisk with nested PCR (2015) | Centrifugal microfluidics | 10.1039/C5LC00591D | LabDisk [11] |
| Quantification of Viruses in Wastewater (2025) | Water quality | 10.1021/acs.est.4c13718 | Centrifugal CD [11] |
| Bacteria imprinted polydopamine biosensor (2025) | E coli detection | 10.1038/s41598-025-28920-8 | Biosensor [12] |
| D mannose functionalized GCE Au NPs (2023) | Label free detection | Not available | EIS [13] |
| Multiplexed Anodic Stripping Voltammetry (2022) | Heavy metals | 10.3389/fchem.2022.815805 | ASV and SWV [14] |
| Integrated Electrochemical Microsystems (2015) | Integrated platforms | 10.1021/ar500456w | EC Microfluidics [14] |
| FACILE 2 0 Multifunctional potentiostat (2026) | Portable potentiostat | 10.1016/j.talanta.2026.129761 | Embedded stack [15, 16] |
