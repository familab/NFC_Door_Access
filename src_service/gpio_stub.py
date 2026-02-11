"""Simple GPIO stub for development on non-Raspberry Pi platforms.
Provides a minimal subset of the RPi.GPIO API used by the project.
"""

# Constants
BCM = 'BCM'
IN = 'IN'
OUT = 'OUT'
LOW = 0
HIGH = 1
PUD_UP = 'PUD_UP'

# Internal state
_pin_modes = {}
_pin_values = {}


def setmode(mode):
    # No-op for stub
    return


def setup(pin, mode, pull_up_down=None):
    _pin_modes[pin] = (mode, pull_up_down)
    _pin_values.setdefault(pin, HIGH)


def input(pin):
    # Return default HIGH (not pressed) unless overridden
    return _pin_values.get(pin, HIGH)


def output(pin, value):
    _pin_values[pin] = value


def cleanup():
    _pin_modes.clear()
    _pin_values.clear()


# Provide simple helper for tests/dev to set a pin value
def _set_input(pin, value):
    """Force an input value for a pin (for development/tests)."""
    _pin_values[pin] = value
