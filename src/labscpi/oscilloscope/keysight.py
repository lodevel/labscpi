# ruff: noqa: E701, E702
"""Keysight oscilloscope adapter — moved VERBATIM from
labscpi.oscilloscope_scpi. KeysightScope is the brand's ONE general adapter
(no MODEL_PATTERNS): it wins stage 1 of pick_adapter on the IDN vendor
field; there are no Keysight model adapters yet.
"""
from __future__ import annotations

from .base import BaseAdapter, BrandAdapter, MathOperator, Measure, NotSupportedError

class KeysightScope(BrandAdapter):
    brand = "KEYSIGHT TECHNOLOGIES"
    vendor_aliases = ("KEYSIGHT", "AGILENT", "HEWLETT-PACKARD", "HP")

    TOKEN_MAP = BaseAdapter.TOKEN_MAP | {
        "math": BaseAdapter.TOKEN_MAP["math"] | {"SUBTRACT": "SUBT", "ABSOLUTE": "ABS"},
        "measure": BaseAdapter.TOKEN_MAP["measure"] | {
            "AVG": "VAV", "RMS": "VRMS", "TOP": "VTOP", "BASE": "VBASE", "PDUTY": "DUTY",
            # Keysight DSO/MSO hardware exposes bare :MEASure:DELay /
            # :MEASure:PHASe; no edge-locked items. Operator authors
            # the procedure with explicit edge (RR_/RF_/FR_/FF_) per
            # grammar; the wire layer collapses all 8 onto the bare
            # commands. The scope's last-configured edges (set earlier
            # in the procedure) carry the operator's edge intent.
            "RR_DELAY": "DELay", "RF_DELAY": "DELay",
            "FR_DELAY": "DELay", "FF_DELAY": "DELay",
            "RR_PHASE": "PHASe", "RF_PHASE": "PHASe",
            "FR_PHASE": "PHASe", "FF_PHASE": "PHASe",
            },
    }



    def screenshot_png(self) -> bytes:

        try:
            return self.s.query_ieee_block(":DISP:DATA? PNG", timeout_ms=10000)
        except Exception:
            raise

    def enable_measure(
            self, kind: Measure | str, src: str = "CHAN1", src2: str | None = None
        ):
            t = self._meas_token(kind)
            need_two = self.MEAS_SIGNATURES.get(t, 1) == 2 or src2 is not None
            if need_two and not src2:
                src2 = "CHAN2"

            q = (
                f":MEASure:{t} {src},{src2}"
                if need_two
                else f":MEASure:{t} {src}"
            )
            
            try:
                self.s.write(q)
            except Exception:
                raise NotSupportedError(f"measurement {kind} not supported")
        

    def get_measure(
            self, kind: Measure | str, src: str = "CHAN1", src2: str | None = None
        ) -> float:
            t = self._meas_token(kind)
            need_two = self.MEAS_SIGNATURES.get(t, 1) == 2 or src2 is not None
            if need_two and not src2:
                src2 = "CHAN2"

            q = (
                f":MEASure:{t}? {src},{src2}"
                if need_two
                else f":MEASure:{t}? {src}"
            )
            
            try:
                return self._parse_float(self.s.query(q))
            except Exception:
                raise NotSupportedError(f"measurement {kind} not supported")


    def get_trigger_status(self) -> bool:
        return self.s.query(":TER?").strip().endswith("1")

    # Math
    def _math_ns(self, math: int | str) -> str:
        m = int(math)
        if m < 1: raise ValueError("math must be >= 1")
        return f":FUNCtion{m}"

    def set_math_source(self, math: int, slot: int, src: str) -> None:
        if slot not in (1, 2): raise ValueError("slot must be 1 or 2")
        ns = self._math_ns(math)
        self.s.write(f"{ns}:SOUR{slot} {src}")

    def set_math_operator(self, math: int, op: MathOperator | str = MathOperator.ADD) -> None:
        ns = self._math_ns(math)
        self.s.write(f"{ns}:OPERation {self._tok('math', op)}")

    def set_math_enabled(self, math: int, on: bool) -> None:
        ns = self._math_ns(math)
        self.s.write(f"{ns}:DISPlay {'ON' if on else 'OFF'}")

    def enable_math(self, math: int, on: bool, op: MathOperator | str = MathOperator.ADD) -> None:
        self.set_math_operator(math, op)
        self.set_math_enabled(math, on)

    def set_math_scale(self, math: int, v_per_div: float) -> None:
        ns = self._math_ns(math)
        self.s.write(f"{ns}:SCALe {v_per_div}")

    def set_math_offset(self, math: int, volts: float) -> None:
        ns = self._math_ns(math)
        self.s.write(f"{ns}:OFFSet {volts}")
