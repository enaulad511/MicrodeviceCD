# Archivos vigentes y legacy

Inventario del 14/10/2026: qué archivos usa hoy la app y cuáles quedaron sin uso. Los sin
uso **no se borraron**: se renombraron con el prefijo `legacy_` (con `git mv`, así
conservan la historia) para que se distingan a simple vista y nadie los tome por código
vivo.

## 1. Cómo se detectó

Grafo de imports estático desde `main.py`, sobre todos los `.py` trackeados (sin
`firmware/`). Se recorre el AST, así que **incluye los imports perezosos dentro de
funciones**, que en este repo son muchos (`gpiod`, `serial` y los drivers se importan
dentro de callbacks).

Se buscaron también imports dinámicos (`importlib`, `__import__`, `exec`, `run_path`):
**no hay ninguno**, así que el grafo es completo. Un archivo es *vigente* si es alcanzable
desde `main.py`, o si es una herramienta que todavía habla el protocolo y el hardware
actuales.

Verificado tras renombrar:

- `import main` funciona;
- los 14 legacy compilan;
- no quedan referencias a los nombres viejos (README, docs, reglas, `update_repo`,
  `runAA`, `.desktop`).

## 2. Vigentes

**App (36 archivos alcanzables desde `main.py`):** `main.py`, todo `ui/` (incluido
`ui/analysis/`), `templates/` y estos `Drivers/`:

- `ClientUDP.py`
- `DriverGPIO.py`
- `DriverStepperSys.py`
- `EmstatUtils.py`
- `ReaderADS.py`

**Herramientas vigentes, fuera de la app:**

- `test/test_ads.py`: chequeo del ADS1115 con el driver actual.
- `test/test_udp_cadence.py` (local, gitignored): diagnóstico de cadencia UDP
  ([pcr_eje_tiempo.md](pcr_eje_tiempo.md) §6).

**Recursos:**

- `resources/settings.json`, `pcr_projects.json` y `electrochem_projects.json`: los usa
  la app.
- `errors_emstat.json`: lo carga `EmstatUtils`.
- `imgs/title.png`: lo usa `FrameInit`.
- `emstat_properties.json`: **ningún código lo carga**. Es una tabla de referencia del
  manual de MethodSCRIPT; se deja como material de consulta, no como legacy.

**Scripts del Pi:** `runAA`, `update_repo`, `*.desktop`.

## 3. Legacy (renombrados `legacy_*`, sin uso)

| archivo (nombre nuevo) | por qué es legacy |
|---|---|
| `Drivers/legacy_PIDController.py` | PID con anti-windup que **nadie importa**. El control térmico de PCR es el PI propio de `PcrFrame` (`_reach_temperature_pi`, `hold_temperature`). La regla de PCR lo presentaba como el PID del ciclador: estaba mal y se corrigió. |
| `Drivers/legacy_DriverMotorDC.py` | Motor DC con BTS7960 (`RPWM`/`LPWM`), reemplazado por el stepper (`DriverStepperSys`). |
| `Drivers/legacy_DriverEncoder.py` | Encoder del motor DC, del mismo stack retirado. |
| `Drivers/legacy_EncoderData.py` | Lectura serial del encoder viejo; nadie lo importa. |
| `legacy_test.py` | Prueba UART del motor DC (`MotorBTS7960`). |
| `test/legacy_curve_motor.py` | Curva del motor DC (`DriverEncoderSys`). |
| `test/legacy_test_bts9760.py` | Prueba del BTS7960 + encoder. |
| `test/legacy_test_raspberry.py` | Prueba del motor DC + encoder. |
| `test/legacy_test_udp_emstat_arduino.py` | Cliente TCP para el **MKR WiFi 1010** con comandos `RUN,LSV,…`: la arquitectura anterior a la cadena Wemos → Pico con JSON. |
| `test/legacy_test_read_upd_plot.py` | Graficaba voltaje y corriente recibidos por UDP en texto tabulado: protocolo retirado. |
| `test/legacy_test_wifi_udp.py` | CV voltaje contra corriente por UDP desde el Arduino: protocolo retirado. |
| `test/legacy_test_emstat_tcp_rasp.py` | Usa las clases actuales, pero su payload **no lleva `"ch"`**, y el firmware v1.6+ lo rechaza con `emstat_error` ([emstat_abort_y_canal.md](emstat_abort_y_canal.md)). La app lo reemplaza. |
| `test/legacy_test_frame_style.py` | Prueba suelta de estilos de ttkbootstrap. |
| `test/legacy_Engranajes.py` | Modelo CAD de engranajes (`cadquery`); no es software del equipo. |

Los scripts legacy que importaban drivers legacy se ajustaron a los nombres nuevos
(`from Drivers.legacy_DriverMotorDC import …`), así que siguen ejecutables si algún día
se necesitan.

## 4. Locales no trackeados (no se tocaron)

Están en la carpeta del usuario pero no en git (gitignored). Solo el usuario sabe si los
sigue usando, así que no se renombraron. Clasificación sugerida:

- **En uso:** los notebooks del paper (`analisis_*.ipynb`, `collage_temp_paper.ipynb`,
  `analysis_plots.ipynb`) y `manuscript_draft.md`.
- **Herramienta válida:** `test_swv_profile.py` renderiza el perfil SWV, y la clase que
  usa (`ShowProfileFrame`) sigue existiendo.
- **Candidatos a legacy:**
  - `test_emstat_tcp_rasp.py` de la raíz: copia idéntica del ya renombrado en `test/`;
  - `test/test_server_tcp.py`: servidor TCP de prueba, de abril.
- **A decidir por el usuario:**
  - `code_test.py` y `test/test_plot_curves.py`: gráficas con pandas de CSV de
    `files_test`, de abril; probablemente superados por los notebooks;
  - `analysis_fluorescense_test.py`: calibración del fotorreceptor, de junio.

## 5. Otros

- **`output.png`** (raíz, trackeado): **nada lo referencia**. Entró en el commit
  `355cf72` ("update stale time"), probablemente por accidente. No se renombró porque no
  es código: decidir si se borra del repo.
- `figures/` y `files_test/` son salidas y datos, gitignored; fuera de este inventario.

__author__ = "Edisson A. Naula"
__date__ = "$ 14/10/2026 $"
