"""
scope_scpi — Minimal, extensible SCPI oscilloscope library built on PyVISA.

Implements:
- Timebase: set/get scale and position
- Vertical: per-channel scale, offset, coupling
- Trigger: type, source, level, edge slope; force; single/auto/run/stop
- Screenshot capture to PNG bytes
- Math channels: enable/disable, operator, sources
- Brand auto-detect via *IDN? and adapter registry
- *OPC? completion + SYST:ERR? draining + optional retries
- Mock instrument for testing

API sketch:
    scope = Oscilloscope("USB0::...::INSTR", timeout_ms=5000)
    scope.connect(); scope.initialize()
    scope.set_time_scale(1e-3)                  # 1 ms/div
    scope.set_channel_scale(1, 0.5)             # 0.5 V/div
    scope.set_channel_coupling(1, "DC")         # DC/AC/GND
    scope.set_trigger(edge_src="CHAN1", level=0.2, slope="POS")
    png = scope.screenshot_png()                 # bytes
    scope.enable_math(True, op="ADD", src1="CHAN1", src2="CHAN2")
    scope.close()


    TBD: the measurement that needs two token are ok, channels enum, math correct implementation.
"""
from __future__ import annotations
import dataclasses, logging, re
from typing import Optional, Tuple, Dict, Type, Any, Iterable
from enum import Enum
from pyvisa.constants import BufferOperation
from math import isfinite, isclose
from math import isfinite, log10, floor
from decimal import Decimal

try:
    import pyvisa  # type: ignore
except Exception:
    pyvisa = None


# ---------------------------
# Enums
# ---------------------------
class Measure(Enum):
    # Voltage
    VPP = "VPP"; VMAX = "VMAX"; VMIN = "VMIN"; TOP = "TOP"; BASE = "BASE"
    AVG = "AVG"; RMS = "RMS"
    # Time / freq
    FREQ = "FREQ"; PERIOD = "PERIOD"
    RISE = "RISE"; FALL = "FALL"
    PDUTY = "PDUTY"; NDUTY = "NDUTY"
    PWID = "PWID";  NWID = "NWID"
    # Cross/sync
    PHASE = "PHASE"; DELAY = "DELAY"

class ChannelUnit(Enum):
    VOLT = "VOLT"
    AMP = "AMP"


class TriggerSweepMode(Enum):
    AUTO = "AUTO"
    NORM = "NORM"
    SINGLE = "SINGLE"


class MathOperator(Enum):
    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    MULTIPLY = "MULTIPLY"
    DIVIDE = "DIVIDE"
    INTEGRATE = "INTEGRATE"
    DIFFERENTIATE = "DIFFERENTIATE"
    FFT = "FFT"
    FFT_PHASE = "FFT_PHASE"
    SQRT = "SQRT"
    MAGNIFY = "MAGNIFY"
    ABSOLUTE = "ABSOLUTE"
    SQUARE = "SQUARE"
    LN = "LN"
    LOG = "LOG"
    EXP = "EXP"
    TEN = "TEN"
    LOWPASS = "LOWPASS"
    HIGHPASS = "HIGHPASS"
    BANDPASS = "BANDPASS"
    AVERAGE = "AVERAGE"
    LINEAR = "LINEAR"
    MAXIMUM = "MAXIMUM"
    MINIMUM = "MINIMUM"
    PEAK = "PEAK"
    MAXHOLD = "MAXHOLD"
    MINHOLD = "MINHOLD"
    TREND = "TREND"
    BTIMING = "BTIMING"
    BSTATE = "BSTATE"
    SERCHART = "SERCHART"

# ---------------------------
# Exceptions
# ---------------------------
class ScopeError(Exception): ...
class NotConnectedError(ScopeError): ...
class SCPIError(ScopeError): ...
class NotSupportedError(ScopeError): ...
class RangeError(ScopeError): ...

# ---------------------------
# Utilities
# ---------------------------
def with_retries(max_retries: int = 1, delay: float = 0.0):
    import time
    def deco(fn):
        def wrapper(self, *a, **k):
            last = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(self, *a, **k)
                except (SCPIError, OSError) as e:
                    last = e
                    if attempt < max_retries:
                        if getattr(self, "logger", None):
                            self.logger.debug("%s failed: %s (retry %d/%d)",
                                              fn.__name__, e, attempt + 1, max_retries)
                        if delay:
                            time.sleep(delay)
                        continue
                    raise
            raise last
        return wrapper
    return deco

def require_connected(fn):
    def wrapper(self, *a, **k):
        if not self._connected:
            raise NotConnectedError("Instrument not connected. Call connect() first.")
        return fn(self, *a, **k)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper

