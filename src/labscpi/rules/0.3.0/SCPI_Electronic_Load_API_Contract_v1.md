---
doc_id: scpi-eload-api-v1
title: SCPI Electronic Load Driver — Public API Contract
type: api_contract
domain: instrumentation
language: en
version: 1.0.0
status: current
effective_date: 2025-11-04
audience: [llm, test, firmware]
product: SCPI_ELOAD
class_name: ElectronicLoad
transports: [TCPIP, ASRL, USB, GPIB]
standards: [SCPI, VISA]
methods_index:
  - connect
  - initialize
  - close
  - set_timeout
  - configure_serial
  - set_current
  - set_voltage
  - set_power
  - set_output
  - output_all
  - get_voltage
  - get_current
  - get_power
  - write_raw
  - query_raw
  - write_direct
  - query_direct
exceptions: [NotConnectedError, ChannelError, RangeError, SCPIError, NotSupportedError]
units: [V, A, W]
channels_base: 1
safety_notes: true
synonyms:
  eload: [electronic load, dc load]
  input: [load input]
related: [scpi-psu-api-v1, scpi-oscilloscope-api-v1, test-rules-llm-ready-v1]
checksum: bbe415752ab423972073a6b1209e0c4bb41d9a6ecf508f8f37dbb0b1726e1116
---

# SCPI Electronic Load Driver — Public API Contract v1

Scope: brand‑agnostic SCPI electronic load driver used by LLM‑generated tests. Mirrors the PSU contract semantics. **This document describes only the public façade** of `eload_scpi.ElectronicLoad`; internal adapters are out of scope.

## 1. Usage

```python
from eload_scpi import ElectronicLoad

el = ElectronicLoad("TCPIP0::192.168.0.50::inst0::INSTR", timeout_ms=3000)
el.connect()
el.initialize()

# Choose ONE mode setter before enabling input
el.set_current(1, 2.0)          # CC mode at 2 A
el.set_output(1, True)          # input ON
v = el.get_voltage(1)           # volts
i = el.get_current(1)           # amps
p = el.get_power(1)             # watts

el.set_output(1, False)
el.close()
```

Notes
- Channels are **1‑based**.
- Calls block; SCPI errors surface if error checking is enabled in the session.
- The **last setter** called before `set_output(True)` defines the active mode (CC/CV/CP).


## 2. API Reference

### 2.1 Connection

- `connect() -> None`  
  Open VISA resource and set IO parameters.

- `initialize() -> None`  
  Query `*IDN?`, select adapter, run adapter startup hook.

- `close() -> None`  
  Run adapter shutdown hook and close the VISA resource. Safe to call multiple times.

### 2.2 Session configuration

- `set_timeout(timeout_ms: int) -> None`  
  Set VISA timeout (ms) on the live session.

- `configure_serial(*, baud: int|None = None, data_bits: int|None = None, stop_bits: int|None = None, parity: Any|None = None, write_termination: str|None = None, read_termination: str|None = None) -> None`  
  Configure ASRL parameters (use for serial resources).

### 2.3 Input configuration and control

- `set_current(channel: int, amps: float) -> None`  
  Program **CC** mode setpoint.

- `set_voltage(channel: int, volts: float) -> None`  
  Program **CV** mode setpoint.

- `set_power(channel: int, watts: float) -> None`  
  Program **CP** mode setpoint.

- `set_output(channel: int, on: bool) -> None`  
  Enable or disable the input (`INP ON|OFF` or `LOAD:STAT`).

- `output_all(on: bool) -> None`  
  Best‑effort enable/disable across channels where available.

### 2.4 Measurements

- `get_voltage(channel: int) -> float`  (V)  
- `get_current(channel: int) -> float`  (A)  
- `get_power(channel: int) -> float`    (W)

### 2.5 Raw passthrough

- `write_raw(cmd: str) -> None` — send a SCPI command with completion and error checks.  
- `query_raw(cmd: str) -> str` — send a SCPI query with error checks.  
- `write_direct(cmd: str) -> None` — send a command without `*OPC?` or `SYST:ERR?` checks.  
- `query_direct(cmd: str) -> str` — send a query without error checks.

### 2.6 Errors

Common exceptions: `NotConnectedError`, `ChannelError`, `RangeError`, `SCPIError`, `NotSupportedError`.


## 3. Determinism and Safety (for LLM codegen)

- **Connect** wiring with inputs **OFF**.  
- **Configure** setpoints with inputs **OFF**.  
- **Apply/Enable** using `set_output(channel, True)` only when safe.  
- Select exactly **one** of `set_current/voltage/power` before enabling input.  
- Always disable input with `set_output(False)` before rewiring.  
- Do not infer channels, limits, or ranges; require explicit parameters from the test.


## 4. Machine‑Readable Method Table (JSON)

```json
{
  "methods": [
    {"name":"connect","args":[],"returns":"None","notes":"Open VISA resource"},
    {"name":"initialize","args":[],"returns":"None","notes":"Detect adapter via *IDN? and run startup"},
    {"name":"close","args":[],"returns":"None","notes":"Shutdown adapter and close session"},

    {"name":"set_timeout","args":[["timeout_ms","int"]],"returns":"None"},

    {"name":"configure_serial",
     "args":[["baud","int|null"],["data_bits","int|null"],["stop_bits","int|null"],
             ["parity","any|null"],["write_termination","str|null"],["read_termination","str|null"]],
     "returns":"None",
     "notes":"Use for ASRL resources"},

    {"name":"set_current","args":[["channel","int"],["amps","float"]],"returns":"None","notes":"CC mode"},
    {"name":"set_voltage","args":[["channel","int"],["volts","float"]],"returns":"None","notes":"CV mode"},
    {"name":"set_power","args":[["channel","int"],["watts","float"]],"returns":"None","notes":"CP mode"},
    {"name":"set_output","args":[["channel","int"],["on","bool"]],"returns":"None"},
    {"name":"output_all","args":[["on","bool"]],"returns":"None","notes":"Best effort across channels"},

    {"name":"get_voltage","args":[["channel","int"]],"returns":"float"},
    {"name":"get_current","args":[["channel","int"]],"returns":"float"},
    {"name":"get_power","args":[["channel","int"]],"returns":"float"},

    {"name":"write_raw","args":[["cmd","str"]],"returns":"None","notes":"With OPC and error checks"},
    {"name":"query_raw","args":[["cmd","str"]],"returns":"str","notes":"With error checks"},
    {"name":"write_direct","args":[["cmd","str"]],"returns":"None","notes":"No OPC or error checks"},
    {"name":"query_direct","args":[["cmd","str"]],"returns":"str","notes":"No error checks"}
  ]
}
```


## 5. Minimal Examples

### 5.1 CC 2 A then OFF
```python
el.set_current(1, 2.0)
el.set_output(1, True)
v,i,p = el.get_voltage(1), el.get_current(1), el.get_power(1)
el.set_output(1, False)
```

### 5.2 Switch mode
```python
el.set_voltage(1, 12.0)   # CV
el.set_power(1, 60.0)     # CP takes effect now
```
