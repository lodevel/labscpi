r"""Equivalence + fix matrix for the NEW labscpi.oscilloscope package.

Runs the SAME IDN matrix recorded in tests/test_adapter_selection_matrix.py
(which pins what the OLD flat-module pick_adapter actually returns) against
the new package's two-stage pick_adapter. Every case must be identical to
the old recording EXCEPT the documented quirk case, where the new result
must be the CORRECT one.

Also pins the package's owner-facing contracts:
  * auto-registration (subclassing IS registration) + registry hygiene,
  * pkgutil auto-import of sibling vendor modules (file-drop contract),
  * two-stage brand->model scoping (cross-brand collisions impossible),
  * series/model nesting via the unique-leaf rule (IN-TEST synthetic
    adapters only — never shipped),
  * order independence of selection over the registry,
  * facade parity with the old module's Oscilloscope.

REGISTRY HYGIENE (pinned by test_registry_fixture_restores): because
BrandAdapter.__init_subclass__ registers ANY subclass at class-definition
time, adapters defined inside a test body land in the shared module-level
registry. Every test that defines a synthetic adapter MUST use the
`registry` fixture, which snapshots and restores _ADAPTERS so test classes
cannot leak into other tests (or into the shipped-registry assertion).
"""
from __future__ import annotations

import random
import re
import sys

import pkgutil

import pytest

import labscpi.oscilloscope as pkg
import labscpi.oscilloscope_scpi as old
from labscpi.oscilloscope import BaseAdapter, Oscilloscope, pick_adapter
from labscpi.oscilloscope.base import _ADAPTERS, BrandAdapter
from labscpi.oscilloscope.keysight import KeysightScope
from labscpi.oscilloscope.rigol import RigolMSO2k4k, RigolScope
from labscpi.oscilloscope.rohde_schwarz import RohdeSchwarzScope

# Same IDNs as the Step-1 recording (tests/test_adapter_selection_matrix.py).
IDN_RIGOL_DS1054Z = "RIGOL TECHNOLOGIES,DS1054Z,DS1ZA000000001,00.04.04.SP4"
IDN_RIGOL_MSO2202 = "RIGOL TECHNOLOGIES,MSO2202A,DS2D000000001,00.03.00"
IDN_KEYSIGHT = "KEYSIGHT TECHNOLOGIES,DSOX1204G,CN61410000,02.12.2021102830"
IDN_RS = "Rohde&Schwarz,RTB2004,1333.1005k04/111111,02.202"
IDN_UNKNOWN = "TEKTRONIX,MSO46,C019966,CF:91.1CT FV:1.44.3.433"
IDN_EMPTY = ""
IDN_JUNK = "garbage-no-commas"

SHIPPED_ADAPTERS = {RigolScope, RigolMSO2k4k, KeysightScope, RohdeSchwarzScope}


@pytest.fixture
def registry():
    """Snapshot/restore the auto-registry around tests that define synthetic
    adapters (see REGISTRY HYGIENE in the module docstring). Yields the live
    _ADAPTERS list object; in-place mutation is visible to pick_adapter."""
    snap = list(_ADAPTERS)
    try:
        yield _ADAPTERS
    finally:
        _ADAPTERS[:] = snap


# ---------------------------------------------------------------------------
# Matrix equivalence (identical to the old recording except the quirk fix)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("idn", "expected"),
    [
        # THE FIX for the pinned quirk: the OLD code returns RigolMSO2k4k for
        # a DS1054Z (most-derived-first + vendor-alias fallback in the model
        # class's inherited select() — see test_adapter_selection_matrix.py).
        # CORRECT: a DS-series model matches no MODEL_PATTERNS, so the
        # general brand adapter RigolScope must be selected.
        pytest.param(IDN_RIGOL_DS1054Z, RigolScope, id="rigol-ds1054z-FIXED"),
        # Identical to the old recording from here on:
        pytest.param(IDN_RIGOL_MSO2202, RigolMSO2k4k, id="rigol-mso2202"),
        pytest.param(IDN_KEYSIGHT, KeysightScope, id="keysight-dsox1204g"),
        pytest.param(IDN_RS, RohdeSchwarzScope, id="rs-rtb2004"),
        pytest.param(IDN_UNKNOWN, BaseAdapter, id="unknown-vendor-tek"),
        pytest.param(IDN_EMPTY, BaseAdapter, id="empty-idn"),
        pytest.param(IDN_JUNK, BaseAdapter, id="junk-idn"),
    ],
)
def test_new_pick_adapter_matrix(idn: str, expected: type) -> None:
    assert pick_adapter(idn) is expected


