# ruff: noqa: E701, E702
"""Mock scope resource + resource manager (test-only helpers).

Moved VERBATIM from the pre-switch flat module ``labscpi.oscilloscope_scpi``
(see that module's shim docstring). Deliberately contains NO BrandAdapter
subclasses: the package ``__init__`` auto-imports every sibling module
(file-drop contract), so anything defined here must be inert with respect
to the adapter registry.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class MockScopeResource:
    def __init__(self, idn: str = "RIGOL TECHNOLOGIES,MSO2072A,DS2A000001,00.01"):
        self.idn = idn
        self.timeout = 5000
        self.write_termination = "\n"
        self.read_termination = "\n"
        self.state: Dict[str, Any] = {
            "tim:scal": 1e-3, "tim:pos": 0.0,
            "chan": {1: {"scal": 1.0, "offs": 0.0, "coup": "DC"}},
            "trig": {"mode": "EDGE", "src": "CHAN1", "lev": 0.0, "slope": "POS"},
            "err": [],
            "bin": b"\x89PNG\r\n\x1a\n...",  # fake PNG header
        }

    def write(self, cmd: str):
        u = cmd.strip().upper()
        if u.startswith(":TIM:SCAL "): self.state["tim:scal"] = float(cmd.split()[-1])
        elif u.startswith(":TIM:POS "): self.state["tim:pos"] = float(cmd.split()[-1])
        elif ":SCAL " in u and ":CHAN" in u:  # :CHANn:SCAL v
            ch = int(u.split(":CHAN")[1].split(":")[0])
            self.state["chan"].setdefault(ch, {"scal":1.0,"offs":0.0,"coup":"DC"})
            self.state["chan"][ch]["scal"] = float(cmd.split()[-1])
        elif ":OFFS " in u and ":CHAN" in u:
            ch = int(u.split(":CHAN")[1].split(":")[0])
            self.state["chan"].setdefault(ch, {"scal":1.0,"offs":0.0,"coup":"DC"})
            self.state["chan"][ch]["offs"] = float(cmd.split()[-1])
        elif ":COUP " in u and ":CHAN" in u:
            ch = int(u.split(":CHAN")[1].split(":")[0])
            self.state["chan"].setdefault(ch, {"scal":1.0,"offs":0.0,"coup":"DC"})
            self.state["chan"][ch]["coup"] = cmd.split()[-1].upper()
        elif u.startswith(":TRIG:MODE"): self.state["trig"]["mode"] = cmd.split()[-1].upper()
        elif u.startswith(":TRIG:EDGE:SOUR"): self.state["trig"]["src"] = cmd.split()[-1].upper()
        elif u.startswith(":TRIG:EDGE:SLOP"): self.state["trig"]["slope"] = cmd.split()[-1].upper()
        elif u.startswith(":TRIG:LEV"): self.state["trig"]["lev"] = float(cmd.split()[-1])
        elif u in {":RUN", ":STOP", ":SING", ":TFOR"}: pass
        elif u.startswith(":DISP:DATA?"): pass
        elif u == ":HCOP:IMM": pass

    def query(self, cmd: str) -> str:
        u = cmd.strip().upper()
        if u == "*IDN?": return self.idn + "\n"
        if u == "*OPC?": return "1\n"
        if u == "SYST:ERR?": return "0,\"No error\"\n"
        if u == ":TIM:SCAL?": return f"{self.state['tim:scal']}\n"
        return "\n"

    def read_raw(self) -> bytes:
        return self.state["bin"]

    def close(self): pass


class MockResourceManager:
    def __init__(self, resource: Optional[MockScopeResource] = None):
        self._resource = resource or MockScopeResource()
    def open_resource(self, address: str):
        return self._resource


__all__ = ["MockScopeResource", "MockResourceManager"]
