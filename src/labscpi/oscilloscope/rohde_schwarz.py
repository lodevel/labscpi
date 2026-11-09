"""Rohde & Schwarz oscilloscope adapter — moved VERBATIM from
labscpi.oscilloscope_scpi. RohdeSchwarzScope is the brand's ONE general
adapter (no MODEL_PATTERNS): it wins stage 1 of pick_adapter on the IDN
vendor field; there are no R&S model adapters yet.
"""
from __future__ import annotations

from .base import BaseAdapter, BrandAdapter

class RohdeSchwarzScope(BrandAdapter):
    brand = "Rohde&Schwarz"
    vendor_aliases = ("R&S", "R\u0026S", "ROHDE")

    TOKEN_MAP = BaseAdapter.TOKEN_MAP | {
        # R&S RTx/RTB hardware exposes bare :MEAS:DEL / :MEAS:PHASe and
        # has no edge-locked items. The grammar still requires the
        # operator to author with an explicit edge (RR_/RF_/FR_/FF_);
        # at the wire level we collapse all 8 onto the bare commands
        # so the scope's last-configured edges (set earlier in the
        # procedure) carry the operator's edge intent. Vendors adding
        # native edge-locked commands later can override this.
        "measure": BaseAdapter.TOKEN_MAP["measure"] | {
            "RR_DELAY": "DEL", "RF_DELAY": "DEL",
            "FR_DELAY": "DEL", "FF_DELAY": "DEL",
            "RR_PHASE": "PHASe", "RF_PHASE": "PHASe",
            "FR_PHASE": "PHASe", "FF_PHASE": "PHASe",
        },
    }

    def screenshot_png(self) -> bytes:
        self.s.write(":HCOP:DEV:LANG PNG")
        self.s.write(":HCOP:IMM")
        return self.resource_read_raw()
