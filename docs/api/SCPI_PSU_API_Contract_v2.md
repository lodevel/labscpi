---
doc_id: scpi-psu-api-contract-v2
title: SCPI PSU — Driver API Contract
type: api_contract
domain: bijective_procedures
language: en
version: "2.0.0"
status: current
audience: [validator, codegen, inspector, test, llm]
package: labscpi
class_name: PowerSupply
facade_module: labscpi.psu_scpi
transports: [ASRL, USB, TCPIP, GPIB]
default_timeout_ms: 5000
related:
 - bijective-procedure-spec-v2
 - procedure-json-schema-v2
 - equipment-and-inventory-v2
 - helpers-api-contract-v2
 - lifecycle-and-cleanup-v2
 - json-code-bijection-v2
description: "Specifies the public API of the PowerSupply driver class: constructor signature, lifecycle, the four codegen-called methods (set_voltage, set_current, output, close), logging behavior, multi-instance naming, and the v2 stability promise."
---

# SCPI PSU — Driver API Contract

This document specifies the **stable public API** of the `PowerSupply` class shipped by the `labscpi` package. Codegen emits Python source that imports this class and calls a fixed set of methods on instances of it. The signatures listed here are part of the v2.0.0 driver API contract: any incompatible change requires bumping the pack version (`labscpi@2.1.0` or higher) and re-pinning every procedure's `meta.labscpi_pack` field.

This is a **contract** document, not an implementation guide. The implementation lives in `labscpi.psu_scpi.PowerSupply` and is exercised by tests under `labscpi/tests/`. The implementation MAY change freely within the v2.x series provided the contract here continues to hold.

> **Scope of this contract.** Only the methods codegen actually calls are part of the v2.0.0 API contract. The class exposes additional methods (e.g. `measure_voltage`, `measure_current`, `set_ovp`, `tracking`, `selftest_interface`, `write_raw`) that are part of the wider labscpi developer API but are NOT codegen-targeted in v2.0.0. Those methods may evolve at the implementer's discretion within v2.x; this doc neither pins nor versions them.

---

## 1. Module location and imports

### 1.1 Class location

The class lives under a single Python module:

```
labscpi.psu_scpi
```

Codegen always imports from this fully-qualified path:

```python
from labscpi.psu_scpi import PowerSupply
```

The exact import line is fixed by codegen for byte-reproducibility. Generated `test.py` files MUST NOT use `as` aliasing on this import; the inspector recognizes the bare name `PowerSupply` in the `Call(func=Name(...))` AST shape, and any alias breaks the recognizer.

### 1.2 Internal module structure (informational)

The class is defined in `labscpi.psu_scpi` and is one of three brand-agnostic SCPI driver façades in the `labscpi` package (the siblings are `labscpi.eload_scpi.ElectronicLoad` and `labscpi.oscilloscope_scpi.Oscilloscope`). The package `__init__` does not re-export the class; callers MUST use the fully-qualified module path.

This is intentional: the codegen-emitted `test.py` lists three import lines — one per labscpi class actually used — so the inspector skip-list can drop unused-class imports automatically.

### 1.3 Pack version coupling

The class is shipped as part of `labscpi@2.0.0`.

### 1.4 Stability promise

For the lifetime of v2.0.0 of this pack:

- No method signature listed in §2 may be removed or have its parameter list narrowed.
- No method may change its return type.
- New keyword-only parameters MAY be added with safe defaults (additive change), provided codegen continues to emit calls that omit the new parameter. Any such addition requires an entry in the pack changelog and bumps the pack PATCH version.
- Method names listed in §2 are reserved: a future v2.x.y MAY add new methods on the class, but MUST NOT shadow names defined in §2.

Breaking signature changes (parameter rename, removal, type change, return-type change) are MAJOR-version events that require a new doc and a new schema.

### 1.5 What this doc does NOT cover

