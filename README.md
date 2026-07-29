<p align="center">
  <img src="resources/imgs/title.png" alt="µAA — Cuidado del Agua" width="620">
</p>

# MicrodeviceCD

Control software for a **centrifugal (CD) microfluidic platform** that combines
LED-photothermal PCR with integrated electrochemical detection, aimed at
**water-quality analysis** — pathogen and heavy-metal screening on a single disc.

The application is a Python/Tkinter GUI that runs on a **Raspberry Pi** and
orchestrates the whole instrument: plasmonic PCR thermal cycling (gold-nanofilm +
high-power LED heating, cooling by disc rotation), fluorescence readout,
disc actuation (DC motor + stepper), and four electrochemical methods driven
through an EmStat potentiostat.

**Status:** all four electrochemical methods — **CV, SQWV, EIS and CA** — are
implemented and validated on hardware. The `docs/` design notes are authoritative
for per-feature detail.

---

## Contents

- [What the GUI does](#what-the-gui-does)
- [Hardware & firmware](#hardware--firmware)
- [Installation](#installation)
- [Running](#running)
- [Updating the instrument](#updating-the-instrument)
- [Configuration](#configuration)
- [Data output](#data-output)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)
- [Design notes (`docs/`)](#design-notes-docs)
- [Development](#development)
- [License & use](#license--use)

---

## What the GUI does

Three top-level tabs (`ui/MainGUI.py`):

| Tab | What it does |
|---|---|
| **PCR** 🧪 | Full thermal cycler. Per-phase PID control (denaturation / high / low / extension), configurable cycle counts and hold times, live temperature + fluorescence plots, and named **project recipes** you can save, load, import and export. |
| **Electrochemical** 🧫 | Runs **CV**, **SQWV**, **EIS** and **CA** on the EmStat. One frame per method plus the electrode-channel selector (8-way MCP23017 mux), live streaming plots, keep-runs overlay, MethodSCRIPT preview, per-method project recipes and CSV export. |
| **Manual Control** 🖥️ | Subsystem exercise bench: **Quick Control** (motor + both LEDs + live temperature/fluorescence in one place), then individual Heating LED, Fluorescence LED, Disc, Photoreceptor and Temperature frames. |

A separate **Analysis** window (`ui/analysis/`) opens on top with four tabs —
*Peaks (CV)*, *SQWV Peaks*, *EIS* and *PCR* — for peak detection, Nyquist
inspection and PCR ramp-rate extraction. It seeds from the live run or from
saved CSVs, and exports/imports its own analysis state.

Temperature can be read from any of three sensors (thermocouple via MAX31855,
or the MLX90614 IR object/ambient channels); the active source is selectable in
the UI and feeds the PCR PID loop. Default is the thermocouple.

---

## Hardware & firmware

Subsystems and how the Pi reaches each one:

| Subsystem | Transport | Driver |
|---|---|---|
| Disc temperature broadcast (MAX31855 thermocouple + MLX90614 IR) | **UDP :5005** broadcast, `t_amb:t_obj:t_tc` | `Drivers/ClientUDP.py` |
| DC motor (BTS7960) and stepper, via a Raspberry Pi Pico | **UART** `/dev/ttyAMA0` | `Drivers/DriverMotorDC.py`, `Drivers/DriverStepperSys.py`, `Drivers/DriverEncoder.py` |
| Photoreceptor / analog reads (ADS1115) | **I²C** | `Drivers/ReaderADS.py` |
| Heating LED, fluorescence LED | **GPIO** (libgpiod v2) | `Drivers/DriverGPIO.py` |
| EmStat potentiostat | **TCP :5006** → Wemos → Pico → EmStat | `ui/EventEmstatFrame.py`, `Drivers/EmstatUtils.py` |

The potentiostat is **not** reached directly. The chain is three nodes, with a
parallel UDP broadcast used to recover packets lost on TCP:

```
Python app (this repo) ──TCP:5006──► Wemos D1 mini ──UART──► Pico 2 ──UART──► EmStat
                        ◄──UDP:5005── (same payload, mirrored for packet recovery)
```

The disc's own UDP broadcast is also how the app **discovers the instrument IP**
(`MainGUI.try_connect_disc`). Until a broadcast arrives, electrochemistry has no
address to send to.

### Expected firmware versions

The host assumes these versions are flashed on the microcontrollers. A version
mismatch is the most common cause of "the app runs but the hardware does nothing".

| Node | Expected | Source of truth |
|---|---|---|
| Pico 2 (EmStat bridge) | `emstat_wifi_v1.9` | `~/MicroPython/DiscPCB/` |
| Pico (stepper) | `StepperClass_V5` | `~/MicroPython/Stepper/` |
| Wemos D1 mini (Wi-Fi bridge) | `WemosD1Mini.ino` | Arduino sketchbook |

> ⚠️ **`firmware/` in this repo is a read-only mirror.** Nothing is flashed from
> here. Edit the originals in the MicroPython/Arduino projects, flash them, then
> refresh the mirror (each `firmware/*/README.md` has the resync command).

---

## Installation

Requires **Python 3.11+**. Tkinter must be available (`sudo apt install python3-tk`
on Raspberry Pi OS if `import tkinter` fails).

### Raspberry Pi (production)

The shipped launcher scripts hardcode a specific layout, with the virtualenv
**next to** the repository rather than inside it:

```
/home/raspb-cd/opt/
├── .venv/              ← virtualenv (outside the repo)
└── MicrodeviceCD/      ← this repository
```

```bash
mkdir -p /home/raspb-cd/opt && cd /home/raspb-cd/opt
git clone https://github.com/enaulad511/MicrodeviceCD.git

python3 -m venv .venv
source .venv/bin/activate

cd MicrodeviceCD
pip install -r requirements.txt

# Hardware-only dependencies — NOT in requirements.txt (see note below)
pip install gpiod pyserial

# Runtime config (.env is gitignored, so a fresh clone has none)
echo "environment=production" > .env

# Make the launchers executable
chmod +x runAA update_repo

# Optional: desktop icons for the operator
cp runAA.desktop ActualizarRepo.desktop ~/Desktop/
chmod +x ~/Desktop/runAA.desktop ~/Desktop/ActualizarRepo.desktop
```

> **To install elsewhere**, edit `PROJECT_DIR` in `runAA`, `REPO` in `update_repo`,
> and `Exec=` in both `.desktop` files.

> **Note on dependencies.** `requirements.txt` does not list `gpiod` (libgpiod **v2**
> Python bindings) or `pyserial`, yet `Drivers/` imports both at module level — so
> install them explicitly as shown. `board`/`busio` arrive transitively via
> `adafruit-circuitpython-ads1x15` (Blinka). `pigpio` is listed but unused by
> current code paths.

### Windows / Linux (development, no hardware)

```powershell
git clone https://github.com/enaulad511/MicrodeviceCD.git
cd MicrodeviceCD
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# REQUIRED off-hardware: skips gpiod/serial/ADS initialisation and CSV writes
echo environment=dev > .env
```

Skip `gpiod`/`pyserial` here — in dev mode those code paths never run.

---

## Running

Three entry points, by reader:

**Operator — desktop icon.** Double-click **runAA** (installed above). It opens a
terminal, activates the venv and starts the app; **Actualizar Repo** runs the
updater.

**Terminal on the Pi.**

```bash
/home/raspb-cd/opt/MicrodeviceCD/runAA
```

`runAA` sets `PROJECT_DIR`, `cd`s into it, extends `PYTHONPATH`, activates
`../.venv` and runs `main.py`.

**Directly (development).**

```powershell
# Windows dev
.venv\Scripts\python.exe main.py

# Raspberry Pi
python main.py
```

> ⚠️ **Always launch from the repository root.** `.env` is read as a *relative*
> path (`dotenv_values(".env")`), so starting from any other working directory
> silently discards the environment flag — which is exactly why `runAA` `cd`s
> first.

On startup `main.py` calls `seed_default_settings()`, which backfills any new
keys into `resources/settings.json` without touching existing local values.

---

## Updating the instrument

```bash
/home/raspb-cd/opt/MicrodeviceCD/update_repo     # or the "Actualizar Repo" icon
```

The updater is deliberately deterministic: it forces the working tree to match
`origin/<branch>`, **discarding local edits to tracked files** — but local
configuration always wins. Before forcing, it snapshots

- `resources/settings.json`
- `resources/electrochem_projects.json`
- `resources/pcr_projects.json`

into a timestamped folder under `.update_backup/`, restores them afterwards, and
offers to recover any earlier snapshot interactively. `.update_backup/` is
untracked, so `git reset --hard` cannot remove it.

---

## Configuration

### `.env` (untracked — create it per machine)

| Value | Effect |
|---|---|
| `environment=dev` | **Off-hardware mode.** `Ads1115Reader` is not constructed, CSV writes are no-ops, and GPIO/serial drivers are not instantiated. |
| anything else / absent | Full hardware mode. On a non-Pi this crashes on `import gpiod` / `board`. |

### `resources/settings.json`

Read and written through `templates.utils.read_settings_from_file` /
`write_settings_to_file`, which merge — partial writes never drop unrelated keys.

| Key | Meaning |
|---|---|
| `pidControllerRPM` | Per-phase PID parameter sets (`denat`, `high`, `low`, `ext`, plus `_h_` heating variants): KP/KI, integral limits, tolerance bands, moving-average windows, spin acceleration, loop period. **Tune here, never in Python.** |
| `ads_fsr` | ADS1115 full-scale range for analog reads. |
| `temp_source` | Active temperature sensor: `thermocouple`, `ir_object` or `ir_ambient`. |
| `photoreceptor` | Photoreceptor options (e.g. differential read). |
| `windows_pcr` | PCR plotting/averaging window. |
| `version` | Settings schema version used by `seed_default_settings`. |

### Project recipes

Named parameter sets, saved from the bar inside each frame:

- `resources/pcr_projects.json` — PCR recipes (**untracked**; local to each device).
- `resources/electrochem_projects.json` — CV/SQWV/EIS recipes, method-namespaced.

Both are preserved across updates. Recipes hold experiment parameters only — PID
tuning stays global in `settings.json`, and the electrode channel is chosen at run
time rather than stored.

---

## Data output

CSVs are written into per-method subfolders of `files/`, created on demand by
`templates.utils.experiment_dir()`:

```
files/
├── PCR/     temperature + photodetector runs, plus the UDP temperature logs
├── CV/
├── SQWV/
├── EIS/
└── CA/
```

All `*.csv` files are gitignored, and **every write is short-circuited when
`environment=dev`** — don't add data-writing paths that ignore that flag.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: gpiod` / `board` on startup | Missing `.env`, so dev mode is off and hardware imports run | Create `.env` with `environment=dev` (off-hardware) — it is gitignored and absent from fresh clones |
| App tries to touch hardware on the Pi even though `.env` says `dev`, or vice-versa | Launched from the wrong working directory; `.env` is resolved relative to CWD | Start from the repository root, or use `runAA` |
| `ModuleNotFoundError: serial` on the Pi | `pyserial`/`gpiod` are not in `requirements.txt` | `pip install gpiod pyserial` inside the venv |
| GUI runs, but motor/EmStat commands do nothing | Microcontroller firmware mismatch | Check the [expected firmware versions](#expected-firmware-versions) and reflash from the source projects |
| Electrochemical run never starts; no instrument IP | No disc UDP broadcast received, so `ip_sender` is unset | Verify the disc is powered and broadcasting on UDP :5005, on the same network/subnet as the Pi |
| Electrochemistry rejected with `emstat_error` | Missing/invalid electrode channel `"ch"` | Select a channel (0–7) in the Electrochemical tab; the firmware validates it strictly |

---

## Architecture

```
main.py
  └── ui/            Tkinter (ttkbootstrap) frames — UI, threads, timing, plotting,
       │             experiment orchestration
       └── Drivers/       Hardware abstraction (GPIO, UART, UDP, I²C/ADS, PID,
            │             EmStat MethodSCRIPT)
            └── templates/    Constants (pins, fonts, .env) and JSON settings I/O
```

UI frames own threads, timing, plots and experiment flow, and call into drivers.
Drivers own hardware state. `templates/` holds cross-cutting constants and
settings I/O only — no hardware logic.

GPIO is **libgpiod v2** (not RPi.GPIO). Pin constants live in
`templates/constants.py`; motor, stepper and sensor pins are defined in the
microcontroller firmware, not here.

---

## Design notes (`docs/`)

In-depth rationale lives in [docs/](docs/), one file per subsystem or feature —
**written in Spanish**. Read the relevant note before changing that area, and keep
it updated alongside the code.

**Electrochemistry — EmStat chain**

| Doc | Topic |
|---|---|
| [emstat_arquitectura_cadena.md](docs/emstat_arquitectura_cadena.md) | The 3-node chain: Python → Wemos → Pico → EmStat |
| [emstat_abort_y_canal.md](docs/emstat_abort_y_canal.md) | STOP vs ABORT, mandatory `"ch"` channel, dead-man switch |
| [emstat_udp_recovery.md](docs/emstat_udp_recovery.md) | Recovering TCP-lost packets from the parallel UDP broadcast |
| [emstat_keep_runs.md](docs/emstat_keep_runs.md) | "Keep runs" retention: overlaying consecutive runs on one plot |
| [electrochem_proyectos.md](docs/electrochem_proyectos.md) | Per-method named recipes (CV/SQWV/EIS) |
| [electrochem_cache_frames.md](docs/electrochem_cache_frames.md) | Caching method frames so data survives a method switch |

**Methods**

| Doc | Topic |
|---|---|
| [emstat_swv_y_fiabilidad_uart.md](docs/emstat_swv_y_fiabilidad_uart.md) | SWV method plus UART reliability |
| [swv_profile_esquematico.md](docs/swv_profile_esquematico.md) | Schematic SWV waveform preview window |
| [sqwv_motor_pretratamiento.md](docs/sqwv_motor_pretratamiento.md) | Running the motor during SWV pre-treatment only |
| [sqwv_plot_precondicionamiento.md](docs/sqwv_plot_precondicionamiento.md) | Keeping pre-treatment out of the plot but in the CSV |
| [sqwv_analisis_picos.md](docs/sqwv_analisis_picos.md) | SQWV multi-peak analysis tab |
| [eis_impedancia.md](docs/eis_impedancia.md) | EIS / Nyquist, scan modes and real package codes |
| [ca_cronoamperometria.md](docs/ca_cronoamperometria.md) | Chronoamperometry: potential step, synthesized time axis |

**PCR**

| Doc | Topic |
|---|---|
| [pcr_temperature_control.md](docs/pcr_temperature_control.md) | Thermal loop and per-phase PID parameter sets |
| [pcr_proyectos.md](docs/pcr_proyectos.md) | PCR project recipes (save/load/import/export) |
| [pcr_analisis.md](docs/pcr_analisis.md) | PCR analysis tab: segment picking, heating/cooling rates |
| [cambios_fluorescencia.md](docs/cambios_fluorescencia.md) | Fluorescence LED / photoreceptor changes |

**Sensors**

| Doc | Topic |
|---|---|
| [temp_source_selector.md](docs/temp_source_selector.md) | Three-temperature broadcast and the source selector |
| [mlx90614_emisividad.md](docs/mlx90614_emisividad.md) | Setting IR emissivity to 0.96 in the MLX90614 EEPROM |
| [mlx90614_fiabilidad_lectura.md](docs/mlx90614_fiabilidad_lectura.md) | IR read failure path end-to-end; sentinel values removed |

**Motion, UI and storage**

| Doc | Topic |
|---|---|
| [stepper_rampa_firmware.md](docs/stepper_rampa_firmware.md) | Stepper speed ramp moved into the Pico firmware |
| [quick_control.md](docs/quick_control.md) | Unified manual-control tab and tab locking |
| [almacenamiento_por_experimento.md](docs/almacenamiento_por_experimento.md) | Per-method CSV subfolders under `files/` |

---

## Development

Use `environment=dev` whenever working off the instrument. It stubs the hardware:
`Ads1115Reader` is never constructed, CSV writes no-op, and GPIO/serial drivers
are not instantiated. Everything UI-side — layout, plotting, parsing, MethodSCRIPT
preview, analysis — is exercisable without the device.

Conventions worth preserving:

- Every Python file opens with `# -*- coding: utf-8 -*-` and closes with
  `__author__ = "Edisson A. Naula"` plus `__date__`.
- Settings go through `read_settings_from_file` / `write_settings_to_file` so
  partial writes merge instead of dropping keys.
- **Spanish** in code comments and driver-level logs is intentional — don't
  translate it. **English** for everything the user sees: widget labels, buttons,
  status and lock messages.
- Never instantiate a second `DriverStepperSys`; the motor is shared through the
  module-level singleton in `ui/DiscFrame.py`.

There is **no test runner**. `test/` and `test_*.py` are ad-hoc hardware sanity
scripts (UART loopback, UDP capture, ADS reads, motor curves), run directly and
kept out of version control. Type checking uses **Pyrefly**; its `pyrefly.toml`
is untracked, so create one locally. `# pyrefly: ignore` comments around
`gpiod`/`board`/`busio`/ttkbootstrap calls are deliberate — preserve them when
editing nearby lines.

---

## License & use

**No license is granted yet.** This code is published for reference alongside
ongoing research; a **manuscript is in preparation**. Please contact the author
before reusing, redistributing or citing this work.

---

**Author:** Edisson A. Naula — <edisson.naulad@tec.mx>
