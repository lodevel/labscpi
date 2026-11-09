__version__ = "2.0.6"

from .oscilloscope_scpi import (
    Oscilloscope, Measure, ChannelUnit, TriggerSweepMode, MathOperator,
)
from .psu_scpi import PowerSupply
from .eload_scpi import ElectronicLoad


def close_resource_manager() -> None:
    """Tear down the process-wide pyvisa ResourceManager (explicit, opt-in).

    pyvisa keeps ONE ResourceManager per backend for the whole process, shared
    by every instrument. An instrument's close() closes only that instrument's
    own VISA session, never this shared manager - closing the manager would
    invalidate every OTHER open instrument in the process. So a multi-instrument
    runtime leaves it alive; pyvisa reclaims it at process exit.

    Call this from a STANDALONE single-instrument script, AFTER close(), for a
    fully clean teardown without waiting for process exit. Do NOT call it while
    any instrument is still in use. No-op if pyvisa is absent; safe even if no
    instrument was ever opened.
    """
    try:
        import pyvisa  # type: ignore
    except ImportError:
        return
    try:
        pyvisa.ResourceManager().close()
    except Exception:
        pass


__all__ = [
    "Oscilloscope","Measure","ChannelUnit","TriggerSweepMode","MathOperator",
    "PowerSupply","ElectronicLoad",
    "close_resource_manager",
]
