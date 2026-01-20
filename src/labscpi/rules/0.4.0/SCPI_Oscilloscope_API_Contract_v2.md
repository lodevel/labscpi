---
doc_id: scpi-oscilloscope-api-v2
title: SCPI Oscilloscope Driver — Public API Contract
type: api_contract
domain: instrumentation
language: en
version: 2.0.0
status: current
effective_date: 2025-11-04
audience: [llm, test, firmware]
product: SCPI_SCOPE
class_name: Oscilloscope
transports: [TCPIP, USB, ASRL, GPIB]
standards: [SCPI, VISA]
methods_index:
  - connect
  - initialize
  - close
  - reset
  - set_time_scale
  - get_time_scale
  - set_time_position
  - set_channel_scale
  - set_channel_offset
  - set_channel_coupling
  - set_channel_enabled
  - is_channel_enabled
  - set_channel_units
  - get_channel_units
  - set_probe_attenuation
  - get_probe_attenuation
  - set_probe_sensitivity
  - get_probe_sensitivity
  - set_trigger
  - set_trigger_sweep
  - get_trigger_sweep
  - get_trigger_status
  - run
  - stop
  - single
  - force_trigger
  - wait_for_acq_complete
  - set_math_source
  - set_math_operator
  - set_math_enabled
  - enable_math
  - set_math_scale
  - set_math_offset
  - enable_measure
  - get_measure
  - enable_measure_stats
  - clear_measure_stats
  - clear_measures
  - measure_stats
  - screenshot_png
  - menu_off
  - write_raw
  - query_raw
  - clear_io
  - autoscale_channel
enums_index:
  Measure: [VPP, VMAX, VMIN, TOP, BASE, AVG, RMS, FREQ, PERIOD, RISE, FALL, PDUTY, NDUTY, PWID, NWID, PHASE, DELAY]
  TriggerSweepMode: [AUTO, NORM, SINGLE]
  ChannelUnit: [VOLT, AMP]
  MathOperator: [ADD, SUBTRACT, MULTIPLY, DIVIDE, FFT, AVERAGE]
exceptions: [NotConnectedError, RangeError, SCPIError, NotSupportedError]
units: [V, A, s, Hz]
channels_base: 1
safety_notes: true
synonyms:
  scope: [oscilloscope, DSO]
  trigger: [acquisition, single-shot]
related: [scpi-psu-api-v1, scpi-eload-api-v1, test-rules-llm-ready-v1]
checksum: e608a8e0da36218e500086366b84062e73d01f3853cfaff2a91f190ba84cc95d
---


# SCPI Oscilloscope Driver — Public API Contract (Façade Only)

This is the **authoritative** public interface for code generation. It excludes internal details and brand SCPI differences.

## Usage

```python
from oscilloscope_scpi import Oscilloscope, Measure

scope = Oscilloscope("TCPIP0::192.168.0.10::INSTR", timeout_ms=3000)
scope.connect()
scope.initialize()

# Work with the scope ...
scope.close()
```

All methods are synchronous. `single()` does **not** block for a trigger. Use `wait_for_acq_complete()` to wait explicitly.

## Acquisition state constraints
Some operations require a completed acquisition frame. If the oscilloscope is in Single (armed) and has not triggered, these calls must not proceed:

- screenshot_png()
- get_measure(...), enable_measure(...), measure_stats(...) when they operate on the current frame
- read_waveform(...), and any API that pulls the latest frame

Required behavior:
- When armed and not yet triggered, do not proceed. Clients should call wait_for_acq_complete(timeout_ms) and, if False, force_trigger() or re-arm.

Portable pattern:
1) Arm: single()
2) Wait: ok = wait_for_acq_complete(timeout_ms)
3) If not ok: force_trigger()
3b) Wait again: ok = wait_for_acq_complete(timeout_ms)
4) Then call the operation (e.g., screenshot_png()).




## Types

### `Measure` enum (canonical tokens)

