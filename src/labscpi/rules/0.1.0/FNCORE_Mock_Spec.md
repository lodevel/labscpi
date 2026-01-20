---
doc_id: fncore-mock-spec-v1
title: FNCORE Mock Device Profile — Line Protocol and Semantics (Deprecated)
type: device_profile
domain: controller
language: en
version: 1.0.0
status: deprecated
effective_date: 2025-11-04
audience: [llm, firmware, test]
product: FNCORE
class_name: FncoreMockProfile
transports: [ASRL]
standards: []
commands_index:
  - writeDigital
  - readDigital
  - writePWM
  - writeAnalog
  - readAnalog
  - uartSend
required_params: [FNCORE_PORT, FNCORE_BAUD, FNCORE_TIMEOUT]
dac_scaling: {bits: 12, vref: 3.3, bipolar: false}
manual_override_prompt: true
logging_fields: [cmd, resp, requested_volts, code]
synonyms:
  controller: [mcu, dsc]
  writeAnalog: [dac, analog_out]
replaced_by: fncore-mock-client-usage-v1
related: [fncore-mock-client-usage-v1, test-rules-llm-ready-v1]
checksum: 4f39ff18087cb0fa09dd72a51e79dea6e7d60a1928b87f7c2ba16e326466a527
---


> **Deprecated:** Raw FNCORE commands are no longer emitted.  
> Manual override, DAC scaling, and logging are implemented directly in the driver (`fncore_mockup_client.py`)  
> and detailed in the usage guide (`fncore_mockup_client_llm_usage.md`).  
> This document is preserved only for historical reference.


# FNCORE_Mock_Spec.md

**profile_id:** FNCORE_MOCK  
**version:** 1.0.0  
**scope:** Defines the FNCORE **mockup** behavior for LLM code generation. Use only when `{DEVICE_PROFILE} = "FNCORE_MOCK"`.

## 1) Command set and line protocol
Each command is one ASCII line terminated by `\n`. The set is:

| Command            | Syntax                                     | Notes |
|-------------------|---------------------------------------------|-------|
| Digital output     | `writeDigital <TARGET> <IO_ID> <0|1>`       | Set IO LOW(0) or HIGH(1). |
| Digital input      | `readDigital <TARGET> <IO_ID>`              | Returns `0` or `1`. |
| PWM output         | `writePWM <TARGET> <PWM_ID> <duty8bit>`     | Duty 0–255; frequency fixed by mock. |
| **Analog output**  | `writeAnalog <TARGET> <DAC_ID> <code>`      | `<code>` is raw DAC register (see §3). |
| Analog input       | `readAnalog <TARGET> <ADC_ID>`              | Returns numeric value. |
| UART transmit      | `uartSend <TARGET> <UART_ID> "<payload>"`   | Payload in double quotes. |

`<TARGET>` tags the MCU/subsystem (e.g., `DSC`). Resource IDs follow the test text (e.g., `IO#18`, `DAC#0`). The set is closed; do not invent variants.

## 2) Connection defaults
- Transport: serial (8N1), no flow control.  
- Parameters from preflight: `{FNCORE_PORT}`, `{FNCORE_BAUD}`, `{FNCORE_TIMEOUT}`.  
- Open with timeout = `{FNCORE_TIMEOUT}` for both read and write.  
- If **manual override** is enabled, do not open serial; see §5.

## 3) DAC scaling (volts → raw code)
- Mapping: **12‑bit, 3.3 V, unipolar**.  
- Conversion:  
  `code = round( clamp(V_out / 3.3, 0, 1 ) * 4095 )`  
  Clamp final code to `[0, 4095]`.  
- Emit: `writeAnalog <TARGET> DAC#<id> <code>`  
- Always log both the **requested volts** and the **emitted code**.  
- Example: request `1.000 V` → `1241` → `writeAnalog DSC DAC#0 1241`.

## 4) Required preflight parameters
- Automatic mode: `["FNCORE_PORT","FNCORE_BAUD","FNCORE_TIMEOUT"]` are mandatory.  
- Manual override: these may be omitted.

## 5) Manual override prompt (mandatory)
Use exactly:
```
print(f"MANUAL_EXEC: {cmd}")
prompt("On the device console, type exactly:\n " + cmd + "\nPress Enter here when done (type 'ok').")
```

No vague prompts; the operator must see the precise line to type.

## 6) Logging
For every command, store `{ "cmd": "<line>", "resp": "<one-line response>" }`.  
For DAC writes add `requested_volts` and `code`. Log even if response is `OK`.

## 7) Examples (request → emitted line)
- EPO high: “Set DSC IO#18 = 1” → `writeDigital DSC IO#18 1`  
- CHG_NCTRL low: “Set DSC IO#42 = 0” → `writeDigital DSC IO#42 0`  
- ISET to 1.0 V: “Set DSC DAC#0 = 1.0 V” → `writeAnalog DSC DAC#0 1241`  
- Read ADC: “Measure DSC ADC#0” → `readAnalog DSC ADC#0`

## 8) Machine‑readable descriptor
```json
{
  "profile_id": "FNCORE_MOCK",
  "version": "1.0.0",
  "required_params": ["FNCORE_PORT","FNCORE_BAUD","FNCORE_TIMEOUT"],
  "commands": {
    "writeDigital": {"args": ["<TARGET>","<IO_ID>","<0|1>"]},
    "readDigital":  {"args": ["<TARGET>","<IO_ID>"]},
    "writePWM":     {"args": ["<TARGET>","<PWM_ID>","<duty8bit>"]},
    "writeAnalog":  {"args": ["<TARGET>","<DAC_ID>","<code>"], "value_semantics": "12bit_code_for_3.3V_unipolar"},
    "readAnalog":   {"args": ["<TARGET>","<ADC_ID>"]},
    "uartSend":     {"args": ["<TARGET>","<UART_ID>","<payload>"]}
  },
  "connection_defaults": {"format": "serial", "databits": 8, "parity": "N", "stopbits": 1, "flow": "none"},
  "manual_override_prompt": "print(f\"MANUAL_EXEC: {cmd}\")\\nprompt(\"On the device console, type exactly:\\n  \" + cmd + \"\\nPress Enter here when done (type 'ok').\")",
  "logging": {"include": ["cmd","resp","requested_volts","code"]}
}