# ---------------------------
# Session wrapper (mirrors PSU style)
# ---------------------------
@dataclasses.dataclass
class _Session:
    resource: Any
    check_errors: bool = True
    wait_opc: bool = True
    logger: Optional[logging.Logger] = None
    _last_cmd: Optional[str] = None

    def __init__(self, resource, check_errors=True, wait_opc=True, logger=None):
        self.resource = resource
        self.check_errors = check_errors
        self.wait_opc = wait_opc
        self.logger = logger
        self._last_cmd = None

    def write(self, cmd: str) -> None:
        self._last_cmd = cmd
        if self.logger: self.logger.debug("→ %s", cmd)
        try:
            self.resource.write(cmd)
        except Exception as e:
            msg = self._quick_scpi_recover()
            if msg and self._is_unsupported_msg(msg):
                raise NotSupportedError(f"Unsupported command after '{cmd}': {msg}") from e
            if msg:
                raise SCPIError(f"Instrument error after '{cmd}': {msg}") from e
            raise
        
        if self.check_errors: self._drain_error_queue()
        if self.wait_opc:
            self.query("*OPC?")
            if self.check_errors: self._drain_error_queue()


    def query(self, cmd: str) -> str:
        if self.logger: self.logger.debug("? %s", cmd)
        try:
            resp = self.resource.query(cmd)
        except Exception as e:
            msg = self._quick_scpi_recover()
            if msg and self._is_unsupported_msg(msg):
                raise NotSupportedError(f"Unsupported query after '{cmd}': {msg}") from e
            if msg:
                raise SCPIError(f"Instrument error after '{cmd}': {msg}") from e
            raise
        
        if self.logger: self.logger.debug("← %s", resp.strip())
        if self.check_errors and not cmd.strip().upper().startswith("SYST:ERR?"):
            self._drain_error_queue()
        return resp

    def _drain_error_queue(self) -> None:
        try:
            for _ in range(16):
                s = self.resource.query("SYST:ERR?").strip()
                if self.logger:
                    self.logger.debug("ERR? %s", s)
                if not s:
                    break
                code_str = s.split(",")[0].strip()
                try:
                    code = int(code_str)   # handles "0", "+0", "-200", etc.
                except ValueError:
                    # if parsing fails, assume nonzero
                    code = 1
                if code == 0:
                    break

                raise SCPIError(f"Instrument error after '{self._last_cmd}': {s}")
        except SCPIError:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug("Error queue check skipped: %s", e)

    from contextlib import contextmanager

    @contextmanager
    def suspend_checks(self):
        old_err, old_opc = self.check_errors, self.wait_opc
        self.check_errors, self.wait_opc = False, False
        try:
            yield
        finally:
            self.check_errors, self.wait_opc = old_err, old_opc

    @contextmanager
    def suspend_opc(self):
        """Temporarily disable *OPC? waiting but keep error checks."""
        old_opc = self.wait_opc
        self.wait_opc = False
        try:
            yield
        finally:
            self.wait_opc = old_opc


    def query_ieee_block(self, cmd: str, timeout_ms: int = 10000) -> bytes:
        r = self.resource
        with self.suspend_checks():
            # save + disable read termination
            old_rt = getattr(r, "read_termination", None)
            old_to = r.timeout
            try:
                if hasattr(r, "read_termination"):
                    r.read_termination = None
                r.timeout = timeout_ms

                r.write(cmd)

                # read header: '#' + <ndigits> + <len>
                h = r.read_bytes(2)  # b"#" + digit
                if not h.startswith(b"#"):
                    raise SCPIError(f"bad block header start: {h!r}")
                nd = int(h[1:2])               # number of digits
                ln = int(r.read_bytes(nd).decode("ascii"))  # payload length

                # read payload of exact length
                data = r.read_bytes(ln)

                # optional terminator consume
                try:
                    r.read_bytes(1)
                except Exception:
                    pass

                return data
            finally:
                r.timeout = old_to
                try:
                    if hasattr(r, "read_termination"):
                        r.read_termination = old_rt
                except Exception:
                    pass

    # --- Minimal SCPI recovery (no I/O flushing, no retries) ---
    def _quick_scpi_recover(self) -> str | None:
        """Try one ERR? then *CLS with short timeout. Never raises."""
        try:
            old = getattr(self.resource, "timeout", None)
            if old is not None:
                try: self.resource.timeout = 100
                except Exception: old = None
            try:
                msg = self.resource.query("SYST:ERR?").strip()
            except Exception:
                msg = None
            try:
                self.resource.write("*CLS")
            except Exception:
                pass
            return msg
        except Exception:
            return None
        finally:
            if 'old' in locals() and old is not None:
                try: self.resource.timeout = old
                except Exception: pass


    def wait_opc_once(self, timeout_ms: int = 10000) -> bool:
        """Block on *OPC? with a temporary timeout. Returns True if OPC=1."""
        r = self.resource
        with self.suspend_checks():
            old = getattr(r, "timeout", None)
            try:
                if old is not None:
                    r.timeout = timeout_ms
                return self.resource.query("*OPC?").strip().startswith("1")
            except Exception:
                return False
            finally:
                if old is not None:
                    try: r.timeout = old
                    except Exception: pass


    @staticmethod
    def _is_unsupported_msg(msg: str) -> bool:
        u = msg.upper()
        return any(tok in u for tok in ("-113", "UNDEFINED HEADER", "HEADER NOT RECOGNIZED",
                                        "-102", "SYNTAX ERROR", "COMMAND ERROR", "-420","Query UNTERMINATED"))


