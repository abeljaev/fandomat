#!/usr/bin/env python3
"""
Backend Simulator - симулятор backend сервиса для тестирования WebSocket API.

Подключается к Application как клиент "app" и позволяет:
- Отправлять команды вручную
- Получать события от автомата
- Тестировать полный цикл работы

Использование:
    python backend_simulator.py              # localhost:8765
    python backend_simulator.py --host HOST --port PORT
"""
import argparse
import asyncio
import json
from datetime import datetime
from typing import List, Optional

import websockets
from websockets.exceptions import ConnectionClosed


# Описания событий для красивого вывода
EVENT_DESCRIPTIONS = {
    "receiver_not_empty": "🟢 Приёмник: ЗАНЯТ",
    "receiver_empty": "⚪ Приёмник: ПУСТ",
    "container_detected": "📦 Контейнер обнаружен",
    "container_recognized": "✅ Контейнер распознан",
    "container_not_recognized": "❌ Контейнер НЕ распознан",
    "container_accepted": "✅ Контейнер принят",
    "container_dumped": "🗑️ Контейнер выгружен",
    "container_unloaded_ack": "📤 Мешок выгружен",
    "hardware_error": "⚠️ ОШИБКА ОБОРУДОВАНИЯ",
    "device_info": "ℹ️ Информация об устройстве",
    "photo_ready": "📷 Фото готово",
    "restore_device_ack": "🔧 Устройство восстановлено",
}


class BackendSimulator:
    """
    Симулятор backend сервиса для тестирования WebSocket API.

    Протокол:
        Подключение → отправка "app" (имя клиента)
        Отправка команд в формате "command:param" или JSON
        Получение событий от автомата
    """

    def __init__(self, host: str, port: int):
        """
        Инициализация симулятора.

        Args:
            host: WebSocket хост.
            port: WebSocket порт.
        """
        self.uri = f"ws://{host}:{port}"
        self.events: List[dict] = []
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False

    async def connect(self) -> bool:
        """
        Подключиться к WebSocket серверу.

        Returns:
            True если подключение успешно.
        """
        try:
            print(f"[Simulator] Подключение к {self.uri}...")
            self.ws = await websockets.connect(self.uri)
            # Отправляем регистрацию в JSON формате
            await self.ws.send(json.dumps({"client_id": "app"}))
            print("[Simulator] Подключено, зарегистрирован как 'app' (JSON)")
            return True
        except Exception as e:
            print(f"[Simulator] Ошибка подключения: {e}")
            return False

    async def send_command(self, command: str, params: dict = None):
        """
        Отправить команду на сервер.

        Args:
            command: Название команды.
            params: Параметры команды.
        """
        if not self.ws:
            print("[Simulator] Нет подключения")
            return

        if params:
            # JSON формат
            msg = json.dumps({"command": command, **params})
        else:
            # Строковый формат
            msg = command

        print(f"[Simulator] Отправка: {msg}")
        await self.ws.send(msg)

    async def listen_events(self, timeout: float = 0.5) -> Optional[dict]:
        """
        Получить событие от сервера.

        Args:
            timeout: Таймаут ожидания.

        Returns:
            Событие или None если таймаут.
        """
        if not self.ws:
            return None

        try:
            message = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            try:
                event = json.loads(message)
                self.events.append(event)
                return event
            except json.JSONDecodeError:
                return {"raw": message}
        except asyncio.TimeoutError:
            return None
        except ConnectionClosed:
            print("[Simulator] Соединение закрыто")
            return None

    async def listen_all_events(self, duration: float = 5.0):
        """
        Слушать все события в течение заданного времени.

        Args:
            duration: Длительность прослушивания в секундах.
        """
        print(f"[Simulator] Прослушивание событий {duration} сек...")
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < duration:
            event = await self.listen_events(timeout=0.5)
            if event:
                self._print_event(event)

    def _print_event(self, event: dict):
        """Вывести событие с красивым форматированием."""
        if "raw" in event:
            print(f"  [Raw] {event['raw']}")
            return

        event_name = event.get("event", "unknown")
        data = event.get("data", {})
        timestamp = event.get("timestamp", "")

        # Получаем описание события или используем имя
        desc = EVENT_DESCRIPTIONS.get(event_name, f"[{event_name}]")

        # Специальное форматирование для разных типов событий
        if event_name == "hardware_error":
            error_code = data.get("error_code", "unknown")
            message = data.get("message", "")
            print(f"\n  {desc}")
            print(f"    Код: {error_code}")
            print(f"    Сообщение: {message}")
        elif event_name == "container_recognized":
            container_type = data.get("type", "?")
            confidence = data.get("confidence", "N/A")
            print(f"\n  {desc}: {container_type} (уверенность: {confidence})")
        elif event_name == "receiver_not_empty":
            bottle = data.get("bottle_exist", False)
            bank = data.get("bank_exist", False)
            print(f"\n  {desc}")
            print(f"    bottle_exist: {bottle}, bank_exist: {bank}")
        elif event_name == "container_detected":
            plc_type = data.get("plc_type", "?")
            print(f"\n  {desc}: {plc_type}")
        elif event_name == "container_accepted":
            container_type = data.get("type", "?")
            counter = data.get("counter", "?")
            print(f"\n  {desc}: {container_type} (счётчик: {counter})")
        elif event_name == "device_info":
            print(f"\n  {desc}:")
            for key, value in data.items():
                print(f"    {key}: {value}")
        else:
            # Стандартный вывод
            if data:
                print(f"\n  {desc}: {data}")
            else:
                print(f"\n  {desc}")

    def show_event_history(self):
        """Показать историю событий."""
        print(f"\n=== История событий ({len(self.events)}) ===")
        for i, event in enumerate(self.events, 1):
            event_name = event.get("event", event.get("raw", "unknown"))
            data = event.get("data", {})
            print(f"{i}. {event_name}: {data}")
        print()

    async def close(self):
        """Закрыть соединение."""
        if self.ws:
            await self.ws.close()
            print("[Simulator] Соединение закрыто")


