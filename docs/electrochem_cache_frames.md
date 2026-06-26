# Conservar datos al cambiar de método electroquímico

## Qué es

`ui/ElectrochemicalFrame.py` es el shell que intercambia el frame del método
(`CVFrame` / `SWVFrame` / `EISFrame` / `CAFrame`) según el combobox
"Select Electrochemical Test". Antes, cada cambio destruía el frame saliente
(`current_test_frame.destroy()`), perdiendo **todo** su estado: `total_data` del
`EventPlotter`, el plot en vivo y las entradas del formulario. Cambiar de CV a
SQWV para alternar (p. ej. CA de acondicionamiento entre corridas SQWV) borraba
los datos previos, y además dejaba un socket TCP huérfano si se cambiaba a mitad
de una corrida.

## Diseño

Los frames **se conservan vivos** en vez de destruirse. Cambios acotados a
`ui/ElectrochemicalFrame.py` (sin tocar los frames de método, `EventPlotter` ni
firmware).

1. **Cache lazy de frames** (`self.frame_cache: dict[str, frame]`,
   [ui/ElectrochemicalFrame.py:73](../ui/ElectrochemicalFrame.py#L73)). El frame
   de cada método se construye **la primera vez** que se selecciona y se reusa
   después. El primer cambio a un método es lento (lo construye); los siguientes
   son instantáneos. La memoria solo crece con los métodos realmente visitados.

2. **Ocultar, no destruir.** El frame saliente se oculta con `grid_forget()` y el
   entrante se muestra con `grid(...)`
   ([on_test_selected](../ui/ElectrochemicalFrame.py#L137)). Como solo se hace
   `grid_forget` del frame de nivel superior, su sub-estado interno (vista de
   entradas vs. vista del plotter) se preserva y se restaura tal cual al volver.

3. **Bloqueo del cambio mientras hay una corrida.** Si el frame saliente tiene
   `udp_plotter.running == True`, el cambio se rechaza: se revierte el combobox a
   `self.current_method` y se avisa ("Stop the current run before switching
   tests."). Evita que dos experimentos compitan por la **única** cadena EmStat
   (Python → Wemos → Pico → EmStat) y garantiza que los datos se conserven porque
   la corrida termina normalmente. `self.current_method` (str) guarda el método
   activo para poder revertir, porque `<<ComboboxSelected>>` dispara *después* de
   que el texto ya cambió.

4. **Sin auto-limpieza.** Los frames en cache viven hasta cerrar la app. Peor
   caso ≈ 100–150 MB con los 4 métodos (~2 % de los 8 GB de la Pi 5) — trivial.
   El reset *dentro* de un frame (limpiar al iniciar la siguiente corrida, salvo
   "Keep runs") queda intacto.

## Lo que sigue correcto

- **Canal** (`get_channel`) e **IP** (`callback_ip`) se leen en vivo al enviar el
  script, así que los frames en cache nunca quedan con un canal/IP obsoletos.
- El **motor** no se puede manejar por duplicado porque el cambio se bloquea
  mientras hay corrida activa.

__author__ = "Edisson A. Naula"
__date__ = "$ 25/06/2026 $"