# ---------------------------
# Base + Brand adapter pattern
# ---------------------------
class BaseAdapter:
    brand: str = "Generic"
    
    TOKEN_MAP = {
        "channel_unit": { "VOLT":"VOLT", "AMP":"AMP" },
        "measure": {
            "VPP":"VPP","VMAX":"VMAX","VMIN":"VMIN","TOP":"TOP","BASE":"BASE",
            "AVG":"AVER","RMS":"RMS","FREQ":"FREQ","PERIOD":"PER","RISE":"RIS","FALL":"FALL",
            "PDUTY":"PDUT","NDUTY":"NDUT","PWID":"PWID","NWID":"NWID","PHASE":"PHASE","DELAY":"DEL"
        },
        "trig_sweep": { "AUTO":"AUTO", "NORM":"NORM", "SINGLE":"SINGLE" },
        "math": {
            "ADD":"ADD","SUBTRACT":"SUBTract","MULTIPLY":"MULTiply","DIVIDE":"DIVide","INTEGRATE":"INTegrate",
            "DIFFERENTIATE":"DIFF","FFT":"FFT","FFT_PHASE":"FFTPhase","SQRT":"SQRT","MAGNIFY":"MAGNify",
            "ABSOLUTE":"ABSolute","SQUARE":"SQUare","LN":"LN","LOG":"LOG","EXP":"EXP","TEN":"TEN",
            "LOWPASS":"LOWPass","HIGHPASS":"HIGHpass","BANDPASS":"BANDpass","AVERAGE":"AVERage","LINEAR":"LINear",
            "MAXIMUM":"MAXimum","MINIMUM":"MINimum","PEAK":"PEAK","MAXHOLD":"MAXHold","MINHOLD":"MINHold",
            "TREND":"TRENd","BTIMING":"BTIMing","BSTATE":"BSTate","SERCHART":"SERChart"
        },
        # optional families you can add later:
        # "coupling": {"DC":"DC","AC":"AC","GND":"GND"},
        # "slope": {"POS":"POS","NEG":"NEG"},
    }

    def __init__(self, s: _Session, idn: str):
        self.s = s
        self.idn = idn
        self.REV_TOKEN_MAP = {fam:{v:k for k,v in m.items()} for fam,m in self.TOKEN_MAP.items()}
        for fam,m in self.TOKEN_MAP.items():
            if len(set(m.values())) != len(m): raise ValueError(f"{fam} tokens must be unique")


    @staticmethod
    def _bstr(on: bool) -> str: return "ON" if on else "OFF"

    @staticmethod
    def _parse_bool(s: str) -> bool:
        u = s.strip().upper()
        return u in {"1", "ON", "TRUE"}

    
    def _tok(self, family: str, v, *, strict: bool = True) -> str:
        k = v.value if hasattr(v, "value") else str(v).upper()
        fam = self.TOKEN_MAP.get(family, {})
        if not strict:
            return fam.get(k, k)  # passthrough if unmapped
        try:
            return fam[k]
        except KeyError:
            raise NotSupportedError(f"unknown {family} token: {k}")

    
    def _untok(self, family: str, vendor_token: str, *, passthrough=True):
        t = vendor_token.strip()
        m = self.REV_TOKEN_MAP.get(family, {})
        if t in m: return m[t]
        return t if passthrough else (_ for _ in ()).throw(NotSupportedError(f"unknown {family} vendor token: {t}"))

    def set_channel_enabled(self, ch: int, on: bool) -> None:
        """Show/hide an analog channel on screen."""
        chan = self._chan(ch)
        for cmd in (f":{chan}:DISP {self._bstr(on)}",    # Keysight/Rigol
                    f":{chan}:STAT {self._bstr(on)}"):   # Rohde & Schwarz
            try:
                self.s.write(cmd)
                return
            except Exception:
                continue
        raise NotSupportedError("Channel display enable not supported by this model")

    def is_channel_enabled(self, ch: int) -> bool | None:
        """Return True/False if query supported, else None."""
        chan = self._chan(ch)
        for q in (f":{chan}:DISP?", f":{chan}:STAT?"):
            try:
                return self._parse_bool(self.s.query(q))
            except Exception:
                continue
        return None


    # Timebase
    def set_time_scale(self, sec_per_div: float) -> None:
        self.s.write(f":TIM:SCAL {sec_per_div}")

    def get_time_scale(self) -> float:
        return float(self.s.query(":TIM:SCAL?"))

    def set_time_position(self, sec: float) -> None:
        self.s.write(f":TIM:POS {sec}")

    # Vertical
    def _chan(self, ch: int) -> str:
        if ch < 1: raise RangeError("channels are 1-based")
        return f"CHAN{ch}"

    def get_channel_scale(self, ch: int) -> float: 
        return float(self.s.query(f":{self._chan(ch)}:SCAL?"))

    def get_channel_offset(self, ch: int) -> float:
        return float(self.s.query(f":{self._chan(ch)}:OFFS?"))


    def set_channel_scale(self, ch: int, v_per_div: float) -> None:
        self.s.write(f":{self._chan(ch)}:SCAL {v_per_div}")

    def set_channel_offset(self, ch: int, volts: float) -> None:
        self.s.write(f":{self._chan(ch)}:OFFS {volts}")

    def set_channel_coupling(self, ch: int, mode: str) -> None:
        token = self._tok('coupling', mode, strict=False)
        self.s.write(f":{self._chan(ch)}:COUP {token}")


    def set_channel_units(self, ch: int, unit: ChannelUnit | str) -> None:
        token = self._tok('channel_unit', unit)
        self.s.write(f":{self._chan(ch)}:UNITs {token}")

    def get_channel_units(self, ch: int) -> ChannelUnit | str:
        token = self.s.query(f":{self._chan(ch)}:UNITs?")
        return self._untok('channel_unit', token)


    #Probe
    def set_probe_attenuation(self, ch: int, factor: float) -> None: 
        self.s.write(f":{self._chan(ch)}:PROBe {factor}")

    def get_probe_attenuation(self, ch: int) -> float: 
        return float(self.s.query(f":{self._chan(ch)}:PROBe?"))

    def set_probe_sensitivity(self, ch: int, v_per_a: float) -> None: 
        self.set_probe_attenuation(ch, 1/v_per_a)

    def get_probe_sensitivity(self, ch: int) -> float: 
        return 1/self.get_probe_attenuation(ch)

    # Trigger
    def set_trigger(self, *, edge_src: str = "CHAN1", level: float = 0.0, slope: str = "POS") -> None:
        self.s.write(":TRIG:MODE EDGE")
        self.s.write(f":TRIG:EDGE:SOUR {edge_src}")
        self.s.write(f":TRIG:LEV {level}")
        self.s.write(f":TRIG:EDGE:SLOP {slope.upper()}")  # POS|NEG

    def set_trigger_sweep(self, mode: TriggerSweepMode | str) -> None:
        token = self._tok('trig_sweep', mode)
        self.s.write(f":TRIG:SWE {token}")

    def get_trigger_sweep(self) -> TriggerSweepMode | str:
        tok = self.s.query(":TRIG:SWE?").strip()
        return self._untok('trig_sweep', tok)

    def get_trigger_status(self) -> bool:
        """True if a trigger occurred since last read. Clears the event register."""
        s = self.s.query(":TER?").strip()
        # :TER? returns "1" when a trigger event occurred since last clear, else "0".
        return s.startswith(("1", "ON", "TRUE"))
    






     # Run/stop

    def run(self) -> None:  self.s.write(":RUN")
    def stop(self) -> None: self.s.write(":STOP")
    def single(self) -> None:
        with self.s.suspend_opc():
            self.s.write(":SING")
            self.get_trigger_status()  # clears TER

    def force_trigger(self) -> None: self.s.write(":TRIGger:FORCe")

    # Math
    def _math_ns(self, math: int | str) -> str:
        m = int(math)
        if m < 1: raise ValueError("math must be >= 1")
        return f":MATH"

    def set_math_source(self, math: int, slot: int, src: str) -> None:
        if slot not in (1, 2): raise ValueError("slot must be 1 or 2")
        ns = self._math_ns(math)
        self.s.write(f"{ns}:SOUR{slot} {src}")

    def set_math_operator(self, math: int, op: MathOperator | str = MathOperator.ADD) -> None:
        ns = self._math_ns(math)
        self.s.write(f"{ns}:OPER {self._tok('math', op)}")

    def set_math_enabled(self, math: int, on: bool) -> None:
        ns = self._math_ns(math)
        self.s.write(f"{ns}:DISP {'ON' if on else 'OFF'}")

    def enable_math(self, math: int, on: bool, op: MathOperator | str = MathOperator.ADD) -> None:
        # sets operator and display only
        self.set_math_operator(math, op)
        self.set_math_enabled(math, on)


    def set_math_scale(self, math: int, v_per_div: float) -> None:
        ns = self._math_ns(math)  # reuses your helper
        self.s.write(f"{ns}:SCAL {v_per_div}")

    def set_math_offset(self, math: int, volts: float) -> None:
        ns = self._math_ns(math)
        self.s.write(f"{ns}:OFFS {volts}")



    def _meas_token(self, kind: Measure | str) -> str:
        try:
            return self._tok('measure', kind)
        except NotSupportedError:
            raise NotSupportedError(f"unknown measure kind: {kind}")

    def _parse_float(self, s: str) -> float:
        import re
        m = re.search(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?', s)
        if not m: raise SCPIError(f"no numeric value in {s!r}")
        return float(m.group(0))

# tokens that require two sources
    MEAS_SIGNATURES: dict[str, int] = {"PHASE": 2, "DELAY": 2}

    def enable_measure(self, kind: Measure | str, src: str = "CHAN1", src2: str | None = None):
        t = self._meas_token(kind)
        need_two = self.MEAS_SIGNATURES.get(t, 1) == 2 or src2 is not None
        if need_two and not src2:
            src2 = "CHAN2"
        forms_1 = (
            f":MEAS:ITEM {t},{src}",
            f":MEAS:{t} {src}",
            f":MEAS:{t} {src},DEF,DEF",
        )
        forms_2 = (
            f":MEAS:ITEM {t},{src},{src2}",
            f":MEAS:{t} {src},{src2}",
            f":MEAS:{t} {src},{src2},DEF,DEF",
        )
        for q in (forms_2 if need_two else forms_1):
            try:
                self.s.write(q); return
            except Exception as e:
                continue
        raise NotSupportedError(f"measurement {kind} not supported: {e}")

    def get_measure(self, kind: Measure | str, src: str = "CHAN1", src2: str | None = None) -> float:
        t = self._meas_token(kind)
        need = self.MEAS_SIGNATURES.get(t, 1)
        two = (need == 2) or (src2 is not None)
        if two and not src2:
            src2 = "CHAN2"
        forms_1 = (
            f":MEAS:ITEM? {t},{src}",
            f":MEAS:{t}? {src}",
            f":MEAS:{t}? {src},DEF,DEF",
        )
        forms_2 = (
            f":MEAS:ITEM? {t},{src},{src2}",
            f":MEAS:{t}? {src},{src2}",
            f":MEAS:{t}? {src},{src2},DEF,DEF",
        )
        for q in (forms_2 if two else forms_1):
            try:
                return self._parse_float(self.s.query(q))
            except Exception:
                continue
        raise NotSupportedError(f"measurement {kind} not supported")

    def enable_measure_stats(self, on: bool = True) -> None:
        for cmd in (":MEAS:STAT ON", ":MEAS:STAT:STATE ON"):
            try:
                self.s.write(cmd if on else cmd.replace("ON","OFF")); return
            except Exception: continue
        raise NotSupportedError("measure stats toggle not supported")
    
    def clear_measures(self) -> None:
        
        try: self.s.write(":MEASure:CLEar"); return
        except Exception:
            raise NotSupportedError("measures clear not supported")

    def clear_measure_stats(self) -> None:
        for cmd in (":MEAS:STAT:CLEAR", ":MEAS:STAT:RES"):
            try: self.s.write(cmd); return
            except Exception: continue
        raise NotSupportedError("measure stats clear not supported")

    def measure_stats(self, kind: Measure | str, src: str = "CHAN1") -> dict:
        t = self._meas_token(kind)
        for q in (f":MEAS:STAT:ITEM? {t},{src}",
                  f":MEAS:STAT:ITEM? {t},{src},ALL"):
            try:
                resp = self.s.query(q).strip()
                vals = [self._parse_float(x) for x in resp.replace(";",",").split(",")]
                if len(vals) >= 4:
                    return {"MEAN":vals[0], "MIN":vals[1], "MAX":vals[2], "STD":vals[3]}
            except Exception:
                continue
        raise NotSupportedError("measure stats not supported")


    # Screenshot → PNG bytes
    def screenshot_png(self) -> bytes:
        for cmd in (":DISPlay:DATA? PNG,SCReen,ON",
                    ":DISP:DATA? PNG,SCREEN,ON",
                    ":DISP:DATA? PNG"):
            try:
                return self.s.query_ieee_block(cmd, timeout_ms=10000)
            except Exception:
                continue
        # Hardcopy fallback
        with self.s.suspend_checks():
            self.s.resource.write(":HCOPy:DEVice:LANGuage PNG")
            self.s.resource.write(":HCOPy:IMMediate")
            return self.resource_read_raw()

    def menu_off(self) -> None:
        try:
            self.s.write(":DISPlay:MENU OFF")
            return
        except Exception as e:
            raise NotSupportedError(f"menu off not supported: {e}")


    def resource_read_raw(self) -> bytes:
        # Use underlying VISA object directly to read binary block
        r = self.s.resource
        if hasattr(r, "read_raw"):
            return r.read_raw()
        # Fallback via query of arbitrary-length binary not supported → fail
        raise NotSupportedError("read_raw not available on this VISA resource")

    # Detection
    @staticmethod
    def matches(idn: str) -> bool:  # fallback
        return True

    def reset(self, opc_timeout_ms: int = 5000) -> None:
        """Hard reset the instrument and unblock Single-mode waits."""
        # 1) device clear (ignore transport that lacks .clear)
        try:
            self.s.clear()          # pyvisa Resource.clear()
        except Exception:
            pass

        # 2) reset + clear status
        self.s.write("*RST")
        self.s.write("*CLS")

        # 3) probe readiness
        old = getattr(self.s, "timeout", None)
        try:
            if old is not None:
                self.s.timeout = opc_timeout_ms
            _ = self.s.query("*OPC?")
        finally:
            if old is not None:
                self.s.timeout = old

        # 4) optional: read one error to drain queue
        try:
            _ = self.s.query(":SYSTem:ERRor?")
        except Exception:
            pass


class BrandAdapter(BaseAdapter):
    _models: list[type["BrandAdapter"]] = []
    brand: str | None = None
    vendor_aliases: tuple[str, ...] = ()

    @classmethod
    def register_model(cls, model_cls):
        cls._models.append(model_cls)
        return model_cls

    @classmethod
    def select(cls, idn: str) -> type["BrandAdapter"]:
        u = idn.upper()
        # prefer MODEL_PATTERNS if provided
        for m in cls._models:
            pats = getattr(m, "MODEL_PATTERNS", ())
            if pats and any(rx.search(u) for rx in pats):
                return m
        for m in cls._models:
            try:
                if hasattr(m, "matches") and m.matches(idn):
                    return m
            except Exception:
                pass
        return cls

    @classmethod
    def matches(cls, idn: str) -> bool:
        if cls is BrandAdapter: return False
        u = idn.upper()
        aliases = [cls.brand or ""] + list(cls.vendor_aliases)
        return any(a.upper() in u for a in aliases if a)




# ---------------------------
# Adapters
# ---------------------------
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
 
            },
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
    def set_trigger(self, *, edge_src: str = "CHAN1", level: float = 0.0, slope: str = "POS") -> None:
        self.s.write(":TRIG:MODE EDGE")
        self.s.write(f":TRIG:EDGE:SOUR {edge_src}")
        self.s.write(f":TRIG:EDGE:LEVel {level}")
        self.s.write(f":TRIG:EDGE:SLOP {slope.upper()}")  # POS|NEG

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

        


