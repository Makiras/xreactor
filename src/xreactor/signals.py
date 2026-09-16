from __future__ import annotations

from typing import Any

from .events import LogicValue


def as_xdata(signal: Any) -> Any:
    """Normalize a signal leaf without introducing a wrapper identity."""

    return signal


def read_signal(signal: Any) -> Any:
    signal = as_xdata(signal)
    unsigned = getattr(signal, "U", None)
    if callable(unsigned):
        return int(unsigned())
    return getattr(signal, "value", signal)


def read_bool(signal: Any, name: str = "signal") -> bool:
    value = read_signal(signal)
    if isinstance(value, LogicValue):
        value = value.as_int()
    try:
        return bool(int(value))
    except (TypeError, ValueError) as error:
        raise TypeError(
            f"{name} must expose an integer-compatible value"
        ) from error


def signal_width(signal: Any) -> int:
    signal = as_xdata(signal)
    width_getter = getattr(signal, "W", None)
    if callable(width_getter):
        width = int(width_getter())
        return 1 if width == 0 else width
    width = getattr(signal, "width", None)
    if width is not None:
        width = int(width)
        if width <= 0:
            raise ValueError("signal width must be positive")
        return width
    value = read_signal(signal)
    if isinstance(value, LogicValue):
        return value.width
    try:
        integer = int(value)
    except (TypeError, ValueError) as error:
        raise TypeError("cannot determine signal width") from error
    return max(1, integer.bit_length())


def sample_signal(signal: Any) -> LogicValue:
    signal = as_xdata(signal)
    width = signal_width(signal)
    if width > 64:
        aval_getter = getattr(signal, "GetBytes", None)
        bval_getter = getattr(signal, "GetBvalBytes", None)
        if callable(aval_getter) and callable(bval_getter):
            mask = (1 << width) - 1
            return LogicValue(
                int.from_bytes(bytes(aval_getter()), "little") & mask,
                int.from_bytes(bytes(bval_getter()), "little") & mask,
                width,
            )
    value = read_signal(signal)
    if isinstance(value, LogicValue):
        return value
    xmask_getter = getattr(signal, "XMask", None)
    x_mask = int(xmask_getter()) if callable(xmask_getter) else 0
    return LogicValue(int(value), x_mask, width)


def write_signal(signal: Any, value: Any, name: str = "signal") -> None:
    signal = as_xdata(signal)
    if isinstance(value, LogicValue):
        if not value.is_known:
            raise ValueError(
                f"{name} contains X/Z; four-state drive is not implemented"
            )
        value = value.value
    setter = getattr(signal, "Set", None)
    if callable(setter):
        setter(value)
        return
    if hasattr(signal, "value"):
        signal.value = value
        return
    raise TypeError(
        f"{name} must provide Set(value) or a writable value attribute"
    )


def signal_identity(signal: Any) -> tuple[str, int]:
    signal = as_xdata(signal)
    native_self = getattr(signal, "CSelf", None)
    if callable(native_self):
        return ("native", int(native_self()))
    return ("python", id(signal))