- The canonical text grammar that maps procedure steps to method calls. See `SCPI_PSU_Text_Procedure_v2.md` (labscpi_pack rules 2.0.1), "Verbs and forms".
- The substitution rules that turn inventory entries into module-level constants (`<ID>_VISA`, `<ID>_CHANNEL`, `<ID>_TIMEOUT_MS`, `<ID>_REMOTE`). 
- The lifecycle scaffolding (where the PSU is constructed in the `try:` block, where `close()` is called in `finally:`). 
- The per-op AST template registry. 
- The wider labscpi developer API: `measure_voltage`, `measure_current`, `set_ovp`, `set_ocp`, `tracking`, `set_max_current`, `selftest_interface`, `write_raw`, `query_raw`, `configure_serial`, etc. These are out of scope.

---

## 2. Class API summary

The codegen-targeted public surface of `labscpi.psu_scpi.PowerSupply` in v2.0.0 (-PSU LIFT) is sixteen entry points: four lifecycle methods plus twelve operator-facing ops.

| Entry point | Signature | Purpose |
|---|---|---|
| `__init__` | `(visa_address, *, timeout_ms=3000, check_errors=True, wait_opc=True, logger=None, rm=None, defer_init_io=True)` | Construct an instance bound to one VISA resource. No I/O. |
| `connect` | `() -> None` | Open the VISA session against `visa_address`. |
| `initialize` | `() -> None` | Identify the instrument and bind a brand adapter. |
| `set_voltage` | `(channel: int, volts: float) -> None` | Set the channel's voltage setpoint. |
| `set_current` | `(channel: int, amps: float) -> None` | Set the channel's current limit. |
| `set_max_current` | `(channel: int) -> None` | Clamp the channel current to the model's rated max. |
| `output` | `(channel: int, on: bool) -> None` | Enable or disable the channel's output. |
| `measure_voltage` | `(channel: int) -> float` | Read the channel's measured voltage (V). |
| `measure_current` | `(channel: int) -> float` | Read the channel's measured current (A). |
| `set_ovp` | `(channel: int, volts: float, on: bool = True) -> None` | Set OVP threshold; codegen omits the third arg, accepting the default. |
| `set_ocp` | `(channel: int, amps: float, on: bool = True) -> None` | Set OCP threshold; codegen omits the third arg. |
| `sense_remote` | `(channel: int, on: bool) -> None` | Configure 4-wire (remote) sensing. |
| `tracking` | `(mode: str) -> None` | Set channel-tracking mode (`"INDEP"`, `"SERIES"`, `"PARALLEL"`). |
| `write_raw` | `(cmd: str) -> None` | Send a raw SCPI command. |
| `query_raw` | `(cmd: str) -> str` | Send a raw SCPI query and return the response string. |
| `close` | `() -> None` | Release the VISA session. Idempotent. |

The constructor + the three lifecycle entry points (`connect`, `initialize`, `close`) plus the twelve op methods are the sixteen names codegen emits in generated `test.py` for any procedure that uses a `psu` equipment entry. Codegen does NOT emit any other method name on a `PowerSupply` instance.

### 2.1 Method ordering and inspector recognition

The inspector keys per-op AST recognition on the method name (`Call(func=Attribute(value=Name(id_lower), attr="<method>"))`). The sixteen names above are the only ones the v2.0.0 inspector recognizes for a `PowerSupply` instance; calls to any other method on a `PowerSupply` instance from generated code are flagged as `JC_AST_UNRECOGNIZED` and break the bijection check.

This is by design: handwritten test code MAY call any method on the class, but generated `test.py` MUST stick to the contracted names so the bijection inspector can round-trip the file back to JSON.

### 2.2 Demoted / infrastructural methods (NOT codegen-targeted)

The class also exposes additional methods that are part of the wider labscpi developer API but are NOT codegen-targeted in v2.0.0:

| Method | Decision | Reason |
|---|---|---|
| `set_timeout` | DEMOTE | VISA timeout is a transport-layer concern; covered by `<ID>_TIMEOUT_MS` constant. |
| `configure_serial` | DEMOTE | Pre-connect ASRL config; bench-wiring concern. |
| `write_direct` / `query_direct` | DEMOTE | Raw passthrough without error/OPC checks; debugging only. |
| `output_all` | SUBSTITUTE | Decomposes into a `@FOR ch in [...]: <n>. Turn <DEV> CH${ch} ON.` macro over `psu.output`. |
| `is_connected` | INFRA | Connection-state property; not procedure-author surface. |
| `selftest_interface` | DEMOTE | Diagnostic adapter probe. |

