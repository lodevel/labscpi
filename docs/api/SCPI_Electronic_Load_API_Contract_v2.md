---
doc_id: scpi-eload-api-contract-v2
title: SCPI Electronic Load — Driver API Contract
type: api_contract
domain: bijective_procedures
language: en
version: "2.0.0"
status: current
audience: [validator, codegen, inspector, test, llm]
package: labscpi
class_name: ElectronicLoad
facade_module: labscpi.eload_scpi
transports: [ASRL, USB, TCPIP, GPIB]
default_timeout_ms: 5000
related:
 - bijective-procedure-spec-v2
 - procedure-json-schema-v2
 - equipment-and-inventory-v2
 - helpers-api-contract-v2
 - lifecycle-and-cleanup-v2
 - json-code-bijection-v2
description: "Specifies the public API of the ElectronicLoad driver class: constructor signature, lifecycle, the four codegen-called methods (set_mode, set_current, set_output, close), logging behavior, multi-instance naming, and the v2 stability promise."
---

# SCPI Electronic Load — Driver API Contract

This document specifies the **stable public API** of the `ElectronicLoad` class shipped by the `labscpi` package. Codegen emits Python source that imports this class and calls a fixed set of methods on instances of it. The signatures listed here are part of the v2.0.0 driver API contract: any incompatible change requires bumping the pack version (`labscpi@2.1.0` or higher) and re-pinning every procedure's `meta.labscpi_pack` field.

This is a **contract** document, not an implementation guide. The implementation lives in `labscpi.eload_scpi.ElectronicLoad` and is exercised by tests under `labscpi/tests/`. The implementation MAY change freely within the v2.x series provided the contract here continues to hold.

> **Scope of this contract.** Eight ELOAD methods are codegen-targeted in v2.0.0 — `set_mode`, `set_current`, `set_voltage`, `set_power`, `set_output`, `get_voltage`, `get_current`, `get_power` — plus the lifecycle trio `connect` / `initialize` / `close`. The class exposes additional methods (`selftest_interface`, `write_raw`, `query_raw`, `set_timeout`) that are part of the wider labscpi developer API but are NOT codegen-targeted. Those out-of-scope methods may evolve at the implementer's discretion within v2.x; this doc neither pins nor versions them.

---

## 1. Module location and imports

### 1.1 Class location

The class lives under a single Python module:

```
labscpi.eload_scpi
```

Codegen always imports from this fully-qualified path:

```python
from labscpi.eload_scpi import ElectronicLoad
```

The exact import line is fixed by codegen for byte-reproducibility. Generated `test.py` files MUST NOT use `as` aliasing on this import; the inspector recognizes the bare name `ElectronicLoad` in the `Call(func=Name(...))` AST shape, and any alias breaks the recognizer.

### 1.2 Internal module structure (informational)

The class is defined in `labscpi.eload_scpi` as one of three brand-agnostic SCPI driver façades in the `labscpi` package. The class API mirrors `labscpi.psu_scpi.PowerSupply` deliberately — the two were designed in parallel so the bring-up/cleanup scaffolding could share patterns.

The package `__init__` does not re-export the class; callers MUST use the fully-qualified module path.

### 1.3 Pack version coupling

The class is shipped as part of `labscpi@2.0.0`.

### 1.4 Stability promise

For the lifetime of v2.0.0 of this pack:

- No method signature listed in §2 may be removed or have its parameter list narrowed.
- No method may change its return type.
- New keyword-only parameters MAY be added with safe defaults (additive change).
- Method names listed in §2 are reserved.

Breaking signature changes are MAJOR-version events that require a new doc and a new schema.

### 1.5 What this doc does NOT cover

- The canonical text grammar that maps procedure steps to method calls. See `SCPI_Electronic_Load_Text_Procedure_v2.md` (labscpi_pack rules 2.0.1), "Verbs and forms".
- The substitution rules that turn inventory entries into module-level constants. 
- The lifecycle scaffolding. 
- The per-op AST template registry. 
- The wider labscpi developer API: `selftest_interface`, `write_raw`, `query_raw`, `set_timeout`. These remain out of scope. (Note: `set_voltage`, `set_power`, `get_voltage`, `get_current`, `get_power` were promoted into scope and are now covered by §5.4–§5.8.)