```
VPP, VMAX, VMIN, TOP, BASE, AVG, RMS,
FREQ, PERIOD, RISE, FALL, PDUTY, NDUTY, PWID, NWID,
PHASE, DELAY
```

Arity:
- Single‑source: all except the two below.
- Two‑source: `PHASE`, `DELAY` require both `src` and `src2` (default for omitted `src2` is `"CHAN2"`).

### `TriggerSweepMode` enum (canonical tokens)

AUTO, NORM, SINGLE

### ChannelUnit enum (canonical tokens)
VOLT, AMP

Notes: Enum keeps the public API vendor‑agnostic. Adapters map enum → vendor token (e.g., VOLT → "VOLT", AMP → "AMP").

### `MathOperator` enum (canonical tokens)

ADD, SUBTRACT, MULTIPLY, DIVIDE, INTEGRATE, DIFFERENTIATE,
FFT, FFT_PHASE, SQRT, MAGNIFY, ABSOLUTE, SQUARE, LN, LOG, EXP, TEN,
LOWPASS, HIGHPASS, BANDPASS, AVERAGE, LINEAR, MAXIMUM, MINIMUM, PEAK,
MAXHOLD, MINHOLD, TREND, BTIMING, BSTATE, SERCHART

### Channel/source strings

Sources are strings like `"CHAN1"`, `"CHAN2"`. Channels are 1‑based.


## API reference

### Connection
- `connect() -> None`
- `initialize() -> None`
- `close() -> None`
- `reset(opc_timeout_ms: int = 8000) -> None`

### Timebase
- `set_time_scale(sec_per_div: float) -> None`
- `get_time_scale() -> float`
- `set_time_position(sec: float) -> None`

### Vertical (per channel)
- `get_channel_scale(ch: int) -> float`
- `get_channel_offset(ch: int) -> float`
- `set_channel_scale(ch: int, v_per_div: float) -> None`
- `set_channel_offset(ch: int, volts: float) -> None`
- `set_channel_coupling(ch: int, mode: str) -> None`  (`"DC"|"AC"|"GND"`)
- `set_channel_enabled(ch: int, on: bool) -> None`
- `is_channel_enabled(ch: int) -> bool | None`
- `set_channel_units(ch: int, unit: ChannelUnit | str) -> None`
- `get_channel_units(ch: int) -> ChannelUnit | str`

- `autoscale_channel(ch, *, max_iters=20) -> (v_per_div, offset)` adjusts V/div and offset on the specified channel to fit ≈80% of the screen. It does not change timebase or trigger settings. Use for steady-state signals only, not single-shot captures. After autoscale, re-apply any required timebase and ensure a completed frame before calling frame-dependent APIs.

### Probe (per channel)
- `set_probe_attenuation(ch: int, factor: float) -> None`
- `get_probe_attenuation(ch: int) -> float → returns attenuation factor`
- `set_probe_sensitivity(ch: int, v_per_a: float) -> None → convenience. sets attenuation = 1 / v_per_a`
- `get_probe_sensitivity(ch: int) -> float → returns V/A sensitivity (1 / attenuation)`

Notes: Sensitivity is for current probes (e.g., 10 V/A).

### Trigger and run control
- `set_trigger(*, edge_src: str = "CHAN1", level: float = 0.0, slope: str = "POS") -> None`
- `set_trigger_sweep(mode: TriggerSweepMode | str) -> None`
- `get_trigger_sweep() -> TriggerSweepMode | str`
- `get_trigger_status() -> bool → True if a trigger occurred since last read; clears the event.`
- `run() -> None`
- `stop() -> None`
- `single() -> None`  _(non‑blocking)_
- `force_trigger() -> None`

### **Operation completion**
- `wait_for_single_acq_complete(timeout_ms: int = 10000) -> bool`  
  Blocks until the current acquisition completes or times out. Returns `True` on completion, `False` on timeout.

### Math

