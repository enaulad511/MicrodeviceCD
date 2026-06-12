# SWV: perfil esquemático en ventana Toplevel

## Problema

El preview del perfil SWV (botón 📈 en `ui/SqwVFrame.py`) dibujaba la señal
completa tal cual se aplica. Con parámetros típicos (E de −0.5 V a 0.5 V con
E_step = 0.01 V a 20 Hz) son ~100 steps con pulsos de 25 ms: el plot se
comprime en una banda sólida ilegible y las etiquetas Forward/Reverse ni
siquiera aparecían (solo se dibujaban con ≤ 20 segmentos). Además el preview
estaba embebido en el frame (`profile_frame`), distinto al patrón de CV que
abre una ventana aparte.

## Decisión

Reemplazar (sin toggle) la señal completa por una **versión esquemática de
pocos steps** en una **`ttk.Toplevel`**, replicando el patrón de
`ui/CvFrame.py` (`ShowProfileFrame`, `self.ShowProfile`,
`on_close_profile_window`). Los valores exactos siguen verificables en el
MethodScript (🗒️).

## Diseño del esquemático

Clase `ShowProfileFrame` en `ui/SqwVFrame.py:68`:

- **Steps dibujados**: `N_SCHEMATIC = 3` si el experimento tiene más de
  `MAX_FULL_STEPS = 5`; si tiene ≤ 5 se dibujan **todos** y no hay indicador
  de continuación (`ui/SqwVFrame.py:78-79`).
- **Escalón exagerado** (`step_draw`): con valores típicos E_step (0.01 V) es
  20× menor que el pulso pico a pico (2·Amp = 0.2 V) y la escalera resultaba
  invisible — el perfil parecía una onda cuadrada plana. Si
  `E_step < 0.6·Amplitude`, el escalón **dibujado** se agranda a
  `0.6·Amplitude`; la cota sigue mostrando el valor real con sufijo
  "(enlarged)". Cuando se exagera, la escalera ya no aterriza en E_end, así
  que se fuerza el modo truncado (3 steps + flecha de continuación) aunque el
  experimento tenga ≤ 5 steps. Amplitude y los niveles E_begin/E_end/fases
  previas sí mantienen proporciones reales en Y.
- **Indicador de continuación**: flecha roja punteada desde el último step
  dibujado hacia la línea de E_end, con texto `+N steps`.
- **Barridos descendentes soportados**: la dirección sale del signo de
  (E_end − E_begin). Esto corrige un bug del preview anterior: con
  E_end < E_begin el `while e_i <= e_end` no generaba nada y el plot salía
  vacío. También se agregó guard para `E_step = 0` (antes congelaba la GUI en
  loop infinito) y `freq <= 0` (`ui/SqwVFrame.py:471-473`).
- **Fases previas**: si su t > 0 se dibujan como tramo plano de **ancho fijo**
  (1 step de ancho, no a escala temporal) a su potencial, etiquetadas con su
  duración real; si t = 0 se omiten. Orden igual al MethodScript generado por
  `construc_individual_script_sqwv` (`Drivers/EmstatUtils.py:149-152`):
  condition → deposition → equilibration → pulsos SWV.
- **Cotas** sobre los primeros steps: `2·Amp` (flecha vertical pico a pico),
  `E step` (línea de referencia punteada al nivel forward del step 1 + flecha
  al step 2; solo si se dibujan ≥ 2 steps) y `t_interval` (flecha horizontal
  bajo el primer pulso forward). Forward/Reverse solo en el primer step.
- **Resumen en el título**: steps totales, t_interval, duración total estimada
  (t_con + t_dep + t_eq + steps·2·t_interval), rango E y frecuencia.
- **Ejes sin ticks**: ambos ejes van sin números y etiquetados
  "Time (not to scale)" / "Potential (not to scale)" — el ancho fijo de las
  fases previas y el escalón exagerado hacen que ninguno de los dos ejes sea
  fiable como escala. Sin ticks tampoco hay rejilla. Todos los valores exactos
  viven en las anotaciones: cotas (2·Amp, E step, t_interval), etiquetas
  E_begin/E_end, fases previas ("Dep. 5 s @ -0.3 V") y el título.
- `total_steps = round(|E_end − E_begin| / |E_step|) + 1` (con `round`, no
  `floor`, para evitar perder el último step por acumulación de flotantes).

## Cambios en SWVFrame

- `callback_generate_profile` (`ui/SqwVFrame.py:456`) ahora valida entradas y
  abre/reemplaza la Toplevel; ya no hay `profile_frame` embebido ni
  `self.canvas` de perfil, y se eliminó el auto-preview al construir el frame.
- `ShowProfileFrame.destroy()` hace `plt.close(self.fig)` para no filtrar
  figuras matplotlib al regenerar el preview.
- Alcance: **solo SQWV**. El perfil de CV (triangular, legible a cualquier
  densidad) no se tocó. EIS no tiene preview de perfil.

## Verificación

`test_swv_profile.py` (raíz, gitignored) renderiza tres casos a PNG sin
hardware: default truncado (101 steps), pocos steps (5, sin truncar) y
descendente con pre-tratamiento.

__author__ = "Edisson A. Naula"