---

## 2. Class API summary

The codegen-targeted public surface of `labscpi.eload_scpi.ElectronicLoad` in v2.0.0 is exactly twelve entry points (Phase A Stream 2 promoted the five non-CC ops to LIVE):

| Entry point | Signature | Purpose |
|---|---|---|
| `__init__` | `(visa_address, *, timeout_ms=3000, check_errors=True, wait_opc=True, logger=None, rm=None, defer_init_io=True)` | Construct an instance bound to one VISA resource. No I/O. |
| `connect` | `() -> None` | Open the VISA session against `visa_address`. |
| `initialize` | `() -> None` | Identify the instrument and bind a brand adapter. |
| `set_mode` | `(channel: int, mode: str) -> None` | Set the channel's mode (`CC`/`CV`/`CP`). |
| `set_current` | `(channel: int, amps: float) -> None` | Set the channel's CC sink current. |
| `set_voltage` | `(channel: int, volts: float) -> None` | Set the channel's CV setpoint. |
| `set_power` | `(channel: int, watts: float) -> None` | Set the channel's CP setpoint. |
| `set_output` | `(channel: int, on: bool) -> None` | Enable or disable the channel's input. |
| `get_voltage` | `(channel: int) -> float` | Read the measured input voltage. |
| `get_current` | `(channel: int) -> float` | Read the measured input current. |
| `get_power` | `(channel: int) -> float` | Read the measured input power. |
| `close` | `() -> None` | Release the VISA session. Idempotent. |

Codegen does NOT emit any other method name on an `ElectronicLoad` instance.

### 2.1 Method ordering and inspector recognition

The inspector keys per-op AST recognition on the method name (`Call(func=Attribute(value=Name(id_lower), attr="<method>"))`). The twelve names above are the only ones the v2.0.0 inspector recognizes for an `ElectronicLoad` instance; calls to any other method on an `ElectronicLoad` instance from generated code are flagged as `JC_AST_UNRECOGNIZED` and break the bijection check.

The inspector additionally distinguishes `eload.set_current` from `psu.set_current` (same method name on a different class) by the equipment-type of the variable's `<ID>` in `P.equipment`.

### 2.2 Method name overlaps

Three method names are shared between `PowerSupply` and `ElectronicLoad`:

| Method | Defined on | Notes |
|---|---|---|
| `set_voltage` | both | On PSU: voltage setpoint (codegen-targeted as `psu.set_voltage`). On ELOAD: CV setpoint (codegen-targeted as `eload.set_voltage`; LIVE in v2.0.0). The inspector disambiguates by the equipment-type of `<ID>` in `P.equipment`. |
| `set_current` | both | On PSU: current limit (codegen-targeted). On ELOAD: CC setpoint (codegen-targeted). |
| `close` | both | Idempotent session release (codegen-targeted). |

The `set_output` (eload) and `output` (psu) methods are NOT overlapping — different names, different semantics. The inspector does not need to disambiguate them.

The `connect`/`initialize` lifecycle pair is shared between all three labscpi classes (`PowerSupply`, `ElectronicLoad`, `Oscilloscope`); each has its own implementation, none of which collide because they're called on different instances.

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
| `visa_address` | str | yes | — | IVI-VISA resource string. |
| `timeout_ms` | int | no | `3000` | VISA I/O timeout per call, in milliseconds. Codegen passes the inventory-substituted `<ID>_TIMEOUT_MS` constant (default `5000`). |
| `check_errors` | bool | no | `True` | Run `SYST:ERR?` after every command and raise `SCPIError` on non-zero. Codegen does NOT pass this; takes the default. |
| `wait_opc` | bool | no | `True` | Block on `*OPC?` after every write. Codegen does NOT pass this; takes the default. |
| `logger` | `logging.Logger \| None` | no | `None` | Optional Python logger; emits SCPI trace at DEBUG level. Codegen does NOT pass this. |
| `rm` | `pyvisa.ResourceManager \| None` | no | `None` | Optional pre-built ResourceManager. Codegen does NOT pass this. |
| `defer_init_io` | bool | no | `True` | When `True`, the constructor and `connect()` perform no `*IDN?` / adapter-bind I/O; the caller MUST invoke `initialize()` explicitly. The codegen-emitted bring-up always uses the default. |

