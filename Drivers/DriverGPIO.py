
# Drivers/DriverGPIO.py
# -*- coding: utf-8 -*-

import gpiod
from gpiod.line import Direction, Value, Bias, Drive
from typing import Optional


class GPIOPin:
    """
    Control de un único GPIO (numeración BCM) con libgpiod v2.
    API estilo:
      - LineSettings / LineConfig / RequestConfig
      - Direction, Value, Bias, Drive
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
        gpio: número BCM del GPIO (ej. 17).
        chip: ruta del chip GPIO (por defecto /dev/gpiochip0).
        consumer: etiqueta del consumidor (para diagnóstico).
        active_low: True si 'ACTIVE' debe mapear a nivel físico bajo (invertido).
        """
        self.offset = int(gpio)
        self.consumer = consumer
        self.active_low = bool(active_low)

        # Recursos libgpiod v2
        self._chip = gpiod.Chip(chip)
        self._req: Optional[gpiod.Request] = None
        self._cfg: Optional[gpiod.LineConfig] = None

        # Estado lógico del modo actual: 'output' | 'input' | None
        self._mode: Optional[str] = None

    # ------------- helpers internos (v2) -------------
    def _make_cfg(
        self,
        direction: Direction,
        value: Optional[Value] = None,
        bias: Optional[Bias] = None,
        drive: Drive = Drive.PUSH_PULL,
    ) -> gpiod.LineConfig:
        """
        Construye un LineConfig con una LineSettings para este offset.
        """
        settings = gpiod.LineSettings(
            direction=direction,
            output_value=value if value is not None else Value.INACTIVE,
            bias=bias if bias is not None else Bias.AS_IS,
            drive=drive,
            active_low=self.active_low,
        )
        cfg = gpiod.LineConfig()
        cfg.add_line_settings(self.offset, settings)
        return cfg

    def _apply_cfg(self, cfg: gpiod.LineConfig):
        """
        Aplica la configuración: si no hay Request, la crea; si existe, reconfigura.
        """
        rcfg = gpiod.RequestConfig(consumer=self.consumer)
        if self._req is None:
            self._req = self._chip.request_lines(rcfg, cfg)
        else:
            self._req.reconfigure_lines(cfg)
        self._cfg = cfg

    # ------------- API pública -------------
    def set_output(self, initial_high: bool = False, drive: Drive = Drive.PUSH_PULL):
        """
        Configura el pin como salida. initial_high=True pone 'ACTIVE' (alto lógico).
        Nota: si active_low=True, 'ACTIVE' corresponde a nivel físico bajo.
        """
        val = Value.ACTIVE if initial_high else Value.INACTIVE
        cfg = self._make_cfg(Direction.OUTPUT, value=val, drive=drive)
        self._apply_cfg(cfg)
        self._mode = "output"
        return self

    def write(self, value: bool):
        """
        Escribe HIGH/LOW lógico (Value.ACTIVE / Value.INACTIVE).
        Autoconfigura salida si aún no está en ese modo.
        """
        if self._mode != "output":
            self.set_output(initial_high=False)
        self._req.set_value(self.offset, Value.ACTIVE if value else Value.INACTIVE)

    def set_input(self, pull: Optional[str] = None):
        """
        Configura el pin como entrada.
        pull: None | 'pull_up' | 'pull_down' | 'disabled'
        """
        bias_map = {
            None: Bias.AS_IS,
            "pull_up": Bias.PULL_UP,
            "pull_down": Bias.PULL_DOWN,
            "disabled": Bias.DISABLED,
        }
        cfg = self._make_cfg(Direction.INPUT, bias=bias_map.get(pull, Bias.AS_IS))
        self._apply_cfg(cfg)
        self._mode = "input"
        return self

    def read(self) -> int:
        """
        Lee el valor lógico del pin (0/1).
        Si no está en modo entrada, se autoconfigura como entrada sin pull.
        """
        if self._mode != "input":
            self.set_input()
        val = self._req.get_value(self.offset)
        return 1 if val == Value.ACTIVE else 0

    def toggle(self):
        """
        Conmuta el estado actual (solo salida).
        Autoconfigura salida si hace falta.
        """
        if self._mode != "output":
            self.set_output(initial_high=False)
        current = self._req.get_value(self.offset)
        self._req.set_value(
            self.offset,
            Value.INACTIVE if current == Value.ACTIVE else Value.ACTIVE,
        )

    def close(self):
        """
        Libera recursos (request y chip).
        """
        try:
            if self._req:
                self._req.release()
                self._req = None
        finally:
            try:
                self._chip.close()
            except Exception:
                pass

    # Context manager opcional
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

