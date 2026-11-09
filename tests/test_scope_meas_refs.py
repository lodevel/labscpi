"""Oscilloscope.enable_measurement / read_measurement take a ref key: a number
({3}) or a name ({Vout}, {Vrail[3]}), as the procedure's codegen emits it
(labscpi 2.0.4). No hardware: the scope's enable/get are recorded on the instance."""
from __future__ import annotations

import pytest

from labscpi import Oscilloscope


def _scope() -> tuple[Oscilloscope, list]:
    sc = Oscilloscope("USB0::MOCK::INSTR")
    sc._connected = True
    calls = []
    sc.enable_measure = lambda kind, src, src2=None: calls.append(("enable", kind, src, src2))
    sc.get_measure = lambda kind, src, src2=None: calls.append(("get", kind, src, src2)) or 1.5
    return sc, calls


@pytest.mark.parametrize("ref", ["Vout", "Vrail[3]", 3])
def test_a_measurement_is_read_back_by_its_ref(ref):
    sc, calls = _scope()
    sc.enable_measurement(ref=ref, kind="FREQ", source_channel="CH1")
    sc.enable_measurement(ref="Other", kind="VPP", source_channel="CH2")
    assert sc.read_measurement(ref=ref) == 1.5
    assert calls[-1] == ("get", "FREQ", "CH1", None)


def test_a_number_and_its_digits_are_the_same_ref():
    sc, calls = _scope()
    sc.enable_measurement(ref="3", kind="RR_DELAY", source_channel="CH1", source_channel_2="CH2")
    sc.read_measurement(ref=3)
    assert calls[-1] == ("get", "RR_DELAY", "CH1", "CH2")


def test_a_ref_never_enabled_is_a_key_error():
    sc, _calls = _scope()
    sc.enable_measurement(ref="Vout", kind="FREQ", source_channel="CH1")
    with pytest.raises(KeyError, match="Vin"):
        sc.read_measurement(ref="Vin")
