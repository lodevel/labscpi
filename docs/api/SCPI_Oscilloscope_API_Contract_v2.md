---
doc_id: scpi-oscilloscope-api-contract-v2
title: SCPI Oscilloscope — Driver API Contract
type: api_contract
domain: bijective_procedures
language: en
version: "2.0.0"
status: current
audience: [validator, codegen, inspector, test, llm]
package: labscpi
class_name: Oscilloscope
facade_module: labscpi.oscilloscope_scpi
transports: [TCPIP, USB, GPIB]
default_timeout_ms: 5000
related:
 - bijective-procedure-spec-v2
 - procedure-json-schema-v2
 - equipment-and-inventory-v2
 - helpers-api-contract-v2
 - lifecycle-and-cleanup-v2
 - json-code-bijection-v2
description: "Specifies the public API of the Oscilloscope driver class: constructor signature, lifecycle, the codegen-called methods (single, wait_acquisition_complete, force_acquisition_stop, enable_measurement, read_measurement, save_screenshot, close), the underlying labscpi method names they wrap, logging behavior, multi-instance naming, and the v2 stability promise."
---

# SCPI Oscilloscope — Driver API Contract

This document specifies the **stable public API** of the `Oscilloscope` class shipped by the `labscpi` package, as consumed by codegen for v2.0.0 `scope.*` ops. Codegen emits Python source that imports this class and calls a fixed set of methods on instances of it. The signatures listed here are part of the v2.0.0 driver API contract: any incompatible change requires bumping the pack version (`labscpi@2.1.0` or higher) and re-pinning every procedure's `meta.labscpi_pack` field.

This is a **contract** document, not an implementation guide. The implementation lives in `labscpi.oscilloscope_scpi.Oscilloscope` and is exercised by tests under `labscpi/tests/`. The implementation MAY change freely within the v2.x series provided the contract here continues to hold.

> **Scope of this contract.** Only the methods codegen actually calls are part of the v2.0.0 API contract. The class exposes a much wider developer API (channel scaling, trigger configuration, math channels, autoscale, raw screenshot bytes, etc.) that is NOT codegen-targeted in v2.0.0. Those methods may evolve at the implementer's discretion within v2.x; this doc neither pins nor versions them.

> **Note on the wrapper layer.** The codegen-called names (`enable_measurement`, `read_measurement`, `save_screenshot`, `wait_acquisition_complete`, `force_acquisition_stop`) are the v2.0.0 codegen contract names. The underlying labscpi class as of v2.0.0 implements `enable_measure`, `get_measure`, `screenshot_png`, `wait_for_single_acq_complete`, and `stop` respectively. Where the names differ, the v2.0.0 contract names are provided either by a thin wrapper layer in `labscpi.oscilloscope_scpi` or by a forthcoming addition documented in the v2.0.x patch (whichever lands first). This doc uses the contract names; §5 cross-references the underlying labscpi method per method.

---

## 1. Module location and imports

### 1.1 Class location

The class lives under a single Python module:

```
labscpi.oscilloscope_scpi
```

Codegen always imports from this fully-qualified path:

```python
from labscpi.oscilloscope_scpi import Oscilloscope
```

The exact import line is fixed by codegen for byte-reproducibility. Generated `test.py` files MUST NOT use `as` aliasing on this import.

### 1.2 Internal module structure (informational)

The class is defined in `labscpi.oscilloscope_scpi.Oscilloscope` as one of three brand-agnostic SCPI driver façades in the `labscpi` package. The class delegates to brand-specific adapters (`RigolScope`, `RigolMSO2k4k`, `KeysightScope`, `RohdeSchwarzScope`, …) selected at `initialize()` time based on `*IDN?`.

The package `__init__` does not re-export the class.

### 1.3 Pack version coupling

The class is shipped as part of `labscpi@2.0.0`.

### 1.4 Stability promise

For the lifetime of v2.0.0 of this pack:

- No method signature listed in §2 may be removed or have its parameter list narrowed.
- No method may change its return type.
- New keyword-only parameters MAY be added with safe defaults (additive change).
- Method names listed in §2 are reserved.

Breaking signature changes are MAJOR-version events.

### 1.5 What this doc does NOT cover