class RohdeSchwarzScope(BrandAdapter):
    brand = "Rohde&Schwarz"
    vendor_aliases = ("R&S", "R\u0026S", "ROHDE")

    def screenshot_png(self) -> bytes:
        self.s.write(":HCOP:DEV:LANG PNG")
        self.s.write(":HCOP:IMM")
        return self.resource_read_raw()


class KeysightScope(BrandAdapter):
    brand = "KEYSIGHT TECHNOLOGIES"
    vendor_aliases = ("KEYSIGHT", "AGILENT", "HEWLETT-PACKARD", "HP")

    TOKEN_MAP = BaseAdapter.TOKEN_MAP | {
        "math": BaseAdapter.TOKEN_MAP["math"] | {"SUBTRACT": "SUBT", "ABSOLUTE": "ABS"},
        "measure": BaseAdapter.TOKEN_MAP["measure"] | {
            "AVG": "VAV", "RMS": "VRMS", "TOP": "VTOP", "BASE": "VBASE", "PDUTY": "DUTY"
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


# Example model specialization via regex
@RigolScope.register_model
class RigolMSO2k4k(RigolScope):
    MODEL_PATTERNS = (re.compile(r",MSO?[24]\d{2}", re.I),)

# ---------------------------
# Adapter selection
# ---------------------------
def pick_adapter(idn: str) -> type[BaseAdapter]:
    candidates: list[type[BrandAdapter]] = []
    for obj in globals().values():
        if isinstance(obj, type):
            try:
                if issubclass(obj, BrandAdapter) and obj is not BrandAdapter:
                    candidates.append(obj)  # type: ignore
            except Exception:
                pass
    candidates.sort(key=lambda c: (-len(c.mro()), c.__name__))
    for Cls in candidates:
        try:
            if hasattr(Cls, "matches") and Cls.matches(idn):  # type: ignore
                return getattr(Cls, "select", lambda _idn: Cls)(idn)  # type: ignore
        except Exception:
            continue
    return BaseAdapter

# ---------------------------
# Public façade
# ---------------------------
class Oscilloscope:
    def __init__(
        self,
        visa_address: str,
        *,
        timeout_ms: int = 5000,
        check_errors: bool = True,
        wait_opc: bool = True,
        logger: Optional[logging.Logger] = None,
        rm: Optional["pyvisa.ResourceManager"] = None,
        retries: int = 10,
        retry_delay: float = 0.1,
        defer_init_io: bool = True,
    ):
        self.address = visa_address
        self.timeout_ms = int(timeout_ms)
        self.check_errors = check_errors
        self.wait_opc = wait_opc
        self.logger = logger or logging.getLogger(__name__ + ".scope")
        self.rm = rm
        self._defer_init_io = defer_init_io
        self._resource = None
        self._session: Optional[_Session] = None
        self._adapter: Optional[BaseAdapter] = None
        self._connected = False
        self.identity: Optional[str] = None
        # optional global retry tuning for session
        self._retries = retries
        self._retry_delay = retry_delay

    def connect(self) -> None:
        """Connect to self.address using VISA only. On VI_ERROR_RSRC_NFOUND,
        rebuild the ResourceManager and retry the SAME address."""
        if pyvisa is None:
            raise ImportError("pyvisa is not installed. Please 'pip install pyvisa'.")
        if self._connected:
            return

        import time
        from typing import Optional

        VI_ERR_NOT_FOUND = getattr(getattr(pyvisa, "constants", object),
                                "VI_ERROR_RSRC_NFOUND", -1073807343)

        last_err: Optional[Exception] = None

        for attempt in range(self._retries + 1):
            try:
                if self.rm is None:
                    self.rm = pyvisa.ResourceManager()

                self._resource = self.rm.open_resource(self.address)

                # Configure terminations early
                try:
                    self._resource.write_termination = "\n"
                    self._resource.read_termination = "\n"
                except Exception:
                    pass
                self._resource.timeout = self.timeout_ms

                # Bind session
                self._session = _Session(self._resource, self.check_errors, self.wait_opc, self.logger)
                self._connected = True
                if not self._defer_init_io:
                    self.initialize()
                return

            except Exception as e:
                last_err = e
                if self.logger:
                    self.logger.debug("connect() attempt %d/%d failed: %s",
                                    attempt + 1, self._retries + 1, e)

                # Hard-reset RM only for "resource not found"
                if getattr(e, "error_code", None) == VI_ERR_NOT_FOUND:
                    try:
                        if self._resource is not None:
                            try: self._resource.close()
                            except Exception: pass
                            self._resource = None
                    except Exception:
                        pass
                    try:
                        if self.rm is not None:
                            try: self.rm.close()
                            except Exception: pass
                    finally:
                        self.rm = None  # force fresh RM next loop

                if attempt < self._retries:
                    time.sleep(self._retry_delay)
                    continue
                break

        raise ScopeError(f"Failed to connect to {self.address} after {self._retries + 1} attempts") from last_err

    def initialize(self) -> None:
        if not self._connected:
            raise NotConnectedError("Not connected; call connect() first.")
        if self._adapter is not None and self.identity is not None:
            return
        self.identity = self._session.query("*IDN?").strip()
        Adapter = pick_adapter(self.identity or "")
        self._adapter = Adapter(self._session, self.identity or "")

    # ---- Thin façade → adapter ----
    @require_connected
    def set_channel_enabled(self, ch: int, on: bool) -> None:
        assert self._adapter is not None
        self._adapter.set_channel_enabled(ch, on)

    @require_connected
    def is_channel_enabled(self, ch: int) -> bool | None:
        assert self._adapter is not None
        return self._adapter.is_channel_enabled(ch)


    @require_connected
    def set_time_scale(self, sec_per_div: float) -> None: self._adapter.set_time_scale(sec_per_div)  # type: ignore
    @require_connected
    def get_time_scale(self) -> float: return self._adapter.get_time_scale()  # type: ignore
    @require_connected
    def set_time_position(self, sec: float) -> None: self._adapter.set_time_position(sec)  # type: ignore


    @require_connected
    def get_channel_scale(self, ch: int) -> float: return self._adapter.get_channel_scale(ch)  # type: ignore
    @require_connected
    def get_channel_offset(self, ch: int) -> float: return self._adapter.get_channel_offset(ch)  # type: ignore

    @require_connected
    def set_channel_scale(self, ch: int, v_per_div: float) -> None: self._adapter.set_channel_scale(ch, v_per_div)  # type: ignore
    @require_connected
    def set_channel_offset(self, ch: int, volts: float) -> None: self._adapter.set_channel_offset(ch, volts)  # type: ignore
    @require_connected
    def set_channel_coupling(self, ch: int, mode: str) -> None: self._adapter.set_channel_coupling(ch, mode)  # type: ignore
    @require_connected
    def set_channel_units(self, ch: int, unit: ChannelUnit | str) -> None: self._adapter.set_channel_units(ch, unit)
    @require_connected
    def get_channel_units(self, ch: int) -> ChannelUnit | str: return self._adapter.get_channel_units(ch)

    @require_connected
    def set_probe_attenuation(self, ch: int, factor: float) -> None: self._adapter.set_probe_attenuation(ch, factor)  # type: ignore
    @require_connected
    def get_probe_attenuation(self, ch: int) -> float: return self._adapter.get_probe_attenuation(ch)  # type: ignore
    @require_connected
    def set_probe_sensitivity(self, ch: int, v_per_a: float) -> None: self._adapter.set_probe_sensitivity(ch, v_per_a)  # type: ignore
    @require_connected
    def get_probe_sensitivity(self, ch: int) -> float: return self._adapter.get_probe_sensitivity(ch)  # type: ignore

    @require_connected
    def set_trigger(self, *, edge_src: str = "CHAN1", level: float = 0.0, slope: str = "POS") -> None:
        self._adapter.set_trigger(edge_src=edge_src, level=level, slope=slope)  # type: ignore

    @require_connected
    def set_trigger_sweep(self, mode: TriggerSweepMode | str) -> None: 
        self._adapter.set_trigger_sweep(mode)  # type: ignore
        self._adapter.get_trigger_sweep()

    @require_connected
    def get_trigger_sweep(self) -> TriggerSweepMode | str: return self._adapter.get_trigger_sweep()  # type: ignore

    @require_connected
    def get_trigger_status(self) -> bool: return self._adapter.get_trigger_status()  # type: ignore

    @require_connected
    def run(self) -> None: self._adapter.run()  # type: ignore
    @require_connected
    def stop(self) -> None: self._adapter.stop()  # type: ignore
    @require_connected
    def single(self) -> None: self._adapter.single()  # type: ignore
    @require_connected
    def force_trigger(self) -> None: self._adapter.force_trigger()  # type: ignore

    @require_connected
    def set_math_source(self, math: int, slot: int, src: str) -> None:
        self._adapter.set_math_source(math, slot, src)  # type: ignore

    @require_connected
    def set_math_operator(self, math: int, op: MathOperator | str = MathOperator.ADD) -> None:
        self._adapter.set_math_operator(math, op)  # type: ignore

    @require_connected
    def set_math_enabled(self, math: int, on: bool) -> None:
        self._adapter.set_math_enabled(math, on)  # type: ignore

    @require_connected
    def enable_math(self, math: int, on: bool, op: MathOperator | str = MathOperator.ADD) -> None:
        self._adapter.enable_math(math, on, op)  # type: ignore


    @require_connected
    def set_math_scale(self, math: int, v_per_div: float) -> None:
        self._adapter.set_math_scale(math, v_per_div)  # type: ignore

    @require_connected
    def set_math_offset(self, math: int, volts: float) -> None:
        self._adapter.set_math_offset(math, volts)  # type: ignore

    @require_connected
    def get_measure(self, kind: Measure | str, src: str = "CHAN1", src2: str | None = None) -> float:
        return self._adapter.get_measure(kind, src, src2)
    
    @require_connected
    def enable_measure(self, kind: Measure | str, src: str = "CHAN1", src2: str | None = None):
        self._adapter.enable_measure(kind, src, src2)

    @require_connected
    def clear_measures(self) -> None:
        self._adapter.clear_measures()

    @require_connected
    def enable_measure_stats(self, on: bool = True) -> None:
        self._adapter.enable_measure_stats(on)

    @require_connected
    def clear_measure_stats(self) -> None:
        self._adapter.clear_measure_stats()

    @require_connected
    def measure_stats(self, kind: Measure | str, src: str = "CHAN1") -> dict:
        return self._adapter.measure_stats(kind, src)

    @require_connected
    def screenshot_png(self) -> bytes:
        return self._adapter.screenshot_png()  # type: ignore

    @require_connected
    def menu_off(self) -> None:
        """Turn off on-screen menus to get a clean screenshot."""
        self._adapter.menu_off()  # type: ignore


    @require_connected
    def write_raw(self, cmd: str) -> None:
        """Send a SCPI command string as-is."""
        assert self._session is not None
        self._session.write(cmd)

    @require_connected
    def query_raw(self, cmd: str) -> str:
        """Send a SCPI query string and return the raw reply."""
        assert self._session is not None
        return self._session.query(cmd)

    def close(self) -> None:
        if not self._connected:
            return
        try:
            if self._resource is not None:
                self._resource.close()
        finally:
            self._resource = None
            self._session = None
            self._adapter = None
            self._connected = False


    @require_connected
    def clear_io(self) -> None:
        r = self._resource
        # 1) VISA device clear (viClear). Best effort.
        try:
            r.clear()
        except Exception:
            pass

        # 2) Drop any queued bytes in driver buffers.
        try:
            r.flush(BufferOperation.discard_io_buffer)  # read+write
        except Exception:
            # older backends may not support flush()
            pass

        # 3) Non-blocking drain of residual device output.
        try:
            old_to = r.timeout
            r.timeout = 50  # ms
            while True:
                try:
                    # prefer byte-wise read if available
                    if hasattr(r, "read_bytes"):
                        r.read_bytes(1024)
                    else:
                        r.read()
                except Exception:
                    break
        finally:
            try:
                r.timeout = old_to
            except Exception:
                pass

        # 4) Clear SCPI status/errors if you also want a clean SCPI state.
        with self._session.suspend_checks():  # no auto-drain
            try:
                self._session.write("*CLS")
            except Exception:
                pass
            # drain error queue explicitly
            for _ in range(16):
                try:
                    if self._session.query("SYST:ERR?").strip().startswith("0"):
                        break
                except Exception:
                    break


    @require_connected
    def wait_for_single_acq_complete(self, timeout_ms: int = 10000) -> bool:
        import time
        deadline = time.monotonic() + timeout_ms / 1000.0

        # immediate check
        if self.get_trigger_status():
            return True

        while time.monotonic() < deadline:
            if self.get_trigger_status():  # returns True when trigger occurred; also clears
                return True
            time.sleep(0.01)
        return False

    @require_connected
    def reset(self, opc_timeout_ms: int = 8000) -> None:
        self._adapter.reset(opc_timeout_ms)  # or self.a.reset(...)




    # ---------- nice numbers ----------
    @staticmethod
    def _snap125_up(x: float) -> float:
        if x <= 0: return 0.0
        e = floor(log10(x)); m = x / (10**e)
        for b in (1.0, 2.0, 5.0, 10.0):
            if m <= b + 1e-12: return b * (10**e)
        return 10.0 * (10**e)

    @staticmethod
    def _snap125_down(x: float) -> float:
        if x <= 0: return 0.0
        e = floor(log10(x)); m = x / (10**e)
        for b in (10.0, 5.0, 2.0, 1.0):
            if m >= b - 1e-12: return b * (10**e)
        return 1.0 * (10**e)

    @staticmethod
    def _round_sig2(x: float) -> float:
        if x == 0.0: return 0.0
        e = floor(log10(abs(x)))
        return round(x, max(0, 1 - e))  # two significant digits total

    # ---------- IO helpers ----------
    def _safe_get(self, ch: int) -> Tuple[float, float]:
        return float(self.get_channel_scale(ch)), float(self.get_channel_offset(ch))

    def _get_vextrema(self, ch: int) -> Tuple[float, float]:
        vmax = float(self.get_measure(Measure.VMAX, src=f"CHAN{ch}"))
        vmin = float(self.get_measure(Measure.VMIN, src=f"CHAN{ch}"))
        return vmax, vmin

    @staticmethod
    def _extrema_ok(vmax: float, vmin: float) -> bool:
        if not (isfinite(vmax) and isfinite(vmin)): return False
        if vmax == vmin: return False
        if abs(vmax) > 1e18 or abs(vmin) > 1e18: return False
        return True

    def _set_scale_resilient(self, ch: int, vdiv_target: float) -> Tuple[float, float]:
        try:
            self.set_channel_scale(ch, vdiv_target)
        except Exception:
            pass  # scope might still change scale or clamp offset
        return self._safe_get(ch)

    def _try_set_offset(self, ch: int, volts: float) -> Tuple[bool, float]:
        try:
            self.set_channel_offset(ch, volts)
            return True, float(self.get_channel_offset(ch))
        except Exception:
            return False, float(self.get_channel_offset(ch))  # readback anyway

    # ---------- fit check (80% window) ----------
    @staticmethod
    def _fits_80(vmax: float, vmin: float, offs: float, vdiv: float) -> bool:
        # 80% of screen = ±3.2 div around center
        lim = 3.2 * vdiv
        return (vmax - offs) <= lim + 1e-12 and (offs - vmin) <= lim + 1e-12

    # ---------- main ----------
    def autoscale_channel(self, ch: int, *, max_iters: int = 20) -> Tuple[float, float]:
        """
        Human workflow:
        1) If out of screen, de-zoom until VMIN/VMAX both inside 80%.
        2) Center at (VMAX+VMIN)/2 (rounded, two sig figs). If refused, keep current.
        3) Try to zoom in one 1-2-5 step. After each zoom-in, re-center.
            If either offset is refused or fit breaks, revert to last good and stop.
        Returns: (final_v_per_div, final_offset_volts)
        """
        # Ensure channel visible
        try:
            if not self.is_channel_enabled(ch):
                self.set_channel_enabled(ch, True)
        except Exception:
            self.set_channel_enabled(ch, True)

        vdiv, offs = self._safe_get(ch)

        # ---- Phase A: ensure visibility by zooming OUT, no offset changes ----
        for _ in range(max_iters):
            vmax, vmin = self._get_vextrema(ch)
            have = self._extrema_ok(vmax, vmin)
            if not have:
                # Measures nonsense → zoom out one notch and retry
                cand = self._snap125_up(max(vdiv * 1.5, vdiv * 2.0))
                prev = vdiv
                vdiv, offs = self._set_scale_resilient(ch, cand)
                if abs(vdiv - prev) <= max(1e-12, 1e-6 * prev):  # limit reached
                    break
                continue

            if self._fits_80(vmax, vmin, offs, vdiv):
                break  # already visible

            # Not visible → zoom out one 1-2-5 step
            cand = self._snap125_up(vdiv * 1.5)
            prev = vdiv
            vdiv, offs = self._set_scale_resilient(ch, cand)
            if abs(vdiv - prev) <= max(1e-12, 1e-6 * prev):  # limit reached
                break

        # Re-measure after visibility phase
        vmax, vmin = self._get_vextrema(ch)
        if not self._extrema_ok(vmax, vmin):
            return self._safe_get(ch)

        # ---- Phase B: center to mid (rounded). If refused, keep current and finish. ----
        mid_req = self._round_sig2(0.5 * (vmax + vmin))
        ok, offs_rb = self._try_set_offset(ch, mid_req)
        if ok:
            offs = offs_rb  # use readback

        # If still not visible after centering, do one safety zoom-out and stop.
        if not self._fits_80(vmax, vmin, offs, vdiv):
            prev = vdiv
            vdiv, offs = self._set_scale_resilient(ch, self._snap125_up(vdiv * 1.5))
            if abs(vdiv - prev) <= max(1e-12, 1e-6 * prev):
                return vdiv, offs
            # no more centering here; goal is readability

        # ---- Phase C: iterative zoom-in with center, revert on failure ----
        best_vdiv, best_offs = vdiv, offs
        for _ in range(max_iters):
            cand_vdiv = self._snap125_down(vdiv / 1.5)  # one 1-2-5 step tighter
            if cand_vdiv <= 0:
                break
            prev = vdiv
            vdiv, offs = self._set_scale_resilient(ch, cand_vdiv)
            if abs(vdiv - prev) <= max(1e-12, 1e-6 * prev):
                break  # hit min scale

            # Re-center at mid; if refused, revert and stop
            ok, offs_rb = self._try_set_offset(ch, mid_req)
            if ok: offs = offs_rb

            # Check fit
            vmax, vmin = self._get_vextrema(ch)
            if not self._extrema_ok(vmax, vmin) or not self._fits_80(vmax, vmin, offs, vdiv) or not ok:
                # revert to last good and stop
                self._set_scale_resilient(ch, best_vdiv)
                _ok2, _ = self._try_set_offset(ch, best_offs)  # may be ignored if refused
                return float(best_vdiv), float(self._safe_get(ch)[1])

            # Accept this tighter config and continue
            best_vdiv, best_offs = vdiv, offs

        return float(best_vdiv), float(best_offs)

    # inside class Oscilloscope
    @require_connected
    def selftest_interface(self, src: str = "CHAN1") -> dict:
        """
        Exercise the public interface using the selected adapter.
        Returns a dict of call results plus per-measurement support.
        """
        from typing import Any, Dict, List
        assert self._adapter is not None

        out: Dict[str, Any] = {"identity": self.identity, "adapter": type(self._adapter).__name__, "calls": {}, "measurements": {}}

        def _call(name: str, fn, *a, **k) -> Any:
            try:
                r = fn(*a, **k)
                out["calls"][name] = {"ok": True}
                return r
            except Exception as e:
                out["calls"][name] = {"ok": False, "err": f"{type(e).__name__}: {e}"}
                return None

        # Timebase
        _call("set_time_scale", self.set_time_scale, 1e-3)
        _call("get_time_scale", self.get_time_scale)
        _call("set_time_position", self.set_time_position, 0.0)

        # Channels
        _call("set_channel_enabled_on", self.set_channel_enabled, 1, True)
        _call("is_channel_enabled", self.is_channel_enabled, 1)

        _call("get_channel_scale", self.get_channel_scale, 1)
        _call("get_channel_offset", self.get_channel_offset, 1)
        _call("set_channel_scale", self.set_channel_scale, 1, 1.0)
        _call("set_channel_offset", self.set_channel_offset, 1, 0.0)
        _call("set_channel_coupling", self.set_channel_coupling, 1, "DC")
        _call("set_channel_units", self.set_channel_units, 1, ChannelUnit.VOLT)
        _call("get_channel_units", self.get_channel_units, 1)

        #Probe
        _call("set_probe_attenuation", self.set_probe_attenuation, 1, 10.0)
        _call("get_probe_attenuation", self.get_probe_attenuation, 1)

        # Trigger and acquisition
        _call("set_trigger", self.set_trigger, edge_src=src, level=0.1, slope="POS")
        _call("set_trigger_sweep", self.set_trigger_sweep, TriggerSweepMode.AUTO)
        _call("get_trigger_sweep", self.get_trigger_sweep)
        _call("get_trigger_status", self.get_trigger_status)
        _call("run", self.run)
        _call("single", self.single)
        _call("force_trigger", self.force_trigger)
        _call("stop", self.stop)

        # Math: configure math channel 1
        math = 1
        _call("set_math_source_m1_s1", self.set_math_source, math, 1, src)
        _call("set_math_source_m1_s2", self.set_math_source, math, 2, "CHAN2")
        _call("set_math_scale_m1", self.set_math_scale, math, 0.5)
        _call("set_math_offset_m1", self.set_math_offset, math, 0.5)

        # --- Math operators: iterate ALL tokens with enable/disable ---
        out["math_ops"] = {}
        math_tokens = sorted({
            *list(MathOperator.__members__.keys()),
            *list(BaseAdapter.TOKEN_MAP["math"].keys()),
        })
        for t in math_tokens:
            on_name  = f"math_enable_{t.lower()}"
            off_name = f"math_disable_{t.lower()}"
            _call(on_name,  self.set_math_operator, math, t)
            _call(on_name,  self.set_math_enabled,  math, True)
            _call(off_name, self.set_math_enabled,  math, False)
            out["math_ops"][t] = bool(out["calls"].get(on_name, {}).get("ok"))


        # Measures housekeeping
        _call("clear_measures", self.clear_measures)
        _call("enable_measure_stats", self.enable_measure_stats, True)
        _call("clear_measure_stats", self.clear_measure_stats)

        # Screenshot
        _call("menu_off", self.menu_off)
        img = _call("screenshot_png", self.screenshot_png)
        if out["calls"]["screenshot_png"]["ok"] and not (isinstance(img, (bytes, bytearray)) and len(img) > 0):
            out["calls"]["screenshot_png"] = {"ok": False, "err": "no image bytes"}

        # Raw I/O sanity
        _call("query_raw_*IDN?", self.query_raw, "*IDN?")

        # --- Measurements: iterate ALL tokens using get_measure only ---
        tokens = sorted({
            *list(Measure.__members__.keys()),
            *list(BaseAdapter.TOKEN_MAP["measure"].keys()),
        })


        for t in tokens:
            needs_two = getattr(type(self._adapter), "MEAS_SIGNATURES", {}).get(t, 1) == 2
            val = _call(
                f"get_measure[{t}]",
                self.get_measure,
                t,
                src,
                ("CHAN2" if needs_two else None),
            )


        return out



# ---------------------------
# Mock for tests
# ---------------------------
class MockScopeResource:
    def __init__(self, idn: str = "RIGOL TECHNOLOGIES,MSO2072A,DS2A000001,00.01"):
        self.idn = idn
        self.timeout = 5000
        self.write_termination = "\n"
        self.read_termination = "\n"
        self.state: Dict[str, Any] = {
            "tim:scal": 1e-3, "tim:pos": 0.0,
            "chan": {1: {"scal": 1.0, "offs": 0.0, "coup": "DC"}},
            "trig": {"mode": "EDGE", "src": "CHAN1", "lev": 0.0, "slope": "POS"},
            "err": [],
            "bin": b"\x89PNG\r\n\x1a\n...",  # fake PNG header
        }

    def write(self, cmd: str):
        u = cmd.strip().upper()
        if u.startswith(":TIM:SCAL "): self.state["tim:scal"] = float(cmd.split()[-1])
        elif u.startswith(":TIM:POS "): self.state["tim:pos"] = float(cmd.split()[-1])
        elif ":SCAL " in u and ":CHAN" in u:  # :CHANn:SCAL v
            ch = int(u.split(":CHAN")[1].split(":")[0])
            self.state["chan"].setdefault(ch, {"scal":1.0,"offs":0.0,"coup":"DC"})
            self.state["chan"][ch]["scal"] = float(cmd.split()[-1])
        elif ":OFFS " in u and ":CHAN" in u:
            ch = int(u.split(":CHAN")[1].split(":")[0])
            self.state["chan"].setdefault(ch, {"scal":1.0,"offs":0.0,"coup":"DC"})
            self.state["chan"][ch]["offs"] = float(cmd.split()[-1])
        elif ":COUP " in u and ":CHAN" in u:
            ch = int(u.split(":CHAN")[1].split(":")[0])
            self.state["chan"].setdefault(ch, {"scal":1.0,"offs":0.0,"coup":"DC"})
            self.state["chan"][ch]["coup"] = cmd.split()[-1].upper()
        elif u.startswith(":TRIG:MODE"): self.state["trig"]["mode"] = cmd.split()[-1].upper()
        elif u.startswith(":TRIG:EDGE:SOUR"): self.state["trig"]["src"] = cmd.split()[-1].upper()
        elif u.startswith(":TRIG:EDGE:SLOP"): self.state["trig"]["slope"] = cmd.split()[-1].upper()
        elif u.startswith(":TRIG:LEV"): self.state["trig"]["lev"] = float(cmd.split()[-1])
        elif u in {":RUN", ":STOP", ":SING", ":TFOR"}: pass
        elif u.startswith(":DISP:DATA?"): pass
        elif u == ":HCOP:IMM": pass

    def query(self, cmd: str) -> str:
        u = cmd.strip().upper()
        if u == "*IDN?": return self.idn + "\n"
        if u == "*OPC?": return "1\n"
        if u == "SYST:ERR?": return "0,\"No error\"\n"
        if u == ":TIM:SCAL?": return f"{self.state['tim:scal']}\n"
        return "\n"

    def read_raw(self) -> bytes:
        return self.state["bin"]

    def close(self): pass

class MockResourceManager:
    def __init__(self, resource: Optional[MockScopeResource] = None):
        self._resource = resource or MockScopeResource()
    def open_resource(self, address: str):
        return self._resource

# ---------------------------
# Demo
# ---------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    rm = MockResourceManager()
    scope = Oscilloscope("MOCK::SCOPE", rm=rm, timeout_ms=3000)
    scope.connect(); scope.initialize()
    scope.set_time_scale(1e-3)
    scope.set_channel_scale(1, 0.5)
    scope.set_channel_coupling(1, "DC")
    scope.set_trigger(edge_src="CHAN1", level=0.2, slope="POS")
    png = scope.screenshot_png()
    print("PNG bytes:", len(png))
    scope.close()