### 3.3 Constructor side effects

The constructor is **pure**: it records arguments on `self`, allocates internal state slots, and returns. No VISA library is touched, no port is opened, no I/O is performed. This is the `defer_init_io=True` contract.

The constructor never raises in the codegen-emitted call site.

### 3.4 Codegen call site
codegen emits one constructor call per declared `eload` equipment id, gated by `<ID>_REMOTE`:

```python
 if ELOAD_REMOTE:
 eload = ElectronicLoad(ELOAD_VISA, timeout_ms=ELOAD_TIMEOUT_MS)
 eload.connect()
 eload.initialize()
```

Codegen passes `visa_address` positionally and `timeout_ms` by keyword. No other constructor parameters appear in generated code.

---

## 4. Lifecycle

### 4.1 `connect()`

```python
def connect(self) -> None: ...
```

Opens the VISA session against `self.address`. On entry: `self._connected == False`. On normal exit: `self._connected == True`, `self._resource` is a live `pyvisa.Resource`, `self._session` is a configured `_Session`.

The call is idempotent on a connected instance. On `pyvisa` not installed it raises `ImportError`. On address resolution / port-busy / permission-denied, the underlying `pyvisa` exception propagates.

When `defer_init_io=False`, `connect()` additionally calls `initialize()` before returning. The codegen-default `defer_init_io=True` keeps the two calls separate.

### 4.2 `initialize()`

```python
def initialize(self) -> None: ...
```

Issues `*IDN?`, parses the identity string, picks the appropriate brand adapter (EA-EL, Chroma, Keysight EL, etc.), and binds it to `self._adapter`. Calls `self._adapter.startup()` to apply the brand-specific safe-default state (mode `CC`, current setpoint `0`, input OFF — row `eload`).

On `not self._connected`: raises `NotConnectedError`.

The call is idempotent.

After `initialize()` returns, the instrument is in the safe-default state listed: mode CC, current 0, input OFF.

### 4.3 `close()`

```python
def close(self) -> None: ...
```

Releases the underlying VISA resource. Idempotent: calling `close()` on an unopened or already-closed instance is a no-op.

The implementation calls `self._adapter.shutdown()` (swallowed on failure), then `self._resource.close()`, then resets the internal state slots. No exception escapes.

### 4.4 Codegen lifecycle pattern

The generated `test.py` constructs and closes one `ElectronicLoad` instance per declared `eload` equipment id. The pattern:

```python
eload = None # forward declaration in run_test()
eload_output_on = False # output-state tracker

def run_test():
 # ...
 try:
 # ...
 if ELOAD_REMOTE:
 eload = ElectronicLoad(ELOAD_VISA, timeout_ms=ELOAD_TIMEOUT_MS)
 eload.connect()
 eload.initialize()
 # ... step bodies, including eload.set_mode(...), eload.set_current(...), eload.set_output(...) ...
 except BaseException as e:
 # ...
 finally:
 # ... output-disable safety ...
 try:
 if ELOAD_REMOTE and eload and eload_output_on:
 eload.set_output(ELOAD_CHANNEL, False)
 except Exception:
 pass
 # ... manual-mode safe-state prompts ...
 # ... close handles ...
 try:
 if ELOAD_REMOTE and eload:
 eload.close()
 except Exception:
 pass
```

The variable name `eload` is the lowercased equipment id with all underscores preserved. For `<ID> = "ELOAD_PRIMARY"`, the variable is `eload_primary`.

---

## 5. Per-method specifications

### 5.1 `set_mode`

```python
def set_mode(self, channel: int, mode: str) -> None: ...
```