- The canonical text grammar that maps procedure steps to method calls. See `SCPI_Oscilloscope_Text_Procedure_v2.md` (labscpi_pack rules 2.0.1), "Step syntax overview" and the per-op sections after it.
- The substitution rules that turn inventory entries into module-level constants. 
- The lifecycle scaffolding. 
- The per-op AST template registry.
- The `scope.measure` ⇄ unit map for `read_measurement` defaults — see `SCPI_Oscilloscope_Text_Procedure_v2.md`, "Closed list of `<english_kind>` values" (each kind's quantity) and "Units".
- The wider labscpi `Oscilloscope` developer API (channel scaling, trigger config, math channels, autoscale, raw bytes accessors, etc.). Out of scope.

---

## 2. Class API summary

The codegen-targeted public surface of `labscpi.oscilloscope_scpi.Oscilloscope` in v2.0.0:

| Entry point | Signature | Purpose |
|---|---|---|
| `__init__` | `(visa_address, *, timeout_ms=5000, check_errors=True, wait_opc=True, logger=None, rm=None, retries=10, retry_delay=0.1, defer_init_io=True)` | Construct an instance bound to one VISA resource. No I/O. |
| `connect` | `() -> None` | Open the VISA session against `visa_address`, with retry on transient failures. |
| `initialize` | `() -> None` | Identify the instrument and bind a brand adapter. |
| `single` | `() -> None` | Arm a single acquisition. Maps `scope.single`. |
| `wait_acquisition_complete` | `(*, timeout_ms: int) -> None` | Block until the most recently armed single acquisition completes; raise `TimeoutError` on timeout. Maps `scope.wait_acquisition` Branch A and the inner call of Branch B. |
| `force_acquisition_stop` | `() -> None` | Force the scope to STOP and accept whatever frame is currently on screen. Maps the recovery path of `scope.wait_acquisition` Branch B. |
| `enable_measurement` | `(ref: int, kind: str, source_channel: str, source_channel_2: str \| None = None) -> None` | Arm a measurement (kind, channel[, channel_2]) under a `{ref}` slot. Maps the first call of `scope.measure`. `source_channel_2` is required for dual-source kinds (DELAY/PHASE + edge-locked). |
| `read_measurement` | `(ref: int) -> float` | Read the most-recent value for the previously-enabled `{ref}`. Maps the second call of `scope.measure`. |
| `save_screenshot` | `(filename: str, *, label: str \| None = None) -> None` | Capture a screenshot and write it to `filename` (relative to cwd). Maps `scope.screenshot`. |
| `close` | `() -> None` | Release the VISA session. Idempotent. |
| `set_channel_scale` | `(ch: int, v_per_div: float) -> None` | Maps `scope.configure_channel.scale_v_per_div`. |
| `set_channel_offset` | `(ch: int, volts: float) -> None` | Maps `scope.configure_channel.offset_v`. |
| `set_channel_coupling` | `(ch: int, mode: str) -> None` | Maps `scope.configure_channel.coupling`. mode in {AC, DC, GND}. |
| `set_channel_enabled` | `(ch: int, on: bool) -> None` | Maps `scope.configure_channel.enabled`. |
| `set_channel_units` | `(ch: int, unit: str) -> None` | Maps `scope.configure_channel.units`. unit in {V, A}. |
| `set_probe_attenuation` | `(ch: int, factor: float) -> None` | Maps `scope.configure_channel.probe_attenuation`. |
| `set_probe_sensitivity` | `(ch: int, v_per_a: float) -> None` | Maps `scope.configure_channel.probe_sensitivity_v_per_a`. |
| `set_time_scale` | `(sec_per_div: float) -> None` | Maps `scope.configure_timebase.time_scale_s_per_div`. |
| `set_time_position` | `(sec: float) -> None` | Maps `scope.configure_timebase.time_position_s`. |
| `set_trigger` | `(*, edge_src: str, level: float \| None = None, slope: str \| None = None) -> None` | Maps `scope.configure_trigger` core. slope in driver tokens {POS, NEG, RFAL}. A `level` / `slope` left out (None) is not written; the scope keeps its own. |
| `set_trigger_sweep` | `(mode: str) -> None` | Maps `scope.configure_trigger.sweep`. mode in driver tokens {AUTO, NORM, SINGLE}. |
| `set_math_source` | `(math: int, slot: 1 \| 2, src: str) -> None` | Maps `scope.configure_math.operand_a/b`. |
| `enable_math` | `(math: int, on: bool, op: str) -> None` | Maps `scope.configure_math.operation`. op in {ADD, SUBTRACT, MULTIPLY, DIVIDE}. |
| `set_math_scale` | `(math: int, v_per_div: float) -> None` | Maps `scope.configure_math.scale_v_per_div`. |
| `set_math_offset` | `(math: int, volts: float) -> None` | Maps `scope.configure_math.offset_v`. |
| `run` | `() -> None` | Maps `scope.run`. |
| `stop` | `() -> None` | Maps `scope.stop`. |
| `force_trigger` | `() -> None` | Maps `scope.force_trigger`. |
| `enable_measure_stats` | `(on: bool) -> None` | Maps `scope.enable_measure_stats`. |
| `clear_measure_stats` | `() -> None` | Maps `scope.clear_measure_stats`. |
| `clear_measures` | `() -> None` | Maps `scope.clear_measures`. |
| `measure_stats` | `(kind: str, src: str) -> dict` | Maps `scope.measure_stats`. Returns `{MEAN, MIN, MAX, STD}` floats. |
| `clear_io` | `() -> None` | Maps `scope.clear_io`. VISA-level clear + buffer flush + error-queue drain. |
| `reset` | `(opc_timeout_ms: int = 8000) -> None` | Maps `scope.reset`. Codegen calls without args. |
| `menu_off` | `() -> None` | Maps `scope.menu_off`. |
| `autoscale_channel` | `(ch: int) -> tuple[float, float]` | Maps `scope.autoscale_channel`. Returns (final_scale, final_offset). |
| `write_raw` | `(cmd: str) -> None` | Maps `scope.write_raw`. |
| `query_raw` | `(cmd: str) -> str` | Maps `scope.query_raw`. |

Codegen does NOT emit any other method name on an `Oscilloscope` instance.

### 2.1 Method ordering and inspector recognition

The inspector keys per-op AST recognition on the method name (`Call(func=Attribute(value=Name(id_lower), attr="<method>"))`). The names above are the only ones the v2.0.0 inspector recognizes for an `Oscilloscope` instance; calls to any other method on an `Oscilloscope` instance from generated code are flagged as `JC_AST_UNRECOGNIZED` and break the bijection check.

### 2.2 Mapping to the underlying labscpi class

The labscpi `Oscilloscope` class as shipped exposes these underlying methods:

| Codegen contract name | Underlying labscpi method | Mapping notes |
|---|---|---|
| `single` | `single()` | Direct one-to-one. |
| `wait_acquisition_complete(timeout_ms=...)` | `wait_for_single_acq_complete(timeout_ms=...) -> bool` | Underlying returns `bool`; the wrapper raises `TimeoutError` on `False` so the codegen `try/except TimeoutError` block fires correctly. |
| `force_acquisition_stop()` | `stop()` | Underlying SCPI is `:STOP`; the wrapper aliases to a name that documents intent. |
| `enable_measurement(ref, kind, source_channel, source_channel_2=None)` | `enable_measure(kind, src=source_channel, src2=source_channel_2)` | Underlying ignores `ref`; the wrapper records the (kind, src, src2) tuple under the ref slot for later read. `source_channel_2` carries the dual-source second channel (DELAY/PHASE + edge-locked). |
| `read_measurement(ref)` | `get_measure(kind, src=source_channel, src2=source_channel_2) -> float` | Underlying re-issues the SCPI query each call; the wrapper resolves `ref` to the previously-recorded (kind, src, src2) tuple and delegates. |
| `save_screenshot(filename, label=None)` | `screenshot_png() -> bytes` | Underlying returns raw PNG bytes; the wrapper writes them to `filename` and ignores `label` (the label is only stored in `res.evidence`). |
| `close` | `close()` | Direct one-to-one. |
| `connect`, `initialize` | identical | Direct one-to-one. |

The wrapper layer is provided either by direct addition to `labscpi.oscilloscope_scpi` in v2.0.0 or by a thin shim in `rules_packager_base.test_helpers`; the choice is implementation-detail. Either way, the names in §2 are the contract.

---

## 3. Constructor

### 3.1 Signature

```python
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
) -> None: ...
```

### 3.2 Parameters

| Parameter | Type | Required? | Default | Notes |
|---|---|---|---|---|
| `visa_address` | str | yes | — | IVI-VISA resource string. Most scopes use `TCPIP[<board>]::<host>::INSTR`. |
| `timeout_ms` | int | no | `5000` | VISA I/O timeout per call, in milliseconds. Codegen passes the inventory-substituted `<ID>_TIMEOUT_MS` constant (default `5000`). Note: the class default is also `5000` (matching the inventory default), unlike `PowerSupply`/`ElectronicLoad` which default to `3000`. |
| `check_errors` | bool | no | `True` | Run `SYST:ERR?` after every command. Codegen does NOT pass this; takes the default. |
| `wait_opc` | bool | no | `True` | Block on `*OPC?` after every write. Codegen does NOT pass this; takes the default. |
| `logger` | `logging.Logger \| None` | no | `None` | Optional Python logger. Codegen does NOT pass this. |
| `rm` | `pyvisa.ResourceManager \| None` | no | `None` | Optional pre-built ResourceManager. Codegen does NOT pass this. |
| `retries` | int | no | `10` | Number of `connect()` retries on `VI_ERROR_RSRC_NFOUND`. Codegen does NOT pass this; takes the default. |
| `retry_delay` | float | no | `0.1` | Delay in seconds between connect retries. Codegen does NOT pass this. |
| `defer_init_io` | bool | no | `True` | When `True`, the constructor and `connect()` perform no `*IDN?` / adapter-bind I/O; the caller MUST invoke `initialize()` explicitly. The codegen-emitted bring-up always uses the default. |

The constructor signature is wider than the PSU/ELOAD constructors (it adds `retries` and `retry_delay`) because scopes are commonly mounted on lab Ethernet and transient resource-not-found errors are routine. The retry loop is in `connect()`, not in per-method calls.

### 3.3 Constructor side effects

The constructor is **pure**: it records arguments on `self`, allocates internal state slots, and returns. No VISA library is touched, no port is opened, no I/O is performed.

The constructor never raises in the codegen-emitted call site.

### 3.4 Codegen call site
codegen emits one constructor call per declared `scope` equipment id, gated by `<ID>_REMOTE`:

```python
 if SCOPE_REMOTE:
 scope = Oscilloscope(SCOPE_VISA, timeout_ms=SCOPE_TIMEOUT_MS)
 scope.connect()
 scope.initialize()
```

Codegen passes `visa_address` positionally and `timeout_ms` by keyword. No other constructor parameters appear in generated code.

---

## 4. Lifecycle

### 4.1 `connect()`

```python
def connect(self) -> None: ...
```

Opens the VISA session against `self.address`, with up to `self._retries` automatic retries on `VI_ERROR_RSRC_NFOUND`. Each retry rebuilds the ResourceManager (some pyvisa backends cache resource enumeration and need a fresh RM to see a freshly-plugged scope). The retry loop sleeps `self._retry_delay` seconds between attempts.

On `pyvisa` not installed: raises `ImportError`.
On other VISA errors that are not `VI_ERROR_RSRC_NFOUND`: propagates immediately (no retry).
After all retries exhausted: raises `ScopeError` carrying the last underlying error as `__cause__`.

When `defer_init_io=False`, `connect()` additionally calls `initialize()` before returning. The codegen-default `defer_init_io=True` keeps the two calls separate.

### 4.2 `initialize()`

```python
def initialize(self) -> None: ...
```

Issues `*IDN?`, parses the identity string, picks the appropriate brand adapter (Rigol DS/MSO, Keysight DSO/MSO, R&S RTM/RTO, …), and binds it to `self._adapter`. The brand adapter handles the SCPI dialect for that vendor (some use `:MEAS:VAVG?`, others use `:MEAS:STAT:ITEM? AVER`, etc.).

On `not self._connected`: raises `NotConnectedError`.

The call is idempotent.

After `initialize()` returns, the instrument is in the safe-default state listed row `scope`: channels declared in `equipment[id].channels` enabled at default coupling, no measurements armed.

### 4.3 `close()`

```python
def close(self) -> None: ...
```

Releases the underlying VISA resource. Idempotent: calling `close()` on an unopened or already-closed instance is a no-op.

The implementation calls `self._resource.close()` and resets the internal state slots. Unlike `PowerSupply.close()`, the scope close does NOT call an adapter-side `shutdown()` (the brand adapters don't expose one); the SCPI session simply terminates.

No exception escapes — resource close failures propagate to the caller's `try: ... except Exception: pass`.

### 4.4 Codegen lifecycle pattern

The generated `test.py` constructs and closes one `Oscilloscope` instance per declared `scope` equipment id. The pattern:

```python
scope = None # forward declaration

def run_test():
 # ...
 try:
 # ...
 if SCOPE_REMOTE:
 scope = Oscilloscope(SCOPE_VISA, timeout_ms=SCOPE_TIMEOUT_MS)
 scope.connect()
 scope.initialize()
 # ... step bodies, including scope.single(), scope.wait_acquisition_complete(...), scope.enable_measurement(...), scope.read_measurement(...), scope.save_screenshot(...) ...
 except BaseException as e:
 # ...
 finally:
 # ... (scope has no output to disable - subsection 1 is empty for scope)
 # ... close handles ...
 try:
 if SCOPE_REMOTE and scope:
 scope.close()
 except Exception:
 pass
```

The variable name `scope` is the lowercased equipment id. For `<ID> = "SCOPE_PRIMARY"`, the variable is `scope_primary`.

---

## 5. Per-method specifications

### 5.1 `single`

```python
def single(self) -> None: ...
```

Arm a single acquisition. The scope transitions to "single-armed, waiting for trigger." When the trigger fires, the scope captures one frame and stops.

**Returns** `None` on success.

**Raises:**
- `NotConnectedError` if called before `connect() + initialize()`.
- `SCPIError` if `check_errors=True` and the instrument's error queue contains a non-zero entry after the command.
- `pyvisa.errors.VisaIOError` on transport failure.

**Codegen call site**:

```python
 if SCOPE_REMOTE:
 scope.single()
 else:
 prompt("Arm SCOPE single acquisition. Type 'ok'.", res.log)
```

**Underlying labscpi.** Direct: the labscpi class exposes `single()` already. The brand adapter sends the appropriate SCPI command (`:SING` for Rigol, `:SINGle` for Keysight, etc.).

### 5.2 `wait_acquisition_complete`

```python
def wait_acquisition_complete(self, *, timeout_ms: int) -> None: ...
```

Block until the most recently armed single acquisition completes (i.e. the trigger has fired and the frame is captured). Polls the trigger-status flag every ~10 ms until either the flag clears or `timeout_ms` elapses.

| Parameter | Type | Notes |
|---|---|---|
| `timeout_ms` | int | Maximum time to wait, in milliseconds. Keyword-only. Codegen passes the JSON op's `timeout_ms` value as a literal integer. |

**Returns** `None` on success (acquisition completed within timeout).

**Raises:**
- `TimeoutError` if `timeout_ms` elapses without the acquisition completing. The Branch B codegen template catches this and falls into the `force_acquisition_stop()` recovery path.
- `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` as per §5.1.

**Codegen call site**:

```python
 if SCOPE_REMOTE:
 scope.wait_acquisition_complete(timeout_ms=10000)
 else:
 prompt("Wait for SCOPE single acquisition to complete (timeout = 10 s). Type 'ok'.", res.log)
```

**Underlying labscpi.** The labscpi class exposes `wait_for_single_acq_complete(timeout_ms=...) -> bool` which polls `get_trigger_status()` and returns `True` on completion or `False` on timeout. The wrapper layer turns the `False` return into a `TimeoutError` raise so the codegen `try/except TimeoutError` block fires correctly. Adding the wrapper is a non-breaking change to the labscpi class (the underlying method continues to exist; the wrapper is the new contract surface).

### 5.3 `force_acquisition_stop`

```python
def force_acquisition_stop(self) -> None: ...
```

Force the scope to STOP and accept whatever frame is currently captured (or partially captured). Used as the recovery path when `wait_acquisition_complete()` times out and the procedure has `force_on_timeout: "yes"`.

**Returns** `None` on success. **Raises** as per §5.1.

**Codegen call site**:

```python
 except TimeoutError:
 msg = f"STEP <n> - timeout after <TIMEOUT> ms; forcing acquisition stop"
 print(msg, flush=True)
 res.log.append(msg)
 scope.force_acquisition_stop()
 scope.wait_acquisition_complete(timeout_ms=<TIMEOUT>)
```

After `force_acquisition_stop()` the scope is in the stopped state. The retry call to `wait_acquisition_complete` is intentional: the wait flag may still need polling to drain.

**Underlying labscpi.** The labscpi class exposes `stop()` which sends `:STOP`. The wrapper layer aliases it to `force_acquisition_stop` for naming clarity at the codegen call site; the underlying SCPI is identical.

### 5.4 `enable_measurement`

```python
def enable_measurement(self, ref: int, kind: str | Measure, source_channel: str, source_channel_2: str | None = None) -> None: ...
```

Arm a measurement of `kind` on `source_channel` (plus `source_channel_2` for dual-source kinds), recording it under the `ref` slot so a subsequent `read_measurement(ref)` returns its value.

| Parameter | Type | Notes |
|---|---|---|
| `ref` | int | The `{N}` measurement id this binds. Used by `read_measurement(ref)` to identify which (kind, channel[, channel_2]) to query. |
| `kind` | str | One of the 25 SCPI tokens: `AVG`, `RMS`, `VPP`, `VMAX`, `VMIN`, `TOP`, `BASE`, `RISE`, `FALL`, `FREQ`, `PERIOD`, `PWID`, `NWID`, `PDUTY`, `NDUTY`, `PHASE`, `DELAY`, `RR_DELAY`, `RF_DELAY`, `FR_DELAY`, `FF_DELAY`, `RR_PHASE`, `RF_PHASE`, `FR_PHASE`, `FF_PHASE`. The 8 edge-locked variants use Rigol-native SCPI tokens (`RRDelay`/.../`FFPHase`) as the cross-vendor default; non-Rigol adapters inherit these names and can override in a future vendor patch if their dialect differs. First letter = source-1 edge, second = source-2 edge (R=rising, F=falling). The driver accepts these tokens directly; brand adapters translate to vendor SCPI internally. |
| `source_channel` | str | One of `CHAN1`, `CHAN2`, ..., `MATH`. The brand adapter accepts the same tokens. For dual-source kinds, this is the primary / source-1 channel. |
| `source_channel_2` | str \| None | Required when `kind` is dual-source (`DELAY`/`PHASE` or any edge-locked variant); forbidden (must be `None`) otherwise. Same enum as `source_channel`. |

**Returns** `None` on success. **Raises** as per §5.1.

**Codegen call site**:

```python
 if SCOPE_REMOTE:
 scope.enable_measurement(ref=1, kind="AVG", source_channel="CHAN1")
 res.measurements[1] = float(scope.read_measurement(ref=1))
 # Dual-source example:
 scope.enable_measurement(ref=2, kind="RR_DELAY", source_channel="CHAN1", source_channel_2="CHAN2")
```

**Underlying labscpi.** The labscpi class exposes `enable_measure(kind, src="CHAN1", src2=None)` which sends the SCPI `:MEAS:STAT:DISP <kind>,<src>[,<src2>]` (Rigol) or vendor equivalent. The wrapper layer adds the `ref` parameter and records the `(kind, src, src2)` tuple in a per-instance dict so `read_measurement(ref)` knows which to query. The `ref` is a wrapper-side concept — the SCPI command itself does not see the ref.

### 5.5 `read_measurement`

```python
def read_measurement(self, ref: int) -> float: ...
```

Read the most recent value of the measurement previously enabled under `ref`.

| Parameter | Type | Notes |
|---|---|---|
| `ref` | int | The same `ref` passed to `enable_measurement(ref, ...)` earlier. |

**Returns** the measurement value as a Python `float`. The unit is implicit (V for voltage kinds, s for time kinds, etc.) per its kind's quantity (`SCPI_Oscilloscope_Text_Procedure_v2.md`, "Closed list of `<english_kind>` values" and "Units"). The driver does not return a unit; the codegen-side `eval_verdicts` and the `expected[]` criteria are responsible for unit-correctness.

**Raises:**
- `KeyError` (or `ScopeError("No measurement enabled for ref <N>")`) if `read_measurement(ref)` is called without a prior `enable_measurement(ref, ...)`. The wrapper's exact exception type is implementation-detail; the codegen contract is "raises on missing ref, lifecycle handler catches it."
- `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` as per §5.1.

**Codegen call site**:

```python
 res.measurements[1] = float(scope.read_measurement(1))
```

The `float(...)` wrapper is intentional — the labscpi return is already a float, but the wrapper guarantees the type at the codegen-call boundary wrapper at the driver-call boundary`).

**Underlying labscpi.** The labscpi class exposes `get_measure(kind, src="CHAN1", src2=None) -> float` which sends `:MEAS:VAVG? CHAN1` (or vendor equivalent) and parses the float response. The wrapper layer takes a `ref`, looks up the recorded `(kind, src)` pair, and delegates. The wrapper re-issues the SCPI query each call (no client-side caching); this is intentional so multiple `read_measurement(ref)` calls in different steps see fresh values.

### 5.6 `save_screenshot`

```python
def save_screenshot(self, filename: str, *, label: Optional[str] = None) -> None: ...
```

Capture a screenshot from the scope and write it to `filename`.

| Parameter | Type | Notes |
|---|---|---|
| `filename` | str | Output filename. Path is relative to the test cwd (typically the test folder). The driver writes the file using the captured PNG bytes; the file is created or overwritten. |
| `label` | str \| None | Keyword-only. Optional label for evidence cross-reference. The driver does NOT embed the label in the PNG file (no metadata write); it is recorded only in the codegen-side `res.evidence.append({"kind": "screenshot", "filename": ..., "label": ...})` dict. |

**Returns** `None` on success. **Raises** as per §5.1, plus:
- `OSError` on file write failure (e.g. read-only filesystem, permission denied, disk full). Propagates uncaught — the lifecycle handler catches it and the test ends with the exception recorded.

**Codegen call sites**:

```python
 # Minimal form (no label):
 if SCOPE_REMOTE:
 scope.save_screenshot("step_16_SCOPE.png")

 # With label:
 if SCOPE_REMOTE:
 scope.save_screenshot("vout1_steady.png", label="VOUT1 steady")
```

The `label` is passed by keyword; the inspector's pattern matches both with-keyword and without-keyword forms.

**Underlying labscpi.** The labscpi class exposes `screenshot_png() -> bytes` which sends `:DISP:DATA?` (or vendor equivalent), reads the IEEE-block response, and returns the raw PNG bytes. The wrapper layer takes `(filename, label=None)`, calls `screenshot_png()`, writes the bytes to `filename`, and ignores `label` (it's stored in `res.evidence` by the codegen template, not by the driver).

The wrapper additionally calls `menu_off()` (a labscpi method that hides the on-screen menu before screenshot) so the captured image is clean. This is not a documented behavior of `save_screenshot`; it's an implementation detail. Procedures that want a different on-screen state are out of scope for v2.0.0 (handwritten test code).

---

## 6. Manual-mode handling

### 6.1 No driver-side manual mode

Like `PowerSupply` and `ElectronicLoad`, the `Oscilloscope` class has **no driver-side manual mode**. The class always opens the VISA port on `connect()` and always sends SCPI on the op methods. There is no `manual_override` constructor parameter.

Manual operation is entirely handled by codegen-side branching: when `<ID>_REMOTE = False`, codegen emits a `prompt(...)` (or `read_measurement(...)` for `scope.measure`) call instead of a driver call, and the `Oscilloscope` is never instantiated for that id.

### 6.2 Codegen contract — special cases

Most scope ops follow the standard `if/else` pattern:

```python
 if SCOPE_REMOTE:
 scope.<method>(...)
 else:
 prompt("<operator-friendly text>. Type 'ok'.", res.log)
```

Two ops have special manual-mode shapes:

**`scope.measure`**: the manual branch uses `read_measurement(...)` (NOT `prompt(...)`), so the operator can type a numeric value with optional unit:

```python
 else:
 res.measurements[<ref>] = read_measurement(
 "Enter {<ref>} <english_kind> on <SOURCE_CHANNEL>:",
 res.log,
 default_unit="V",
 )
```

**`scope.wait_acquisition`**: the manual branch text differs between Branch A (`force_on_timeout: "no"`) and Branch B (`force_on_timeout: "yes"`); Branch B's prompt explicitly tells the operator to STOP the scope manually if the acquisition does not complete.

### 6.3 Why no driver-side manual mode

Same rationale as `PowerSupply` (per `SCPI_PSU_API_Contract_v2.md` §6.3) and `ElectronicLoad` (per `SCPI_Electronic_Load_API_Contract_v2.md` §6.3): the labscpi classes were designed assuming the driver always talks to hardware; the codegen-side `if/else` branching subsumes manual-mode use cases.

---

## 7. Behavioral contracts

### 7.1 Logging

The class does NOT append per-call log lines to a per-test list. It uses Python's `logging` module: a `logger` parameter at construction (default `logging.getLogger(__name__ + ".scope")`), DEBUG-level SCPI trace.

Same rationale as `PowerSupply` (per `SCPI_PSU_API_Contract_v2.md` §7.1).

### 7.2 Error handling

- `check_errors=True` (default): every command is followed by `SYST:ERR?`; non-zero raises `SCPIError`.
- `wait_opc=True` (default): every write is followed by `*OPC?` blocking until completion.

Both flags are constructor-controlled and codegen never overrides them.

### 7.3 Connection retry

The constructor's `retries=10, retry_delay=0.1` defaults apply only to `connect()` (not to per-method calls). On `VI_ERROR_RSRC_NFOUND` during connect, the driver rebuilds the ResourceManager and retries the same address, sleeping `retry_delay` seconds between attempts.

After `connect()` succeeds, per-method calls have no automatic retry; transient SCPI failures propagate as `SCPIError` or `pyvisa.errors.VisaIOError`. The lifecycle's `except BaseException` handler catches them.

### 7.4 Thread safety

The class is **not** thread-safe. A single `Oscilloscope` instance MUST NOT be used from more than one thread concurrently.

### 7.5 Reentrancy

`connect()`, `initialize()`, `close()`, `single()`, `wait_acquisition_complete()`, `force_acquisition_stop()`, `enable_measurement()`, `read_measurement()`, `save_screenshot()` are NOT safe to call recursively from a signal handler.

### 7.6 Per-instance measurement registry

The wrapper layer (per §2.2) maintains a per-instance dict mapping `ref → (kind, source_channel, source_channel_2)`. The dict is populated by `enable_measurement(ref, kind, source_channel, source_channel_2=None)` and queried by `read_measurement(ref)`. The dict is per-instance: if a procedure has two scope ids, each has its own registry. For single-source kinds `source_channel_2` is `None`; for dual-source kinds it carries the second channel.

The dict is NOT exposed publicly; callers cannot enumerate or mutate it. It is reset on `close()` (so a re-connect after close requires re-arming all measurements).

---

## 8. Multi-instance naming

When a procedure declares two or more `scope` equipment ids, codegen emits one `Oscilloscope` instance per id, with module-level constants and local variable names.

### 8.1 Worked example

For:

```
## Equipment
SCOPE_PRIMARY : scope channels=[1,2]
SCOPE_AUX : scope channels=[1]
```

with inventory:

```json
{
 "SCOPE_PRIMARY": {"type": "scope", "visa": "TCPIP0::192.168.1.42::INSTR", "timeout_ms": 5000, "remote": true},
 "SCOPE_AUX": {"type": "scope", "visa": "TCPIP0::192.168.1.43::INSTR", "timeout_ms": 5000, "remote": true}
}
```

codegen emits the constants:

```python
SCOPE_PRIMARY_REMOTE = True
SCOPE_PRIMARY_VISA = "TCPIP0::192.168.1.42::INSTR"
SCOPE_PRIMARY_TIMEOUT_MS = 5000

SCOPE_AUX_REMOTE = True
SCOPE_AUX_VISA = "TCPIP0::192.168.1.43::INSTR"
SCOPE_AUX_TIMEOUT_MS = 5000
```

(Note: no `<ID>_CHANNEL` constant for scopes; the channel list comes from the equipment record's `channels` array, not from inventory —.)

And the bring-up:

```python
if SCOPE_PRIMARY_REMOTE:
 scope_primary = Oscilloscope(SCOPE_PRIMARY_VISA, timeout_ms=SCOPE_PRIMARY_TIMEOUT_MS)
 scope_primary.connect()
 scope_primary.initialize()
if SCOPE_AUX_REMOTE:
 scope_aux = Oscilloscope(SCOPE_AUX_VISA, timeout_ms=SCOPE_AUX_TIMEOUT_MS)
 scope_aux.connect()
 scope_aux.initialize()
```

The two instances are independent: separate VISA sessions, separate brand adapters, separate measurement registries.

### 8.2 Local variable name derivation

| Equipment id | Local variable |
|---|---|
| `SCOPE` | `scope` |
| `SCOPE_PRIMARY` | `scope_primary` |
| `SCOPE_AUX` | `scope_aux` |

The derivation is a pure `<id>.lower()`.

### 8.3 No output-state tracker

Unlike `PowerSupply`/`ElectronicLoad`, the `Oscilloscope` class has no enable/disable verb that codegen emits an `<id_lower>_output_on` tracker for. The cleanup block's output-disable subsection emits nothing for scopes; the manual-prompt subsection emits nothing; only the close-handles subsection runs `scope.close()`.

Future spec revisions may add a `<id>_armed` tracker if a scope-disarm cleanup verb becomes safety-relevant. Not in v2.0.0.

---

## 9. Error semantics summary

| Method | Raises | Notes |
|---|---|---|
| `__init__` | none | Pure constructor; never raises. |
| `connect` | `ImportError`, `ScopeError` (after retries), `pyvisa.errors.VisaIOError` (non-NFOUND) | Up to `retries` automatic retries on NFOUND. |
| `initialize` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | |
| `close` | none | Failures swallowed and ignored. |
| `single` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | |
| `wait_acquisition_complete` | `TimeoutError`, `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | `TimeoutError` is the recovery trigger for Branch B. |
| `force_acquisition_stop` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | |
| `enable_measurement` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | |
| `read_measurement` | `KeyError` or `ScopeError` (missing ref), `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | |
| `save_screenshot` | `OSError` (file write), `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | |

The lifecycle's `except BaseException` handler catches every exception type listed above. The Branch B template for `scope.wait_acquisition` is the only place codegen emits a per-call `try/except` around a driver method — and it catches only `TimeoutError`, leaving other exceptions to the lifecycle handler.

---

## 10. Bijection notes

### 10.1 The driver is on the code-side only

The methods specified here appear only in the generated `test.py`. Canonical text and JSON never name `Oscilloscope` or its methods.

### 10.2 Inspector recognition

The inspector recognizes scope ops by AST shape:

- `scope.single`: `If(test=Name("<ID>_REMOTE"))` wrapping `Call(func=Attribute(value=Name("<id_lower>"), attr="single"), args=[])`.
- `scope.wait_acquisition` Branch A: `If(...)` wrapping `Call(...attr="wait_acquisition_complete", keywords=[keyword("timeout_ms", Constant(<timeout>))])`.
- `scope.wait_acquisition` Branch B: `If(...)` wrapping a `Try` node with the §5.2 shape predicates.
- `scope.measure`: `If(...)` wrapping a two-statement body: `Call(...attr="enable_measurement", keywords=[ref=<ref>, kind="<KIND>", source_channel="<SRC>" (+ source_channel_2="<SRC2>" for dual-source kinds)])` then `Assign(targets=[Subscript(...)], value=Call(Name("float"), [Call(...attr="read_measurement", keywords=[ref=<ref>])]))`.
- `scope.screenshot`: `If(...)` wrapping `Call(...attr="save_screenshot", args=[Constant("<filename>")], keywords=[...])` followed by `Expr(Call(...attr="append", args=[Dict(...)]))` for the evidence.

The inspector reads `<ID>` from the if-test, `<id_lower>` from the call attribute owner, and the per-op fields from the call args/keywords. From these it reconstructs the JSON op.

### 10.3 Method-name ABI

Renaming any of the names in §2 is a v3.0.0 event because:

1. The inspector AST patterns reference the names as string literals in `code_inspector.py`.
2. The codegen AST templates reference the names as `Attribute(attr=...)` strings.

The wrapper-vs-underlying distinction (§2.2) is internal: the wrapper names are the v2.0.0 ABI; the underlying labscpi method names may evolve within the wrapper as long as the wrapper continues to expose §2's contract names with §5's signatures.

### 10.4 What about the wider class API?

Methods like `set_channel_scale`, `set_time_scale`, `set_trigger`, `set_channel_coupling`, `enable_math`, `autoscale_channel`, `clear_io` exist on the class but are NOT codegen-targeted in v2.0.0. They remain available to handwritten test code; only the four ops in §2 are codegen-bound and participate in the JSON ⇄ code bijection.

---

## 12. Cross-references

- `SCPI_Oscilloscope_Text_Procedure_v2.md` (labscpi_pack rules 2.0.1) — the authoring rules for the canonical text whose steps codegen turns into these method calls; its closed list of measurement kinds with their quantities, and its units.
- Sibling: `SCPI_PSU_API_Contract_v2.md` — the parallel API contract for the `psu` type.
- Sibling: `SCPI_Electronic_Load_API_Contract_v2.md` — the parallel API contract for the `eload` type.
- Legacy: `labscpi_SCOPE_CODEGEN_client_usage.md` v1.x — the predecessor doc this one replaces.

---

## 13. Conformance summary

A `labscpi` installation conforms to this contract iff:

1. The class `labscpi.oscilloscope_scpi.Oscilloscope` exists and is importable.
2. Its constructor signature matches §3.1 exactly (positional `visa_address`, keyword-only `timeout_ms`, `check_errors`, `wait_opc`, `logger`, `rm`, `retries`, `retry_delay`, `defer_init_io` with the documented defaults).
3. Each method in §2 is exposed at the documented name with the documented signature (whether implemented directly on the class or via a thin wrapper layer per §2.2).
4. `connect()` opens the VISA session with up to `retries` retries on `VI_ERROR_RSRC_NFOUND`; `initialize()` issues `*IDN?` and binds a brand adapter; `close()` releases the session (idempotently and infallibly).
5. `wait_acquisition_complete(timeout_ms=...)` raises `TimeoutError` on timeout (so the Branch B codegen template's `try/except TimeoutError` fires correctly).
6. `enable_measurement(ref, kind, source_channel, source_channel_2=None)` records the (kind, channel, channel_2) tuple under `ref`; `read_measurement(ref)` retrieves the value for the previously-recorded tuple.
7. `save_screenshot(filename, label=None)` writes the captured PNG to `filename` and ignores `label` (the label is recorded in `res.evidence` by the codegen template, not by the driver).
8. The constructor is pure (no I/O when `defer_init_io=True`).
9. The class does not introduce a driver-side `manual_override` parameter (per §6.1).
10. Method names listed in §2 are not shadowed by future v2.x.y additions.

The validator does not directly check (1)–(10); they are enforced by the pack's own unit tests under `labscpi/tests/`. A procedure pinned to `labscpi@2.0.0` whose installed wheel fails any of the above is a packaging bug, not a procedure bug.
