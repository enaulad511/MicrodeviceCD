
# Drivers/DriverGPIO.py
# -*- coding: utf-8 -*-

import gpiod    # pyrefly: ignore
from gpiod.line import Direction, Value, Bias, Drive # pyrefly: ignore
from typing import Optional


class GPIOPin:
    """
    Control de un único GPIO (numeración BCM) con libgpiod v2 usando el patrón:
        request = gpiod.request_lines(chip, consumer=..., config=...)
    donde 'config' es un dict {offset: gpiod.LineSettings}.

    Métodos:
      - set_output(initial_high=False, drive=Drive.PUSH_PULL)
      - write(value: bool)
      - set_input(pull: Optional[str] = None)
      - read() -> int
      - toggle()
      - close()
    """

    def __init__(
        self,
        gpio: int,
        chip: str = "/dev/gpiochip0",
        consumer: str = "gpio-pin",
        active_low: bool = False,
    ):
        """
        gpio: número BCM (offset en el chip).
        chip: path del chip, ej. "/dev/gpiochip0".
        consumer: etiqueta para identificar el consumidor (diagnóstico).
        active_low: True si 'ACTIVE' debe mapear a nivel físico bajo (lógica invertida).
        """
        self.offset = int(gpio)
        self.chip = chip
        self.consumer = consumer
        self.active_low = bool(active_low)

        # Request actual (gpiod.Request). Se crea en set_output/set_input.
        self.request: Optional[gpiod.Request] = None

        # Estado del modo actual: 'output' | 'input' | None
        self._mode: Optional[str] = None

    # ------------- helpers internos -------------
    def _build_output_config(self, initial_high: bool, drive: Drive = Drive.PUSH_PULL):
        """
        Devuelve el dict {offset: LineSettings} para salida.
        """
        settings = gpiod.LineSettings(
            direction=Direction.OUTPUT,
            output_value=Value.ACTIVE if initial_high else Value.INACTIVE,
            drive=drive,
            bias=Bias.AS_IS,
            active_low=self.active_low,
        )
        return {self.offset: settings}

    def _build_input_config(self, pull: Optional[str]):
        """
        Devuelve el dict {offset: LineSettings} para entrada con bias opcional.
        pull: None | 'pull_up' | 'pull_down' | 'disabled'
        """
        bias_map = {
            None: Bias.AS_IS,
            "pull_up": Bias.PULL_UP,
            "pull_down": Bias.PULL_DOWN,
            "disabled": Bias.DISABLED,
        }
        settings = gpiod.LineSettings(
            direction=Direction.INPUT,
            bias=bias_map.get(pull, Bias.AS_IS),
            active_low=self.active_low,
        )
        return {self.offset: settings}

    def _ensure_request(self, config: dict):
        """
        Aplica la configuración:
          - Si no hay request, usa gpiod.request_lines(...)
          - Si ya hay, reconfigura con gpiod.reconfigure_lines(...)
        """
        if self.request is None:
            # Solicita las líneas
            self.request = gpiod.request_lines(
                self.chip, consumer=self.consumer, config=config
            )
        else:
            # Reconfigurar en caliente
            gpiod.reconfigure_lines(self.request, config)

    # ------------- API pública -------------
    def set_output(self, initial_high: bool = False, drive: Drive = Drive.PUSH_PULL):
        """
        Configura el pin como salida. initial_high=True pone 'ACTIVE' (alto lógico).
        Nota: si active_low=True, 'ACTIVE' corresponde a nivel físico bajo.
        """
        config = self._build_output_config(initial_high=initial_high, drive=drive)
        self._ensure_request(config)
        self._mode = "output"
        return self

    def write(self, value: bool):
        """
        Escribe HIGH/LOW lógico (Value.ACTIVE / Value.INACTIVE).
        Si aún no está en salida, se autoconfigura como salida en bajo.
        """
        if self._mode != "output":
            self.set_output(initial_high=False)
        self.request.set_value(self.offset, Value.ACTIVE if value else Value.INACTIVE)  # pyrefly: ignore

    def set_input(self, pull: Optional[str] = None):
        """
        Configura el pin como entrada con pull opcional:
          - None: Bias.AS_IS
          - 'pull_up': Bias.PULL_UP
          - 'pull_down': Bias.PULL_DOWN
          - 'disabled': Bias.DISABLED
        """
        config = self._build_input_config(pull=pull)
        self._ensure_request(config)
        self._mode = "input"
        return self

    def read(self) -> int:
        """
        Lee el valor lógico del pin (0/1).
        Si no está en modo entrada, se autoconfigura como entrada sin pull.
        """
        if self._mode != "input":
            self.set_input(pull=None)
        val = self.request.get_value(self.offset)       # pyrefly: ignore
        return 1 if val == Value.ACTIVE else 0

    def toggle(self):
        """
        Conmuta el estado actual (solo salida).
        Autoconfigura salida si hace falta.
        """
        if self._mode != "output":
            self.set_output(initial_high=False)
        current = self.request.get_value(self.offset)       # pyrefly: ignore
        self.request.set_value(     # pyrefly: ignore
            self.offset,
            Value.INACTIVE if current == Value.ACTIVE else Value.ACTIVE,
        )

    def close(self):
        """
        Libera el request (si existe). El chip lo maneja internamente en libgpiod v2
        para este patrón de request_lines módulo.
        """
        try:
            if self.request:
                self.request.release()      # pyrefly: ignore
                self.request = None
                print(f"Pin {self.offset} liberado.")
        except Exception:
            pass

    # Context manager opcional
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