- `set_math_source(math: int, slot: int, src: string) -> None // slot ∈ {1,2}`
- `set_math_operator(math: int, op: MathOp | string = "ADD") -> None`
- `set_math_enabled(math: int, on: bool) -> None`
- `enable_math(math: int, on: bool, op: MathOp | string = "ADD") -> None`
Note: does not set sources; use set_math_source for slot 1 and 2.

- `set_math_scale(math: int, v_per_div: float) -> None`
- `set_math_offset(math: int, volts: float) -> None`

### Measurements
- `enable_measure(kind: Measure | str, src: str = "CHAN1", src2: str | None = None) -> None`
- `get_measure(kind: Measure | str,   src: str = "CHAN1", src2: str | None = None) -> float`
- `enable_measure_stats(on: bool = True) -> None`
- `clear_measure_stats() -> None`
- `clear_measures() -> None`
- `measure_stats(kind: Measure | str, src: str = "CHAN1") -> dict`  → `{"MEAN","MIN","MAX","STD"}`

Notes: requires a completed acquisition; in Single pre-trigger, call wait_for_acq_complete(...) or force_trigger() first. **If wait_for_acq_complete(...) returns False, force_trigger() then call wait_for_acq_complete(...) again before proceeding.**


### Display / UI
- `menu_off() -> None`

Turns off on-screen softkeys/menus to produce a clean screenshot.


### Screenshot
- `screenshot_png() -> bytes`

Notes: requires a completed acquisition; in Single pre-trigger, call wait_for_acq_complete(...) or force_trigger() first. **If wait_for_acq_complete(...) returns False, force_trigger() then call wait_for_acq_complete(...) again before proceeding.**


### Raw passthrough and optional I/O cleanup
- `write_raw(cmd: str) -> None`
- `query_raw(cmd: str) -> str`
- `clear_io() -> None`



## Machine‑readable method table (JSON)

