"""
psu_scpi — A small, extensible SCPI power-supply library built on PyVISA.

Features
- Brand auto-detect via *IDN? and lightweight adapters (Rigol, R&S, Aim-TTi, EA Elektro-Automatik, plus a Generic SCPI fallback).
- Multi-channel by normalized 1-based integer channel indices.
- Set voltage/current, enable/disable output, read back measured V/I.
- Optional OVP/OCP, sense (local/remote) and tracking helpers where supported.
- Connection lifecycle with explicit connect(); every other public API raises NotConnectedError if not connected.
- Timeout configurable at init and via set_timeout().
- Command completion enforced with *OPC? and robust error checking via SYST:ERR?.
- Logging integration for command trace and debugging.
- Mock instrument for testing without hardware.

Usage
-------
from psu_scpi import PowerSupply

psu = PowerSupply("USB0::0x1AB1::0x0E11::DP8C123456::INSTR", timeout_ms=5000)
psu.connect()
print(psu.identity)
psu.set_voltage(1, 5.0)
psu.set_current(1, 0.5)
psu.output(1, True)
print("V,I:", psu.measure_voltage(1), psu.measure_current(1))
psu.close()

Note
----
This module aims to use widely adopted SCPI forms. Some exact commands vary by model/firmware.
Adapters can override specifics as needed.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Optional, Tuple, Dict, Type, Any
import re

try:
    import pyvisa  # type: ignore
except Exception as e:  # pragma: no cover - imported at runtime
    pyvisa = None  # Library consumer must install pyvisa


# ---------------------------
# Exceptions
# ---------------------------
class PSUError(Exception):
    """Base error for this library."""


class NotConnectedError(PSUError):
    pass


class ChannelError(PSUError):
    pass


class RangeError(PSUError):
    pass


class SCPIError(PSUError):
    pass


class NotSupportedError(PSUError):
    pass


# ---------------------------
# Utilities / Decorators
# ---------------------------

def require_connected(fn):
    def wrapper(self, *args, **kwargs):
        if not self._connected:
            raise NotConnectedError("Instrument not connected. Call connect() first.")
        return fn(self, *args, **kwargs)

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper

def with_retries(max_retries: int = 1, delay: float = 0.0):
    """Retry a SCPI command on SCPIError or I/O error."""
    import time
    def deco(fn):
        def wrapper(self, *args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(self, *args, **kwargs)
                except (SCPIError, OSError) as e:
                    last_exc = e
                    if attempt < max_retries:
                        if self.logger:
                            self.logger.debug(
                                "%s failed (%s), retry %d/%d",
                                fn.__name__, e, attempt + 1, max_retries
                            )
                        if delay:
                            time.sleep(delay)
                        continue
                    raise
            raise last_exc
        return wrapper
    return deco

_NUM_RE = re.compile(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')

def _parse_number(resp: str) -> float:
    m = _NUM_RE.search(resp)
    if not m:
        raise ValueError(f"no numeric value in response: {resp!r}")
    return float(m.group(0))

# ---------------------------
# Low-level session wrapper
# ---------------------------
@dataclasses.dataclass
class _Session:
    resource: Any
    check_errors: bool = True
    wait_opc: bool = True
    logger: Optional[logging.Logger] = None
    _last_cmd: Optional[str] = None

    def __init__(
        self, resource, check_errors=True, wait_opc=True, logger=None):
        self.resource = resource
        self.check_errors = check_errors
        self.wait_opc = wait_opc
        self.logger = logger
        self._last_cmd = None

    def write(self, cmd: str) -> None:
        self._last_cmd = cmd
        if self.logger:
            self.logger.debug("→ %s", cmd)
        self.resource.write(cmd)
        if self.check_errors:
            self._drain_error_queue()
        if self.wait_opc:
            self.query("*OPC?")
            if self.check_errors:
                self._drain_error_queue()

    def query(self, cmd: str) -> str:
        if self.logger:
            self.logger.debug("? %s", cmd)
        resp = self.resource.query(cmd)
        if self.logger:
            self.logger.debug("← %s", resp.strip())
        if self.check_errors and not cmd.strip().upper().startswith("SYST:ERR?"):
            self._drain_error_queue()
        return resp

    @staticmethod
    def _parse_bool(s: str) -> bool:
        u = s.strip().upper()
        return u in {"1", "ON", "TRUE"}

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


class BaseAdapter:
    brand: str = "Generic"


    def __init__(self, session: _Session, idn: str):
        self.s = session
        self.idn = idn



    # no-op defaults
    def configure(self, **opts) -> None:
        pass

    def startup(self) -> None:
        """Run after adapter is selected and before first use."""
        pass

    def shutdown(self) -> None:
        """Run before IO is torn down."""
        pass


    # --- detection ---
    @staticmethod
    def matches(idn: str) -> bool:
        return True  # fallback


    # --- helpers ---
    @staticmethod
    def _bstr(on: bool) -> str:
        return "ON" if on else "OFF"

    @staticmethod
    def _parse_bool(s: str) -> bool:
        u = s.strip().upper()
        return u in {"1", "ON", "TRUE"}

    def _get_master_out_state(self) -> Optional[bool]:
        # Try common master-output queries
        for q in ("OUTP:MAST?", "OUTP:GEN?", "OUTP:STAT?", "OUTP?"):
            try:
                resp = self.s.query(q)
                return self._parse_bool(resp)
            except Exception:
                continue
        return None

    def _get_ch_out_state(self, ch: int) -> Optional[bool]:
        self._sel(ch)
        for q in ("OUTP?", "OUTP:STAT?"):
            try:
                resp = self.s.query(q)
                return self._parse_bool(resp)
            except Exception:
                continue
        return None

    # --- channel handling ---
    def _sel(self, ch: int) -> None:
        if ch < 1:
            raise ChannelError("Channels are 1-based and must be >= 1")
        # Common selection pattern used by many vendors
        try:
            self.s.write(f"INST:NSEL {ch}")
        except Exception:
            # Fallback: some models use INST:SEL CHn
            self.s.write(f"INST:SEL CH{ch}")

    # --- core operations ---
    def set_voltage(self, ch: int, volts: float) -> None:
        self._sel(ch)
        self.s.write(f"SOUR:VOLT {volts}")
        # Best-effort verification: read back setpoint or measurement if available
        try:
            # Some PSUs echo setpoint via SOUR:VOLT?; if not, fall back to MEAS
            val = self.get_voltage_config(ch)
            if abs(val - volts) > 0.01:
                raise SCPIError(f"Voltage set verification failed (got {val}, want {volts})")
        except Exception:
            # Ignore if command unsupported; measurement may differ under load
            raise

    def set_current(self, ch: int, amps: float) -> None:
        self._sel(ch)
        self.s.write(f"SOUR:CURR {amps}")
        try:
            val = self.get_current_config(ch)
            if abs(val - amps) > 0.01:
                raise SCPIError(f"Current set verification failed (got {val}, want {amps})")
        except Exception:
            raise

    def set_max_current(self, ch: int) -> None:
        self._sel(ch)
        # Common command to set current limit to max rated current
        for cmd in ("SOUR:CURR:LIM MAX", "SOUR:CURR MAX", "SOUR:CURR:MAX", "SOUR:CURR:LIMIT MAX"):
            try:
                self.s.write(cmd)
                return
            except Exception:
                continue
        raise NotSupportedError("Setting max current not supported on this model")

    def output(self, ch: int, on: bool) -> None:
        # Per-channel output where possible; many units toggle selected channel
        self._sel(ch)
        try:
            self.s.write(f"OUTP {self._bstr(on)}")
        except Exception:
            # Some require channel-qualified output
            self.s.write(f"OUTP CH{ch},{self._bstr(on)}")
        # Verify state when possible
        st = self._get_ch_out_state(ch)
        if st is not None and st != on:
            raise SCPIError("Per-channel output state did not match requested value")


    def measure_voltage(self, ch: int) -> float:
        self._sel(ch)
        v = self.s.query("MEAS:VOLT?")
        return _parse_number(v)

    def measure_current(self, ch: int) -> float:
        self._sel(ch)
        a = self.s.query("MEAS:CURR?")
        return _parse_number(a)
    

    def get_voltage_config(self, ch: int) -> float:
        self._sel(ch)
        v = self.s.query("SOUR:VOLT?")
        return _parse_number(v)

    def get_current_config(self, ch: int) -> float:
        self._sel(ch)
        a = self.s.query("SOUR:CURR?")
        return _parse_number(a)


    # --- optional features (best-effort) ---
    def set_ovp(self, ch: int, volts: float, on: bool = True) -> None:
        self._sel(ch)
        self.s.write(f"SOUR:VOLT:PROT {volts}")
        self.s.write(f"SOUR:VOLT:PROT:STAT {self._bstr(on)}")

    def set_ocp(self, ch: int, amps: float, on: bool = True) -> None:
        self._sel(ch)
        self.s.write(f"SOUR:CURR:PROT {amps}")
        self.s.write(f"SOUR:CURR:PROT:STAT {self._bstr(on)}")

    def sense_remote(self, ch: int, on: bool) -> None:
        self._sel(ch)
        self.s.write(f"SENS:REM {self._bstr(on)}")

    def tracking(self, mode: str) -> None:
        """Set tracking mode: 'INDEP', 'SERIES', or 'PARALLEL' if supported."""
        self.s.write(f"OUTP:TRAC {mode}")


    # --- optional features (best-effort) ---
    def set_ovp(self, ch: int, volts: float, on: bool = True) -> None:
        self._sel(ch)
        self.s.write(f"SOUR:VOLT:PROT {volts}")
        self.s.write(f"SOUR:VOLT:PROT:STAT {'ON' if on else 'OFF'}")

    def set_ocp(self, ch: int, amps: float, on: bool = True) -> None:
        self._sel(ch)
        self.s.write(f"SOUR:CURR:PROT {amps}")
        self.s.write(f"SOUR:CURR:PROT:STAT {'ON' if on else 'OFF'}")

    def sense_remote(self, ch: int, on: bool) -> None:
        self._sel(ch)
        self.s.write(f"SENS:REM {'ON' if on else 'OFF'}")

    def tracking(self, mode: str) -> None:
        """Set tracking mode: 'INDEP', 'SERIES', or 'PARALLEL' if supported."""
        self.s.write(f"OUTP:TRAC {mode}")





class BrandAdapter(BaseAdapter):

    """Brand-level adapter with model registry and selection."""
    _models: list[type["BrandAdapter"]] = []
    brand: str | None = None
    vendor_aliases: tuple[str, ...] = ()   # <── new


    @classmethod
    def register_model(cls, model_cls): cls._models.append(model_cls); return model_cls

    @classmethod
    def select(cls, idn: str) -> type["BrandAdapter"]:
        u = idn.upper()
        for m in cls._models:
            pats = getattr(m, "MODEL_PATTERNS", ())
            if pats and any(rx.search(u) for rx in pats): return m
        for m in cls._models:
            if getattr(m, "matches", lambda _idn: False)(idn): return m
        return cls

    @classmethod
    def matches(cls, idn: str) -> bool:
        if cls is BrandAdapter: return False
        u = idn.upper()
        aliases = [cls.brand or ""] + list(cls.vendor_aliases)
        return any(a.upper() in u for a in aliases if a)



def pick_adapter(idn: str) -> type[BaseAdapter]:
    """Prefer model subclasses. Then fall back to brand.select(idn)."""
    # Collect all concrete subclasses of BrandAdapter
    candidates: list[type[BrandAdapter]] = []
    for obj in globals().values():
        if isinstance(obj, type):
            try:
                if issubclass(obj, BrandAdapter) and obj is not BrandAdapter:
                    candidates.append(obj)  # type: ignore
            except Exception:
                pass

    # Sort: most specific first (deeper MRO), then by name for stability
    candidates.sort(key=lambda c: (-len(c.mro()), c.__name__))

    # First try direct matches on the most specific classes (models first)
    for Cls in candidates:
        try:
            if hasattr(Cls, "matches") and Cls.matches(idn):  # type: ignore
                # If Cls is a model, this returns the model itself; if it's a brand, fallback to select()
                chosen = getattr(Cls, "select", lambda _idn: Cls)(idn)  # type: ignore
                return chosen  # type: ignore
        except Exception:
            continue

    return BaseAdapter




class RigolAdapter(BrandAdapter):
    brand = "RIGOL"
    vendor_aliases = ("RIGOL TECHNOLOGIES",)

    @staticmethod
    def matches(idn: str) -> bool:
        return "RIGOL" in idn.upper()

    def __init__(self, session: _Session, idn: str):
        super().__init__(session, idn)

    def _sel(self, ch: int) -> None:
        if ch < 1:
            raise ChannelError("Channels are 1-based and must be >= 1")
        # Newer DP series support INST:NSEL; prefer it.
        try:
            self.s.write(f"INST:NSEL {ch}")
        except Exception:
            self.s.write(f"INST:SEL CH{ch}")

    def output(self, ch: int, on: bool) -> None:
        # Rigol typically allows per-channel OUTP when a channel is selected
        try:
            super().output(ch, on)
        except Exception:
            # Explicit form
            self.s.write(f"OUTP CH{ch},{self._bstr(on)}")
        st = self._get_ch_out_state(ch)
        if st is not None and st != on:
            raise SCPIError("Rigol per-channel output verification failed")



class RohdeSchwarzAdapter(BrandAdapter):
    brand = "Rohde&Schwarz"
    vendor_aliases = ("R&S","R\u0026S","ROHDE")

    @staticmethod
    def matches(idn: str) -> bool:
        u = idn.upper()
        return ("ROHDE" in u) or ("R&S" in u) or ("R\u0026S" in u)

    def output(self, ch: int, on: bool) -> None:
        # R&S often requires selecting output channel, then OUTP:STAT
        self._sel(ch)
        try:
            self.s.write(f"OUTP:STAT {'ON' if on else 'OFF'}")
        except Exception:
            super().output(ch, on)


@BrandAdapter.register_model
class TTICPX200DPAdapter(BrandAdapter):
    """TTI CPX200DP model-specific adapter using simplified command set."""
    MODEL_PATTERNS = (re.compile(r"CPX200DP", re.I),)
    brand = "Aim-TTi"
    vendor_aliases = ("TTI", "Aim")

    def _sel(self, ch: int) -> None:
        # CPX200DP is dual-output (channels 1-2 only)
        # Commands include channel number directly, no selection needed
        if ch < 1 or ch > 2:
            raise ChannelError("CPX200DP supports channels 1-2 only")

    def output(self, ch: int, on: bool) -> None:
        # CPX200DP uses OP{ch} 1/0 syntax
        self._sel(ch)  # Validate channel only
        self.s.write(f"OP{ch} {1 if on else 0}")
        # Verify state
        st = self._get_ch_out_state(ch)
        if st is not None and st != on:
            raise SCPIError("Per-channel output state did not match requested value")

    def _get_ch_out_state(self, ch: int) -> Optional[bool]:
        # Query with OP{ch}? returns 1 or 0
        try:
            resp = self.s.query(f"OP{ch}?")
            return self._parse_bool(resp)
        except Exception:
            return None

    def set_voltage(self, ch: int, volts: float) -> None:
        # CPX200DP uses V{ch} {value} syntax
        self._sel(ch)  # Validate channel only
        self.s.write(f"V{ch} {volts:.3f}")

    def set_current(self, ch: int, amps: float) -> None:
        # CPX200DP uses I{ch} {value} syntax
        self._sel(ch)  # Validate channel only
        self.s.write(f"I{ch} {amps:.3f}")

    def get_voltage_config(self, ch: int) -> float:
        # Query V{ch}? returns "V{ch} {value}" format
        self._sel(ch)  # Validate channel only
        resp = self.s.query(f"V{ch}?")
        # Response format: "V1 5.00" - strip prefix and parse number
        parts = resp.strip().split()
        if len(parts) >= 2:
            return _parse_number(parts[1])
        return _parse_number(resp)

    def get_current_config(self, ch: int) -> float:
        # Query I{ch}? returns "I{ch} {value}" format
        self._sel(ch)  # Validate channel only
        resp = self.s.query(f"I{ch}?")
        # Response format: "I1 1.00" - strip prefix and parse number
        parts = resp.strip().split()
        if len(parts) >= 2:
            return _parse_number(parts[1])
        return _parse_number(resp)

    def measure_voltage(self, ch: int) -> float:
        # Query V{ch}O? returns value with unit suffix like "4.994V"
        self._sel(ch)  # Validate channel only
        resp = self.s.query(f"V{ch}O?")
        # Response format: "4.994V" - strip trailing 'V' and parse
        return _parse_number(resp.rstrip('Vv'))

    def measure_current(self, ch: int) -> float:
        # Query I{ch}O? returns value with unit suffix like "0.500A"
        self._sel(ch)  # Validate channel only
        resp = self.s.query(f"I{ch}O?")
        # Response format: "0.500A" - strip trailing 'A' and parse
        return _parse_number(resp.rstrip('Aa'))


class AimTTiAdapter(BrandAdapter):
    brand = "Aim-TTi"
    vendor_aliases = ("TTI","Aim")

    @staticmethod
    def matches(idn: str) -> bool:
        u = idn.upper()
        return ("AIM-TTI" in u) or ("TTI" in u) or ("THURLBY" in u) or ("TTi" in idn)

    def _sel(self, ch: int) -> None:
        # Many Aim-TTi supplies are single-output; multi-output models may use INST:NSEL
        try:
            self.s.write(f"INST:NSEL {ch}")
        except Exception:
            if ch != 1:
                raise NotSupportedError("This Aim-TTi model may not support multi-channel selection")

    def output(self, ch: int, on: bool) -> None:
        # Some models use OUTP n,ON
        try:
            self.s.write(f"OUTP {ch},{'ON' if on else 'OFF'}")
        except Exception:
            super().output(ch, on)


class EAAdapter(BrandAdapter):
    brand = "EA Elektro-Automatik"
    vendor_aliases = ("ELEKTRO-AUTOMATIK", "EA-PS", "EA ")

    @staticmethod
    def matches(idn: str) -> bool:
        u = idn.upper()
        return ("ELEKTRO-AUTOMATIK" in u) or ("EA-" in u) or ("EA ") in u

    def output(self, ch: int, on: bool) -> None:
        # EA often uses OUTP:STAT ON
        self._sel(ch)
        try:
            self.s.write(f"OUTP:STAT {'ON' if on else 'OFF'}")
        except Exception:
            super().output(ch, on)




@EAAdapter.register_model
class EA9080Adapter(EAAdapter):
    """Elektro-Automatik PSU model 9080 specifics."""
    MODEL_PATTERNS = (re.compile(r",9080", re.I),)
    

    def startup(self) -> None:
        """Run after adapter is selected and before first use."""
        self.s.wait_opc = False
        super().startup()
        try:
            # Some PSUs echo setpoint via SOUR:VOLT?; if not, fall back to MEAS
            self.s.write("SYST:LOCK ON")

        except Exception:
            # Ignore if command unsupported; measurement may differ under load
            raise

        return

    def shutdown(self) -> None:
        """Run before IO is torn down."""

        try:
            # Some PSUs echo setpoint via SOUR:VOLT?; if not, fall back to MEAS
            self.s.write("SYST:LOCK OFF")

        except Exception:
            # Ignore if command unsupported; measurement may differ under load
            raise

        return



    def _sel(self, ch: int) -> None:
        if ch != 1:
            raise ChannelError("Only one channel available")
        return

    def _get_ch_out_state(self, ch: int) -> Optional[bool]:
        self._sel(ch)
        for q in ("OUTP?", "OUTP:STAT?"):
            try:
                resp = self.s.query(q)
                return self._parse_bool(resp)
            except Exception:
                continue
        return None

    def output(self, ch: int, on: bool) -> None:
        # Rigol typically allows per-channel OUTP when a channel is selected
        try:
            super().output(ch, on)
        except Exception:
            # Explicit form
            self.s.write(f"OUTP {self._bstr(on)}")
        st = self._get_ch_out_state(ch)
        if st is not None and st != on:
            raise SCPIError("Rigol per-channel output verification failed")



# Registry order matters: more specific before Generic
ADAPTERS: Tuple[Type[BaseAdapter], ...] = (
    RigolAdapter,
    RohdeSchwarzAdapter,
    TTICPX200DPAdapter,  # Model-specific TTI adapter
    AimTTiAdapter,
    EAAdapter,
    BaseAdapter,  # fallback generic
)


# ---------------------------
# Public façade
# ---------------------------
def _parse_idn(idn: str) -> Dict[str, str]:
    parts = [p.strip() for p in (idn or "").split(',')]
    return {
        'vendor': parts[0] if len(parts) > 0 else '',
        'model': parts[1] if len(parts) > 1 else '',
        'serial': parts[2] if len(parts) > 2 else '',
        'firmware': parts[3] if len(parts) > 3 else '',
    }

class PowerSupply:
    """Brand-agnostic SCPI PSU controller using PyVISA.

    Parameters
    ----------
    visa_address : str
        The VISA resource string, e.g. "USB0::...::INSTR" or "TCPIP0::...::hpib,5::INSTR".
    timeout_ms : int
        VISA I/O timeout in milliseconds.
    check_errors : bool
        After every command, query SYST:ERR? and raise SCPIError on any nonzero error.
    wait_opc : bool
        After every write, block on *OPC? to ensure completion.
    logger : Optional[logging.Logger]
        If provided, verbose SCPI trace is emitted at DEBUG level.
    rm : Optional[pyvisa.ResourceManager]
        Optionally pass an existing ResourceManager (advanced use/tests).
    """

    def __init__(
        self,
        visa_address: str,
        *,
        timeout_ms: int = 3000,
        check_errors: bool = True,
        wait_opc: bool = True,
        logger: Optional[logging.Logger] = None,
        rm: Optional["pyvisa.ResourceManager"] = None,
        defer_init_io: bool = True,
    ) -> None:
        self.address = visa_address
        self.timeout_ms = int(timeout_ms)
        self.check_errors = check_errors
        self.wait_opc = wait_opc
        self.logger = logger or logging.getLogger(__name__ + ".psu")
        self.rm = rm
        self._defer_init_io = defer_init_io

        self._resource = None
        self._session: Optional[_Session] = None
        self._adapter: Optional[BaseAdapter] = None
        self._connected = False
        self.identity: Optional[str] = None

    # ----- lifecycle -----
    def connect(self) -> None:
        if pyvisa is None:
            raise ImportError("pyvisa is not installed. Please 'pip install pyvisa'.")
        if self._connected:
            return
        if self.rm is None:
            self.rm = pyvisa.ResourceManager()  # auto-detect backend
        self._resource = self.rm.open_resource(self.address)
        # Termination defaults that work well for USB/TCPIP
        try:
            self._resource.write_termination = "\n"
            self._resource.read_termination = "\n"
        except Exception:
            pass
        self._resource.timeout = self.timeout_ms

        self._session = _Session(
            resource=self._resource,
            check_errors=self.check_errors,
            wait_opc=self.wait_opc,
            logger=self.logger,
        )
        self._connected = True
        if self._defer_init_io:
            return
        self.initialize()
    def initialize(self) -> None:
        if not self._connected:
            raise NotConnectedError("Not connected; call connect() first.")
        if self._adapter is not None and self.identity is not None:
            return
        self.identity = self._session.query("*IDN?").strip()
        info = _parse_idn(self.identity)
        if self.logger:
            self.logger.debug("IDN parsed: %s", info)
        Adapter = pick_adapter(self.identity or "")
        self._adapter = Adapter(self._session, self.identity or "")
        # pass runtime options if you want toggles like autolock
        self._adapter.startup()




    def close(self) -> None:
        if not self._connected:
            return
        try:
            if self._adapter is not None:
                try:
                    self._adapter.shutdown()
                except Exception:
                    pass
            if self._resource is not None:
                self._resource.close()

        finally:
            self._resource = None
            self._session = None
            self._adapter = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ----- config/runtime -----
    @require_connected
    def set_timeout(self, timeout_ms: int) -> None:
        self.timeout_ms = int(timeout_ms)
        assert self._resource is not None
        self._resource.timeout = self.timeout_ms

    # ----- core API -----
    @require_connected
    def set_voltage(self, channel: int, volts: float) -> None:
        assert self._adapter is not None
        self._adapter.set_voltage(channel, volts)

    @require_connected
    def set_current(self, channel: int, amps: float) -> None:
        assert self._adapter is not None
        self._adapter.set_current(channel, amps)

    @require_connected
    def set_max_current(self, channel: int) -> None:
        assert self._adapter is not None
        self._adapter.set_max_current(channel)

    @require_connected
    def output(self, channel: int, on: bool) -> None:
        assert self._adapter is not None
        self._adapter.output(channel, on)

    @require_connected
    def output_all(self, on: bool) -> None:
        assert self._adapter is not None
        try:
            self._adapter.output_all(on)
        except Exception:
            # Fallback: select each of the first few channels and toggle. This is a best-effort.
            for ch in range(1, 5):
                try:
                    self._adapter.output(ch, on)
                except Exception:
                    break

    @require_connected
    def is_connected(self) -> bool:
        return self._connected

    # ----- config/runtime -----
    @require_connected
    def set_timeout(self, timeout_ms: int) -> None:
        self.timeout_ms = int(timeout_ms)
        assert self._resource is not None
        self._resource.timeout = self.timeout_ms

    # ----- core API -----
    @require_connected
    def set_voltage(self, channel: int, volts: float) -> None:
        assert self._adapter is not None
        self._adapter.set_voltage(channel, volts)

    @require_connected
    def set_current(self, channel: int, amps: float) -> None:
        assert self._adapter is not None
        self._adapter.set_current(channel, amps)

    @require_connected
    def output(self, channel: int, on: bool) -> None:
        assert self._adapter is not None
        self._adapter.output(channel, on)

    @require_connected
    def output_all(self, on: bool) -> None:
        assert self._adapter is not None
        try:
            self._adapter.output_all(on)
        except Exception:
            # Fallback: select each of the first few channels and toggle. This is a best-effort.
            for ch in range(1, 5):
                try:
                    self._adapter.output(ch, on)
                except Exception:
                    break

    @require_connected
    def measure_voltage(self, channel: int) -> float:
        assert self._adapter is not None
        return self._adapter.measure_voltage(channel)

    @require_connected
    def measure_current(self, channel: int) -> float:
        assert self._adapter is not None
        return self._adapter.measure_current(channel)

    # ----- raw passthrough -----
    @require_connected
    def write_raw(self, cmd: str) -> None:
        """Send a raw SCPI command."""
        assert self._session is not None
        self._session.write(cmd)

    @require_connected
    def query_raw(self, cmd: str) -> str:
        """Send a raw SCPI query and return the response string."""
        assert self._session is not None
        return self._session.query(cmd)

    # ----- serial helpers -----
    @require_connected
    def configure_serial(self, *, baud: Optional[int] = None, data_bits: Optional[int] = None, stop_bits: Optional[int] = None, parity: Optional[Any] = None, write_termination: Optional[str] = None, read_termination: Optional[str] = None) -> None:
        """Configure serial parameters on an ASRL resource before calling initialize()."""
        if self._resource is None:
            raise NotConnectedError("Not connected.")
        if baud is not None: self._resource.baud_rate = baud
        if data_bits is not None: self._resource.data_bits = data_bits
        if stop_bits is not None: self._resource.stop_bits = stop_bits
        if parity is not None: self._resource.parity = parity
        if write_termination is not None: self._resource.write_termination = write_termination
        if read_termination is not None: self._resource.read_termination = read_termination

    # ----- raw passthrough (no error/OPC check) -----
    @require_connected
    def write_direct(self, cmd: str) -> None:
        """Send a raw SCPI command directly to the instrument (no error/OPC checks)."""
        assert self._resource is not None
        self._resource.write(cmd)

    @require_connected
    def query_direct(self, cmd: str) -> str:
        """Send a raw SCPI query directly and return the response (no error/OPC checks)."""
        assert self._resource is not None
        return self._resource.query(cmd)

    # ----- optional features -----
    @require_connected
    def set_ovp(self, channel: int, volts: float, on: bool = True) -> None:
        assert self._adapter is not None
        self._adapter.set_ovp(channel, volts, on)

    @require_connected
    def set_ocp(self, channel: int, amps: float, on: bool = True) -> None:
        assert self._adapter is not None
        self._adapter.set_ocp(channel, amps, on)

    @require_connected
    def sense_remote(self, channel: int, on: bool) -> None:
        assert self._adapter is not None
        self._adapter.sense_remote(channel, on)

    @require_connected
    def tracking(self, mode: str) -> None:
        assert self._adapter is not None
        self._adapter.tracking(mode.upper())


    @require_connected
    def selftest_interface(self, channels: tuple[int, ...] = (1,)) -> dict:
        """
        Exercise the public PSU interface using the active adapter.
        Returns a dict: identity, adapter, calls[], features[].
        """
        from typing import Any, Dict
        assert self._adapter is not None

        out: Dict[str, Any] = {
            "identity": self.identity,
            "adapter": type(self._adapter).__name__,
            "calls": {},
            "features": {},
        }

        def _call(name: str, fn, *a, **k):
            try:
                r = fn(*a, **k)
                out["calls"][name] = {"ok": True}
                return r
            except NotSupportedError as e:
                out["calls"][name] = {"ok": False, "error": "NotSupported", "msg": str(e)}
            except Exception as e:
                out["calls"][name] = {"ok": False, "error": type(e).__name__, "msg": str(e)}

        # pick a channel to exercise
        ch = channels[0] if channels else 1

        # Core set/read
        _call("set_voltage", self.set_voltage, ch, 1.0)
        _call("set_current", self.set_current, ch, 0.1)
        _call("set_max_current", self.set_max_current, ch)
        _call("output_on", self.output, ch, True)
        _call("measure_voltage", self.measure_voltage, ch)
        _call("measure_current", self.measure_current, ch)
        _call("output_off", self.output, ch, False)

        # Optional capabilities: mark feature support
        def _feature(name: str, fn, *a, **k):
            try:
                fn(*a, **k)
                out["features"][name] = True
            except NotSupportedError:
                out["features"][name] = False
            except Exception as e:
                out["features"][name] = f"error:{type(e).__name__}"

        _feature("ovp", self.set_ovp, ch, 5.0, True)
        _feature("ocp", self.set_ocp, ch, 0.2, True)
        _feature("sense_remote", self.sense_remote, ch, False)
        _feature("tracking_series", self.tracking, "SERIES")
        _feature("tracking_parallel", self.tracking, "PARALLEL")
        _feature("tracking_indep", self.tracking, "INDEP")

        # Raw/direct passthrough sanity (non-fatal)
        _call("write_raw_noop", self.write_raw, "*OPC?")
        _call("query_raw_idn", self.query_raw, "*IDN?")

        return out

# ---------------------------
# Mock instrument for tests/CI (no hardware required)
# ---------------------------
class MockVisaResource:
    def __init__(self, idn: str = "RIGOL TECHNOLOGIES,DP832,DP8C000000,00.01.00"):
        self.idn = idn
        self.timeout = 3000
        self.write_termination = "\n"
        self.read_termination = "\n"
        self.state: Dict[str, Any] = {
            "ch": 1,
            "v": {1: 0.0, 2: 0.0, 3: 0.0},
            "i": {1: 0.0, 2: 0.0, 3: 0.0},
            "out": {1: False, 2: False, 3: False},
            "err": [],
        }

    def write(self, cmd: str):
        cmd = cmd.strip()
        if cmd.upper().startswith("INST:NSEL"):
            self.state["ch"] = int(cmd.split()[-1])
        elif cmd.upper().startswith("INST:SEL"):
            self.state["ch"] = int(cmd.split("CH")[-1])
        elif cmd.upper().startswith("SOUR:VOLT "):
            self.state["v"][self.state["ch"]] = float(cmd.split()[-1])
        elif cmd.upper().startswith("SOUR:CURR "):
            self.state["i"][self.state["ch"]] = float(cmd.split()[-1])
        elif cmd.upper().startswith("OUTP:GEN"):
            val = "ON" in cmd.upper()
            for k in self.state["out"]:
                self.state["out"][k] = val
        elif cmd.upper().startswith("OUTP CH"):
            part = cmd.split()[1]
            ch = int(part[2:].rstrip(",ONoff"))
            val = cmd.strip().upper().endswith("ON")
            self.state["out"][ch] = val
        elif cmd.upper().startswith("OUTP:STAT") or cmd.upper().startswith("OUTP"):
            val = cmd.strip().upper().endswith("ON")
            self.state["out"][self.state["ch"]] = val
        # ignore others

    def query(self, cmd: str) -> str:
        u = cmd.strip().upper()
        if u == "*IDN?":
            return self.idn + "\n"
        if u == "*OPC?":
            return "1\n"
        if u == "SYST:ERR?":
            if self.state["err"]:
                return self.state["err"].pop(0) + "\n"
            return "0,\"No error\"\n"
        if u in {"OUTP?", "OUTP:STAT?"}:
            return ("ON\n" if self.state["out"][self.state["ch"]] else "OFF\n")
        if u.startswith("OUTP? CH"):
            ch = int(u.split("CH")[-1])
            return ("ON\n" if self.state["out"].get(ch, False) else "OFF\n")
        if u == "MEAS:VOLT?":
            return f"{self.state['v'][self.state['ch']]}\n"
        if u == "MEAS:CURR?":
            return f"{self.state['i'][self.state['ch']]}\n"
        return "\n"

    def close(self):
        pass


class MockResourceManager:
    def __init__(self, resource: Optional[MockVisaResource] = None):
        self._resource = resource or MockVisaResource()

    def open_resource(self, address: str):  # address is ignored in mock
        return self._resource


# ---------------------------
# Simple self-test when run as a script
# ---------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    mock_rm = MockResourceManager()
    psu = PowerSupply("MOCK::INSTR", rm=mock_rm, timeout_ms=2000)
    psu.connect()
    psu.initialize() 
    print("ID:", psu.identity)
    psu.set_voltage(1, 5.0)
    psu.set_current(1, 0.5)
    psu.output(1, True)
    print("V=", psu.measure_voltage(1), "I=", psu.measure_current(1))
    psu.set_timeout(1000)
    psu.close()




