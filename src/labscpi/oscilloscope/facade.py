# ruff: noqa: E701, E702
r"""labscpi.oscilloscope.facade — the public ``Oscilloscope`` facade.

Moved VERBATIM from the package ``__init__`` (which keeps the selection
contract docstring, the auto-import/registration machinery, ``pick_adapter``
and the re-exports). This module is itself one of the pkgutil auto-imported
siblings, so the move costs no extra import anywhere; ``__init__`` simply
re-exports ``Oscilloscope`` from here.

Import-order note: ``from . import pick_adapter`` below runs while the
package ``__init__`` is still executing (its auto-import loop imports this
module); that works because ``__init__`` defines ``pick_adapter`` BEFORE
the loop.
"""
from __future__ import annotations

import logging
from math import floor, isfinite, log10
from typing import Optional, Tuple

from pyvisa.constants import BufferOperation

try:
    import pyvisa  # type: ignore
except Exception:
    pyvisa = None

from .base import (
    _Session,
    BaseAdapter,
    ChannelUnit,
    MathOperator,
    Measure,
    NotConnectedError,
    ScopeError,
    TriggerSweepMode,
    require_connected,
)
from . import pick_adapter

__all__ = ["Oscilloscope"]

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
        from typing import Optional  # noqa: F401 — verbatim port (shadowed module-level import)

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

                # A resource this attempt opened never stays open (the next attempt opens its own)
                if self._resource is not None:
                    try:
                        self._resource.close()
                    except Exception:
                        pass
                self._resource, self._session, self._connected = None, None, False
                # Hard-reset RM only for "resource not found"
                if getattr(e, "error_code", None) == VI_ERR_NOT_FOUND:
                    # Drop our RM reference so the next attempt re-fetches it,
                    # but do NOT close it - pyvisa caches the ResourceManager per
                    # backend, so close() tears down the SHARED RM and invalidates
                    # every OTHER instrument's open VISA session (e.g. a held PSU).
                    self.rm = None

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

    # ----- config/runtime -----
    def set_timeout(self, timeout_ms: int) -> None:
        """Retarget the VISA I/O timeout (native unit: int milliseconds) —
        mirror of the PSU/ELoad method for per-run timeout retargeting.
        Disconnected: attribute only (applied by the next ``connect()``);
        connected: pushed to the live resource too.  Adapters share the
        single ``_resource``, so this one method covers the class; the
        save/restore blocks (``query_ieee_block`` / ``wait_opc_once`` /
        ``reset`` / ``drain``) restore around whatever is applied.
        Validates FIRST, matching the serial drivers' contract (float
        coercion; bool and negatives rejected), then pushes to a live
        resource BEFORE assigning the durable attribute, so a rejected
        or failed retarget never poisons the value the next
        ``connect()`` applies."""
        if isinstance(timeout_ms, bool):
            raise ValueError(f"Not a valid timeout: {timeout_ms!r}")
        value = float(timeout_ms)   # non-numeric raises, state untouched
        if value < 0:
            raise ValueError(f"Not a valid timeout: {timeout_ms!r}")
        if self._resource is not None:
            self._resource.timeout = int(value)
        self.timeout_ms = int(value)

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
    def set_trigger(self, *, edge_src: str, level: float | None = None, slope: str | None = None) -> None:
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
        if self._resource is None:  # never opened, or closed
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


    # ---------------------------------------------------------------------
    # v2.0.0 bijective spec wrapper methods.
    # The bijective codegen emits calls to the spec method names below; these
    # are thin wrappers around the underlying implementation methods. Keeping
    # the spec names additive (not renaming the underlying methods) preserves
    # backwards compatibility with existing test code.
    # ---------------------------------------------------------------------

    @require_connected
    def wait_acquisition_complete(self, timeout_ms: int = 10000) -> None:
        """v2 spec wrapper: poll for single-acquisition completion; raise on timeout.

        Underlying: `wait_for_single_acq_complete` returns bool. v2 codegen
        relies on raise-on-timeout so the lifecycle handler catches it.
        """
        if not self.wait_for_single_acq_complete(timeout_ms=timeout_ms):
            raise RuntimeError(
                f"wait_acquisition_complete: timed out after {timeout_ms} ms"
            )

    @require_connected
    def force_acquisition_stop(self) -> None:
        """v2 spec wrapper: alias for `stop()`; force-end an in-progress acquisition."""
        self.stop()

    @require_connected
    def save_screenshot(self, filename: str, label: Optional[str] = None) -> None:
        """v2 spec wrapper: write `screenshot_png()` bytes to `filename`.

        `label` is informational (the bijective evidence record carries it
        separately); accepted here so the codegen call signature matches.
        """
        del label  # informational only; carried by the codegen evidence dict
        png = self.screenshot_png()
        with open(filename, "wb") as f:
            f.write(png)

    @require_connected
    def enable_measurement(
        self,
        ref: "int | str",
        kind: "Measure | str",
        source_channel: str,
        source_channel_2: Optional[str] = None,
    ) -> None:
        """v2 spec wrapper: associate a measurement ref with (kind, source[, source_2]).

        v2 codegen assigns ref ids to scope measurements in the procedure, a
        number (`{3}`) or a name (`{Vout}`, `{Vrail[3]}`), and later reads them
        back by ref; `3` and `"3"` are the same ref. The underlying `enable_measure`
        doesn't know about refs; we maintain a per-instance ref→(kind, src, src2)
        tuple so `read_measurement(ref)` can route to `get_measure(kind, src, src2=...)`.

        For dual-source kinds (DELAY, PHASE), pass `source_channel_2`; the
        underlying SCPI driver routes it to the adapter's `src2` parameter.
        """
        if not hasattr(self, "_v2_meas_refs"):
            self._v2_meas_refs: dict[str, tuple] = {}
        self._v2_meas_refs[str(ref)] = (kind, source_channel, source_channel_2)
        self.enable_measure(kind, src=source_channel, src2=source_channel_2)

    @require_connected
    def read_measurement(self, ref: "int | str") -> float:
        """v2 spec wrapper: read the measurement bound to `ref`.

        Looks up the (kind, source, source_2) tuple registered by
        `enable_measurement` and delegates to `get_measure`. Raises KeyError
        if `ref` was not previously enabled — codegen-side authoring bug.
        """
        if not hasattr(self, "_v2_meas_refs") or str(ref) not in self._v2_meas_refs:
            raise KeyError(
                f"read_measurement({ref}): no enable_measurement call preceded "
                f"this read. Codegen should always emit enable_measurement before "
                f"read_measurement for the same ref."
            )
        kind, src, src2 = self._v2_meas_refs[str(ref)]
        return self.get_measure(kind, src=src, src2=src2)

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

    # SCPI IEEE-488.2 "measurement not available" sentinel. Most scopes
    # return ~9.91e37 when a measurement cannot be evaluated (no trigger,
    # signal absent, instrument in STOP, etc.). Distinct from "signal
    # off-screen" — different reactions required (see autoscale_channel).
    _NOMEAS_SENTINEL_THRESH = 1e30

    @staticmethod
    def _is_no_measurement(vmax: float, vmin: float) -> bool:
        """True when EITHER reading is the IEEE-488.2 no-data sentinel
        (~9.91e37). Caller treats this as 'no signal observable' rather
        than 'signal off-screen' — zooming/offset changes don't help."""
        return abs(vmax) > Oscilloscope._NOMEAS_SENTINEL_THRESH or \
               abs(vmin) > Oscilloscope._NOMEAS_SENTINEL_THRESH

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

    def _settle_acquisition(self, *, min_s: float = 1.5) -> None:
        """Sleep long enough for the scope to complete at least two full
        sweeps at its current timebase, so a subsequent VMAX/VMIN query
        reads from a fresh trace and the measurement engine has had time
        to update its rolling stats.

        Wait = max(min_s, 24 * timebase). One sweep alone (12 × tb) is
        not enough: after a STOP→RUN transition the first sweep leaves
        the scope in trig=WAIT with stale extrema; the second sweep is
        when AUTO actually fires and the measurement engine refreshes.
        The 1.5 s floor covers (a) SCPI/TCP latency variance, (b) AC-
        coupling cap settle if the operator just toggled coupling, and
        (c) internal debouncing. Failures to read timebase fall back to
        ``min_s``."""
        import time as _t
        try:
            tb = float(self.get_time_scale())
        except Exception:
            tb = 0.0
        _t.sleep(max(min_s, 24.0 * tb))

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

        Safety changes (see internal notes):
        - Offset is reset to 0 V at the start of Phase A and after each
          scale change so the Rigol's vdiv-coupled offset auto-clamp
          doesn't drift the trace far off-screen during the hunt.
        - The IEEE-488.2 sentinel ``9.91e37`` returned by ``VMAX/VMIN``
          (signal absent / measurement not available) is handled the same
          as "off-screen" — we keep zooming out. This is correct: at
          1 mV/div a 30 V signal also reads as sentinel until enough
          zoom-out brings it on screen. The exit gate is hitting the
          scope's vdiv clamp limit (`abs(vdiv - prev) <= eps`) — at that
          point we've exhausted the 1-2-5 ladder and the entry state is
          restored. ``max_iters`` is the absolute upper bound.
        - On any failure path (clamp hit, post-Phase-A still-no-measure)
          the entry (vdiv, offset) is restored instead of leaving the
          scope at the degenerate end state.
        - Between each scale change and the next VMAX/VMIN read, we wait
          one full sweep time (12 × timebase) via ``_settle_acquisition``
          so the measurement engine reads from a settled trace rather
          than the in-flight acquisition.

        Returns: (final_v_per_div, final_offset_volts)
        """
        # Ensure channel visible
        try:
            if not self.is_channel_enabled(ch):
                self.set_channel_enabled(ch, True)
        except Exception:
            self.set_channel_enabled(ch, True)

        # Save trigger sweep mode + run state so we can put the operator's
        # setup back exactly where we found it. Autoscale FORCES AUTO sweep
        # + RUN for the duration so VMAX/VMIN reads always land on fresh
        # sweeps; without this, a stopped scope (or NORM with no trigger)
        # makes the loop operate on frozen / sentinel data and the algo
        # never converges (see autoscale_channel docstring).
        try:
            entry_sweep = self.get_trigger_sweep()
        except Exception:
            entry_sweep = None
        try:
            _status = str(self.get_trigger_status())
            entry_running = "STOP" not in _status.upper()
        except Exception:
            entry_running = True  # safe default: re-run at restore
        try:
            self.set_trigger_sweep(TriggerSweepMode.AUTO)
        except Exception:
            pass
        try:
            self.run()
        except Exception:
            pass

        try:
            return self._autoscale_channel_body(ch, max_iters=max_iters)
        finally:
            # Restore operator's pre-autoscale trigger setup. Each step
            # is independently guarded so a failed restore can't mask
            # the function's return value.
            if not entry_running:
                try: self.stop()
                except Exception: pass
            if entry_sweep is not None:
                try: self.set_trigger_sweep(entry_sweep)
                except Exception: pass

    def _autoscale_channel_body(self, ch: int, *, max_iters: int) -> Tuple[float, float]:
        """Pure autoscale algorithm — wrapped by :meth:`autoscale_channel`
        which handles the operator-visible trigger sweep / run-state
        save+restore so this body can focus on the vdiv/offset hunt.
        Always called with the scope already in AUTO + RUN."""
        # Snapshot entry state — restored on failure so the operator never
        # ends up with a worse scope than they started with.
        entry_vdiv, entry_offs = self._safe_get(ch)
        vdiv, offs = entry_vdiv, entry_offs

        # Neutralize Rigol-style "offset auto-grows with vdiv" by zeroing
        # the offset before starting the zoom-out search. The original
        # value is in (entry_vdiv, entry_offs) for restoration.
        zero_ok, offs_after_zero = self._try_set_offset(ch, 0.0)
        if zero_ok:
            offs = offs_after_zero

        # Wait one sweep before the first read so Phase A sees fresh extrema.
        self._settle_acquisition()

        # ---- Phase A: ensure visibility by zooming OUT ----
        # All three "zoom out" branches use the same exit gate: when
        # `_set_scale_resilient` reports the scale didn't change (scope
        # clamped at min/max), restore the entry state and return. That
        # naturally handles both "no signal connected" (sentinel reads
        # all the way to max vdiv → clamp hit → restore) and "signal
        # exists but is much bigger than the starting scale" (sentinel
        # reads until the right scale is reached, then a valid extrema
        # appears and the loop drops into the fit check).
        for _ in range(max_iters):
            vmax, vmin = self._get_vextrema(ch)
            need_zoom_out = (
                self._is_no_measurement(vmax, vmin) or
                not self._extrema_ok(vmax, vmin) or
                not self._fits_80(vmax, vmin, -offs, vdiv)  # SCPI offset is subtractive: screen center = -scpi_offs
            )
            if not need_zoom_out:
                break  # signal visible and fits 80%

            cand = self._snap125_up(max(vdiv * 1.5, vdiv * 2.0))
            prev = vdiv
            vdiv, offs = self._set_scale_resilient(ch, cand)
            # Re-zero offset to counter Rigol's vdiv-coupled auto-clamp.
            # `_try_set_offset` already returns the readback — reuse it
            # instead of a second `_safe_get(ch)[1]` SCPI round-trip.
            _ok, offs = self._try_set_offset(ch, 0.0)
            # Wait one sweep so the next VMAX/VMIN reads a settled trace.
            self._settle_acquisition()
            if abs(vdiv - prev) <= max(1e-12, 1e-6 * prev):
                # Scope clamped — exhausted the 1-2-5 ladder without
                # finding the signal. Restore entry state.
                self._set_scale_resilient(ch, entry_vdiv)
                self._try_set_offset(ch, entry_offs)
                _v, _o = self._safe_get(ch)
                return float(_v), float(_o)

        # Re-measure after visibility phase
        vmax, vmin = self._get_vextrema(ch)
        if self._is_no_measurement(vmax, vmin) or not self._extrema_ok(vmax, vmin):
            # Still nothing usable — restore entry state, don't leave the
            # scope at the max zoom-out.
            self._set_scale_resilient(ch, entry_vdiv)
            self._try_set_offset(ch, entry_offs)
            _v, _o = self._safe_get(ch)
            return float(_v), float(_o)

        # ---- Phase B: center to mid (rounded). If refused, keep current and finish. ----
        # SCPI offset is subtractive on Rigol (and probably other scopes): the
        # screen-center voltage is `-:CHAN:OFFS?`. To put the signal mid-point
        # at the screen center, write the NEGATIVE of mid_req via the offset
        # setter.
        mid_req = self._round_sig2(0.5 * (vmax + vmin))
        ok, offs_rb = self._try_set_offset(ch, -mid_req)
        if ok:
            offs = offs_rb  # raw SCPI value; screen center = -offs

        # If still not visible after centering, do one safety zoom-out and stop.
        if not self._fits_80(vmax, vmin, -offs, vdiv):
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

            # Re-center at mid; if refused, revert and stop. Same sign flip
            # as Phase B — write -mid_req so the screen center sits at +mid_req.
            ok, offs_rb = self._try_set_offset(ch, -mid_req)
            if ok: offs = offs_rb

            # Read fresh vmax/vmin at the new (tighter) scale.
            vmax, vmin = self._get_vextrema(ch)

            # Adaptive re-center: if the signal has drifted (e.g. AC coupling
            # cap finished settling between Phase B and now, or thermal/load
            # transient), the original mid_req may now be wrong. Recompute
            # from the latest vmax/vmin; if it moved more than 0.1 * vdiv,
            # re-center to the new mid and re-read. Threshold prevents
            # jitter on stable signals.
            if self._extrema_ok(vmax, vmin):
                new_mid = self._round_sig2(0.5 * (vmax + vmin))
                if abs(new_mid - mid_req) > 0.1 * vdiv:
                    mid_req = new_mid
                    ok2, offs_rb2 = self._try_set_offset(ch, -mid_req)
                    if ok2:
                        offs = offs_rb2
                        self._settle_acquisition()
                        vmax, vmin = self._get_vextrema(ch)

            # Check fit (screen-center = -offs, see Phase A comment).
            if not self._extrema_ok(vmax, vmin) or not self._fits_80(vmax, vmin, -offs, vdiv) or not ok:
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

        Progress is streamed to ``self.logger`` at INFO level — one
        "selftest >> <name>" line per attempted call, followed by either
        "selftest    OK   (<ms>) <name>" or "selftest    FAIL (<ms>)
        <name>: <ExcType>: <msg>". Consumers (GUIs, log files, CI) attach
        a ``logging.Handler`` to route progress wherever they need;
        the library itself stays universal — no Qt or app-specific
        coupling.
        """
        from typing import Any, Dict
        import time as _time
        assert self._adapter is not None
        log = self.logger

        out: Dict[str, Any] = {"identity": self.identity, "adapter": type(self._adapter).__name__, "calls": {}, "measurements": {}}

        def _call(name: str, fn, *a, **k) -> Any:
            log.info("selftest >> %s", name)
            t = _time.time()
            try:
                r = fn(*a, **k)
                log.info("selftest    OK   (%.0f ms) %s", (_time.time() - t) * 1000, name)
                out["calls"][name] = {"ok": True}
                return r
            except Exception as e:
                log.info("selftest    FAIL (%.0f ms) %s: %s: %s",
                         (_time.time() - t) * 1000, name, type(e).__name__, e)
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
            val = _call(  # noqa: F841 — verbatim port (result intentionally unused)
                f"get_measure[{t}]",
                self.get_measure,
                t,
                src,
                ("CHAN2" if needs_two else None),
            )


        return out