# ---------------------------------------------------------------------------
# Nested series/model (owner's scenario — IN-TEST ONLY, never shipped)
# ---------------------------------------------------------------------------
def _define_mso5000_nesting():
    """Synthetic Rigol series adapter + defined model UNDER the series.
    Defining them registers them (auto-registration) — callers must hold
    the `registry` fixture."""

    class Mso5000Series(RigolScope):  # series: any MSO5xxx
        MODEL_PATTERNS = (re.compile(r"^MSO5\d{3}", re.I),)

    class Mso5040(Mso5000Series):  # defined model within the series
        MODEL_PATTERNS = (re.compile(r"^MSO5040", re.I),)

    return Mso5000Series, Mso5040


def test_nested_series_model_leaf_wins(registry) -> None:
    series, model = _define_mso5000_nesting()
    # Both patterns hit an MSO5040 -> the MOST SPECIALIZED class (the unique
    # leaf, which subclasses every other hit) wins.
    assert pick_adapter("RIGOL TECHNOLOGIES,MSO5040,MS5A000000001,00.01") is model
    # Only the series pattern hits an MSO5104 -> the series adapter wins.
    assert pick_adapter("RIGOL TECHNOLOGIES,MSO5104,MS5A000000002,00.01") is series
    # A DS1054Z hits neither -> plain general brand adapter. Series and
    # model coexist with the brand default without disturbing it.
    assert pick_adapter(IDN_RIGOL_DS1054Z) is RigolScope
    # And the unrelated shipped model adapter is untouched too.
    assert pick_adapter(IDN_RIGOL_MSO2202) is RigolMSO2k4k


# ---------------------------------------------------------------------------
# Cross-brand collision (stage-1 scoping)
# ---------------------------------------------------------------------------
def test_cross_brand_model_pattern_never_crosses_brands(registry) -> None:
    class KeysightMsoClash(KeysightScope):
        # Deliberately IDENTICAL pattern to RigolMSO2k4k's. Stage 1 decides
        # the brand from the vendor field alone; stage 2 only ever tests
        # the winning brand's own model adapters, so this class must never
        # be selected for a Rigol IDN.
        MODEL_PATTERNS = (re.compile(r"^MSO?[24]\d{2}", re.I),)

    assert pick_adapter(IDN_RIGOL_MSO2202) is RigolMSO2k4k
    assert pick_adapter(IDN_RIGOL_DS1054Z) is RigolScope
    # And on its own brand it works as a normal model adapter (model field
    # "MSO2012A" hits the clash pattern):
    assert (
        pick_adapter("KEYSIGHT TECHNOLOGIES,MSO2012A,MY00000000,02.65")
        is KeysightMsoClash
    )


# ---------------------------------------------------------------------------
# Order independence: selection must not depend on registration order
# ---------------------------------------------------------------------------
def test_selection_is_order_independent(registry) -> None:
    series, model = _define_mso5000_nesting()  # exercise the leaf rule too
    matrix = [
        IDN_RIGOL_DS1054Z, IDN_RIGOL_MSO2202, IDN_KEYSIGHT, IDN_RS,
        IDN_UNKNOWN, IDN_EMPTY, IDN_JUNK,
        "RIGOL TECHNOLOGIES,MSO5040,MS5A000000001,00.01",
        "RIGOL TECHNOLOGIES,MSO5104,MS5A000000002,00.01",
    ]
    baseline = [pick_adapter(idn) for idn in matrix]

    orders = [list(reversed(_ADAPTERS))]
    rng = random.Random(0xC0FFEE)
    for _ in range(5):
        perm = list(_ADAPTERS)
        rng.shuffle(perm)
        orders.append(perm)

    for perm in orders:  # 6 permutations incl. reversed
        _ADAPTERS[:] = perm
        assert [pick_adapter(idn) for idn in matrix] == baseline


