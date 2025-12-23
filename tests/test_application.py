"""
Тесты для модуля Application.

Проверяет state machine и переходы между состояниями.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
import time


class TestAppStateEnum:
    """Тесты для enum AppState."""

    def test_states_exist(self):
        """Проверить наличие всех состояний."""
        from plc import AppState

        assert hasattr(AppState, 'IDLE')
        assert hasattr(AppState, 'WAITING_VISION')
        assert hasattr(AppState, 'DUMPING_PLASTIC')
        assert hasattr(AppState, 'DUMPING_ALUMINUM')
        assert hasattr(AppState, 'ERROR')

    def test_state_values(self):
        """Проверить значения состояний."""
        from plc import AppState

        assert AppState.IDLE.value == "idle"
        assert AppState.WAITING_VISION.value == "waiting_vision"
        assert AppState.DUMPING_PLASTIC.value == "dumping_plastic"
        assert AppState.DUMPING_ALUMINUM.value == "dumping_aluminum"
        assert AppState.ERROR.value == "error"


class TestApplicationInit:
    """Тесты для инициализации Application."""

    @pytest.fixture
    def mock_plc(self):
        """Mock для PLC."""
        with patch('plc.application.PLC') as mock:
            yield mock

    @pytest.fixture
    def mock_websocket(self):
        """Mock для WebSocket."""
        with patch('plc.application.WebSocket') as mock:
            yield mock

    def test_state_machine_fields_exist(self, mock_plc, mock_websocket):
        """Проверить наличие полей state machine."""
        from plc import Application, AppState

        app = Application(
            serial_port='/dev/ttyUSB0',
            baudrate=115200,
            slave_address=2
        )

        # Проверяем state machine поля
        assert hasattr(app, 'state')
        assert hasattr(app, 'state_lock')
        assert hasattr(app, 'vision_timeout')
        assert hasattr(app, 'dump_timeout')
        assert hasattr(app, 'current_plc_detection')
        assert hasattr(app, 'vision_request_time')
        assert hasattr(app, 'dump_started_time')

    def test_initial_state_is_idle(self, mock_plc, mock_websocket):
        """Проверить начальное состояние IDLE."""
        from plc import Application, AppState

        app = Application(
            serial_port='/dev/ttyUSB0',
            baudrate=115200,
            slave_address=2
        )

        assert app.state == AppState.IDLE

    def test_timeout_values(self, mock_plc, mock_websocket):
        """Проверить значения таймаутов."""
        from plc import Application

        app = Application(
            serial_port='/dev/ttyUSB0',
            baudrate=115200,
            slave_address=2
        )

        assert app.vision_timeout == 2.0
        assert app.dump_timeout == 3.0


class TestVisionResponseHandler:
    """Тесты для _handle_vision_response."""

    @pytest.fixture
    def app_with_mocks(self):
        """Application с замоканными зависимостями."""
        with patch('plc.application.PLC') as mock_plc, \
             patch('plc.application.WebSocket') as mock_ws:
            from plc import Application

            app = Application(
                serial_port='/dev/ttyUSB0',
                baudrate=115200,
                slave_address=2
            )
            app.PLC = MagicMock()
            yield app

    def test_bottle_confirmed(self, app_with_mocks):
        """Проверить подтверждение бутылки."""
        app = app_with_mocks
        app.current_plc_detection = "bottle"

        app._handle_vision_response("bottle")

        app.PLC.cmd_radxa_detected_bottle.assert_called_once()

    def test_bank_confirmed(self, app_with_mocks):
        """Проверить подтверждение банки."""
        app = app_with_mocks
        app.current_plc_detection = "bank"

        app._handle_vision_response("bank")

        app.PLC.cmd_radxa_detected_bank.assert_called_once()

    def test_vision_none_does_nothing(self, app_with_mocks):
        """Проверить, что none не вызывает команды ПЛК."""
        app = app_with_mocks
        app.current_plc_detection = "bottle"

        app._handle_vision_response("none")

        app.PLC.cmd_radxa_detected_bottle.assert_not_called()
        app.PLC.cmd_radxa_detected_bank.assert_not_called()

    def test_mismatch_does_not_call_plc(self, app_with_mocks):
        """Проверить, что несовпадение не вызывает команды ПЛК."""
        app = app_with_mocks
        app.current_plc_detection = "bottle"

        app._handle_vision_response("bank")

        app.PLC.cmd_radxa_detected_bottle.assert_not_called()
        app.PLC.cmd_radxa_detected_bank.assert_not_called()


class TestErrorStateHandler:
    """Тесты для _handle_error_state_commands."""

    @pytest.fixture
    def app_in_error_state(self):
        """Application в состоянии ERROR."""
        with patch('plc.application.PLC') as mock_plc, \
             patch('plc.application.WebSocket') as mock_ws:
            from plc import Application, AppState

            app = Application(
                serial_port='/dev/ttyUSB0',
                baudrate=115200,
                slave_address=2
            )
            app.PLC = MagicMock()
            app.websocket_server = MagicMock()
            app.state = AppState.ERROR
            yield app

    def test_dump_plastic_in_error_state(self, app_in_error_state):
        """Проверить обработку dump_container:plastic в ERROR."""
        from plc import AppState

        app = app_in_error_state
        app.websocket_server.get_command.return_value = "dump_container:plastic"

        app._handle_error_state_commands()

        assert app.state == AppState.DUMPING_PLASTIC
        app.PLC.cmd_force_move_carriage_left.assert_called_once()

    def test_dump_aluminium_in_error_state(self, app_in_error_state):
        """Проверить обработку dump_container:aluminium в ERROR."""
        from plc import AppState

        app = app_in_error_state
        app.websocket_server.get_command.return_value = "dump_container:aluminium"

        app._handle_error_state_commands()

        assert app.state == AppState.DUMPING_ALUMINUM
        app.PLC.cmd_force_move_carriage_right.assert_called_once()

    def test_restore_device_exits_error(self, app_in_error_state):
        """Проверить, что restore_device переводит в IDLE."""
        from plc import AppState

        app = app_in_error_state
        app.websocket_server.get_command.return_value = "restore_device"

        app._handle_error_state_commands()

        assert app.state == AppState.IDLE

    def test_unknown_command_ignored(self, app_in_error_state):
        """Проверить, что неизвестные команды игнорируются."""
        from plc import AppState

        app = app_in_error_state
        app.websocket_server.get_command.return_value = "some_unknown_command"

        app._handle_error_state_commands()

        assert app.state == AppState.ERROR  # Остаётся в ERROR

    def test_empty_command_does_nothing(self, app_in_error_state):
        """Проверить, что пустая команда ничего не делает."""
        from plc import AppState

        app = app_in_error_state
        app.websocket_server.get_command.return_value = ""

        app._handle_error_state_commands()

        assert app.state == AppState.ERROR


class TestHelperFunctions:
    """Тесты для вспомогательных функций."""

    @pytest.fixture
    def app_with_mocks(self):
        """Application с замоканными зависимостями."""
        with patch('plc.application.PLC') as mock_plc, \
             patch('plc.application.WebSocket') as mock_ws:
            from plc import Application

            app = Application(
                serial_port='/dev/ttyUSB0',
                baudrate=115200,
                slave_address=2
            )
            app.websocket_server = MagicMock()
            yield app

    def test_create_event_basic(self, app_with_mocks):
        """Проверить создание базового события."""
        import json
        app = app_with_mocks

        result = app.create_event("test_event")
        parsed = json.loads(result)

        assert parsed["event"] == "test_event"
        assert parsed["data"] == {}
        assert "timestamp" in parsed

    def test_create_event_with_data(self, app_with_mocks):
        """Проверить создание события с данными."""
        import json
        app = app_with_mocks

        result = app.create_event("container_detected", {"plc_type": "bottle"})
        parsed = json.loads(result)

        assert parsed["event"] == "container_detected"
        assert parsed["data"]["plc_type"] == "bottle"

    def test_send_event_to_app(self, app_with_mocks):
        """Проверить отправку события клиенту app."""
        app = app_with_mocks

        app.send_event_to_app("test_event", {"key": "value"})

        app.websocket_server.send_to_client.assert_called_once()
        call_args = app.websocket_server.send_to_client.call_args
        assert call_args[0][0] == "app"

    def test_parse_command_json(self, app_with_mocks):
        """Проверить парсинг JSON команды."""
        app = app_with_mocks

        cmd, params = app.parse_command('{"command": "get_photo", "quality": 85}')

        assert cmd == "get_photo"
        assert params["quality"] == 85

    def test_parse_command_string_with_param(self, app_with_mocks):
        """Проверить парсинг строковой команды с параметром."""
        app = app_with_mocks

        cmd, params = app.parse_command("dump_container:plastic")

        assert cmd == "dump_container"
        assert params["param"] == "plastic"

    def test_parse_command_simple_string(self, app_with_mocks):
        """Проверить парсинг простой строковой команды."""
        app = app_with_mocks

        cmd, params = app.parse_command("get_device_info")

        assert cmd == "get_device_info"
        assert params == {}

    def test_parse_command_empty(self, app_with_mocks):
        """Проверить парсинг пустой команды."""
        app = app_with_mocks

        cmd, params = app.parse_command("")

        assert cmd is None
        assert params == {}

    def test_parse_command_json_container_type(self, app_with_mocks):
        """Проверить парсинг JSON с container_type."""
        app = app_with_mocks

        cmd, params = app.parse_command('{"command": "dump_container", "container_type": "plastic"}')

        assert cmd == "dump_container"
        assert params["param"] == "plastic"

    def test_parse_command_json_type(self, app_with_mocks):
        """Проверить парсинг JSON с type."""
        app = app_with_mocks

        cmd, params = app.parse_command('{"command": "container_unloaded", "type": "aluminium"}')

        assert cmd == "container_unloaded"
        assert params["param"] == "aluminium"

    def test_parse_command_none(self, app_with_mocks):
        """Проверить парсинг None."""
        app = app_with_mocks

        cmd, params = app.parse_command(None)

        assert cmd is None
        assert params == {}


class TestCommandHandlers:
    """Тесты для обработчиков команд."""

    @pytest.fixture
    def app_with_mocks(self):
        """Application с замоканными зависимостями."""
        with patch('plc.application.PLC') as mock_plc, \
             patch('plc.application.WebSocket') as mock_ws:
            from plc import Application

            app = Application(
                serial_port='/dev/ttyUSB0',
                baudrate=115200,
                slave_address=2
            )
            app.PLC = MagicMock()
            app.websocket_server = MagicMock()

            # Настроим возвращаемые значения PLC
            app.PLC.get_bottle_count.return_value = 10
            app.PLC.get_bank_count.return_value = 5
            app.PLC.get_bottle_fill_percent.return_value = 50
            app.PLC.get_bank_fill_percent.return_value = 25
            app.PLC.get_state_left_sensor_carriage.return_value = 0
            app.PLC.get_state_center_sensor_carriage.return_value = 1
            app.PLC.get_state_right_sensor_carriage.return_value = 0
            app.PLC.get_state_weight_error.return_value = 0

            yield app

    def test_handle_get_device_info(self, app_with_mocks):
        """Проверить обработку get_device_info."""
        import json
        app = app_with_mocks

        app.handle_get_device_info()

        app.websocket_server.send_to_client.assert_called_once()
        call_args = app.websocket_server.send_to_client.call_args
        assert call_args[0][0] == "app"

        # Проверяем содержимое события
        event_json = call_args[0][1]
        event = json.loads(event_json)
        assert event["event"] == "device_info"
        assert event["data"]["bottle_count"] == 10
        assert event["data"]["bank_count"] == 5

    def test_handle_container_dump_plastic(self, app_with_mocks):
        """Проверить обработку dump_container:plastic."""
        from plc import AppState
        app = app_with_mocks

        app.handle_container_dump("plastic")

        assert app.state == AppState.DUMPING_PLASTIC
        app.PLC.cmd_force_move_carriage_left.assert_called_once()

    def test_handle_container_dump_aluminium(self, app_with_mocks):
        """Проверить обработку dump_container:aluminium."""
        from plc import AppState
        app = app_with_mocks

        app.handle_container_dump("aluminium")

        assert app.state == AppState.DUMPING_ALUMINUM
        app.PLC.cmd_force_move_carriage_right.assert_called_once()

    def test_handle_container_unloaded_plastic(self, app_with_mocks):
        """Проверить обработку container_unloaded:plastic."""
        app = app_with_mocks

        app.handle_container_unloaded("plastic")

        app.PLC.cmd_reset_bottle_counters.assert_called_once()

    def test_handle_container_unloaded_aluminium(self, app_with_mocks):
        """Проверить обработку container_unloaded:aluminium."""
        app = app_with_mocks

        app.handle_container_unloaded("aluminium")

        app.PLC.cmd_reset_bank_counters.assert_called_once()

    def test_handle_stub_command(self, app_with_mocks):
        """Проверить обработку команды-заглушки."""
        import json
        app = app_with_mocks

        app.handle_stub_command("open_shutter")

        # Проверяем, что отправлено событие с ack
        app.websocket_server.send_to_client.assert_called_once()
        call_args = app.websocket_server.send_to_client.call_args
        event_json = call_args[0][1]
        event = json.loads(event_json)
        assert event["event"] == "open_shutter_ack"
        assert event["data"]["status"] == "not_implemented"


class TestVisionResponseWithEvents:
    """Тесты для _handle_vision_response_with_events."""

    @pytest.fixture
    def app_with_mocks(self):
        """Application с замоканными зависимостями."""
        with patch('plc.application.PLC') as mock_plc, \
             patch('plc.application.WebSocket') as mock_ws:
            from plc import Application

            app = Application(
                serial_port='/dev/ttyUSB0',
                baudrate=115200,
                slave_address=2
            )
            app.PLC = MagicMock()
            app.websocket_server = MagicMock()
            yield app

    def test_bottle_confirmed_sends_container_recognized(self, app_with_mocks):
        """Проверить отправку события container_recognized при подтверждении бутылки."""
        import json
        app = app_with_mocks
        app.current_plc_detection = "bottle"

        app._handle_vision_response_with_events("bottle")

        app.PLC.cmd_radxa_detected_bottle.assert_called_once()

        # Проверяем событие
        call_args = app.websocket_server.send_to_client.call_args
        event_json = call_args[0][1]
        event = json.loads(event_json)
        assert event["event"] == "container_recognized"
        assert event["data"]["type"] == "PET"

    def test_bank_confirmed_sends_container_recognized(self, app_with_mocks):
        """Проверить отправку события container_recognized при подтверждении банки."""
        import json
        app = app_with_mocks
        app.current_plc_detection = "bank"

        app._handle_vision_response_with_events("bank")

        app.PLC.cmd_radxa_detected_bank.assert_called_once()

        # Проверяем событие
        call_args = app.websocket_server.send_to_client.call_args
        event_json = call_args[0][1]
        event = json.loads(event_json)
        assert event["event"] == "container_recognized"
        assert event["data"]["type"] == "ALUMINUM"

    def test_vision_none_sends_container_not_recognized(self, app_with_mocks):
        """Проверить отправку события container_not_recognized при none от vision."""
        import json
        app = app_with_mocks
        app.current_plc_detection = "bottle"

        app._handle_vision_response_with_events("none")

        # Проверяем событие
        call_args = app.websocket_server.send_to_client.call_args
        event_json = call_args[0][1]
        event = json.loads(event_json)
        assert event["event"] == "container_not_recognized"

    def test_mismatch_sends_container_not_recognized(self, app_with_mocks):
        """Проверить отправку события container_not_recognized при несовпадении."""
        import json
        app = app_with_mocks
        app.current_plc_detection = "bottle"

        app._handle_vision_response_with_events("bank")

        # PLC команды не должны вызываться
        app.PLC.cmd_radxa_detected_bottle.assert_not_called()
        app.PLC.cmd_radxa_detected_bank.assert_not_called()

        # Проверяем событие
        call_args = app.websocket_server.send_to_client.call_args
        event_json = call_args[0][1]
        event = json.loads(event_json)
        assert event["event"] == "container_not_recognized"
        assert event["data"]["plc_type"] == "bottle"
        assert event["data"]["vision_type"] == "bank"