Set the specified channel's operating mode.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. Codegen passes `<ID>_CHANNEL`. |
| `mode` | str | One of `"CC"`, `"CV"`, `"CP"`. The driver's brand adapter accepts the same uppercase tokens; lowercase is rejected at the adapter boundary. |

**Returns** `None` on success.

**Raises:**
- `NotConnectedError` if called before `connect() + initialize()`.
- `SCPIError` if `check_errors=True` (the constructor default) and the instrument's error queue contains a non-zero entry after the command.
- `pyvisa.errors.VisaIOError` on transport failure.
- `ChannelError` on multi-channel-only mode for a single-channel chassis (e.g. EA-EL family on `channel != 1`; see §7).

**Codegen call site**:

```python
 if ELOAD_REMOTE:
 eload.set_mode(ELOAD_CHANNEL, "CC")
```

The `mode` argument is a bare `Constant("CC")` (no `float` wrapper since it's a string). The inspector pattern recovers `mode` from the second positional argument's value.

**Behavior notes:**
- The driver delegates to the bound brand adapter's mode-set sequence (typically `INST:NSEL <ch>` followed by `MODE CC`/`CV`/`CP` or vendor-specific equivalent).
- Mode change is non-disruptive to the input ON/OFF state. If the input is on when the mode changes, the load continues sinking — the new mode's setpoint takes effect immediately.

### 5.2 `set_current`

```python
def set_current(self, channel: int, amps: float) -> None: ...
```

Set the channel's CC setpoint.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. |
| `amps` | float | CC setpoint in amperes (SI base). The driver coerces with `float(amps)` internally before delegating. |

**Returns** `None` on success. **Raises** as per §5.1.

**Codegen call site**:

```python
 if ELOAD_REMOTE:
 eload.set_current(ELOAD_CHANNEL, float(4.0))
```

The `float(...)` wrapper is intentional and part of the inspector pattern.

**Behavior notes:**
- The driver delegates to the bound brand adapter's `set_current(channel, float(amps))`.
- The setpoint is recorded by the load even when not in CC mode; switching to CC mode later activates the most-recently-set value. Neither the validator nor the driver makes this an error.

### 5.3 `set_output`

```python
def set_output(self, channel: int, on: bool) -> None: ...
```

Enable or disable the channel's input.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. |
| `on` | bool | `True` enables the input (load starts sinking); `False` disables. The driver coerces with `bool(on)` internally. |

**Returns** `None` on success. **Raises** as per §5.1.

**Codegen call site**:

```python
 if ELOAD_REMOTE:
 eload.set_output(ELOAD_CHANNEL, True)
 else:
 prompt("Turn ELOAD CH1 ON. Type 'ok'.", res.log)
 eload_output_on = True
```

The trailing `eload_output_on = True` is an output-state tracker emitted by codegen.

**Naming note.** The driver method is `set_output` even though English speakers say "the load's input." The label "input" is the right model at the connector (the load receives current from the DUT) but "output" is the naming the SCPI specs settled on (the load's input is its "output stage" when modeled as a current sink). Both labscpi and the brand adapters use `output` consistently. The canonical text uses the same noun: `Set <ID> CH<ch> output = <ON|OFF>.` (`SCPI_Electronic_Load_Text_Procedure_v2.md`, "Verbs and forms").

### 5.4 `set_voltage`

```python
def set_voltage(self, channel: int, volts: float) -> None: ...
```

Set the channel's CV setpoint.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. |
| `volts` | float | CV setpoint in volts (SI base). The driver coerces with `float(volts)` internally before delegating. |

**Returns** `None` on success. **Raises** as per §5.1.

**Codegen call site**:

```python
 if ELOAD_REMOTE:
 eload.set_voltage(ELOAD_CHANNEL, float(12.0))
```

**Behavior notes:** Same as `set_current` (§5.2) but for the CV setpoint. The setpoint is recorded by the load even when not in CV mode; switching to CV mode later activates the most-recently-set value. The `EL_MODE_MISMATCH` warning flags procedures that set the voltage before establishing CV mode.

### 5.5 `set_power`

```python
def set_power(self, channel: int, watts: float) -> None: ...
```

Set the channel's CP setpoint.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. |
| `watts` | float | CP setpoint in watts (SI base). The driver coerces with `float(watts)` internally before delegating. |

**Returns** `None` on success. **Raises** as per §5.1.

**Codegen call site**:

```python
 if ELOAD_REMOTE:
 eload.set_power(ELOAD_CHANNEL, float(25.0))
```

**Behavior notes:** Same as `set_current` (§5.2) but for the CP setpoint. The `EL_MODE_MISMATCH` warning flags procedures that set the power before establishing CP mode.

### 5.6 `get_voltage`

```python
def get_voltage(self, channel: int) -> float: ...
```

Read the measured input voltage.

| Parameter | Type | Notes |
|---|---|---|
| `channel` | int | 1-based channel index. |

**Returns** the measured voltage in volts (SI base) as a float. **Raises** as per §5.1.

**Codegen call site**:

```python
 if ELOAD_REMOTE:
 res.measurements[1] = float(eload.get_voltage(ELOAD_CHANNEL))
 else:
 res.measurements[1] = read_measurement(
 "Enter {1} mean voltage on ELOAD CH1:",
 res.log,
 default_unit="V",
 )
```

The `float(...)` wrapper is intentional and part of the inspector pattern.

**Behavior notes:** The driver delegates to the bound brand adapter's `get_voltage(channel)`. Mode-independent — works in CC/CV/CP.

### 5.7 `get_current`

```python
def get_current(self, channel: int) -> float: ...
```

Read the measured input current.

**Returns** the measured current in amperes (SI base). **Raises** as per §5.1.

**Codegen call site**:

```python
 if ELOAD_REMOTE:
 res.measurements[2] = float(eload.get_current(ELOAD_CHANNEL))
```

### 5.8 `get_power`

```python
def get_power(self, channel: int) -> float: ...
```

Read the measured input power.

**Returns** the measured power in watts (SI base). **Raises** as per §5.1.

**Codegen call site**:

```python
 if ELOAD_REMOTE:
 res.measurements[3] = float(eload.get_power(ELOAD_CHANNEL))
```

---

## 6. Manual-mode handling

### 6.1 No driver-side manual mode

Like `PowerSupply` (per `SCPI_PSU_API_Contract_v2.md` §6), the `ElectronicLoad` class has **no driver-side manual mode**. The class always opens the VISA port on `connect()` and always sends SCPI on `set_mode()`/`set_current()`/`set_output()`. There is no `manual_override` constructor parameter.

Manual operation is entirely handled by codegen-side branching: when `<ID>_REMOTE = False`, codegen emits a `prompt(...)` call instead of a driver call, and the `ElectronicLoad` is never instantiated for that id.

### 6.2 Codegen contract

The pattern is fixed:

```python
 if ELOAD_REMOTE:
 eload.set_mode(ELOAD_CHANNEL, "CC")
 else:
 prompt("Set ELOAD CH1 mode to CC. Type 'ok'.", res.log)
```

When `ELOAD_REMOTE = False`, the `eload` variable is `None`, and the `else:` branch fires for every `eload.*` call site in the test. The cleanup block's output-disable subsection also guards on `ELOAD_REMOTE` and emits a manual safe-state prompt instead.

### 6.3 Why no driver-side manual mode

Same rationale as `PowerSupply` (per `SCPI_PSU_API_Contract_v2.md` §6.3): the labscpi classes were designed assuming the driver always talks to hardware; the codegen-side `if/else` branching subsumes manual-mode use cases with the added benefit that the operator-friendly prompt text is part of `test.py` (operator-readable, version-controlled with the procedure).

---

## 7. Behavioral contracts

### 7.1 Logging

The class does NOT append per-call log lines to a per-test list. It uses Python's `logging` module: a `logger` parameter at construction (default `logging.getLogger(__name__ + ".eload")`), DEBUG-level SCPI trace.

Same rationale as `PowerSupply` (per `SCPI_PSU_API_Contract_v2.md` §7.1): SCPI traffic is verbose and machine-parseable; the per-test `res.log` is operator-readable and step-grained.

### 7.2 Error handling

- `check_errors=True` (default): every command is followed by `SYST:ERR?`; non-zero raises `SCPIError`.
- `wait_opc=True` (default): every write is followed by `*OPC?` blocking until completion.

Both flags are constructor-controlled and codegen never overrides them.

### 7.3 Single-channel chassis

The `EA-EL` family (which the labscpi `MockLoadResource` emulates) is single-channel. The `EaElAdapter._enforce_single_channel(ch)` check raises `ChannelError("Single-channel electronic load")` on `ch != 1`. Procedures that declare `channel: 2` or higher against an EA-EL inventory entry will fail at runtime on the first method call.

The authoring rules (`SCPI_Electronic_Load_Text_Procedure_v2.md`, "Equipment line") do not enforce a single-channel rule globally because some bench installations have multi-bay loads under one VISA session. The bench owner is responsible for matching the procedure's per-id channel binding to the installed chassis's channel count.

### 7.4 Thread safety

The class is **not** thread-safe. A single `ElectronicLoad` instance MUST NOT be used from more than one thread concurrently.

### 7.5 Reentrancy

`connect()`, `initialize()`, `close()`, `set_mode()`, `set_current()`, `set_output()` are NOT safe to call recursively from a signal handler.

---

## 8. Multi-instance naming

When a procedure declares two or more `eload` equipment ids, codegen emits one `ElectronicLoad` instance per id, with module-level constants and local variable names.

### 8.1 Worked example

For:

```
## Equipment
ELOAD_PRIMARY : eload
ELOAD_AUX : eload
```

with inventory:

```json
{
 "ELOAD_PRIMARY": {"type": "eload", "visa": "ASRL4::INSTR", "channel": 1, "timeout_ms": 5000, "remote": true},
 "ELOAD_AUX": {"type": "eload", "visa": "ASRL6::INSTR", "channel": 1, "timeout_ms": 5000, "remote": true}
}
```

codegen emits the constants:

```python
ELOAD_PRIMARY_REMOTE = True
ELOAD_PRIMARY_VISA = "ASRL4::INSTR"
ELOAD_PRIMARY_CHANNEL = 1
ELOAD_PRIMARY_TIMEOUT_MS = 5000

ELOAD_AUX_REMOTE = True
ELOAD_AUX_VISA = "ASRL6::INSTR"
ELOAD_AUX_CHANNEL = 1
ELOAD_AUX_TIMEOUT_MS = 5000
```

and the bring-up:

```python
if ELOAD_PRIMARY_REMOTE:
 eload_primary = ElectronicLoad(ELOAD_PRIMARY_VISA, timeout_ms=ELOAD_PRIMARY_TIMEOUT_MS)
 eload_primary.connect()
 eload_primary.initialize()
if ELOAD_AUX_REMOTE:
 eload_aux = ElectronicLoad(ELOAD_AUX_VISA, timeout_ms=ELOAD_AUX_TIMEOUT_MS)
 eload_aux.connect()
 eload_aux.initialize()
```

The two instances are independent: separate VISA sessions, separate brand adapters, separate timeouts.

### 8.2 Local variable name derivation

The local variable name is the lowercased equipment id with underscores preserved:

| Equipment id | Local variable |
|---|---|
| `ELOAD` | `eload` |
| `ELOAD_PRIMARY` | `eload_primary` |
| `ELOAD_AUX` | `eload_aux` |

The derivation is a pure `<id>.lower()` — no transformation, no escaping.

### 8.3 Multi-channel from one chassis (rare)

When two ids share the same `visa` but differ on `channel`, codegen still emits two independent `ElectronicLoad` instances. This is rare for ELOADs (most chassis are single-channel), but the codegen pattern is identical to PSU multi-channel (per `SCPI_PSU_API_Contract_v2.md` §8.3).

---

## 9. Error semantics summary

| Method | Raises | Notes |
|---|---|---|
| `__init__` | none | Pure constructor; never raises. |
| `connect` | `ImportError`, `pyvisa.errors.VisaIOError` | Raises on `pyvisa` not installed or address-resolution failure. |
| `initialize` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError` | Raises if `connect()` was not called or `*IDN?` fails. |
| `close` | none | Failures swallowed and ignored. |
| `set_mode` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError`, `ChannelError` | `ChannelError` from single-channel chassis. |
| `set_current` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError`, `ChannelError` | As above. |
| `set_output` | `NotConnectedError`, `SCPIError`, `pyvisa.errors.VisaIOError`, `ChannelError` | As above. |

The lifecycle's `except BaseException` handler catches every exception type listed above.

---

## 10. Bijection notes

### 10.1 The driver is on the code-side only

The methods specified here appear only in the generated `test.py`. Canonical text and JSON never name `ElectronicLoad` or its methods.

### 10.2 Inspector recognition

The inspector recognizes an `eload.set_mode` block by AST shape: `If(test=Name("<ID>_REMOTE"))` wrapping `Call(func=Attribute(value=Name("<id_lower>"), attr="set_mode"), args=[Name("<ID>_CHANNEL"), Constant("<mode>")])`. Recovery: `<ID>` from the if-test, `<id_lower>` from the call attribute owner, `<ID>_CHANNEL` from the first arg, `<mode>` from the second arg's Constant value.

For `set_current`, the second arg is `Call(Name("float"), [Constant(<amps>)])`; the inspector unwraps the float-call to recover `amps`.

For `set_output`, the second arg is `Constant(<True|False>)`; the inspector reads it directly.

### 10.3 Method-name ABI

Renaming any of the seven names in §2 is a v3.0.0 event because:

1. The inspector AST patterns reference the names as string literals in `code_inspector.py`.
2. The codegen AST templates reference the names as `Attribute(attr=...)` strings.
3. `SCPI_Electronic_Load_Text_Procedure_v2.md`'s "Verbs and forms" table names each method.

Adding new methods to the class does not break anything; renaming is a coordinated three-file change plus a doc-version bump.

### 10.4 What about the wider class API?

Methods `set_voltage`, `set_power`, `get_voltage`, `get_current`, `get_power` are now ALL codegen-targeted as of v2.0.0. The class exposes `selftest_interface`, `write_raw`, `query_raw`, and `set_timeout` for developer use; those remain out of scope for codegen. The wider class API is otherwise stable.

---

## 12. Cross-references

- `SCPI_Electronic_Load_Text_Procedure_v2.md` (labscpi_pack rules 2.0.1) — the authoring rules for the canonical text; its "Verbs and forms" table maps each step form to the method it calls.
- Sibling: `SCPI_PSU_API_Contract_v2.md` — the parallel API contract for the `psu` type; §2.2 discusses the `set_current` method-name overlap.
- Sibling: `SCPI_Oscilloscope_API_Contract_v2.md` — the parallel API contract for the `scope` type.
- Legacy: `labscpi_ELOAD_CODEGEN_client_usage.md` v1.x — the predecessor doc this one replaces.

---

## 13. Conformance summary

A `labscpi` installation conforms to this contract iff:

1. The class `labscpi.eload_scpi.ElectronicLoad` exists and is importable.
2. Its constructor signature matches §3.1 exactly.
3. Each method in §2 is exposed at the documented name with the documented signature.
4. `connect()` opens the VISA session; `initialize()` issues `*IDN?` and binds a brand adapter; `close()` releases the session (idempotently and infallibly).
5. `set_mode`, `set_current`, `set_output` raise `NotConnectedError` when called before `connect() + initialize()`; otherwise they delegate to the brand adapter and surface SCPI errors as `SCPIError`.
6. The constructor is pure (no I/O when `defer_init_io=True`).
7. The class does not introduce a driver-side `manual_override` parameter (per §6.1).
8. Method names listed in §2 are not shadowed by future v2.x.y additions.

The validator does not directly check (1)–(8); they are enforced by the pack's own unit tests under `labscpi/tests/`. A procedure pinned to `labscpi@2.0.0` whose installed wheel fails any of the above is a packaging bug, not a procedure bug.