```json
{
  "types": {
    "Measure": ["VPP","VMAX","VMIN","TOP","BASE","AVG","RMS",
                "FREQ","PERIOD","RISE","FALL","PDUTY","NDUTY","PWID","NWID",
                "PHASE","DELAY"],
    "ChannelUnit": ["VOLT","AMP"],
    "TriggerSweepMode": ["AUTO","NORM","SINGLE"],
    "MathOperator": ["ADD","SUBTRACT","MULTIPLY","DIVIDE","INTEGRATE","DIFFERENTIATE",
                 "FFT","FFT_PHASE","SQRT","MAGNIFY","ABSOLUTE","SQUARE","LN","LOG","EXP","TEN",
                 "LOWPASS","HIGHPASS","BANDPASS","AVERAGE","LINEAR","MAXIMUM","MINIMUM","PEAK",
                 "MAXHOLD","MINHOLD","TREND","BTIMING","BSTATE","SERCHART"]
  },
  "methods": [
    {"name":"connect","args":[],"returns":"None","notes":"Open VISA resource"},
    {"name":"initialize","args":[],"returns":"None","notes":"Detects adapter via *IDN?"},
    {"name":"close","args":[],"returns":"None","notes":"Close session"},
    {"name":"reset","args":[["opc_timeout_ms","int",5000]],"returns":"None","notes":"Hard reset via *RST, *CLS, *OPC?; clears settings"},


    {"name":"set_time_scale","args":[["sec_per_div","float"]],"returns":"None"},
    {"name":"get_time_scale","args":[],"returns":"float"},
    {"name":"set_time_position","args":[["sec","float"]],"returns":"None"},

    {"name":"set_channel_scale","args":[["ch","int"],["v_per_div","float"]],"returns":"None"},
    {"name":"set_channel_offset","args":[["ch","int"],["volts","float"]],"returns":"None"},
    {"name":"get_channel_scale","args":[["ch","int"]],"returns":"float"},
    {"name":"get_channel_offset","args":[["ch","int"]],"returns":"float"},
    {"name":"set_channel_coupling","args":[["ch","int"],["mode","str"]],"returns":"None","notes":"mode in {DC,AC,GND}"},
    {"name":"set_channel_enabled","args":[["ch","int"],["on","bool"]],"returns":"None"},
    {"name":"is_channel_enabled","args":[["ch","int"]],"returns":"bool|null"},
    {"name":"set_channel_units","args":[["ch","int"],["unit","ChannelUnit|string"]],"returns":"None"},
    {"name":"get_channel_units","args":[["ch","int"]],"returns":"ChannelUnit|string"},

    {"name":"set_probe_attenuation","args":[["ch","int"],["factor","float"]],"returns":"None"},
    {"name":"get_probe_attenuation","args":[["ch","int"]],"returns":"float"},
    {"name":"set_probe_sensitivity","args":[["ch","int"],["v_per_a","float"]],"returns":"None","notes":"sets attenuation = 1/sensitivity"},
    {"name":"get_probe_sensitivity","args":[["ch","int"]],"returns":"float","notes":"returns 1/attenuation (V/A)"},

    {"name":"set_trigger","args":[["edge_src","str","CHAN1"],["level","float",0.0],["slope","str","POS"]],"returns":"None"},
    {"name":"set_trigger_sweep","args":[["mode","TriggerSweepMode|string"]],"returns":"None"},
    {"name":"get_trigger_sweep","args":[],"returns":"TriggerSweepMode|string"},
    {"name":"get_trigger_status","args":[],"returns":"bool"},

    {"name":"run","args":[],"returns":"None"},
    {"name":"stop","args":[],"returns":"None"},
    {"name":"single","args":[],"returns":"None","notes":"non-blocking"},
    {"name":"force_trigger","args":[],"returns":"None"},

    {"name":"wait_for_single_acq_complete","args":[["timeout_ms","int",10000]],"returns":"bool","notes":"True on completion; False on timeout; in Single, if False then clients must force_trigger() and wait again before frame-dependent operations"},

    {"name":"set_math_source","args":[["math","int"],["slot","int"],["src","string"]],"returns":"None"},
    {"name":"set_math_operator","args":[["math","int"],["op","MathOp|string"]],"returns":"None"},
    {"name":"set_math_enabled","args":[["math","int"],["on","bool"]],"returns":"None"},
    {"name":"enable_math","args":[["math","int"],["on","bool"],["op","MathOp|string"]],"returns":"None"},
    {"name":"set_math_scale","args":[["math","int"],["v_per_div","float"]],"returns":"None"},
    {"name":"set_math_offset","args":[["math","int"],["volts","float"]],"returns":"None"},

    {"name":"enable_measure","args":[["kind","Measure|str"],["src","str","CHAN1"],["src2","str|null","auto for PHASE/DELAY"]],"returns":"None"},
    {"name":"get_measure","args":[["kind","Measure|str"],["src","str","CHAN1"],["src2","str|null","auto for PHASE/DELAY"]],"returns":"float"},
    {"name":"enable_measure_stats","args":[["on","bool",true]],"returns":"None"},
    {"name":"clear_measure_stats","args":[],"returns":"None"},
    {"name":"clear_measures","args":[],"returns":"None"},
    {"name":"measure_stats","args":[["kind","Measure|str"],["src","str","CHAN1"]],"returns":"object"},

    {"name":"screenshot_png","args":[],"returns":"bytes","notes":"Requires completed acquisition; in Single pre-trigger call wait_for_acq_complete(...) or force_trigger() first; if wait returns False, force_trigger() then wait again before proceeding"},
	{"name":"menu_off","args":[],"returns":"None","notes":"Hide on-screen menu/softkeys before screenshots; NotSupportedError if unavailable"},
    {"name":"write_raw","args":[["cmd","str"]],"returns":"None"},
    {"name":"query_raw","args":[["cmd","str"]],"returns":"str"},
    {"name":"clear_io","args":[],"returns":"None"},
	
	{"name":"autoscale_channel","args":[["ch","int"],["max_iters","int",20]],"returns":"[float,float]","notes":"Vertical-only autoscale to fit ~80% screen; returns (v_per_div, offset)."}
  ]
}
```

