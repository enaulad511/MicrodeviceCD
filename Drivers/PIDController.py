# -*- coding: utf-8 -*-
from time import perf_counter
__author__ = "Edisson Naula"
__date__ = "$ 18/11/2025 at 15:10 $"

class PIDController:
    def __init__(
        self,
        kp: float,
        ki: float,
        kd: float,
        setpoint: float = 0.0,
        output_limits: tuple = (None, None),
        ts: float | None = None,
        aw_tracking_time: float
        | None = 0.1,  # Tt: constante de seguimiento (s). None -> deshabilitar
    ):
        """PID controller con anti-windup por Back-Calculation (seguimiento del actuador).
        :param kp: Proportional gain.
        :type kp: float
        :param ki: Integral gain.
        :type ki: float
        :param kd: Derivative gain.
        :type kd: float
        :param setpoint: Objective value, defaults to 0.0
        :type setpoint: float, optional
        :param output_limits: (min, max) output limits. Use None to not limit., defaults to (None, None)
        :type output_limits: tuple, optional
        :param ts: Fixed sampling time in seconds. If None, use dynamic dt with perf_counter()., defaults to None
        :type ts: float | None, optional
        :param aw_tracking_time: Tt (s). Anti-windup tracking constant. If None, disables anti-windup. Typical values: ~ts to 10*ts. Smaller values ​​result in stronger correction., defaults to 0.1
        :type aw_tracking_time: float | None, optional
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.output_limits = output_limits
        self.fixed_dt = ts
        self.aw_tracking_time = aw_tracking_time

        self._integral = 0.0  # Estado del integrador I (antes de multiplicar por ki)
        self._last_error: float | None = None
        self._last_time: float | None = None

    def compute(self, measurement: float, current_time: float | None = None) -> float:
        """Compute the output value given a measurement and current time

        :param measurement: _description_
        :type measurement: float
        :param current_time: _description_, defaults to None
        :type current_time: float | None, optional
        :return: _description_
        :rtype: float
        """
        error = self.setpoint - measurement

        # Tiempo actual
        if current_time is None:
            current_time = perf_counter()

        # dt
        if self.fixed_dt is not None:
            dt = self.fixed_dt
        else:
            dt = current_time - self._last_time if self._last_time is not None else 0.0

        # Proporcional
        p = self.kp * error

        # Derivativo
        d = 0.0
        if self._last_error is not None and dt > 0:
            d = self.kd * (error - self._last_error) / dt

        # === Integrador + Back-Calculation ===
        # Paso 1: integrar el error normalmente
        if dt > 0:
            self._integral += error * dt

        # i preliminar y salida sin limitar
        i_pre = self.ki * self._integral
        u_unsat = p + i_pre + d

        # Aplicar límites
        lower, upper = self.output_limits
        u_sat = u_unsat
        if lower is not None:
            u_sat = max(lower, u_sat)
        if upper is not None:
            u_sat = min(upper, u_sat)

        # Paso 2: corrección anti-windup (Back-Calculation)
        # I += ((u_sat - u_unsat) / (ki * Tt)) * dt
        if dt > 0 and self.aw_tracking_time is not None and self.ki != 0.0:
            self._integral += (
                (u_sat - u_unsat) / (self.ki * self.aw_tracking_time)
            ) * dt

        # i final y salida (volver a calcular tras corrección)
        i = self.ki * self._integral
        output = p + i + d

        # Limitar de nuevo por robustez (debería coincidir con u_sat)
        if lower is not None:
            output = max(lower, output)
        if upper is not None:
            output = min(upper, output)

        # Estado
        self._last_error = error
        self._last_time = current_time

        # Debug
        print(
            f"Er: {error:.3f}, Ms: {measurement:.3f}, P: {p:.4f}, I: {i:.4f}, D: {d:.4f}, "
            f"U*: {u_unsat:.4f}, U_sat: {u_sat:.4f}, Out: {output:.4f}"
        )

        return output


if __name__ == "__main__":
    pid = PIDController(
        kp=1.0,
        ki=0.1,
        kd=0.05,
        setpoint=100.0,
        output_limits=(0.0, 255.0),
        ts=0.01,
        aw_tracking_time=0.05,  # ejemplo: Tt = 50 ms
    )

    medicion = 50.0
    salida = pid.compute(medicion)
    print("PWM:", salida)
    help(PIDController)
