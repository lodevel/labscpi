# eload_scpi.py
# Brand-agnostic SCPI Electronic Load using PyVISA.
# Mirrors psu_scpi.PowerSupply structure and ergonomics.

from __future__ import annotations
from typing import Optional, Any, Dict, Type, Tuple
import logging
import re

try:
    import pyvisa  # type: ignore
except Exception:
    pyvisa = None  # installed by the user

# ---------------------------
# Exceptions (mirror psu_scpi)
# ---------------------------
class ELoadError(Exception): ...
class NotConnectedError(ELoadError): ...
class ChannelError(ELoadError): ...
class SCPIError(ELoadError): ...
class NotSupportedError(ELoadError): ...

# ---------------------------
# Utilities (mirror psu_scpi)
# ---------------------------
def require_connected(fn):
    def wrapper(self, *a, **k):
        if not self._connected:
            raise NotConnectedError("Instrument not connected. Call connect() first.")
        return fn(self, *a, **k)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper

_NUM_RE = re.compile(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')
def _parse_number(resp: str) -> float:
    m = _NUM_RE.search(resp)
    if not m:
        raise ValueError(f"no numeric value in response: {resp!r}")
    return float(m.group(0))

# ---------------------------
# Low-level session (mirror style)
# ---------------------------
class _Session:
    def __init__(self, resource, *, check_errors=True, wait_opc=True, logger=None):
        self.resource = resource
        self.check_errors = check_errors
        self.wait_opc = wait_opc
        self.logger: Optional[logging.Logger] = logger
        self._last_cmd: Optional[str] = None

    @staticmethod
    def _parse_bool(s: str) -> bool:
        return s.strip().upper() in {"1", "ON", "TRUE"}

    def write(self, cmd: str) -> None:
        self._last_cmd = cmd
        if self.logger: self.logger.debug("→ %s", cmd)
        self.resource.write(cmd)
        if self.check_errors:
            self._drain_error_queue()
        if self.wait_opc:
            self.query("*OPC?")

    def query(self, cmd: str) -> str:
        if self.logger: self.logger.debug("? %s", cmd)
        resp = self.resource.query(cmd)
        if self.logger: self.logger.debug("← %s", resp.strip())
        if self.check_errors and not cmd.strip().upper().startswith("SYST:ERR?"):
            self._drain_error_queue()
        return resp

    def _drain_error_queue(self) -> None:
        try:
            for _ in range(16):
                s = self.resource.query("SYST:ERR?").strip()
                if self.logger: self.logger.debug("ERR? %s", s)
                if not s: break
                code_str = s.split(",")[0].strip()
                try: code = int(code_str)
                except ValueError: code = 1
                if code == 0: break
                raise SCPIError(f"Instrument error after '{self._last_cmd}': {s}")
        except SCPIError:
            raise
        except Exception:
            # Some loads lack SYST:ERR?
            pass

# ---------------------------
# Adapter base and brand/model selectors
# ---------------------------
class BaseAdapter:
    brand: str = "Generic"
    def __init__(self, session: _Session, idn: str):
        self.s = session
        self.idn = idn

    @staticmethod
    def matches(idn: str) -> bool: return True  # fallback

    # Lifecycle hooks (present in psu_scpi adapters)
    def startup(self) -> None:
        """Optional startup per model (panel lock, clear, mode reset)."""
        pass
    def shutdown(self) -> None:
        """Optional shutdown per model (unlock panel, local control)."""
        pass
    def configure(self, **kwargs) -> None:
        """Optional per-model configuration before first use."""
        pass


    # helpers
    @staticmethod
    def _bstr(on: bool) -> str: return "ON" if on else "OFF"
    @staticmethod
    def _parse_bool(s: str) -> bool: return s.strip().upper() in {"1","ON","TRUE"}

    # channel select: many e-loads are single-channel; default INST:NSEL
    def _sel(self, ch: int) -> None:
        if ch < 1: raise ChannelError("Channels are 1-based and must be >= 1")
        try:
            self.s.write(f"INST:NSEL {ch}")
        except Exception:
            self.s.write(f"INST:SEL CH{ch}")

    # ---- Core API expected by facade ----
    # Modes are implied by the setter you use (CC/CV/CP).
    def set_current(self, ch: int, amps: float) -> None:
        self._sel(ch); self.s.write(f"SOUR:CURR {amps}")

    def set_voltage(self, ch: int, volts: float) -> None:
        self._sel(ch); self.s.write(f"SOUR:VOLT {volts}")

    def set_power(self, ch: int, watts: float) -> None:
        self._sel(ch); self.s.write(f"SOUR:POW {watts}")

    def set_output(self, ch: int, on: bool) -> None:
        self._sel(ch)
        # Many loads use INP; some use LOAD:STAT
        try:
            self.s.write(f"INP {self._bstr(on)}")
        except Exception:
            self.s.write(f"LOAD:STAT {self._bstr(on)}")
        # optional verify
        try:
            st = self.s.query("INP?"); ok = self._parse_bool(st)
            if ok != on: raise SCPIError("Input state mismatch")
        except Exception:
            pass

    def get_current(self, ch: int) -> float:
        self._sel(ch); return _parse_number(self.s.query("MEAS:CURR?"))

    def get_voltage(self, ch: int) -> float:
        self._sel(ch); return _parse_number(self.s.query("MEAS:VOLT?"))

    def get_power(self, ch: int) -> float:
        self._sel(ch); return _parse_number(self.s.query("MEAS:POW?"))

class BrandAdapter(BaseAdapter):
    _models: list[type["BrandAdapter"]] = []
    brand: str | None = None
    vendor_aliases: tuple[str, ...] = ()
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
            if hasattr(Cls, "matches") and Cls.matches(idn):
                chosen = getattr(Cls, "select", lambda _idn: Cls)(idn)
                return chosen  # type: ignore
        except Exception:
            continue
    return BaseAdapter

# ---------------------------
# Example brand: EA Elektro-Automatik EL series
# ---------------------------
class EAAdapter(BrandAdapter):
    brand = "EA Elektro-Automatik"
    vendor_aliases = ("ELEKTRO-AUTOMATIK", "EA-EL", "EA ")
    @staticmethod
    def matches(idn: str) -> bool:
        u = idn.upper()
        return ("ELEKTRO-AUTOMATIK" in u) or ("EA-EL" in u) or (" EA " in u)
    


    def startup(self) -> None:
            """Run after adapter is selected and before first use."""

            try:
                # Some PSUs echo setpoint via SOUR:VOLT?; if not, fall back to MEAS
                self.s.write("SYST:LOCK 1")

            except Exception:
                # Ignore if command unsupported; measurement may differ under load
                raise

            return

    def shutdown(self) -> None:
        """Run before IO is torn down."""

        try:
            # Some PSUs echo setpoint via SOUR:VOLT?; if not, fall back to MEAS
            self.s.write("SYST:LOCK 0")

        except Exception:
            # Ignore if command unsupported; measurement may differ under load
            raise

        return



@EAAdapter.register_model
class EA_EL9000Adapter(EAAdapter):
    MODEL_PATTERNS = (re.compile(r"EL9\d\d\d", re.I),)
    def _sel(self, ch: int) -> None:
        if ch != 1: raise ChannelError("Single-channel electronic load")

    def startup(self) -> None:
        self.s.wait_opc = False
        super().startup()
        

# ---------------------------
# Public façade (mirrors psu_scpi.PowerSupply)
# ---------------------------
class ElectronicLoad:
    """
    Brand-agnostic SCPI Electronic Load controller using PyVISA.

    Parameters
    ----------
    visa_address : str
        VISA resource string, e.g. "TCPIP0::...::INSTR" or "USB0::...::INSTR".
    timeout_ms : int
        VISA I/O timeout in milliseconds.
    check_errors : bool
        After each command, try SYST:ERR? and raise SCPIError if nonzero.
    wait_opc : bool
        After each write, block on *OPC? to ensure completion.
    logger : Optional[logging.Logger]
        If provided, SCPI trace is emitted at DEBUG level.
    rm : Optional[pyvisa.ResourceManager]
        Pass an existing ResourceManager if desired.
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
        self.logger = logger or logging.getLogger(__name__ + ".eload")
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
            self.rm = pyvisa.ResourceManager()
        self._resource = self.rm.open_resource(self.address)
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

    @require_connected
    def set_timeout(self, timeout_ms: int) -> None:
        self.timeout_ms = int(timeout_ms)
        assert self._resource is not None
        self._resource.timeout = self.timeout_ms

    # ----- core API (mirrors user request) -----
    @require_connected
    def set_current(self, channel: int, amps: float) -> None:
        assert self._adapter is not None
        self._adapter.set_current(channel, float(amps))

    @require_connected
    def set_voltage(self, channel: int, volts: float) -> None:
        assert self._adapter is not None
        self._adapter.set_voltage(channel, float(volts))

    @require_connected
    def set_power(self, channel: int, watts: float) -> None:
        assert self._adapter is not None
        self._adapter.set_power(channel, float(watts))

    @require_connected
    def set_output(self, channel: int, on: bool) -> None:
        assert self._adapter is not None
        self._adapter.set_output(channel, bool(on))

    @require_connected
    def get_voltage(self, channel: int) -> float:
        assert self._adapter is not None
        return self._adapter.get_voltage(channel)

    @require_connected
    def get_current(self, channel: int) -> float:
        assert self._adapter is not None
        return self._adapter.get_current(channel)

    @require_connected
    def get_power(self, channel: int) -> float:
        assert self._adapter is not None
        return self._adapter.get_power(channel)

    # ----- raw passthrough (optional) -----
    @require_connected
    def write_raw(self, cmd: str) -> None:
        assert self._session is not None
        self._session.write(cmd)

    @require_connected
    def query_raw(self, cmd: str) -> str:
        assert self._session is not None
        return self._session.query(cmd)


    @require_connected
    def selftest_interface(self, channels: tuple[int, ...] = (1,)) -> dict:
        """
        Exercise the public Electronic Load interface using the active adapter.
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

        ch = channels[0] if channels else 1

        # Core set/read
        _call("set_current", self.set_current, ch, 0.5)
        _call("set_voltage", self.set_voltage, ch, 2.0)
        _call("set_power", self.set_power, ch, 3.0)
        _call("set_output_on", self.set_output, ch, True)
        _call("get_voltage", self.get_voltage, ch)
        _call("get_current", self.get_current, ch)
        _call("get_power", self.get_power, ch)
        _call("set_output_off", self.set_output, ch, False)

        return out


# ---------------------------
# Minimal mock (optional) for unit tests
# ---------------------------
class MockLoadResource:
    def __init__(self, idn="EA-EL,EL9000,123456,1.00"):
        self.idn = idn
        self.timeout = 3000
        self.write_termination = "\n"
        self.read_termination = "\n"
        self.state: Dict[str, Any] = {
            "ch": 1,
            "mode": "CC",
            "set": {"I": 0.0, "V": 0.0, "P": 0.0},
            "meas": {"V": 0.0, "I": 0.0, "P": 0.0},
            "inp": False,
        }
    def write(self, cmd: str):
        u = cmd.strip().upper()
        if u.startswith("INST:NSEL"):
            self.state["ch"] = int(cmd.split()[-1])
        elif u.startswith("INST:SEL"):
            self.state["ch"] = int(cmd.split("CH")[-1])
        elif u.startswith("SOUR:CURR "):
            self.state["set"]["I"] = float(cmd.split()[-1]); self.state["mode"] = "CC"
        elif u.startswith("SOUR:VOLT "):
            self.state["set"]["V"] = float(cmd.split()[-1]); self.state["mode"] = "CV"
        elif u.startswith("SOUR:POW "):
            self.state["set"]["P"] = float(cmd.split()[-1]); self.state["mode"] = "CP"
        elif u.startswith("INP "):
            self.state["inp"] = u.endswith("ON")
        elif u.startswith("LOAD:STAT "):
            self.state["inp"] = u.endswith("ON")
        # naive meas echo
        self.state["meas"]["V"] = self.state["set"]["V"]
        self.state["meas"]["I"] = self.state["set"]["I"]
        self.state["meas"]["P"] = self.state["set"]["P"]
    def query(self, cmd: str) -> str:
        u = cmd.strip().upper()
        if u == "*IDN?": return self.idn + "\n"
        if u == "*OPC?": return "1\n"
        if u == "SYST:ERR?": return "0,\"No error\"\n"
        if u == "MEAS:VOLT?": return f"{self.state['meas']['V']}\n"
        if u == "MEAS:CURR?": return f"{self.state['meas']['I']}\n"
        if u == "MEAS:POW?":  return f"{self.state['meas']['P']}\n"
        if u in {"INP?", "LOAD:STAT?"}: return ("ON\n" if self.state["inp"] else "OFF\n")
        return "\n"

class MockResourceManager:
    def __init__(self, resource: Optional[MockLoadResource] = None):
        self._resource = resource or MockLoadResource()
    def open_resource(self, address: str):
        return self._resource

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    rm = MockResourceManager()
    el = ElectronicLoad("MOCK::INSTR", rm=rm, timeout_ms=1500)
    el.connect(); el.initialize()
    print("ID:", el.identity)
    el.set_current(1, 2.0)
    el.set_output(1, True)
    print("V/I/P:", el.get_voltage(1), el.get_current(1), el.get_power(1))
    el.set_power(1, 30.0)
    print("P:", el.get_power(1))
    el.set_output(1, False)
    el.close()