These methods may evolve at the implementer's discretion within v2.x; this doc does not pin their signatures.

---

## 3. Constructor

### 3.1 Signature

```python
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
) -> None: ...
```

### 3.2 Parameters

| Parameter | Type | Required? | Default | Notes |
|---|---|---|---|---|
| `visa_address` | str | yes | — | IVI-VISA resource string. Examples: `"ASRL3::INSTR"`, `"TCPIP0::192.168.1.10::INSTR"`. The constructor records the value but does not validate it; the address is exercised at `connect()` time. |
| `timeout_ms` | int | no | `3000` | VISA I/O timeout per call, in milliseconds. Codegen passes the inventory-substituted `<ID>_TIMEOUT_MS` constant (default `5000`) — note the difference: the class default is `3000` but codegen always passes an explicit value. |
| `check_errors` | bool | no | `True` | Run `SYST:ERR?` after every command and raise `SCPIError` on non-zero. Codegen does NOT pass this; it takes the default. |
| `wait_opc` | bool | no | `True` | Block on `*OPC?` after every write. Codegen does NOT pass this; it takes the default. |
| `logger` | `logging.Logger \| None` | no | `None` | Optional Python logger; emits SCPI trace at DEBUG level. Codegen does NOT pass this. |
| `rm` | `pyvisa.ResourceManager \| None` | no | `None` | Optional pre-built ResourceManager (advanced use). Codegen does NOT pass this; the driver auto-builds one on `connect()`. |
| `defer_init_io` | bool | no | `True` | When `True`, the constructor and `connect()` perform no `*IDN?` / adapter-bind I/O; the caller MUST invoke `initialize()` explicitly to identify the instrument. The codegen-emitted bring-up calls `connect()` then `initialize()`, so the default is the right choice. |

### 3.3 Constructor side effects

The constructor is **pure**: it records arguments on `self`, allocates internal state slots (`self._resource = None`, `self._session = None`, etc.), and returns. No VISA library is touched, no port is opened, no I/O is performed. This is the `defer_init_io=True` contract.

The constructor never raises in the codegen-emitted call site. A bad `visa_address` (e.g. malformed) still constructs successfully; the failure surfaces at `connect()`.

### 3.4 Codegen call site
codegen emits one constructor call per declared `psu` equipment id, gated by `<ID>_REMOTE`:

```python
 if PSU1_REMOTE:
 psu1 = PowerSupply(PSU1_VISA, timeout_ms=PSU1_TIMEOUT_MS)
 psu1.connect()
 psu1.initialize()
```

Codegen passes `visa_address` positionally and `timeout_ms` by keyword. No other constructor parameters appear in generated code.

---

## 4. Lifecycle

### 4.1 `connect()`

```python
def connect(self) -> None: ...
```

Opens the VISA session against `self.address`. On entry: `self._connected == False`. On normal exit: `self._connected == True`, `self._resource` is a live `pyvisa.Resource`, `self._session` is a configured `_Session`.

The call is idempotent on a connected instance (returns immediately). On `pyvisa` not installed it raises `ImportError`. On address resolution / port-busy / permission-denied, the underlying `pyvisa` exception propagates (typically `pyvisa.errors.VisaIOError`).

When `defer_init_io=False`, `connect()` additionally calls `initialize()` before returning. The codegen-default `defer_init_io=True` keeps the two calls separate so the bring-up block reads cleanly as connect-then-init.

### 4.2 `initialize()`

```python
def initialize(self) -> None: ...
```

