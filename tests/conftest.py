"""
Pytest конфигурация и общие фикстуры.
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# Мокаем модули, которые недоступны в тестовом окружении
sys.modules['modbus_tk'] = MagicMock()
sys.modules['modbus_tk.defines'] = MagicMock()
sys.modules['modbus_tk.modbus_rtu'] = MagicMock()
sys.modules['serial'] = MagicMock()


@pytest.fixture
def project_root() -> Path:
    """Корневая директория проекта."""
    return Path(__file__).parent.parent


@pytest.fixture
def test_data_dir(project_root: Path) -> Path:
    """Директория с тестовыми данными."""
    return project_root / "tests" / "data"
