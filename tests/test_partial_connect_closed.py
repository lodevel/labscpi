"""A connect() that fails after it opened the VISA resource never leaves it open: close() closes
it (a code test's plug closes its driver when opening it fails; a text test's cleanup too), and the
scope's retries close each attempt's resource."""

from __future__ import annotations

import pytest

from labscpi import ElectronicLoad, Oscilloscope, PowerSupply


class _Resource:
    """A VISA resource whose timeout cannot be set: the open succeeds, the connect fails after it."""

    def __init__(self, opened: list) -> None:
        self.closed = False
        opened.append(self)

    def __setattr__(self, name, value):
        if name == "timeout":
            raise OSError("the instrument refused the timeout")
        object.__setattr__(self, name, value)

    def close(self) -> None:
        self.closed = True


class _Manager:
    def __init__(self) -> None:
        self.opened: list[_Resource] = []

    def open_resource(self, address):
        return _Resource(self.opened)


@pytest.mark.parametrize("driver", [PowerSupply, ElectronicLoad])
def test_a_connect_failing_after_the_open_is_closed_by_close(driver):
    rm = _Manager()
    device = driver("ASRL20::INSTR", rm=rm)
    with pytest.raises(OSError):
        device.connect()
    assert [r.closed for r in rm.opened] == [False]  # the failed connect left it open
    device.close()
    assert [r.closed for r in rm.opened] == [True]
    device.close()  # closed already: nothing to do


def test_a_scope_closes_the_resource_of_every_failed_attempt():
    rm = _Manager()
    scope = Oscilloscope("USB0::1", rm=rm, retries=2, retry_delay=0)
    with pytest.raises(Exception, match="after 3 attempts"):
        scope.connect()
    assert [r.closed for r in rm.opened] == [True, True, True]
    scope.close()
