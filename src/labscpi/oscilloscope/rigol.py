# ruff: noqa: E701, E702
"""Rigol oscilloscope adapters — moved VERBATIM from labscpi.oscilloscope_scpi.

RigolScope is the brand's ONE general adapter (no MODEL_PATTERNS); it wins
stage 1 of pick_adapter on the IDN vendor field. RigolMSO2k4k is a model
adapter: it subclasses RigolScope and competes only in stage 2, its anchored
MODEL_PATTERNS tested against the IDN model field.
"""
from __future__ import annotations

import re
from decimal import Decimal

from .base import BaseAdapter, BrandAdapter, NotSupportedError

class RigolScope(BrandAdapter):
    brand = "RIGOL"
    vendor_aliases = ("RIGOL TECHNOLOGIES",)


    TOKEN_MAP = BaseAdapter.TOKEN_MAP | {
        "math": BaseAdapter.TOKEN_MAP["math"] | {"SUBTRACT": "SUBT", "ABSOLUTE": "ABS"},
        "measure": BaseAdapter.TOKEN_MAP["measure"] | {
            "VPP": "VPP", "VMAX":"VMAX", "VMIN":"VMIN", "TOP":"VTOP", "BASE":"VBASE",
            "AVG":"VAVG", "RMS":"VRMS",
            "FREQ":"FREQ", "PERIOD":"PER",
            "RISE":"RTIMe", "FALL":"FTIMe",
            "PDUTY":"PDUTy", "NDUTY":"NDUTy",
            "PWID":"PWDIth", "NWID":"NWIDth",
            # (Edge-locked RR_/RF_/FR_/FF_DELAY|PHASE inherited from
            # BaseAdapter — Rigol tokens are the cross-vendor default.)
            },
        "slope": BaseAdapter.TOKEN_MAP["slope"] | {"BOTH": "RFAL"},
    }


    # Rigol-specific screenshot is robust
    # def screenshot_png(self) -> bytes:
        # self.s.write(":DISP:DATA? ON,0,PNG")
        # return self.resource_read_raw()

    # Some Rigol need channel select explicitly for coupling
    def set_channel_coupling(self, ch: int, mode: str) -> None:
        self.s.write(f":{self._chan(ch)}:COUP {mode.upper()}")

    def get_trigger_status(self):
        stat = self.s.query(":TRIG:STAT?").strip().endswith("STOP")
        return stat
        
    def force_trigger(self) -> None: self.s.write(":TFORCe")
    
    def set_time_position(self, sec: float) -> None:
        self.s.write(f":TIM:OFFS {sec}")

    # Trigger
    TRIG_LEVEL_CMD = ":TRIG:EDGE:LEVel"

    # Math
    def _math_ns(self, math: int | str) -> str:
        m = int(math)
        if m < 1: raise ValueError("math must be >= 1")
        return f":MATH{m}"

    def clear_measures(self) -> None:
        
        try: self.s.write(":MEASure:CLEar ALL"); return
        except Exception:
            raise NotSupportedError("measures clear not supported")


    def enable_measure_stats(self, on: bool = True) -> None:
        for cmd in (":MEASure:STATistic:DISPlay ON"):
            try:
                self.s.write(cmd if on else cmd.replace("ON","OFF")); return
            except Exception: continue
        raise NotSupportedError("measure stats toggle not supported")

    def menu_off(self) -> None:
        try:
            self.s.write(":SYSTem:KEY:PRESs MOFF")
            return
        except Exception as e:
            raise NotSupportedError(f"menu off not supported: {e}")

        

    

    

    def set_probe_attenuation(self, ch: int, factor: float, *, snap: bool = False) -> None:
        d = Decimal(str(factor)).normalize()

        # Allowed probe attenuation factors
        _ALLOWED_FACTORS = tuple(Decimal(s) for s in
            ("0.01","0.02","0.05","0.1","0.2","0.5","1","2","5","10","20","50","100","200","500","1000"))

        def _fmt_num(x: Decimal) -> str:
            s = format(x.normalize(), "f")
            return s.rstrip("0").rstrip(".") if "." in s else s

        if snap:
            # snap to the nearest allowed value
            d = min(_ALLOWED_FACTORS, key=lambda a: abs(a - d))

        if d not in _ALLOWED_FACTORS:
            allowed = ", ".join(_fmt_num(a) for a in _ALLOWED_FACTORS)
            raise ValueError(f"factor must be one of {{{allowed}}}")

        self.s.write(f":{self._chan(ch)}:PROBe {_fmt_num(d)}")


class RigolMSO2k4k(RigolScope):
    # Deliberate mechanical delta from the old module: the raw-IDN pattern
    # ",MSO?[24]\d{2}" (leading comma = a field boundary in the raw IDN)
    # becomes the model-field-anchored "^MSO?[24]\d{2}", because the new
    # pick_adapter tests MODEL_PATTERNS against the parsed MODEL field
    # only. EXACT consequence: identical selection on the model field, and
    # the old whole-IDN search's ability to hit a LOOKALIKE IN THE SERIAL
    # FIELD (a serial like "MS241..." also sits after a comma) is gone —
    # model-field scoping stops serial-field lookalike hits by
    # construction. That stray-hit behavior is subsumed by the quirk fix:
    # in the old selector any Rigol IDN already ended up on this class via
    # the vendor-alias fallback, so removing both defects together changes
    # exactly the pinned quirk cases and nothing else.
    # (No decorator: subclassing BrandAdapter IS registration — base.py.)
    MODEL_PATTERNS = (re.compile(r"^MSO?[24]\d{2}", re.I),)
