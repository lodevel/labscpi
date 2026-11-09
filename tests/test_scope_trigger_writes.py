"""set_trigger writes only what it is given: a level or slope left out is not sent (the scope keeps its own)."""
from __future__ import annotations

import pytest

from labscpi.oscilloscope.base import BaseAdapter
from labscpi.oscilloscope.rigol import RigolScope


class _Session:
    def __init__(self):
        self.sent = []

    def write(self, cmd):
        self.sent.append(cmd)


def _sent(adapter_cls, **kwargs):
    session = _Session()
    adapter_cls(session, "IDN").set_trigger(**kwargs)
    return session.sent


@pytest.mark.parametrize("adapter, level_cmd", [(BaseAdapter, ":TRIG:LEV"), (RigolScope, ":TRIG:EDGE:LEVel")])
def test_only_the_source_is_written_when_level_and_slope_are_left_out(adapter, level_cmd):
    assert _sent(adapter, edge_src="CHAN2") == [":TRIG:MODE EDGE", ":TRIG:EDGE:SOUR CHAN2"]


@pytest.mark.parametrize("adapter, level_cmd", [(BaseAdapter, ":TRIG:LEV"), (RigolScope, ":TRIG:EDGE:LEVel")])
def test_a_given_level_and_slope_are_written(adapter, level_cmd):
    sent = _sent(adapter, edge_src="CHAN1", level=0.0, slope="NEG")
    assert sent == [":TRIG:MODE EDGE", ":TRIG:EDGE:SOUR CHAN1", f"{level_cmd} 0.0", ":TRIG:EDGE:SLOP NEG"]
