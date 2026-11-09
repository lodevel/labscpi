# ruff: noqa: E402 — import order is load-bearing here: pick_adapter must be
# defined before the auto-import loop (facade.py imports it), and the
# re-exports must come after the loop (the loop is what imports the siblings).
r"""labscpi.oscilloscope — SCPI oscilloscope driver package.

The public ``Oscilloscope`` facade (facade.py) and the vendor adapter
classes (one vendor per sibling module) moved VERBATIM out of
``labscpi.oscilloscope_scpi``, which is now a compatibility shim over this
package.

ADAPTER AUTHORING RULE — this section IS the selection contract:

* To add a vendor: drop a new module into ``labscpi/oscilloscope/`` and
  subclass ``BrandAdapter`` in it. Nothing else — no registry edit, no
  hand-kept list, no import to add anywhere. This ``__init__`` auto-imports
  every sibling module (pkgutil loop below) and
  ``BrandAdapter.__init_subclass__`` (base.py) registers every subclass at
  class-definition time.
* ONE general adapter per brand: exactly one registered class per vendor
  WITHOUT ``MODEL_PATTERNS``. It competes in stage 1 of ``pick_adapter``,
  matching its brand / vendor_aliases substrings against the IDN's VENDOR
  field only.
* Vendor aliases must be DISTINCTIVE: stage 1 matches brand /
  vendor_aliases as SUBSTRINGS of the vendor field, so a short alias
  over-matches — "HP" would hit any vendor whose name merely contains
  those two letters. Use the full vendor string as the instrument reports
  it in *IDN? (e.g. "KEYSIGHT TECHNOLOGIES"), never a 2–3 letter
  abbreviation.
* Model adapters (classes WITH ``MODEL_PATTERNS``) subclass their brand's
  general adapter and compete only in stage 2, scoped to the winning brand.
  Patterns are anchored (start with ``^``) and match the IDN's MODEL field,
  not the raw IDN string.
* Unrelated model adapters within one brand have DISJOINT patterns. When a
  brand has both a series adapter (e.g. ``^MSO5\d{3}``) and a defined model
  (e.g. ``^MSO5040``), the model SUBCLASSES the series; selection picks the
  most specialized hit (the unique leaf). There is deliberately NO
  overlap-error machinery anywhere in selection: overlaps are forbidden by
  this authoring rule, not detected at runtime.
"""
from __future__ import annotations

from .base import (
    _ADAPTERS,
    BaseAdapter,
    BrandAdapter,
    ChannelUnit,
    MathOperator,
    Measure,
    NotConnectedError,
    NotSupportedError,
    RangeError,
    ScopeError,
    SCPIError,
    TriggerSlope,
    TriggerSweepMode,
    require_connected,
    with_retries,
)


# ---------------------------
# Adapter selection (two-stage: brand, then model)
# ---------------------------
# Defined BEFORE the auto-import loop below: facade.py (one of the
# auto-imported siblings) does ``from . import pick_adapter`` at module
# level, so the name must already exist on this partially-initialized
# package when the loop imports it. The _ADAPTERS registry it reads is
# only consulted at call time, after the loop has run.
def pick_adapter(idn: str) -> type[BaseAdapter]:
    """Select the adapter class for an ``*IDN?`` string.

    Two stages over the auto-registered ``_ADAPTERS`` (see the ADAPTER
    AUTHORING RULE in the module docstring): the brand is decided on the
    IDN's vendor field by the general adapters alone, then only that
    brand's model adapters are tested against the model field.
    """
    fields = [f.strip().upper() for f in idn.split(",")]
    vendor_field = fields[0]
    # Comma-less / garbage IDN degrades to vendor-field-only matching
    # (empty model field hits no anchored pattern) → BaseAdapter fallback.
    model_field = fields[1] if len(fields) > 1 else ""

    # STAGE 1 — BRAND: only general adapters (no MODEL_PATTERNS) compete,
    # on the vendor field alone. No brand match → generic BaseAdapter.
    brand = next((c for c in _ADAPTERS
                  if not getattr(c, "MODEL_PATTERNS", ()) and c.matches(vendor_field)),
                 None)
    if brand is None:
        return BaseAdapter

    # STAGE 2 — MODEL: only THAT brand's model adapters are tested, their
    # anchored patterns against the MODEL field.
    hits = [c for c in _ADAPTERS
            if issubclass(c, brand) and getattr(c, "MODEL_PATTERNS", ())
            and any(rx.search(model_field) for rx in c.MODEL_PATTERNS)]

    # Series/model nesting: the most specialized hit (the unique leaf) wins.
    # No hits → the general brand adapter. No unique leaf would mean the
    # authoring rule was violated (unrelated overlap) — degrade to the
    # general brand adapter rather than carry error machinery.
    leaf = next((c for c in hits if all(issubclass(c, o) for o in hits)), None)
    return leaf if leaf is not None else brand


# ---------------------------------------------------------------------------
# AUTO-IMPORT (file-drop contract, part 1 of 2): import every sibling module
# of this package so that merely ADDING a vendor file makes its adapters
# live — no import statement to add here or anywhere else. Part 2 is
# BrandAdapter.__init_subclass__ (base.py), which appends each subclass to
# the module-level _ADAPTERS registry the moment its class statement runs.
# ---------------------------------------------------------------------------
import importlib as _importlib
import pkgutil as _pkgutil

for _mod in _pkgutil.iter_modules(__path__):
    _importlib.import_module(f"{__name__}.{_mod.name}")


# ---------------------------
# Re-exports
# ---------------------------
# The facade and the SHIPPED vendor classes, for the package's import
# surface (``from labscpi.oscilloscope import Oscilloscope, RigolScope``).
# All already imported by the loop above, so these bind names only.
# NOTE: a dropped-in vendor file does NOT need a line here — registration
# and selection are automatic; this list is import-surface convenience for
# the shipped adapters, which the shim and external tests import by name.
from .facade import Oscilloscope
from .keysight import KeysightScope
from .rigol import RigolMSO2k4k, RigolScope
from .rohde_schwarz import RohdeSchwarzScope

__all__ = [
    "Oscilloscope", "pick_adapter",
    "Measure", "ChannelUnit", "TriggerSweepMode", "TriggerSlope", "MathOperator",
    "ScopeError", "NotConnectedError", "SCPIError", "NotSupportedError", "RangeError",
    "BaseAdapter", "BrandAdapter",
    "with_retries", "require_connected",
    "RigolScope", "RigolMSO2k4k", "KeysightScope", "RohdeSchwarzScope",
]