# ---------------------------------------------------------------------------
# Drop-in registration: subclassing IS registration, zero other edits
# ---------------------------------------------------------------------------
def test_drop_in_adapter_is_immediately_selectable(registry) -> None:
    # A brand-new vendor defined right here: no registry edit, no list, no
    # import edit anywhere — the class statements alone make it selectable.
    class SiglentScope(BrandAdapter):
        brand = "SIGLENT"
        vendor_aliases = ("SIGLENT TECHNOLOGIES",)

    class SiglentSDS2k(SiglentScope):
        MODEL_PATTERNS = (re.compile(r"^SDS2\d{3}", re.I),)

    assert (
        pick_adapter("Siglent Technologies,SDS2104X Plus,SDS2PEE000001,1.6.2")
        is SiglentSDS2k
    )
    assert (
        pick_adapter("Siglent Technologies,SDS804X HD,SDS08A000001,1.0.1")
        is SiglentScope
    )
    # Other brands are undisturbed.
    assert pick_adapter(IDN_KEYSIGHT) is KeysightScope


def test_registry_fixture_restores() -> None:
    """Hygiene pin: after any fixture-guarded test above, the registry holds
    EXACTLY the four shipped adapter classes — synthetic test adapters must
    not leak. Also pins the owner order: the SHIPPED package contains
    exactly the existing four classes and nothing else."""
    assert set(_ADAPTERS) == SHIPPED_ADAPTERS
    assert len(_ADAPTERS) == 4


# ---------------------------------------------------------------------------
# Auto-import (file-drop) contract
# ---------------------------------------------------------------------------
def test_every_vendor_module_auto_imported() -> None:
    present = {m.name for m in pkgutil.iter_modules(pkg.__path__)}
    # "mocks" joined the package at the switch commit (moved out of the old
    # flat module); "facade" holds the Oscilloscope facade (moved out of
    # the package __init__). Neither defines a BrandAdapter subclass, so
    # auto-importing them registers nothing
    # (test_registry_fixture_restores still pins 4).
    assert present == {"base", "facade", "keysight", "rigol", "rohde_schwarz", "mocks"}
    for name in present:
        assert f"labscpi.oscilloscope.{name}" in sys.modules, (
            f"package __init__ failed to auto-import sibling module {name!r}"
        )


# ---------------------------------------------------------------------------
# Facade parity with the old module
# ---------------------------------------------------------------------------
def test_facade_public_api_parity() -> None:
    old_names = {n for n in dir(old.Oscilloscope) if not n.startswith("_")}
    new_names = {n for n in dir(Oscilloscope) if not n.startswith("_")}
    assert new_names == old_names


def test_facade_mock_session_smoke() -> None:
    # Drive the facade with the mock resource via the OLD import path —
    # since the switch commit this exercises the shim's re-export of
    # labscpi.oscilloscope.mocks.
    res = old.MockScopeResource()  # IDN: RIGOL ...,MSO2072A,...
    scope = Oscilloscope("MOCK::SCOPE", rm=old.MockResourceManager(res))
    scope.connect()
    scope.initialize()
    assert isinstance(scope._adapter, RigolMSO2k4k)  # model-field pattern hit

    scope.set_time_scale(2e-3)
    assert scope.get_time_scale() == pytest.approx(2e-3)

    scope.set_timeout(1234)  # the branch's set_timeout work, live push
    assert scope.timeout_ms == 1234
    assert res.timeout == 1234

    scope.close()
