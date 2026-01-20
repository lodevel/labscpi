---
doc_id: fncore-mock-client-usage-v1
title: FNCORE Mockup Client — LLM Usage Guide
type: usage_guide
domain: controller
language: en
version: 1.0.0
status: current
effective_date: 2025-11-04
audience: [llm, test, firmware]
product: FNCORE
class_name: FncoreMockupClient
facade_module: fncore_mockup_client
transports: [ASRL]
methods_index:
  - write_digital
  - read_digital
  - write_pwm
  - write_analog_volts
  - read_analog
  - uart_send
manual_override_prompt: true
logging_fields: [cmd, resp, requested_volts, code]
default_baud: 115200
timeout_s_default: 2.0
supports_manual_override: true
synonyms:
  controller: [mcu, dsc]
  manual_override: [dry_run, operator_mode]
related: [fncore-mock-spec-v1, test-rules-llm-ready-v1]
checksum: 5fed84ed8a117336dcbf62d7ad81bb4cf45d88f46c6db3188b1bd91c3563c590
---


> **Note:** This is the authoritative FNCORE reference. It replaces the deprecated `FNCORE_Mock_Spec.md`.

# FNCORE Mockup Client — LLM Usage Guide

## Goal
Control a FNCORE-based DUT via a simple serial line protocol while writing readable, auditable test code. This class wraps ASCII commands and keeps a structured log for each action.

## Import
```python
from fncore_mockup_driver import FncoreMockupClient as FncoreClient
```

## Lifecycle
1. Construct with connection parameters and a shared `controller_log` list.
2. Call command methods.
3. Call `close()` in `finally`.

```python
controller_log = []
fn = FncoreClient(port="COM7", baud=115200, timeout_s=2.0,
                  log_list=controller_log, manual_override=False)

try:
    fn.write_digital("DSC", "IO#DSC18", 1)
finally:
    fn.close()
```

## Constructor
```python
FncoreClient(port, baud, timeout_s, log_list, manual_override=False)
```
- `port`: e.g., `"COM7"`, `"/dev/ttyUSB0"`.
- `baud`: integer. Typical `115200`.
- `timeout_s`: float seconds for serial read.
- `log_list`: a Python list that collects dict entries per command.
- `manual_override`: if `True`, no serial I/O; prints the exact line and waits for operator confirmation.

## Manual-override semantics
- Prints `MANUAL_EXEC: <command>` and prompts the operator to type it on the device console.
- Methods return `"OK"` for writes and still append to `controller_log`.
- Use when hardware is unavailable or during dry runs.

## Commands
All commands include a `TARGET` namespace (e.g., `"DSC"`).

### `write_digital(TARGET, io_id, val01)`
Set a digital output.
```python
fn.write_digital("DSC", "IO#DSC41", 1)   # drive high
```

### `read_digital(TARGET, io_id) -> int|str`
Read a digital input.
```python
state = fn.read_digital("DSC", "IO#DSC5")
```

### `write_pwm(TARGET, pwm_id, duty8bit)`
Set an 8-bit PWM duty (0–255).
```python
fn.write_pwm("DSC", "PWM#DSC0", 128)     # ≈50% duty
```

### `write_analog_volts(TARGET, dac_id, volts) -> dict`
Write a DAC voltage. `0.0…3.3 V` maps to `0…4095`.
```python
rec = fn.write_analog_volts("DSC", "DAC#DSC0", 3.3)
```

### `read_analog(TARGET, adc_id) -> float|str`
Read an analog input.
```python
v = fn.read_analog("DSC", "ADC#DSC2")
```

### `uart_send(TARGET, uart_id, payload)`
Send a UART frame.
```python
fn.uart_send("DSC", "UART#0", "HELLO")
```

## Logging
Each method appends a dict to `controller_log`.
```json
{
  "cmd": "writeAnalog DSC DAC#DSC0 4095",
  "resp": "OK",
  "requested_volts": 3.3,
  "code": 4095
}
```

## Patterns for LLM-generated tests

## Minimal example
```python
from fncore_mockup_driver import FncoreMockupClient as FncoreClient
controller_log = []
fn = FncoreClient("COM7", 115200, 2.0, controller_log, manual_override=False)

try:
    # Step 1 — Enable charger control so PPU path is active
    fn.write_digital("DSC", "IO#DSC41", 1)
    # Step 2 — Drive DAC to nominal command
    fn.write_analog_volts("DSC", "DAC#DSC0", 3.3)
    # Step 3 — Verify status input
    ok = int(fn.read_digital("DSC", "IO#DSC12")) == 1
    # Step 4 — Sample a feedback node
    fb_v = float(fn.read_analog("DSC", "ADC#DSC3"))
    # Step 5 — Send a diagnostic string over UART
    fn.uart_send("DSC", "UART#0", "PING")
finally:
    fn.close()
print(controller_log)
```

## Error handling rules
- Always `close()` in `finally`.
- Treat non-parseable numeric reads as failure. Keep raw.
- No retries by default. If needed, max 1 retry with 100 ms delay.
- Clip inputs: PWM 0–255, DAC 0.0–3.3 V, digital 0/1.
- Never assume default `TARGET`.
- In manual mode, methods return `"OK"` for writes; reads are **UNVERIFIED** if used in assertions.
