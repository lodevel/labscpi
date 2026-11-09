"""Oscilloscope.set_timeout (per-run timeout retargeting, labscpi 2.0.3).

The scope mirror of the existing PSU/ELoad method: native unit is int
milliseconds; disconnected -> attribute only (picked up by the next
``connect()``); connected -> pushed to the live VISA resource too.  No
hardware: the resource is a plain fake with a ``timeout`` attribute.
"""
from __future__ import annotations

from labscpi import Oscilloscope


class _FakeResource:
    def __init__(self):
        self.timeout = None


def test_set_timeout_disconnected_is_attribute_only():
    sc = Oscilloscope("USB0::MOCK::INSTR")
    sc.set_timeout(2500)
    assert sc.timeout_ms == 2500
    assert sc._resource is None          # nothing to push to, nothing opened


def test_set_timeout_connected_pushes_to_live_resource():
    sc = Oscilloscope("USB0::MOCK::INSTR", timeout_ms=5000)
    res = _FakeResource()
    sc._resource = res
    sc.set_timeout(1234.0)               # float in -> int stored (native ms)
    assert sc.timeout_ms == 1234
    assert isinstance(sc.timeout_ms, int)
    assert res.timeout == 1234           # live resource retargeted


def test_set_timeout_rejects_bool_and_negative_nothing_assigned():
    # Pin (the serial drivers' contract): bool (either value) and negatives raise
    # BEFORE any assignment — durable attribute and live resource untouched.
    import pytest

    sc = Oscilloscope("USB0::MOCK::INSTR", timeout_ms=5000)
    res = _FakeResource()
    sc._resource = res
    for bad in (True, False, -1, -500.0, "nope"):
        with pytest.raises(ValueError):
            sc.set_timeout(bad)
    assert sc.timeout_ms == 5000         # durable value untouched
    assert res.timeout is None           # live resource never touched
