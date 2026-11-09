"""labscpi.oscilloscope_scpi — compatibility shim over the labscpi.oscilloscope package.

THE PACKAGE IS NOW THE IMPLEMENTATION. This module only re-exports the
public API of ``labscpi.oscilloscope`` so that every pre-existing import
path (``from labscpi.oscilloscope_scpi import Oscilloscope`` etc.) keeps
working unchanged.

The old flat-module implementation is PRESERVED IN GIT HISTORY: revert
this switch commit to restore it wholesale (the owner's rollback path).
It will be deleted for good only once the package is confirmed working
on hardware.

Deltas carried by the switch (owner-approved):

* ``pick_adapter`` is the package's two-stage brand→model selector. It
  fixes the pinned DS1054Z quirk: a DS-series Rigol now selects the
  general ``RigolScope``, no longer the ``RigolMSO2k4k`` model adapter
  (see tests/test_scope_package_equivalence.py).
* ``BrandAdapter._models`` / ``register_model`` / ``select`` no longer
  exist — superseded by ``__init_subclass__`` auto-registration in the
  package (subclassing IS registration). A grep across all consumer
  repos (labscpi lib + pack, other packs' drivers, helper, host GUI) found no
  external caller of that machinery.
* ``MockScopeResource`` / ``MockResourceManager`` moved verbatim into
  ``labscpi.oscilloscope.mocks`` and are re-exported here.
"""
from __future__ import annotations

from .oscilloscope import (
    ChannelUnit,
    MathOperator,
    Measure,
    NotConnectedError,
    NotSupportedError,
    Oscilloscope,
    RangeError,
    SCPIError,
    ScopeError,
    TriggerSlope,
    TriggerSweepMode,
    BaseAdapter,
    BrandAdapter,
    pick_adapter,
    require_connected,
    with_retries,
)
from .oscilloscope.base import _Session
from .oscilloscope.keysight import KeysightScope
from .oscilloscope.mocks import MockResourceManager, MockScopeResource
from .oscilloscope.rigol import RigolMSO2k4k, RigolScope
from .oscilloscope.rohde_schwarz import RohdeSchwarzScope

__all__ = [
    "Oscilloscope", "pick_adapter",
    "Measure", "ChannelUnit", "TriggerSweepMode", "TriggerSlope", "MathOperator",
    "ScopeError", "NotConnectedError", "SCPIError", "NotSupportedError", "RangeError",
    "BaseAdapter", "BrandAdapter",
    "with_retries", "require_connected",
    "_Session",  # private, but part of the old module's importable surface
    "RigolScope", "RigolMSO2k4k", "KeysightScope", "RohdeSchwarzScope",
    "MockScopeResource", "MockResourceManager",
]
