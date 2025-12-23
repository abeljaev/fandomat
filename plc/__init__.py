"""PLC модуль: управление ПЛК, State Machine, Application."""

from plc.modbus_register import ModbusRegister
from plc.plc import PLC

__all__ = ["ModbusRegister", "PLC", "Application", "AppState"]


def __getattr__(name):
    if name == "Application":
        from plc.application import Application
        return Application
    elif name == "AppState":
        from plc.application import AppState
        return AppState
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