async def interactive_mode(simulator: BackendSimulator):
    """
    Интерактивный режим управления симулятором.

    Args:
        simulator: Экземпляр BackendSimulator.
    """
    print("\n=== Backend Simulator ===")
    print("Команды:")
    print("  1. get_device_info   - Получить информацию об устройстве")
    print("  2. get_photo         - Получить фото с камеры")
    print("  3. dump:plastic      - Выгрузить пластик")
    print("  4. dump:aluminium    - Выгрузить алюминий")
    print("  5. unload:plastic    - Мешок пластика выгружен")
    print("  6. unload:aluminium  - Мешок алюминия выгружен")
    print("  7. restore           - Восстановить устройство (из ERROR)")
    print("  8. listen            - Слушать события 5 сек")
    print("  9. history           - Показать историю событий")
    print("  0. clear_register    - Очистить регистр команд ПЛК")
    print("  l. lock_door         - Заблокировать дверь")
    print("  u. unlock_door       - Разблокировать дверь")
    print("  i. device_init       - Инициализировать устройство")
    print("  q. Выход")
    print("-" * 40)

    while True:
        try:
            cmd = input("\n> ").strip().lower()

            if cmd == "q":
                break
            elif cmd == "1":
                await simulator.send_command("get_device_info")
                await asyncio.sleep(0.3)
                event = await simulator.listen_events(timeout=2.0)
                if event:
                    simulator._print_event(event)
            elif cmd == "2":
                await simulator.send_command("get_photo")
                await asyncio.sleep(0.3)
                event = await simulator.listen_events(timeout=3.0)
                if event:
                    data = event.get("data", {})
                    photo_path = data.get("photo_path")
                    if photo_path:
                        print(f"  [Событие] photo_ready")
                        print(f"  [Файл] Путь на устройстве: {photo_path}")
                    elif "error" in data:
                        print(f"  [Ошибка] {data['error']}")
                    else:
                        simulator._print_event(event)
            elif cmd == "3":
                await simulator.send_command("dump_container", {"container_type": "plastic"})
                await simulator.listen_all_events(duration=5.0)
            elif cmd == "4":
                await simulator.send_command("dump_container", {"container_type": "aluminum"})
                await simulator.listen_all_events(duration=5.0)
            elif cmd == "5":
                await simulator.send_command("container_unloaded", {"container_type": "plastic"})
                await asyncio.sleep(0.3)
                event = await simulator.listen_events(timeout=2.0)
                if event:
                    simulator._print_event(event)
            elif cmd == "6":
                await simulator.send_command("container_unloaded", {"container_type": "aluminum"})
                await asyncio.sleep(0.3)
                event = await simulator.listen_events(timeout=2.0)
                if event:
                    simulator._print_event(event)
            elif cmd == "7":
                await simulator.send_command("restore_device")
                await asyncio.sleep(0.3)
                event = await simulator.listen_events(timeout=2.0)
                if event:
                    simulator._print_event(event)
            elif cmd == "8":
                await simulator.listen_all_events(duration=60.0)
            elif cmd == "9":
                simulator.show_event_history()
            elif cmd == "0":
                await simulator.send_command("cmd_full_clear_register")
                print("  Команда отправлена")
            elif cmd == "l":
                await simulator.send_command("lock_door")
                await asyncio.sleep(0.3)
                event = await simulator.listen_events(timeout=2.0)
                if event: simulator._print_event(event)
            elif cmd == "u":
                await simulator.send_command("unlock_door")
                await asyncio.sleep(0.3)
                event = await simulator.listen_events(timeout=2.0)
                if event: simulator._print_event(event)
            elif cmd == "i":
                config = {
                    "max_plastic_count": 500,
                    "max_aluminum_count": 300,
                    "accepted_types": ["plastic", "aluminum"]
                }
                await simulator.send_command("device_init", {"config": config})
                await asyncio.sleep(0.3)
                event = await simulator.listen_events(timeout=2.0)
                if event: simulator._print_event(event)

        except KeyboardInterrupt:
            print("\nПрервано")
            break
        except Exception as e:
            print(f"Ошибка: {e}")


def parse_args():
    """Парсинг аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Backend Simulator для тестирования WebSocket API"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="WebSocket хост (по умолчанию: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="WebSocket порт (по умолчанию: 8765)"
    )
    return parser.parse_args()


async def main():
    """Точка входа."""
    args = parse_args()
    simulator = BackendSimulator(args.host, args.port)

    if await simulator.connect():
        try:
            await interactive_mode(simulator)
        finally:
            await simulator.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nВыход")
