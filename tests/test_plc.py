"""
Тесты для модуля PLC.

Проверяет работу регистров счетчиков и процентов (20-23).
"""
import pytest
from unittest.mock import Mock, MagicMock, patch


class TestPLCRegisters:
    """Тесты для регистров счетчиков и процентов."""

    @pytest.fixture
    def mock_modbus_register(self):
        """Mock для ModbusRegister."""
        with patch('plc.plc.ModbusRegister') as mock:
            mock_instance = MagicMock()
            mock.return_value = mock_instance
            yield mock, mock_instance

    @pytest.fixture
    def mock_serial(self):
        """Mock для serial."""
        with patch('plc.plc.serial.Serial') as mock:
            yield mock

    @pytest.fixture
    def mock_modbus_rtu(self):
        """Mock для modbus_rtu."""
        with patch('plc.plc.modbus_rtu') as mock:
            mock_server = MagicMock()
            mock_slave = MagicMock()
            mock.RtuServer.return_value = mock_server
            mock_server.add_slave.return_value = mock_slave
            yield mock, mock_server, mock_slave

    def test_registers_created(self, mock_serial, mock_modbus_rtu, mock_modbus_register):
        """Проверить создание регистров 20-23."""
        from plc import PLC

        mock_reg_class, _ = mock_modbus_register
        _, _, mock_slave = mock_modbus_rtu

        plc = PLC('/dev/ttyUSB0', 115200, 2)

        # Проверяем, что ModbusRegister вызывался с нужными номерами
        call_args = [call[0][1] for call in mock_reg_class.call_args_list]

        assert 20 in call_args, "Регистр 20 (bank_counter) не создан"
        assert 21 in call_args, "Регистр 21 (bottle_counter) не создан"
        assert 22 in call_args, "Регистр 22 (bottle_percent) не создан"
        assert 23 in call_args, "Регистр 23 (bank_percent) не создан"

    def test_get_bank_count(self, mock_serial, mock_modbus_rtu, mock_modbus_register):
        """Проверить получение количества банок."""
        from plc import PLC

        _, mock_instance = mock_modbus_register
        mock_instance.get_value.return_value = 42

        plc = PLC('/dev/ttyUSB0', 115200, 2)
        result = plc.get_bank_count()

        mock_instance.get_value.assert_called()
        assert result == 42

    def test_get_bottle_count(self, mock_serial, mock_modbus_rtu, mock_modbus_register):
        """Проверить получение количества бутылок."""
        from plc import PLC

        _, mock_instance = mock_modbus_register
        mock_instance.get_value.return_value = 100

        plc = PLC('/dev/ttyUSB0', 115200, 2)
        result = plc.get_bottle_count()

        assert result == 100

    def test_get_bottle_fill_percent(self, mock_serial, mock_modbus_rtu, mock_modbus_register):
        """Проверить получение процента заполнения бутылок."""
        from plc import PLC

        _, mock_instance = mock_modbus_register
        mock_instance.get_value.return_value = 75

        plc = PLC('/dev/ttyUSB0', 115200, 2)
        result = plc.get_bottle_fill_percent()

        assert result == 75

    def test_get_bank_fill_percent(self, mock_serial, mock_modbus_rtu, mock_modbus_register):
        """Проверить получение процента заполнения банок."""
        from plc import PLC

        _, mock_instance = mock_modbus_register
        mock_instance.get_value.return_value = 50

        plc = PLC('/dev/ttyUSB0', 115200, 2)
        result = plc.get_bank_fill_percent()

        assert result == 50

    def test_update_data_syncs_new_registers(self, mock_serial, mock_modbus_rtu, mock_modbus_register):
        """Проверить, что update_data() синхронизирует новые регистры."""
        from plc import PLC

        _, mock_instance = mock_modbus_register

        plc = PLC('/dev/ttyUSB0', 115200, 2)

        # Сбрасываем счетчик вызовов после инициализации
        mock_instance.sync_from_device.reset_mock()

        plc.update_data()

        # update_data должен вызвать sync_from_device для всех регистров
        # status, bank_counter, bottle_counter, bottle_percent, bank_percent = 5 раз
        # (counter закомментирован в PLC.py)
        assert mock_instance.sync_from_device.call_count == 5
