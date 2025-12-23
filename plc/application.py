import time
import json
import base64
from pathlib import Path
from datetime import datetime
from plc.plc import PLC
import threading
import signal
import sys
from websocket import WebSocket
from enum import Enum
from core.logging_config import get_logger, setup_logging

# Инициализация логирования
setup_logging()
logger = get_logger(__name__)


class AppState(Enum):
    """Состояния конечного автомата приложения."""
    IDLE = "idle"
    WAITING_VISION = "waiting_vision"
    DUMPING_PLASTIC = "dumping_plastic"
    DUMPING_ALUMINUM = "dumping_aluminum"
    ERROR = "error"

class Application:
    def __init__(self, serial_port, baudrate, slave_address, cmd_register = 25, status_register = 26, update_data_period = 0.1, web_socket_port = 8765, web_socket_host = 'localhost', speed = 500, photos_dir = 'imgs'):
        self.PLC = None
        self.websocket_server = None
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.slave_address = slave_address
        self.cmd_register = cmd_register
        self.status_register = status_register
        self.update_data_period = update_data_period
        self.web_socket_port = web_socket_port
        self.web_socket_host = web_socket_host
        self.running = True
        self.speed = speed
        self.photos_dir = Path(photos_dir)
        # Создаём папку для фото, если её нет
        self.photos_dir.mkdir(parents=True, exist_ok=True)

        # Конфигурация устройства
        self.device_config = None
        
        # Состояние виртуальной двери (пока нет поддержки в ПЛК)
        self.door_locked = False

        self.flag = False
        self.time_flag = time.time()

        self.thread_websocket = None
        self.thread_terminal = None
        self.thread_update_data = None
        
        # State Machine
        self.state = AppState.IDLE
        self.state_lock = threading.Lock()  # Lock для потокобезопасности

        # Таймауты (секунды)
        self.vision_timeout = 2.0           # Таймаут ответа от vision
        self.dump_timeout = 3.0             # Таймаут движения каретки

        # Временные данные для state machine
        self.current_plc_detection = None   # "bottle" или "bank" - что детектировал ПЛК
        self.vision_request_time = None     # Время отправки запроса к vision
        self.dump_started_time = None       # Время начала сброса каретки

        # Отслеживание завесы
        self.prev_veil_state = 0            # Предыдущее состояние завесы
        self.veil_just_cleared = False      # Флаг: завеса только что освободилась
        self.veil_cleared_time = None       # Время когда veil_just_cleared стал True

        # Отслеживание движения каретки после детекции
        self.carriage_moving_bottle = False  # Флаг: каретка движется после детекции бутылки
        self.carriage_moving_bank = False   # Флаг: каретка движется после детекции банки
        self.carriage_moving_start_time = None  # Время начала движения каретки
        self.carriage_reset_timeout = 2.0   # Таймаут для обнуления регистров (секунды)

        # Отслеживание состояния приёмника и ошибок (для событий)
        self._prev_receiver_state = False      # Предыдущее состояние приёмника (есть контейнер?)
        self._prev_weight_error = False        # Предыдущее состояние ошибки веса
        self._prev_weight_too_small = False    # Предыдущее состояние "вес слишком маленький"
        self._prev_left_movement_error = False # Предыдущее состояние ошибки движения влево
        self._prev_right_movement_error = False # Предыдущее состояние ошибки движения вправо

        # Защита от повторного инференса для одного контейнера
        self._inference_requested = False      # Флаг: инференс уже запрошен для текущего контейнера
        self._pending_vision_response = None   # Ответ vision, ожидающий ответа ПЛК

        # Command Registry: команда → (handler, требует_param)
        self._command_handlers = {
            "get_photo": (self.handle_get_photo, False),
            "get_device_info": (self.handle_get_device_info, False),
            "device_init": (self.handle_device_init, True),
            "dump_container": (self.handle_container_dump, True),
            "container_unloaded": (self.handle_container_unloaded, True),
            "lock_door": (self.handle_lock_door, False),
            "unlock_door": (self.handle_unlock_door, False),
            # Заглушки
            "enter_service_mode": (self.handle_stub_command, False),
            "exit_service_mode": (self.handle_stub_command, False),
            "restore_device": (self.handle_stub_command, False),
            "open_shutter": (self.handle_stub_command, False),
            "reboot_device": (self.handle_stub_command, False),
            # Служебные команды PLC
            "cmd_full_clear_register": (lambda: self.PLC.cmd_full_clear_register(), False),
            "cmd_force_move_carriage_left": (lambda: self.PLC.cmd_force_move_carriage_left(), False),
            "cmd_force_move_carriage_right": (lambda: self.PLC.cmd_force_move_carriage_right(), False),
            "cmd_weight_error_reset": (lambda: self.PLC.cmd_weight_error_reset(), False),
            "cmd_reset_weight_reading": (lambda: self.PLC.cmd_reset_weight_reading(), False),
        }

        # Конфигурация состояний DUMPING для унификации
        self._dumping_config = {
            AppState.DUMPING_PLASTIC: {
                "sensor_getter": lambda: self.PLC.get_state_left_sensor_carriage(),
                "type": "plastic",
                "counter_getter": lambda: self.PLC.get_bottle_count(),
                "error_code": "carriage_left_timeout",
                "error_message": "Таймаут движения каретки влево",
                "direction": "влево",
            },
            AppState.DUMPING_ALUMINUM: {
                "sensor_getter": lambda: self.PLC.get_state_right_sensor_carriage(),
                "type": "aluminum",
                "counter_getter": lambda: self.PLC.get_bank_count(),
                "error_code": "carriage_right_timeout",
                "error_message": "Таймаут движения каретки вправо",
                "direction": "вправо",
            },
        }

    def signal_handler(self, sig, frame):
        self.running = False

    def start_threads(self):
        self.thread_update_data = threading.Thread(target=self.PLC_update_data)
        self.thread_update_data.start()

        # self.websocket_server = WebSocket(self.PLC, self.web_socket_host, self.web_socket_port)
        self.websocket_server.start()

    def stop(self):
        self.running = False
        if self.thread_update_data and self.thread_update_data.is_alive():
            self.thread_update_data.join()
        if self.PLC:
            self.PLC.stop()
        if self.websocket_server:
            self.websocket_server.stop()
        logger.info("Application stopped")


    def PLC_update_data(self):
        """Поток непрерывного опроса данных ПЛК."""
        try:
            while self.running:
                self.PLC.update_data()
                time.sleep(self.update_data_period)
        except Exception as e:
            logger.error(f"Ошибка обновления данных PLC: {e}")


    def setup(self):
        try:
            self.PLC = PLC(self.serial_port, self.baudrate, self.slave_address, self.cmd_register, self.status_register, self.speed)
            self.websocket_server = WebSocket(self.PLC, self.web_socket_host, self.web_socket_port)
            time.sleep(1) 
            self.start_threads()

        except Exception as e:
            logger.error(f"Ошибка инициализации: {e}")
            return False
        return True



    def run(self):
        signal.signal(signal.SIGINT, self.signal_handler)
        try:
            while self.running:
                # ОБРАБОТКА СОСТОЯНИЙ STATE MACHINE
                if self.state in (AppState.DUMPING_PLASTIC, AppState.DUMPING_ALUMINUM):
                    self._handle_dumping_state(self.state)

                # Проверка таймаута для обнуления регистров после детекции
                if self.carriage_moving_bottle and self.carriage_moving_start_time:
                    if time.time() - self.carriage_moving_start_time > self.carriage_reset_timeout:
                        logger.info("Таймаут движения каретки (бутылка) → обнуление регистра")
                        self.PLC.cmd_radxa_stop_detected_bottle()
                        self.carriage_moving_bottle = False
                        self.carriage_moving_start_time = None
                
                if self.carriage_moving_bank and self.carriage_moving_start_time:
                    if time.time() - self.carriage_moving_start_time > self.carriage_reset_timeout:
                        logger.info("Таймаут движения каретки (банка) → обнуление регистра")
                        self.PLC.cmd_radxa_stop_detected_bank()
                        self.carriage_moving_bank = False
                        self.carriage_moving_start_time = None

                if self.state == AppState.WAITING_VISION:
                    # Получаем ответ от vision (одноразовое чтение)
                    vision_response = self.websocket_server.get_command("vision")

                    # Сохраняем ответ vision, если получен
                    if vision_response and vision_response != "" and self._pending_vision_response is None:
                        logger.info(f"Vision ответил: {vision_response}")
                        self._pending_vision_response = vision_response

                        # Вычисляем дельту времени между veil_just_cleared и ответом от vision
                        if self.veil_cleared_time is not None:
                            delta_ms = (time.time() - self.veil_cleared_time) * 1000
                            print(f"[TIMING] Дельта: {delta_ms:.2f} мс (veil_cleared → vision_response)")
                            self.veil_cleared_time = None

                    # Обновляем current_plc_detection из ПЛК если ещё не определён
                    if self.current_plc_detection is None:
                        if self.PLC.get_bottle_exist() == 1:
                            self.current_plc_detection = "plastic"
                            logger.info("ПЛК определил: plastic")
                        elif self.PLC.get_bank_exist() == 1:
                            self.current_plc_detection = "aluminum"
                            logger.info("ПЛК определил: aluminum")

                    # Проверяем готовность обоих результатов
                    if self._pending_vision_response is not None and self.current_plc_detection is not None:
                        # Оба готовы - принимаем решение
                        self._handle_vision_response_with_events(self._pending_vision_response)
                        with self.state_lock:
                            self.state = AppState.IDLE
                        self.vision_request_time = None
                        self.current_plc_detection = None
                        self._pending_vision_response = None
                    elif time.time() - self.vision_request_time > self.vision_timeout:
                        # Таймаут ожидания
                        if self._pending_vision_response is None:
                            logger.warning("ТАЙМАУТ ожидания vision → IDLE")
                        else:
                            logger.warning("ТАЙМАУТ ожидания ПЛК → IDLE")

                        # Вычисляем дельту времени даже при таймауте
                        if self.veil_cleared_time is not None:
                            delta_ms = (time.time() - self.veil_cleared_time) * 1000
                            print(f"[TIMING] Дельта (таймаут): {delta_ms:.2f} мс (veil_cleared → timeout)")
                            self.veil_cleared_time = None

                        with self.state_lock:
                            self.state = AppState.IDLE
                        self.vision_request_time = None
                        self.current_plc_detection = None
                        self._pending_vision_response = None
                        # Событие: контейнер не распознан
                        self.send_event_to_app("container_not_recognized", {})

                elif self.state == AppState.ERROR:
                    # В состоянии ошибки принимаем команды, но обрабатываем только некоторые
                    self._handle_error_state_commands()

                # ОБРАБОТКА КОМАНД ТОЛЬКО В СОСТОЯНИИ IDLE
                elif self.state == AppState.IDLE:
                    
                    # Проверка подключения нового клиента (app)
                    if self.websocket_server.is_client_just_connected("app"):
                        logger.info("Новое подключение app → отправка device_info")
                        self.handle_get_device_info()

                    # Отслеживание завесы
                    current_veil = self.PLC.get_state_veil()
                    bottle_exist = self.PLC.get_bottle_exist()
                    bank_exist = self.PLC.get_bank_exist()
                    container_detected = bottle_exist == 1 or bank_exist == 1

                    # Сброс флага инференса когда контейнер убран из приёмника
                    if not container_detected:
                        self._inference_requested = False

                    # Детект перехода завесы: пересечена → свободна (рука убрана)
                    # Запуск инференса СРАЗУ при освобождении завесы (параллельно с ПЛК)
                    if self.prev_veil_state == 1 and current_veil == 0 and not self._inference_requested:
                        self.veil_just_cleared = True
                        self.veil_cleared_time = time.time()
                        self._inference_requested = True  # Помечаем что инференс запрошен

                        logger.info("Завеса освободилась → WAITING_VISION (инференс запущен)")
                        self.vision_request_time = time.time()

                        # Определяем тип контейнера по ПЛК (если уже есть) или используем bottle_exist по умолчанию
                        if self.PLC.get_bottle_exist() == 1:
                            self.current_plc_detection = "plastic"
                            vision_cmd = "bottle_exist"
                        elif self.PLC.get_bank_exist() == 1:
                            self.current_plc_detection = "aluminum"
                            vision_cmd = "bank_exist"
                        else:
                            # ПЛК ещё не определил тип - запускаем инференс всё равно
                            self.current_plc_detection = None
                            vision_cmd = "bottle_exist"  # Команда для запуска инференса

                        # Событие: контейнер обнаружен
                        self.send_event_to_app("container_detected", {"container_type": self.current_plc_detection or "unknown"})
                        # Сброс старых ответов vision перед новым запросом
                        self.websocket_server.get_command("vision")
                        self.websocket_server.send_to_client("vision", vision_cmd)
                        with self.state_lock:
                            self.state = AppState.WAITING_VISION

                    # Сброс флага если завеса снова пересечена
                    if current_veil == 1:
                        self.veil_just_cleared = False
                        self.veil_cleared_time = None

                    self.prev_veil_state = current_veil

                    # Обработка команд от app через command registry
                    app_message = self.websocket_server.get_command("app")
                    if app_message:
                        app_command, params = self.parse_command(app_message)
                        if app_command:
                            self._dispatch_command(app_command, params)

                # Проверка состояния приёмника и ошибок (отправка событий при изменении)
                self._check_receiver_state()
                self._check_hardware_errors()

                time.sleep(0.01)

        except Exception as e:
            logger.error(f"Ошибка в главном цикле: {e}")
        finally:
            self.stop()

    # === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ СОБЫТИЙ И КОМАНД ===

    def _handle_dumping_state(self, state: AppState) -> None:
        """
        Унифицированная обработка состояний DUMPING_PLASTIC/DUMPING_ALUMINUM.

        Args:
            state: Текущее состояние (DUMPING_PLASTIC или DUMPING_ALUMINUM).
        """
        config = self._dumping_config[state]

        if config["sensor_getter"]() == 1:
            logger.info(f"Датчик {config['direction']} достигнут, обнуляем регистры")
            self.PLC.cmd_full_clear_register()
            with self.state_lock:
                self.state = AppState.IDLE
            self.dump_started_time = None
            self.send_event_to_app("container_accepted", {
                "container_type": config["type"],
                "counter": config["counter_getter"]()
            })
        elif time.time() - self.dump_started_time > self.dump_timeout:
            logger.warning(f"ТАЙМАУТ при движении {config['direction']}! → ERROR")
            self.PLC.cmd_full_clear_register()
            with self.state_lock:
                self.state = AppState.ERROR
            self.dump_started_time = None
            self.send_event_to_app("hardware_error", {
                "error_code": config["error_code"],
                "message": config["error_message"]
            })

    def _dispatch_command(self, command: str, params: dict) -> bool:
        """
        Диспетчер команд через command registry.

        Args:
            command: Название команды.
            params: Параметры команды.

        Returns:
            True если команда обработана, False если неизвестная команда.
        """
        if command not in self._command_handlers:
            logger.warning(f"Неизвестная команда от app: {command}")
            self.send_event_to_app("command_error", {
                "command": command,
                "error": "unknown_command"
            })
            return False

        handler, requires_param = self._command_handlers[command]

        # Заглушки получают название команды
        if handler == self.handle_stub_command:
            handler(command)
        elif requires_param:
            handler(params.get("param"))
        else:
            handler()

        return True

    def create_event(self, event_name: str, data: dict = None) -> str:
        """
        Создать JSON событие для отправки клиенту app.

        Args:
            event_name: Название события.
            data: Данные события (опционально).

        Returns:
            JSON строка с событием.
        """
        return json.dumps({
            "event": event_name,
            "data": data or {},
            "timestamp": datetime.now().isoformat()
        })

    def send_event_to_app(self, event_name: str, data: dict = None):
        """
        Отправить событие клиенту app.

        Args:
            event_name: Название события.
            data: Данные события (опционально).
        """
        event = self.create_event(event_name, data)
        self.websocket_server.send_to_client("app", event)
        logger.debug(f"Event → app: {event_name}: {data}")

    def _check_receiver_state(self):
        """Проверить и отправить событие состояния приёмника."""
        bottle = self.PLC.get_bottle_exist()
        bank = self.PLC.get_bank_exist()
        current_state = bottle or bank

        if current_state != self._prev_receiver_state:
            if current_state:
                self.send_event_to_app("receiver_not_empty", {
                    "bottle_exist": bottle,
                    "bank_exist": bank
                })
            else:
                self.send_event_to_app("receiver_empty", {})
            self._prev_receiver_state = current_state

    def _check_hardware_errors(self):
        """Проверить и отправить события об ошибках оборудования."""
        # Ошибка веса
        weight_error = self.PLC.get_state_weight_error()
        if weight_error and not self._prev_weight_error:
            self.send_event_to_app("hardware_error", {
                "error_code": "weight_error",
                "message": "Ошибка взвешивания"
            })
        self._prev_weight_error = weight_error

        # Вес слишком маленький
        weight_small = self.PLC.get_weight_too_small()
        if weight_small and not self._prev_weight_too_small:
            self.send_event_to_app("hardware_error", {
                "error_code": "weight_too_small",
                "message": "Вес слишком маленький"
            })
        self._prev_weight_too_small = weight_small

        # Ошибка движения влево
        left_error = self.PLC.get_left_movement_error()
        if left_error and not self._prev_left_movement_error:
            self.send_event_to_app("hardware_error", {
                "error_code": "left_movement_error",
                "message": "Ошибка движения каретки влево"
            })
        self._prev_left_movement_error = left_error

        # Ошибка движения вправо
        right_error = self.PLC.get_right_movement_error()
        if right_error and not self._prev_right_movement_error:
            self.send_event_to_app("hardware_error", {
                "error_code": "right_movement_error",
                "message": "Ошибка движения каретки вправо"
            })
        self._prev_right_movement_error = right_error

    def parse_command(self, message: str) -> tuple:
        """
        Парсить команду от клиента (только JSON).

        Поддерживает форматы:
        - JSON: {"command": "name", "container_type": "plastic"}
        - JSON: {"command": "name", "param": "value"} (для обратной совместимости некоторых команд)

        Args:
            message: Сообщение от клиента.

        Returns:
            Tuple (command_name, params_dict).
        """
        if not message:
            return None, {}

        # Попытка парсинга JSON
        try:
            data = json.loads(message)
            command = data.get("command")
            
            # Приоритет параметра container_type
            if "container_type" in data:
                data["param"] = data["container_type"]
            elif "config" in data:
                data["param"] = data["config"]
            
            return command, data
        except json.JSONDecodeError:
            logger.warning(f"Получена некорректная команда (не JSON): {message}")
            return None, {}

        return None, {}

    # === ОБРАБОТЧИКИ КОМАНД ОТ APP ===

    def handle_device_init(self, config: dict):
        """
        Обработчик команды device_init.
        
        Принимает конфигурацию устройства (лимиты, типы тары и т.д.).
        
        Args:
            config: Словарь с конфигурацией.
        """
        if not config:
            logger.warning("device_init: получена пустая конфигурация")
            return

        logger.info(f"Инициализация устройства с конфигурацией: {config}")
        self.device_config = config
        
        # Отправляем подтверждение
        self.send_event_to_app("device_init_ack", {"status": "ok"})

    def handle_get_device_info(self):
        """
        Обработчик команды get_device_info.

        Собирает информацию с ПЛК и отправляет событие device_info.
        """
        device_info = {
            "bottle_count": self.PLC.get_bottle_count(),
            "bank_count": self.PLC.get_bank_count(),
            "bottle_fill_percent": self.PLC.get_bottle_fill_percent(),
            "bank_fill_percent": self.PLC.get_bank_fill_percent(),
            "state": self.state.value,
            "left_sensor": self.PLC.get_state_left_sensor_carriage(),
            "center_sensor": self.PLC.get_state_center_sensor_carriage(),
            "right_sensor": self.PLC.get_state_right_sensor_carriage(),
            "weight_error": self.PLC.get_state_weight_error(),
            "door_locked": self.door_locked,  # Добавляем статус двери
        }
        self.send_event_to_app("device_info", device_info)

    def handle_get_photo(self):
        """
        Обработчик команды get_photo.

        Запускает фоновый поток, чтобы не блокировать главный цикл state machine.
        """
        threading.Thread(
            target=self._handle_get_photo_worker,
            daemon=True,
            name="photo-request-worker",
        ).start()

    def _handle_get_photo_worker(self):
        """
        Фоновая обработка get_photo.

        Запрашивает фото у vision сервиса, сохраняет на диск и отправляет путь клиенту app.
        Base64 данные клиенту НЕ отправляются.
        """
        # Сброс старых ответов и отправка команды get_photo в vision
        self.websocket_server.get_command("vision")
        self.websocket_server.send_to_client("vision", '{"command": "get_photo"}')

        # Ждём ответа с таймаутом (одноразовое чтение)
        start_time = time.time()
        while self.running and time.time() - start_time < 2.0:
            response = self.websocket_server.get_command("vision")
            if not response:
                time.sleep(0.1)
                continue
            if response.startswith("{"):
                try:
                    data = json.loads(response)
                    if "photo_base64" in data:
                        # Сохраняем фото в файл
                        photo_path = self._save_photo(data["photo_base64"])

                        # Формируем ответ клиенту: ТОЛЬКО ПУТЬ
                        response_data = {"timestamp": data.get("timestamp")}

                        if photo_path:
                            # Возвращаем абсолютный путь к файлу
                            response_data["photo_path"] = str(photo_path.absolute())
                            logger.info(f"Фото сохранено: {photo_path}")
                        else:
                            response_data["error"] = "save_failed"

                        self.send_event_to_app("photo_ready", response_data)
                        return
                    elif "error" in data:
                        self.send_event_to_app("photo_ready", {"error": data["error"]})
                        return
                except json.JSONDecodeError:
                    pass
            time.sleep(0.1)

        # Таймаут - vision недоступен
        self.send_event_to_app("photo_ready", {"error": "vision_unavailable"})

    def handle_container_dump(self, container_type: str):
        """
        Обработчик команды container_dump.

        Args:
            container_type: Тип контейнера ("plastic" или "aluminum").
        """
        if container_type == "plastic":
            logger.info("Команда: сброс пластика (влево)")
            with self.state_lock:
                self.state = AppState.DUMPING_PLASTIC
            self.dump_started_time = time.time()
            self.PLC.cmd_force_move_carriage_left()
            self.send_event_to_app("container_dumped", {"container_type": "plastic"})
        elif container_type == "aluminum":
            logger.info("Команда: сброс алюминия (вправо)")
            with self.state_lock:
                self.state = AppState.DUMPING_ALUMINUM
            self.dump_started_time = time.time()
            self.PLC.cmd_force_move_carriage_right()
            self.send_event_to_app("container_dumped", {"container_type": "aluminum"})
        else:
            logger.warning(f"Неизвестный тип контейнера: {container_type}")

    def handle_container_unloaded(self, container_type: str):
        """
        Обработчик команды container_unloaded (мешок выгружен).

        Args:
            container_type: Тип контейнера ("plastic" или "aluminum").
        """
        if container_type == "plastic":
            logger.info("Мешок пластика выгружен, сброс счетчика")
            self.PLC.cmd_reset_bottle_counters()
        elif container_type == "aluminum":
            logger.info("Мешок алюминия выгружен, сброс счетчика")
            self.PLC.cmd_reset_bank_counters()
        self.send_event_to_app("container_unloaded_ack", {"container_type": container_type})

    def handle_lock_door(self):
        """Обработчик команды блокировки двери."""
        logger.info("Команда: lock_door")
        self.door_locked = True
        self.send_event_to_app("up_door_locked", {"status": "ok"})

    def handle_unlock_door(self):
        """Обработчик команды разблокировки двери."""
        logger.info("Команда: unlock_door")
        self.door_locked = False
        self.send_event_to_app("up_door_unlocked", {"status": "ok"})

    def handle_stub_command(self, command_name: str):
        """
        Заглушка для команд, которые пока не реализованы.

        Args:
            command_name: Название команды.
        """
        logger.debug(f"Заглушка команды: {command_name}")
        self.send_event_to_app(f"{command_name}_ack", {"status": "not_implemented"})

    def _save_photo(self, photo_base64: str) -> Path:
        """
        Сохранить фото из base64 строки в файл.

        Args:
            photo_base64: Base64 строка с изображением.

        Returns:
            Path к сохранённому файлу или None в случае ошибки.
        """
        try:
            # Декодируем base64
            image_data = base64.b64decode(photo_base64)
            
            # Генерируем имя файла на основе timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # миллисекунды
            filename = f"photo_{timestamp}.jpg"
            file_path = self.photos_dir / filename
            
            # Сохраняем файл
            with open(file_path, 'wb') as f:
                f.write(image_data)
            
            return file_path
        except Exception as e:
            logger.error(f"Ошибка сохранения фото: {e}")
            return None

    # === ОБРАБОТЧИКИ VISION И ERROR ===

    def _handle_vision_response(self, vision_response: str):
        """
        Обработка ответа от vision сервиса (без событий, для тестов).

        Args:
            vision_response: Ответ vision ("plastic", "aluminum", "none").
        """
        if vision_response == "none":
            logger.info("Vision: контейнер не распознан")
            return

        # Проверяем совпадение с детектом ПЛК
        if self.current_plc_detection == "plastic" and vision_response == "plastic":
            logger.info("Vision: подтверждено plastic → PLC cmd")
            self.PLC.cmd_radxa_detected_bottle()
        elif self.current_plc_detection == "aluminum" and vision_response == "aluminum":
            logger.info("Vision: подтверждено aluminum → PLC cmd")
            self.PLC.cmd_radxa_detected_bank()
        else:
            logger.warning(f"Vision: несовпадение! ПЛК: {self.current_plc_detection}, Vision: {vision_response}")

    def _handle_vision_response_with_events(self, vision_response: str):
        """
        Обработка ответа от vision сервиса с отправкой событий.

        Args:
            vision_response: Ответ vision ("plastic", "aluminum", "none").
        """
        if vision_response == "none":
            logger.info("Vision: контейнер не распознан")
            # Событие: контейнер не распознан
            self.send_event_to_app("container_not_recognized", {})
            return

        # Проверяем совпадение с детектом ПЛК
        if self.current_plc_detection == "plastic" and vision_response == "plastic":
            logger.info("Vision: plastic → PLC cmd")
            self.PLC.cmd_radxa_detected_bottle()
            # Устанавливаем флаг начала движения каретки
            self.carriage_moving_bottle = True
            self.carriage_moving_start_time = time.time()
            # Событие: контейнер распознан
            self.send_event_to_app("container_recognized", {
                "container_type": "plastic",
                "confidence": 1.0  # TODO: получать от vision
            })
        elif self.current_plc_detection == "aluminum" and vision_response == "aluminum":
            logger.info("Vision: aluminum → PLC cmd")
            self.PLC.cmd_radxa_detected_bank()
            # Устанавливаем флаг начала движения каретки
            self.carriage_moving_bank = True
            self.carriage_moving_start_time = time.time()
            # Событие: контейнер распознан
            self.send_event_to_app("container_recognized", {
                "container_type": "aluminum",
                "confidence": 1.0  # TODO: получать от vision
            })
        else:
            logger.warning(f"Vision: несовпадение! ПЛК: {self.current_plc_detection}, Vision: {vision_response}")
            # Событие: несовпадение детекта
            self.send_event_to_app("container_not_recognized", {
                "plc_type": self.current_plc_detection,
                "vision_type": vision_response
            })

    def _handle_error_state_commands(self):
        """
        Обработка команд в состоянии ERROR.

        Принимает все команды, но обрабатывает только:
        - get_photo
        - get_device_info
        - dump_container
        - restore_device
        """
        app_message = self.websocket_server.get_command("app")
        app_command, params = self.parse_command(app_message)
        if not app_command:
            return

        app_param = params.get("param")

        # В ERROR обрабатываем только эти команды
        if app_command == "get_photo":
            self.handle_get_photo()
        elif app_command == "get_device_info":
            self.handle_get_device_info()
        elif app_command == "dump_container":
            self.handle_container_dump(app_param)
        elif app_command == "restore_device":
            logger.info("ERROR State: восстановление устройства → IDLE")
            with self.state_lock:
                self.state = AppState.IDLE
            self.send_event_to_app("restore_device_ack", {"status": "ok"})
        else:
            logger.debug(f"ERROR State: команда {app_command} игнорируется")
            self.send_event_to_app("command_error", {
                "command": app_command,
                "error": "not_allowed_in_error_state"
            })


if __name__ == "__main__":
    import os

    serial_port = os.getenv('PLC_SERIAL_PORT', '/dev/ttyUSB0')
    baudrate = int(os.getenv('PLC_BAUDRATE', '115200'))
    slave_address = int(os.getenv('PLC_SLAVE_ADDRESS', '2'))
    
    logger.info(f"Запуск Application с параметрами:")
    logger.info(f"  serial_port: {serial_port}")
    logger.info(f"  baudrate: {baudrate}")
    logger.info(f"  slave_address: {slave_address}")
    
    try:
        app = Application(
            serial_port=serial_port,
            baudrate=baudrate,
            slave_address=slave_address
        )
    
        if not app.setup():
            logger.error("Не удалось инициализировать приложение")
            sys.exit(1)
        
        logger.info("Application успешно инициализирован, запуск...")
        app.run()
        
    except KeyboardInterrupt:
        logger.info("завершение работы...")
    except Exception as e:
        logger.error(f"Ошибка при запуске приложения: {e}", exc_info=True)
        sys.exit(1)
