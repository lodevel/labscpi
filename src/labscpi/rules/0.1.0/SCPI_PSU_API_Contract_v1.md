---
doc_id: scpi-psu-api-v1
title: SCPI Power Supply Driver — Public API Contract
type: api_contract
domain: instrumentation
language: en
version: 1.0.0
status: current
effective_date: 2025-11-04
audience: [llm, test, firmware]
product: SCPI_PSU
class_name: PowerSupply
transports: [ASRL, TCPIP, USB, GPIB]
standards: [SCPI, VISA]
methods_index:
  - connect
  - initialize
  - close
  - set_timeout
  - configure_serial
  - set_voltage
  - set_current
  - output
  - output_all
  - measure_voltage
  - measure_current
  - set_ovp
  - set_ocp
  - sense_remote
  - tracking
  - write_raw
  - query_raw
  - write_direct
  - query_direct
enums_index:
  TrackingMode: [INDEP, SERIES, PARALLEL]
exceptions: [NotConnectedError, ChannelError, RangeError, SCPIError, NotSupportedError]
units: [V, A]
channels_base: 1
safety_notes: true
synonyms:
  psu: [power supply, source]
  channel: [output]
related: [scpi-oscilloscope-api-v1, scpi-eload-api-v1, test-rules-llm-ready-v1]
checksum: af078b6848f6f30eba21a06487e2ac08c73b63e297724b10330abb3fb7ba4d53
---

# SCPI Power Supply Driver — Public API Contract (Façade Only)

This is the **authoritative** public interface for `psu_scpi.PowerSupply`. It excludes internal adapter details and model-specific SCPI variants.

---

## Usage

```python
from psu_scpi import PowerSupply

psu = PowerSupply("USB0::0x1AB1::0x0E11::DP8C123456::INSTR", timeout_ms=5000)
psu.connect()
psu.initialize()

psu.set_voltage(1, 5.0)
psu.set_current(1, 0.50)
psu.output(1, True)
v = psu.measure_voltage(1)
i = psu.measure_current(1)

psu.close()
```

Notes:
- All methods are synchronous. Each write waits for completion and surfaces SCPI errors.
- Channels are **1-based**.
- Brand/model detection uses `*IDN?` and selects a lightweight adapter (Rigol, Rohde&Schwarz, Aim-TTi, EA Elektro-Automatik, or a Generic fallback).

---

## Types

### `TrackingMode` tokens

```
INDEP, SERIES, PARALLEL
```

Availability is model dependent.

---

## API reference

### Connection
- `connect() -> None`  
  Open VISA resource and set IO parameters.
- `initialize() -> None`  
  Query `*IDN?`, select adapter, run adapter startup hook.
- `close() -> None`  
  Run adapter shutdown hook and close the VISA resource. Safe to call multiple times.

### Session configuration
- `set_timeout(timeout_ms: int) -> None`  
  Set VISA timeout (ms) on the live session.
- `configure_serial(*, baud: int|None = None, data_bits: int|None = None, stop_bits: int|None = None, parity: Any|None = None, write_termination: str|None = None, read_termination: str|None = None) -> None`  
  Configure ASRL parameters before `initialize()` for serial resources.

### Output configuration and control
- `set_voltage(channel: int, volts: float) -> None`  
  Set voltage setpoint. May verify via `SOUR:VOLT?` and raise on mismatch.
- `set_current(channel: int, amps: float) -> None`  
  Set current setpoint. May verify via `SOUR:CURR?` and raise on mismatch.
- `output(channel: int, on: bool) -> None`  
  Enable or disable the selected output (per-channel where supported).
- `output_all(on: bool) -> None`  
  Enable or disable all outputs if supported; otherwise best-effort per channel.

### Measurements
- `measure_voltage(channel: int) -> float`  
  Read measured output voltage (V).
- `measure_current(channel: int) -> float`  
  Read measured output current (A).

### Protections and sense
- `set_ovp(channel: int, volts: float, on: bool = True) -> None`  
  Configure over-voltage protection and enable/disable it (model dependent).
- `set_ocp(channel: int, amps: float, on: bool = True) -> None`  
  Configure over-current protection and enable/disable it (model dependent).
- `sense_remote(channel: int, on: bool) -> None`  
  Toggle remote sensing, if available.
- `tracking(mode: str) -> None`  
  Set tracking mode token: `"INDEP"|"SERIES"|"PARALLEL"` (model dependent).

### Raw passthrough
- `write_raw(cmd: str) -> None`  
  Send a SCPI command with completion and error checks.
- `query_raw(cmd: str) -> str`  
  Send a SCPI query with error checks.
- `write_direct(cmd: str) -> None`  
  Send a command without `*OPC?` or `SYST:ERR?` checks.
- `query_direct(cmd: str) -> str`  
  Send a query without error checks.

### Errors
Common exceptions: `NotConnectedError`, `ChannelError`, `RangeError`, `SCPIError`, `NotSupportedError`.

---

## Behavior notes

- After each write, the session performs `*OPC?` and drains `SYST:ERR?` to surface device errors.
- Adapter startup/shutdown may run on certain models (e.g., panel lock on some EA units).
- Brand/model specifics are isolated inside adapters; the façade remains stable.

---

## Machine-readable method table (JSON)

```json
{
  "types": {
    "TrackingMode": ["INDEP","SERIES","PARALLEL"]
  },
  "methods": [
    {"name":"connect","args":[],"returns":"None","notes":"Open VISA resource"},
    {"name":"initialize","args":[],"returns":"None","notes":"Detect adapter via *IDN? and run startup"},
    {"name":"close","args":[],"returns":"None","notes":"Shutdown adapter and close session"},

    {"name":"set_timeout","args":[["timeout_ms","int"]],"returns":"None"},

    {"name":"configure_serial",
     "args":[["baud","int|null"],["data_bits","int|null"],["stop_bits","int|null"],
             ["parity","any|null"],["write_termination","str|null"],["read_termination","str|null"]],
     "returns":"None",
     "notes":"Use for ASRL before initialize()"},

    {"name":"set_voltage","args":[["channel","int"],["volts","float"]],"returns":"None",
     "notes":"May verify setpoint and raise on mismatch"},
    {"name":"set_current","args":[["channel","int"],["amps","float"]],"returns":"None",
     "notes":"May verify setpoint and raise on mismatch"},
    {"name":"output","args":[["channel","int"],["on","bool"]],"returns":"None"},
    {"name":"output_all","args":[["on","bool"]],"returns":"None","notes":"Best effort across channels"},

    {"name":"measure_voltage","args":[["channel","int"]],"returns":"float"},
    {"name":"measure_current","args":[["channel","int"]],"returns":"float"},

    {"name":"set_ovp","args":[["channel","int"],["volts","float"],["on","bool",true]],"returns":"None"},
    {"name":"set_ocp","args":[["channel","int"],["amps","float"],["on","bool",true]],"returns":"None"},
    {"name":"sense_remote","args":[["channel","int"],["on","bool"]],"returns":"None"},
    {"name":"tracking","args":[["mode","str"]],"returns":"None","notes":"mode in {INDEP,SERIES,PARALLEL}"},

    {"name":"write_raw","args":[["cmd","str"]],"returns":"None","notes":"With OPC and error checks"},
    {"name":"query_raw","args":[["cmd","str"]],"returns":"str","notes":"With error checks"},
    {"name":"write_direct","args":[["cmd","str"]],"returns":"None","notes":"No OPC or error checks"},
    {"name":"query_direct","args":[["cmd","str"]],"returns":"str","notes":"No error checks"}
  ]
}
```