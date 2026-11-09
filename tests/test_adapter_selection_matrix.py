"""Selection matrix pin for the EXISTING labscpi.oscilloscope_scpi.pick_adapter.

Recorded from actually RUNNING the old code (2026-08-27, branch tip 0abb40b) —
these asserts pin what the old selector RETURNS, not what it should return.
The refactored labscpi.oscilloscope package is held against this matrix by
tests/test_scope_package_equivalence.py, which asserts identical results for
every case EXCEPT the documented defect below (where the new package must
return the correct adapter instead).

Recorded matrix (old pick_adapter, verbatim run output):

    Rigol DS1054Z-style    -> RigolMSO2k4k   (KNOWN DEFECT, see below)
    Rigol MSO2202-style    -> RigolMSO2k4k
    Keysight               -> KeysightScope
    Rohde&Schwarz          -> RohdeSchwarzScope
    Unknown vendor         -> BaseAdapter
    empty                  -> BaseAdapter
    junk (no commas)       -> BaseAdapter

KNOWN DEFECT (most-derived-first quirk): pick_adapter sorts candidates by
MRO length descending, so RigolMSO2k4k (5-deep) is tried before RigolScope
(4-deep). RigolMSO2k4k inherits BrandAdapter.matches, which matches on the
VENDOR alias ("RIGOL") alone — so ANY Rigol IDN "matches" the MSO2k4k model
class, and its inherited select() then returns RigolMSO2k4k again via the
same vendor-alias match even though the MODEL_PATTERNS regex does not hit.
A DS1054Z therefore gets the MSO2k4k model adapter instead of the general
RigolScope. Pinned here as OLD behavior; corrected in the new package.

SWITCH NOTE (switch commit): labscpi.oscilloscope_scpi is now a shim that
re-exports the labscpi.oscilloscope package, so this matrix now pins the
SHIM import path and the quirk case asserts the CORRECTED answer
(RigolScope). The pre-switch recording above is preserved verbatim in git
history with the old implementation; revert the switch commit to restore
both.
"""
from __future__ import annotations

import pytest

from labscpi.oscilloscope_scpi import (
    BaseAdapter,
    KeysightScope,
    RigolMSO2k4k,
    RigolScope,
    RohdeSchwarzScope,
    pick_adapter,
)

# IDN strings built from each adapter's brand / vendor_aliases (realistic
# vendor,model,serial,firmware shapes as the instruments actually report).
IDN_RIGOL_DS1054Z = "RIGOL TECHNOLOGIES,DS1054Z,DS1ZA000000001,00.04.04.SP4"
IDN_RIGOL_MSO2202 = "RIGOL TECHNOLOGIES,MSO2202A,DS2D000000001,00.03.00"
IDN_KEYSIGHT = "KEYSIGHT TECHNOLOGIES,DSOX1204G,CN61410000,02.12.2021102830"
IDN_RS = "Rohde&Schwarz,RTB2004,1333.1005k04/111111,02.202"
IDN_UNKNOWN = "TEKTRONIX,MSO46,C019966,CF:91.1CT FV:1.44.3.433"
IDN_EMPTY = ""
IDN_JUNK = "garbage-no-commas"


@pytest.mark.parametrize(
    ("idn", "expected"),
    [
        # KNOWN DEFECT — FIXED BY THE SWITCH: through the shim this import
        # path now runs the package's two-stage selector, so the DS1054Z
        # correctly gets the general RigolScope (see SWITCH NOTE in the
        # module docstring; old recording: RigolMSO2k4k).
        pytest.param(IDN_RIGOL_DS1054Z, RigolScope, id="rigol-ds1054z-FIXED"),
        # Legitimate model hit: ,MSO22xx matches RigolMSO2k4k's pattern.
        pytest.param(IDN_RIGOL_MSO2202, RigolMSO2k4k, id="rigol-mso2202"),
        pytest.param(IDN_KEYSIGHT, KeysightScope, id="keysight-dsox1204g"),
        pytest.param(IDN_RS, RohdeSchwarzScope, id="rs-rtb2004"),
        pytest.param(IDN_UNKNOWN, BaseAdapter, id="unknown-vendor-tek"),
        pytest.param(IDN_EMPTY, BaseAdapter, id="empty-idn"),
        pytest.param(IDN_JUNK, BaseAdapter, id="junk-idn"),
    ],
)
def test_old_pick_adapter_matrix(idn: str, expected: type) -> None:
    assert pick_adapter(idn) is expected
