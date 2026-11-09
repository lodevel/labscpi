# ruff: noqa: E701, E702
"""labscpi.oscilloscope.base — session, base/brand adapters, enums, errors.

Code moved VERBATIM from labscpi.oscilloscope_scpi (feat/timeout-retarget
@ 0abb40b). Minimal edits only:

  * BrandAdapter drops the ``_models`` / ``register_model`` / ``select``
    machinery — superseded by AUTO-REGISTRATION via ``__init_subclass__``
    (see the ``_ADAPTERS`` registry below) plus the two-stage
    ``pick_adapter`` in this package's ``__init__``.
  * Imports trimmed to what this module actually uses.
"""
from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Any, Optional

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
    # Cross/sync — edge-locked dual-source variants only (Rigol token
    # convention; <s1><s2>: R=rising, F=falling). Bare DELAY / PHASE
    # are intentionally NOT exposed: they leave edge intent implicit,
    # which can't survive adapters that map to bare hardware commands
    # without knowing what the operator meant. The grammar enforces the
    # explicit form at parse time (SCP_DELAY_PHASE_REQUIRES_EDGE).
    RR_DELAY = "RR_DELAY"; RF_DELAY = "RF_DELAY"
    FR_DELAY = "FR_DELAY"; FF_DELAY = "FF_DELAY"
    RR_PHASE = "RR_PHASE"; RF_PHASE = "RF_PHASE"
    FR_PHASE = "FR_PHASE"; FF_PHASE = "FF_PHASE"

class ChannelUnit(Enum):
    VOLT = "VOLT"
    AMP = "AMP"


class TriggerSweepMode(Enum):
    AUTO = "AUTO"
    NORM = "NORM"
    SINGLE = "SINGLE"


class TriggerSlope(Enum):
    POS = "POS"      # rising edge
    NEG = "NEG"      # falling edge
    BOTH = "BOTH"    # either edge (SCPI standard token; some brands need override, e.g. Rigol -> RFAL)


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
            "PDUTY":"PDUT","NDUTY":"NDUT","PWID":"PWID","NWID":"NWID",
            # Edge-locked dual-source delay/phase — Rigol-native tokens as the
            # cross-vendor default. Vendor adapters whose hardware lacks the
            # edge-locked SCPI items must override these 8 entries to map onto
            # whatever the instrument does expose (e.g. bare :MEAS:DEL on
            # Keysight + R&S — see KeysightScope / RohdeSchwarzScope below).
            "RR_DELAY":"RRDelay","RF_DELAY":"RFDelay","FR_DELAY":"FRDelay","FF_DELAY":"FFDelay",
            "RR_PHASE":"RRPHase","RF_PHASE":"RFPHase","FR_PHASE":"FRPHase","FF_PHASE":"FFPHase",
        },
        "trig_sweep": { "AUTO":"AUTO", "NORM":"NORM", "SINGLE":"SINGLE" },
        "slope": { "POS":"POS", "NEG":"NEG", "BOTH":"BOTH" },
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
    # The level command differs by brand (RigolScope overrides it).
    TRIG_LEVEL_CMD = ":TRIG:LEV"

    def set_trigger(self, *, edge_src: str, level: float | None = None, slope: TriggerSlope | str | None = None) -> None:
        """Edge trigger on ``edge_src``. A ``level`` / ``slope`` left None is not written: the scope keeps its own."""
        self.s.write(":TRIG:MODE EDGE")
        self.s.write(f":TRIG:EDGE:SOUR {edge_src}")
        if level is not None:
            self.s.write(f"{self.TRIG_LEVEL_CMD} {level}")
        if slope is not None:
            self.s.write(f":TRIG:EDGE:SLOP {self._tok('slope', slope)}")

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
        return f":MATH"  # noqa: F541 — verbatim port

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
    MEAS_SIGNATURES: dict[str, int] = {
        "RR_DELAY": 2, "RF_DELAY": 2, "FR_DELAY": 2, "FF_DELAY": 2,
        "RR_PHASE": 2, "RF_PHASE": 2, "FR_PHASE": 2, "FF_PHASE": 2,
    }

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
        last_exc = None
        for q in (forms_2 if need_two else forms_1):
            try:
                self.s.write(q); return
            except Exception as e:
                last_exc = e
                continue
        raise NotSupportedError(f"measurement {kind} not supported: {last_exc}")

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


# ---------------------------
# Automatic adapter registry (file-drop contract, part 2 of 2)
# ---------------------------
# Every BrandAdapter SUBCLASS is appended here by __init_subclass__ the
# moment its `class` statement executes — subclassing IS registration.
# No decorator, no hand-kept list, no per-adapter import edit anywhere.
# (Part 1 is the pkgutil auto-import loop in the package __init__, which
# imports every sibling module so those class statements actually run.)
_ADAPTERS: list[type["BrandAdapter"]] = []


class BrandAdapter(BaseAdapter):
    brand: str | None = None
    vendor_aliases: tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs) -> None:
        # AUTO-REGISTRATION: fires for every subclass at class-definition
        # time — never for BrandAdapter itself (__init_subclass__ only
        # fires on subclasses). Intermediate vendor bases and series
        # classes register too: they are legitimate selection candidates.
        super().__init_subclass__(**kwargs)
        _ADAPTERS.append(cls)

    @classmethod
    def matches(cls, idn: str) -> bool:
        if cls is BrandAdapter: return False
        u = idn.upper()
        aliases = [cls.brand or ""] + list(cls.vendor_aliases)
        return any(a.upper() in u for a in aliases if a)
