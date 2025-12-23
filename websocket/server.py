import asyncio
import websockets
import json
from typing import Set
import threading
import signal
import time
from core.logging_config import get_logger

logger = get_logger(__name__)

command_list = {
    "open_shutter": "NONE",
    "close_shutter": "NONE",
    "get_photo": "NONE",
    "get_device_info": "NONE",
    "enter_service_mode": "NONE",
    "exit_service_mode": "NONE",
    "dump_container": "NONE",
    "restore_device": "NONE",
    "unlock_door": "NONE",
    "lock_door": "NONE",

    #состояние
    "shutter_opened": "NONE",
    "shutter_closed": "NONE",
    "receiver_not_empty": "NONE",
    "receiver_empty": "NONE",
    "container_detected": "NONE",
    "container_recognized": "NONE",
    "container_not_recognized": "NONE",
    "photo_captured": "NONE",
    "container_accepted": "NONE",
    "device_info_updated": "NONE",
    "service_mode_exited": "NONE",
    "hardware_error": "NONE",
    "photo_ready": "NONE",
    "device_info": "NONE",
    "container_dumped": "NONE",
    "unload_completed": "NONE",
    "restore_started": "NONE",
    "restore_completed": "NONE",
    "door_locked": "NONE",
    "door_unlocked": "NONE",
    "door_opened": "NONE",
    "door_closed": "NONE",
}

class WebSocket:
    def __init__(self, PLC, host = "localhost", port= 8765):
        self.host = host
        self.port = port
        self.PLC = PLC
        self.clients = {}  # Словарь: {"client_name": websocket}
        self._clients_lock = threading.Lock()  # Lock для потокобезопасного доступа к clients
        self.server = None
        self.loop = None
        self._thread = None
        self._running = False

        # Новая архитектура: словарь последних сообщений
        self.client_messages = {}
        self.message_lock = threading.Lock()
        
        # Старые переменные для обратной совместимости (deprecated)
        self.request = "NONE"
        self.response = ""
        self.message_app = ""
        
    async def _handler(self, websocket):
        client_name = None
        logger.debug(f"Новое подключение. Всего клиентов: {len(self.clients)}")
        
        try:
            # Первое сообщение - регистрация
            raw_msg = await websocket.recv()
            try:
                # Пытаемся распарсить JSON
                data = json.loads(raw_msg)
                # Поддержка разных форматов ключей для гибкости
                client_name = data.get("client_id") or data.get("name") or data.get("client")
            except json.JSONDecodeError:
                # Fallback для старых клиентов (plain text)
                client_name = raw_msg.strip()
                logger.warning(f"Клиент использует устаревший формат регистрации (plain text): '{client_name}'")

            if not client_name:
                logger.error("Не удалось определить имя клиента, закрываю соединение")
                await websocket.close()
                return

            with self._clients_lock:
                self.clients[client_name] = websocket

            # Инициализируем хранилище для этого клиента
            with self.message_lock:
                self.client_messages[client_name] = {
                    "message": "",
                    "timestamp": time.time(),
                    "just_connected": True  # Флаг нового подключения
                }
            
            logger.info(f"Клиент зарегистрирован: '{client_name}'. Всего: {len(self.clients)}")
            
            # Дальше обрабатываем обычные сообщения
            while True:
                message = await websocket.recv()
                
                # Сохраняем в новую структуру
                with self.message_lock:
                    self.client_messages[client_name] = {
                        "message": message,
                        "timestamp": time.time()
                    }
                
                # Обратная совместимость
                self.request = message
                if client_name == "app":
                    self.message_app = message
                
        except websockets.exceptions.ConnectionClosed:
            logger.debug(f"Соединение закрыто ({client_name})")
        finally:
            if client_name:
                with self._clients_lock:
                    if client_name in self.clients:
                        del self.clients[client_name]
                with self.message_lock:
                    if client_name in self.client_messages:
                        del self.client_messages[client_name]
            with self._clients_lock:
                remaining = len(self.clients)
            logger.info(f"Клиент отключен ({client_name}). Осталось: {remaining}")




    
    async def _run_server(self):
        self.server = await websockets.serve(
            self._handler,
            self.host,
            self.port
        )
        logger.info(f"Сервер запущен на ws://{self.host}:{self.port}")
        
        # Бесконечный цикл
        self._running = True
        while self._running:
            await asyncio.sleep(1)
    
    def _run_in_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._run_server())
    
    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("Сервер уже запущен")
            return
        
        self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self._thread.start()
        logger.debug("Сервер запускается в фоновом потоке...")
    
    def stop(self):
        self._running = False
        
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._stop_async(), self.loop)
        
        if self._thread:
            self._thread.join(timeout=2)
            logger.info("Сервер остановлен")
    
    async def _stop_async(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
    
    def is_running(self):
        return self._running and self._thread and self._thread.is_alive()
    
    async def send_to_client_async(self, client_name: str, message: str):
        """Отправить сообщение конкретному клиенту"""
        with self._clients_lock:
            websocket = self.clients.get(client_name)
        if websocket:
            try:
                await websocket.send(message)
            except Exception as e:
                logger.error(f"Ошибка отправки клиенту {client_name}: {e}")
        else:
            logger.debug(f"Клиент {client_name} не найден")
    
    def send_to_client(self, client_name: str, message: str):
        """Отправить сообщение конкретному клиенту (из синхронного кода)"""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.send_to_client_async(client_name, message),
                self.loop
            )
    
    async def broadcast_async(self, message: str):
        """Отправить сообщение всем клиентам"""
        with self._clients_lock:
            clients_copy = list(self.clients.values())
        if clients_copy:
            await asyncio.gather(
                *[client.send(message) for client in clients_copy],
                return_exceptions=True
            )
    
    def broadcast(self, message: str):
        """Отправить сообщение всем клиентам (из синхронного кода)"""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.broadcast_async(message),
                self.loop
            )
    
    def get_command(self, client_name: str) -> str:
        """Получить команду от клиента (одноразовое действие) и обнулить её"""
        with self.message_lock:
            if client_name in self.client_messages:
                message = self.client_messages[client_name]["message"]
                self.client_messages[client_name]["message"] = ""  # Обнуляем после прочтения
                return message
            return ""

    def is_client_just_connected(self, client_name: str) -> bool:
        """
        Проверить, подключился ли клиент только что.
        Сбрасывает флаг после проверки.
        """
        with self.message_lock:
            if client_name in self.client_messages:
                if self.client_messages[client_name].get("just_connected", False):
                    self.client_messages[client_name]["just_connected"] = False
                    return True
        return False
    
    def get_state(self, client_name: str) -> str:
        """Получить состояние от клиента (непрерывное значение)"""
        with self.message_lock:
            if client_name in self.client_messages:
                return self.client_messages[client_name]["message"]
            return ""