Issues `*IDN?`, parses the identity string into `(vendor, model, serial, firmware)`, picks the appropriate brand adapter (Rigol DP800, Keysight E36*, etc.), and binds it to `self._adapter`. Calls `self._adapter.startup()` to apply the brand-specific safe-default state (output OFF, voltage 0, current limit at the adapter's default).

On `not self._connected`: raises `NotConnectedError` (defined in `labscpi.psu_scpi` as a subclass of `ScopeError` for parallel structure with the scope class — naming is historical; the runtime semantics are the same regardless of subclass tree).

The call is idempotent: `initialize()` on an already-initialized instance returns immediately. The brand-adapter binding is permanent for the session.

After `initialize()` returns, the instrument is in the safe-default state listed row `psu`: output OFF, voltage 0, current limit at adapter default.

### 4.3 `close()`

```python
def close(self) -> None: ...
```

Releases the underlying VISA resource. Idempotent: calling `close()` on an unopened or already-closed instance is a no-op (returns immediately on `not self._connected`).

The implementation calls `self._adapter.shutdown()` (swallowed on failure), then `self._resource.close()`, then resets the internal state slots to their pre-`connect()` values. No exception escapes — adapter shutdown failures are caught and ignored, resource close failures propagate to the caller's `try: ... except Exception: pass`.

### 4.4 Codegen lifecycle pattern

The generated `test.py` constructs and closes one `PowerSupply` instance per declared `psu` equipment id. The pattern:

```python
psu1 = None # forward declaration in run_test()

def run_test():
 # ...
 try:
 # ...
 if PSU1_REMOTE:
 psu1 = PowerSupply(PSU1_VISA, timeout_ms=PSU1_TIMEOUT_MS)
 psu1.connect()
 psu1.initialize()
 # ... step bodies, including psu1.set_voltage(...), psu1.output(...) ...
 except BaseException as e:
 # ...
 finally:
 # ... output-disable safety ...
 try:
 if PSU1_REMOTE and psu1 and psu1_output_on:
 psu1.output(PSU1_CHANNEL, False)
 except Exception:
 pass
 # ... manual-mode safe-state prompts ...
 # ... close handles ...
 try:
 if PSU1_REMOTE and psu1:
 psu1.close()
 except Exception:
 pass
```

The variable name `psu1` is the lowercased equipment id with all underscores preserved. For `<ID> = "PSU1_CH3"`, the variable is `psu1_ch3`.

---

## 5. Per-method specifications

### 5.1 `set_voltage`

```python
def set_voltage(self, channel: int, volts: float) -> None: ...
```

Set the specified channel's voltage setpoint.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. Codegen passes `<ID>_CHANNEL` (substituted from inventory). |
| `volts` | float | Voltage setpoint in volts (SI base). Codegen passes `float(<volts>)` where `<volts>` is the literal from the JSON op. |

**Returns** `None` on success.

**Raises:**
- `NotConnectedError` if called before `connect() + initialize()`.
- `SCPIError` if `check_errors=True` (the constructor default) and the instrument's error queue contains a non-zero entry after the command.
- `pyvisa.errors.VisaIOError` on transport failure (port closed mid-write, read timeout, etc.). All exceptions propagate uncaught — the lifecycle handler catches them.

**Codegen call site**:

```python
 if PSU1_REMOTE:
 psu1.set_voltage(PSU1_CHANNEL, float(28.0))
```

The `float(...)` wrapper is intentional and part of the inspector pattern wrapper at the driver-call boundary`). It guarantees a float-typed argument regardless of the JSON literal's integer/float distinction.

**Behavior notes:**
- The driver delegates to the bound brand adapter's `set_voltage(channel, volts)`. The brand adapter is responsible for the SCPI command sequence (`INST:NSEL <ch>` or `INST:SEL CH<ch>` followed by `VOLT <volts>` or vendor-specific equivalent).
- Range clipping is brand-dependent. Out-of-range values may raise `SCPIError` (Rigol on `Settings out of range`), be silently clipped (some Keysight models), or saturate at the model's max. The driver layer does not impose a uniform behavior; the bench owner is responsible for matching procedure values to the installed PSU's range.

### 5.2 `set_current`

```python
def set_current(self, channel: int, amps: float) -> None: ...
```

Set the specified channel's current limit.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. |
| `amps` | float | Current limit in amperes (SI base). |

**Returns** `None` on success. **Raises** as per §5.1.

**Codegen call site**:

```python
 if PSU1_REMOTE:
 psu1.set_current(PSU1_CHANNEL, float(15.0))
```

The semantics are "set the limit at which the supply transitions from CV to CC". The supply remains in CV mode (sourcing the voltage setpoint) until the load draws `amps`; then it transitions to CC mode (sourcing `amps`, lowering voltage as needed).

### 5.3 `output`

```python
def output(self, channel: int, on: bool) -> None: ...
```

Enable or disable the channel's output.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. |
| `on` | bool | `True` enables output; `False` disables. |

**Returns** `None` on success. **Raises** as per §5.1.

**Codegen call site**:

```python
 if PSU1_REMOTE:
 psu1.output(PSU1_CHANNEL, True)
 else:
 prompt("Turn PSU1 CH1 ON. Type 'ok'.", res.log)
 psu1_output_on = True
```

The trailing `psu1_output_on = True` is an output-state tracker emitted by codegen, not part of the driver call. The driver does not maintain its own per-channel on/off state visible to the caller; the tracker is in the generated test, not in the driver.

The driver delegates to the bound brand adapter's `output(channel, on)`, which sends the appropriate `OUTP ON` / `OUTP OFF` (or vendor-specific) sequence.

---

## 6. Manual-mode handling

### 6.1 No driver-side manual mode

Unlike a driver that takes a manual-override flag, the `PowerSupply` class has **no driver-side manual mode**. The class always opens the VISA port on `connect()` and always sends SCPI on `set_voltage()`/`set_current()`/`output()`. There is no `manual_override` constructor parameter.

Manual operation is entirely handled by codegen-side branching: when `<ID>_REMOTE = False`, codegen emits a `prompt(...)` call instead of a driver call, and the `PowerSupply` is never instantiated for that id. The lifecycle bring-up block guards every constructor call with `if <ID>_REMOTE:`.

### 6.2 Codegen contract

The pattern is fixed:

```python
 if PSU1_REMOTE:
 psu1.set_voltage(PSU1_CHANNEL, float(28.0))
 else:
 prompt("Set PSU1 CH1 to 28 V. Type 'ok'.", res.log)
```

When `PSU1_REMOTE = False`, the `psu1` variable is `None` (never bound by the bring-up block), and the `else:` branch fires for every `psu1.*` call site in the test. The cleanup block's output-disable subsection also guards on `PSU1_REMOTE` and emits a manual safe-state prompt instead.

### 6.3 Why no driver-side manual mode

The labscpi PSU class predates the bijective codegen by years and was designed assuming the driver always talks to hardware. The codegen-side `if/else` branching subsumes the use-cases that a driver-side manual mode would serve, with the added benefit that the operator-friendly prompt text is part of `test.py` (operator-readable, version-controlled with the procedure) rather than a static string in the driver's Python code.

This is a deliberate design difference from a driver with a `manual_override` flag: such a flag exists for non-codegen callers (REPL, alternate test harnesses) that don't emit the `prompt(...)` branch themselves. The labscpi classes have no such non-codegen use case in v2.0.0, so the simpler "always-remote, codegen branches" model fits.

---

## 7. Behavioral contracts

### 7.1 Logging

The class does NOT append per-call log lines to a per-test list (as a driver taking a `log_list` parameter would). It uses Python's `logging` module: a `logger` parameter at construction (default `logging.getLogger(__name__ + ".psu")`), DEBUG-level SCPI trace.

This is a deliberate contract difference from such a driver: SCPI traffic is verbose and machine-parseable; the per-test `res.log` is operator-readable and step-grained. Codegen emits `step_progress(n, "<description>", res.log)` per step and lets the SCPI trace stay in the Python logger (where it is captured by the test runner's logging handlers, not by `res.log`).

If a bench operator wants to capture the SCPI trace, they configure a Python logging handler in the test runner — outside the v2.0.0 codegen-emitted scaffolding.

### 7.2 Error handling

- `check_errors=True` (constructor default): every command is followed by `SYST:ERR?`; a non-zero entry raises `SCPIError` carrying the error text.
- `wait_opc=True` (constructor default): every write is followed by `*OPC?` blocking until the instrument reports completion. This serializes commands and avoids races where the next command sees stale state.

Both flags are constructor-controlled and codegen never overrides them. The defaults are the safe choice for bench bring-up.

### 7.3 Thread safety

The class is **not** thread-safe. A single `PowerSupply` instance MUST NOT be used from more than one thread concurrently. Generated tests are single-threaded; this is fine for the codegen contract. Hand-written test code that wants concurrency must guard the instance with its own lock.

### 7.4 Reentrancy

`connect()`, `initialize()`, `close()`, `set_voltage()`, `set_current()`, `output()` are NOT safe to call recursively from a signal handler. The session uses `pyvisa`'s blocking I/O, which is not signal-safe.

---

## 8. Multi-instance naming

When a procedure declares two or more `psu` equipment ids, codegen emits one `PowerSupply` instance per id, with module-level constants and local variable names.

### 8.1 Worked example

For:

```
## Equipment
PSU1 : psu
PSU2 : psu
```

with inventory:

```json
{
 "PSU1": {"type": "psu", "visa": "ASRL3::INSTR", "channel": 1, "timeout_ms": 5000, "remote": true},
 "PSU2": {"type": "psu", "visa": "ASRL5::INSTR", "channel": 1, "timeout_ms": 5000, "remote": true}
}
```

codegen emits the constants:

```python
PSU1_REMOTE = True
PSU1_VISA = "ASRL3::INSTR"
PSU1_CHANNEL = 1
PSU1_TIMEOUT_MS = 5000

PSU2_REMOTE = True
PSU2_VISA = "ASRL5::INSTR"
PSU2_CHANNEL = 1
PSU2_TIMEOUT_MS = 5000
```

and the bring-up:

```python
if PSU1_REMOTE:
 psu1 = PowerSupply(PSU1_VISA, timeout_ms=PSU1_TIMEOUT_MS)
 psu1.connect()
 psu1.initialize()
if PSU2_REMOTE:
 psu2 = PowerSupply(PSU2_VISA, timeout_ms=PSU2_TIMEOUT_MS)
 psu2.connect()
 psu2.initialize()
```

The two instances are independent: separate VISA sessions, separate brand adapters, separate timeouts. They share no state.

### 8.2 Local variable name derivation

The local variable name is the lowercased equipment id with underscores preserved:

| Equipment id | Local variable |
|---|---|
| `PSU1` | `psu1` |
| `PSU2` | `psu2` |
| `PSU1_CH3` | `psu1_ch3` |
| `PSU_AUX` | `psu_aux` |

The derivation is a pure `<id>.lower()` — no transformation, no escaping. Equipment id syntax (`^[A-Z][A-Z0-9_]{0,31}$`,) ensures the lowercased form is a valid Python identifier.

### 8.3 Per-id channel binding (multi-channel from one chassis)

When two ids share the same `visa` but differ on `channel` (the `PSU1_CH1`/`PSU1_CH2`/`PSU1_CH3` pattern), codegen still emits two independent `PowerSupply` instances. Both call `connect()` against the same VISA address; pyvisa's ResourceManager returns two distinct session objects and the chassis arbitrates between them.

This is wasteful (two sessions to one chassis) but consistent: the alternative — share a single session across ids — would couple their lifecycles and complicate cleanup. The v2.0.0 codegen prefers redundancy over coupling.

---

## 9. Error semantics summary

| Method | Raises | Notes |
|---|---|---|
| `__init__` | none | Pure constructor; never raises. |
| `connect` | `ImportError`, `pyvisa.errors.VisaIOError` | Raises on `pyvisa` not installed or address-resolution failure. |
| `initialize` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | Raises if `connect()` was not called or `*IDN?` fails. |
| `close` | none | Failures swallowed and ignored. |
| `set_voltage` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | Out-of-range behavior is brand-dependent (see §5.1). |
| `set_current` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | As above. |
| `output` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | As above. |

The lifecycle's `except BaseException` handler catches every exception type listed above; codegen does NOT need per-call try/except wrappers around the op methods. The cleanup `finally:` block wraps each `close()` call in `try: ... except Exception: pass` defensively, even though `close()` itself never raises.

---

## 10. Bijection notes

### 10.1 The driver is on the code-side only

The methods specified here appear only in the generated `test.py`. Canonical text (`procedure_text.md`) and `procedure.json` never name `PowerSupply` or any of its methods — the canonical text uses verb forms (`Set`, `Measure`, `Send raw SCPI to`, `Query raw from`) and the JSON uses the abstract op names (`psu.set_voltage`, `psu.set_current`, `psu.output`).

### 10.2 Inspector recognition

The inspector recognizes a `psu.set_voltage` block by AST shape: an `If(test=Name("<ID>_REMOTE"))` wrapping a `Call(func=Attribute(value=Name("<id_lower>"), attr="set_voltage"), args=[Name("<ID>_CHANNEL"), Call(func=Name("float"), args=[Constant(<volts>)])])`. The inspector reads `<ID>` from the if-test, `<id_lower>` from the call attribute owner, `<ID>_CHANNEL` from the first positional arg's name, and `<volts>` from the float-wrapped Constant. From these it reconstructs the JSON op.

The same shape with `attr="set_current"` recovers `psu.set_current`; with `attr="output"` and the second arg a bare `Constant(True/False)` (no `float` wrapper), recovers `psu.output`.

### 10.3 Method-name ABI

Renaming any of the seven names in §2 is a v3.0.0 event because:

1. The inspector AST patterns reference the names as string literals in `code_inspector.py`.
2. The codegen AST templates reference the names as `Attribute(attr=...)` strings.
3. `SCPI_PSU_Text_Procedure_v2.md`'s "Verbs and forms" table names each method.

Adding new methods to the class does not break anything; renaming is a coordinated three-file change plus a doc-version bump. The v2.0.0 method names are the contract.

### 10.4 What about the wider class API?

Methods like `measure_voltage`, `measure_current`, `set_ovp`, `set_ocp` exist on the class but are NOT codegen-targeted. Calls to them in handwritten test code work fine but are flagged as `JC_AST_UNRECOGNIZED` during the bijection check. The bijection check is therefore meaningful only for codegen-emitted files; handwritten files use the wider API at the cost of skipping the round-trip guarantee.

In v2.0.0, only the three setpoint ops are codegen-bound. The other class methods (`measure_voltage`, `measure_current`, `set_ovp`, `set_ocp`, etc.) remain available to handwritten test code; they are not enumerated as authored ops and therefore do not participate in the JSON ⇄ code bijection.

---

## 12. Cross-references

- `SCPI_PSU_Text_Procedure_v2.md` (labscpi_pack rules 2.0.1) — the authoring rules for the canonical text; its "Verbs and forms" table maps each step form to the method it calls.
- Sibling: `SCPI_Electronic_Load_API_Contract_v2.md` — the parallel API contract for the `eload` type.
- Sibling: `SCPI_Oscilloscope_API_Contract_v2.md` — the parallel API contract for the `scope` type.
- Legacy: `labscpi_PSU_CODEGEN_client_usage.md` v1.x — the predecessor doc this one replaces.

---

## 13. Conformance summary

A `labscpi` installation conforms to this contract iff:

1. The class `labscpi.psu_scpi.PowerSupply` exists and is importable.
2. Its constructor signature matches §3.1 exactly (positional `visa_address`, keyword-only `timeout_ms`, `check_errors`, `wait_opc`, `logger`, `rm`, `defer_init_io` with the documented defaults).
3. Each method in §2 is exposed at the documented name with the documented signature.
4. `connect()` opens the VISA session; `initialize()` issues `*IDN?` and binds a brand adapter; `close()` releases the session (idempotently and infallibly).
5. `set_voltage`, `set_current`, `output` raise `NotConnectedError` when called before `connect() + initialize()`; otherwise they delegate to the brand adapter and surface SCPI errors as `SCPIError`.
6. The constructor is pure (no I/O when `defer_init_io=True`).
7. The class does not introduce a driver-side `manual_override` parameter (per §6.1).
8. Method names listed in §2 are not shadowed by future v2.x.y additions.

The validator does not directly check (1)–(8); they are enforced by the pack's own unit tests under `labscpi/tests/`. A procedure pinned to `labscpi@2.0.0` whose installed wheel fails any of the above is a packaging bug, not a procedure bug.
