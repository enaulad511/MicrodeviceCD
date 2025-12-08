
# Drivers/DriverGPIO.py
from typing import Optional

class GPIOPin:
    """
    Clase GPIO compatible con libgpiod v2 y v1.
    - Numeración BCM como offset del chip.
    - Métodos: set_output(), write(), set_input(), read(), toggle(), close()
    """

    def __init__(self, gpio: int, chip: str = "/dev/gpiochip0", consumer: str = "gpio-pin", active_low: bool = False):
        self.offset = int(gpio)
        self.consumer = consumer
        self.active_low = bool(active_low)
        self._chip_path = chip

        # Estados internos
        self._lib = None
        self._api = None  # 2 o 1
        self._chip = None
        self._req = None      # v2: gpiod.Request
        self._cfg = None      # v2: gpiod.LineConfig
        self._line = None     # v1: gpiod.Line
        self._mode = None     # 'output' | 'input'

        # Cargar gpiod y detectar API
        self._detect_api()

    def _detect_api(self):
        try:
            import gpiod as gpiod_mod
            self._lib = gpiod_mod
            # v2 tiene LineConfig
            if hasattr(gpiod_mod, "LineConfig"):
                self._api = 2
                from gpiod.line import Direction, Value, Bias, Drive  # type: ignore
                self.Direction = Direction
                self.Value = Value
                self.Bias = Bias
                self.Drive = Drive
                # Abrir chip (v2 usa gpiod.Chip(path))
                self._chip = gpiod_mod.Chip(self._chip_path)
            else:
                # API v1
                self._api = 1
                # v1 constants están en el propio módulo
                self.LINE_REQ_DIR_OUT = getattr(gpiod_mod, "LINE_REQ_DIR_OUT")
                self.LINE_REQ_DIR_IN = getattr(gpiod_mod, "LINE_REQ_DIR_IN")
                self._chip = gpiod_mod.chip(self._chip_path)
        except Exception as e:
            raise RuntimeError("No se pudo importar/abrir libgpiod. ¿Está instalado python3-libgpiod?") from e

    # ======================= API v2 helpers =======================
    def _v2_make_cfg(self, direction, value=None, bias=None, drive=None):
        g = self._lib
        settings = g.LineSettings(
            direction=direction,
            output_value=value if value is not None else self.Value.INACTIVE,
            bias=bias if bias is not None else self.Bias.AS_IS,
            drive=drive if drive is not None else self.Drive.PUSH_PULL,
            active_low=self.active_low,
        )
        cfg = g.LineConfig()
        cfg.add_line_settings(self.offset, settings)
        return cfg

    def _v2_apply_cfg(self, cfg):
        g = self._lib
        rcfg = g.RequestConfig(consumer=self.consumer)
        if self._req is None:
            self._req = self._chip.request_lines(rcfg, cfg)
        else:
            self._req.reconfigure_lines(cfg)
        self._cfg = cfg

    # ======================= API v1 helpers =======================
    def _v1_request_output(self, initial_val: int):
        g = self._lib
        self._line = self._chip.get_line(self.offset)
        # Nota: v1 no soporta 'active_low' en el request; se maneja manualmente al escribir/leer
        self._line.request(consumer=self.consumer, type=self.LINE_REQ_DIR_OUT, default_val=initial_val)

    def _v1_request_input(self):
        g = self._lib
        self._line = self._chip.get_line(self.offset)
        self._line.request(consumer=self.consumer, type=self.LINE_REQ_DIR_IN)

    # ======================= API pública =======================
    def set_output(self, initial_high: bool = False):
        """Configura el pin como salida."""
        if self._api == 2:
            val = self.Value.ACTIVE if initial_high else self.Value.INACTIVE
            cfg = self._v2_make_cfg(self.Direction.OUTPUT, value=val)
            self._v2_apply_cfg(cfg)
        else:
            # Si active_low=True, invertimos el valor físico deseado
            physical_val = 0 if (initial_high and self.active_low) else (1 if initial_high else 0)
            self._v1_request_output(physical_val)
        self._mode = "output"
        return self

    def write(self, value: bool):
        """Escribe True(ON)/False(OFF)."""
        if self._mode != "output":
            self.set_output(initial_high=False)

        if self._api == 2:
            self._req.set_value(self.offset, self.Value.ACTIVE if value else self.Value.INACTIVE)
        else:
            # En v1, set_value usa 0/1 físicos; respetamos active_low
            physical = 0 if (value and self.active_low) else (1 if value else 0)
            self._line.set_value(physical)

    def set_input(self, pull: Optional[str] = None):
        """Configura el pin como entrada."""
        if self._api == 2:
            bias_map = {
                None: self.Bias.AS_IS,
                "pull_up": self.Bias.PULL_UP,
                "pull_down": self.Bias.PULL_DOWN,
                "disabled": self.Bias.DISABLED,
            }
            cfg = self._v2_make_cfg(self.Direction.INPUT, bias=bias_map.get(pull, self.Bias.AS_IS))
            self._v2_apply_cfg(cfg)
        else:
            # v1: no hay bias configurable portable; se ignora o requiere ioctl específico
            self._v1_request_input()
        self._mode = "input"
        return self

    def read(self) -> int:
        """Lee 0/1 (lógico)."""
        if self._mode != "input":
            self.set_input()

        if self._api == 2:
            val = self._req.get_value(self.offset)
            return 1 if val == self.Value.ACTIVE else 0
        else:
            physical = self._line.get_value()
            # Si active_low=True, invertimos al lógico
            return 0 if (physical == 1 and self.active_low) else (1 if physical == 1 else 0)

    def toggle(self):
        """Conmuta el estado actual (solo salida)."""
        if self._mode != "output":
            self.set_output(initial_high=False)

        if self._api == 2:
            current = self._req.get_value(self.offset)
            self._req.set_value(self.offset, self.Value.INACTIVE if current == self.Value.ACTIVE else self.Value.ACTIVE)
        else:
            # Leer físico y escribir invertido
            cur = self._line.get_value()
            self._line.set_value(0 if cur == 1 else 1)

    def close(self):
        """Libera recursos."""
        try:
            if self._api == 2 and self._req:
                self._req.release()
                self._req = None
            if self._api == 1 and self._line:
                try:
                    self._line.release()
                except Exception:
                    pass
                self._line = None
            if self._chip:
                try:
                    self._chip.close()
                except Exception:
                    pass
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
