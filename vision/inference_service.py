#!/usr/bin/env python3
"""
Inference Service - WebSocket клиент для классификации объектов.

Протокол:
    Подключение → отправка "vision" (имя клиента)
    Получение "bottle_exist" → выполнение инференса → отправка "bottle" или "bank"
    Получение "bank_exist" → выполнение инференса → отправка "bottle" или "bank"
    Получение "none" → отправка "none"

Использование:
    python inference_service.py              # Запуск WebSocket клиента
    python inference_service.py --camera     # Интерактивный режим камеры
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Подавляем предупреждения OpenCV
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_VIDEOIO_DEBUG", "0")

import cv2
import websockets
from websockets.exceptions import ConnectionClosed

from vision.camera_manager import CameraManager
from core.config import Settings, get_settings
from vision.inference_engine import InferenceEngine
from core.logging_config import get_logger, setup_logging

# Инициализация логирования
setup_logging()
logger = get_logger(__name__)


class InferenceClient:
    """
    WebSocket клиент для обработки запросов на инференс.

    Протокол:
        Подключение → отправка "vision" (имя клиента)
        Получение "bottle_exist" → инференс → отправка "bottle" или "bank"
        Получение "bank_exist" → инференс → отправка "bottle" или "bank"
        Получение "none" → отправка "none"
    """

    def __init__(self, settings: Settings):
        """
        Инициализация клиента.

        Args:
            settings: Настройки приложения.
        """
        self._settings = settings
        self._camera = CameraManager(settings)
        self._engine = InferenceEngine(settings)
        self._running = False
        self._websocket = None

    def initialize(self) -> bool:
        """
        Инициализация: загрузка и прогрев модели.

        Returns:
            True если инициализация успешна.
        """
        logger.info("Инициализация...")

        if not self._engine.load_model():
            return False

        if not self._engine.warmup():
            return False

        # Создаём директорию для сохранения кадров
        if self._settings.save_frames:
            self._settings.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Инициализация завершена")
        return True

    async def start(self) -> None:
        """Запустить WebSocket клиент с автоматическим переподключением."""
        if not self._engine.is_ready():
            logger.error("Модель не готова")
            return

        uri = f"ws://{self._settings.websocket_host}:{self._settings.websocket_port}"
        self._running = True

        while self._running:
            try:
                logger.info(f"Подключение к {uri}...")
                async with websockets.connect(uri) as websocket:
                    self._websocket = websocket
                    logger.debug("Подключено, отправка имени клиента 'vision'...")

                    # Отправляем имя клиента (JSON)
                    await websocket.send(json.dumps({"client_id": "vision"}))
                    logger.info("Зарегистрирован как 'vision', ожидание запросов...")

                    # Открываем камеру и запускаем захват (с попыткой разных индексов)
                    if not self._camera.is_open():
                        camera_opened = False
                        camera_idx_used = None
                        # Пробуем разные индексы камеры
                        for camera_idx in range(5):  # Пробуем индексы 0-4
                            logger.debug(f"Попытка открыть камеру с индексом {camera_idx}...")
                            if self._camera.open(camera_index=camera_idx):
                                camera_opened = True
                                camera_idx_used = camera_idx
                                # Обновляем индекс в настройках для дальнейшего использования
                                self._settings.camera_index = camera_idx
                                logger.info(f"Камера успешно открыта с индексом {camera_idx}")
                                break
                            else:
                                # Сбрасываем состояние камеры перед следующей попыткой
                                self._camera.close()

                        if not camera_opened:
                            logger.error("Не удалось открыть камеру ни с одним индексом (0-4)")
                            await asyncio.sleep(self._settings.websocket_reconnect_delay)
                            continue

                    if not self._camera.start_capture():
                        logger.error("Не удалось запустить захват кадров")
                        self._camera.close()
                        await asyncio.sleep(self._settings.websocket_reconnect_delay)
                        continue

                    logger.info("Камера открыта, захват запущен")

                    # Основной цикл обработки сообщений
                    while self._running:
                        try:
                            # Получаем сообщение от сервера
                            message = await asyncio.wait_for(
                                websocket.recv(),
                                timeout=1.0
                            )
                            
                            response = await self._handle_message(message)
                            if response:
                                await websocket.send(response)

                        except asyncio.TimeoutError:
                            # Таймаут - это нормально, продолжаем слушать
                            continue
                        except ConnectionClosed:
                            logger.warning("Соединение закрыто сервером")
                            break
                        except Exception as e:
                            logger.error(f"Ошибка обработки сообщения: {e}")
                            continue

            except ConnectionRefusedError:
                logger.warning(f"Не удалось подключиться к {uri}, повтор через {self._settings.websocket_reconnect_delay} сек...")
            except Exception as e:
                logger.error(f"Ошибка подключения: {e}")
            
            # Закрываем камеру при разрыве соединения
            self._camera.stop_capture()
            self._camera.close()

            if self._running:
                await asyncio.sleep(self._settings.websocket_reconnect_delay)

        self._cleanup()

    def stop(self) -> None:
        """Остановить клиент."""
        self._running = False

    async def _handle_message(self, message: str) -> Optional[str]:
        """
        Обработка сообщения от сервера.

        Поддерживает форматы:
        - Строки: "bottle_exist", "bank_exist", "none"
        - JSON: {"command": "get_photo"}

        Args:
            message: Сообщение от сервера.

        Returns:
            Ответ клиенту или None если ответ не требуется.
        """
        logger.debug(f"Получено сообщение: {message}")

        # Попытка парсинга JSON команды
        try:
            data = json.loads(message)
            command = data.get("command")

            if command == "get_photo":
                return await self._handle_get_photo()

            logger.warning(f"Неизвестная JSON команда: {command}")
            return json.dumps({"error": "unknown_command"})

        except json.JSONDecodeError:
            pass  # Fallback к строковому протоколу

        # Строковый протокол
        message = message.strip().lower()

        if message == "none":
            return "none"

        if message in ("bottle_exist", "bank_exist"):
            return await self._handle_inference()

        logger.debug(f"Неизвестное сообщение: {message}")
        return None

    async def _handle_inference(self) -> str:
        """
        Выполнить мульти-инференс (3 кадра) и вернуть результат по большинству.

        Returns:
            "bottle", "bank" или "none".
        """
        # Фиксируем время начала распознавания
       
        
        if not self._camera.is_open():
            logger.warning("Камера не открыта")
            return "none"

        num_frames = 1#3
        results = []
        confidences = []

        for i in range(num_frames):
            # Получаем кадр
            frame = self._camera.get_frame()
            if frame is None:
                frame = self._camera.capture_single_frame()
                if frame is None:
                    logger.warning(f"Не удалось получить кадр {i+1}/{num_frames}")
                    continue

            # Сохраняем кадр если нужно
            if self._settings.save_frames:
                self._save_frame(frame, suffix=f"_inf{i+1}")

            # Выполняем инференс
            inference_start_time = time.time()
            class_name, confidence = self._engine.predict(frame)
            inference_delta_ms = (time.time() - inference_start_time) * 1000
            print(f"[TIMING] Дельта распознавания: {inference_delta_ms:.2f}")

            # Маппим результат
            if class_name == "plastic":
                result = "plastic"
            elif class_name == "aluminum":
                result = "aluminum"
            else:
                result = "none"

            results.append(result)
            confidences.append(confidence)
            logger.debug(f"Кадр {i+1}/{num_frames}: {class_name} ({confidence:.3f}) -> {result}")

        if not results:
            logger.warning("Не удалось получить ни одного кадра")
            return "none"

        # Голосование по большинству
        from collections import Counter
        vote_counts = Counter(results)
        final_result, count = vote_counts.most_common(1)[0]
        avg_confidence = sum(confidences) / len(confidences)

        # Вычисляем дельту времени между запросом и завершением распознавания
        

        logger.info(f"Итог: {final_result} (голосов: {count}/{len(results)}, средняя уверенность: {avg_confidence:.3f})")
        return final_result

    async def _handle_get_photo(self) -> str:
        """
        Обработчик команды get_photo.

        Захватывает кадр и возвращает его как base64 JSON.

        Returns:
            JSON с photo_base64 или error.
        """
        if not self._camera.is_open():
            logger.warning("Камера не открыта")
            return json.dumps({"error": "camera_unavailable"})

        # Получаем кадр
        frame = self._camera.get_frame()
        if frame is None:
            frame = self._camera.capture_single_frame()
            if frame is None:
                logger.warning("Не удалось получить кадр для get_photo")
                return json.dumps({"error": "frame_capture_failed"})

        # Сохраняем фото в папку для тестирования
        saved_path = self._save_frame(frame, suffix="_get_photo")

        # Кодируем в JPEG и base64
        try:
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            photo_b64 = base64.b64encode(buffer).decode('utf-8')

            return json.dumps({
                "photo_base64": photo_b64,
                "timestamp": datetime.now().isoformat(),
                "saved_path": str(saved_path) if saved_path else None
            })
        except Exception as e:
            logger.error(f"Ошибка кодирования кадра: {e}")
            return json.dumps({"error": "encoding_failed"})

    def _save_frame(self, frame, suffix: str = "") -> Path:
        """
        Сохранить кадр на диск.

        Args:
            frame: Кадр для сохранения.
            suffix: Суффикс для имени файла.

        Returns:
            Путь к сохранённому файлу или None при ошибке.
        """
        try:
            self._settings.output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = self._settings.output_dir / f"{timestamp}{suffix}.jpg"
            cv2.imwrite(str(filename), frame)
            logger.debug(f"Сохранено: {filename}")

            # Ротация: удаляем самые старые файлы при превышении лимита
            self._rotate_saved_frames()

            return filename
        except Exception as e:
            logger.error(f"Ошибка сохранения кадра: {e}")
            return None

    def _rotate_saved_frames(self, max_files: int = 1000) -> None:
        """
        Удалить самые старые файлы в output_dir при превышении лимита.

        Args:
            max_files: Максимальное количество файлов.
        """
        try:
            saved_files = sorted(
                [p for p in self._settings.output_dir.glob("*.jpg") if p.is_file()],
                key=lambda p: p.stat().st_mtime
            )
            overflow = len(saved_files) - max_files
            if overflow > 0:
                for old_file in saved_files[:overflow]:
                    try:
                        old_file.unlink()
                    except OSError as e:
                        logger.warning(f"Не удалось удалить старый файл {old_file}: {e}")
                logger.debug(f"Ротация: удалено {overflow} старых кадров")
        except Exception as e:
            logger.warning(f"Ошибка при ротации кадров: {e}")

    def _cleanup(self) -> None:
        """Освободить ресурсы."""
        self._camera.stop_capture()
        self._camera.close()
        logger.info("Остановлен")


def run_interactive_camera(settings: Settings) -> None:
    """
    Интерактивный режим камеры для тестирования.

    Args:
        settings: Настройки приложения.
    """
    engine = InferenceEngine(settings)
    camera = CameraManager(settings)

    if not engine.load_model():
        logger.error("Не удалось загрузить модель")
        return

    if not engine.warmup():
        logger.error("Не удалось прогреть модель")
        return

    if not camera.open():
        logger.error("Не удалось открыть камеру")
        return

    settings.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Интерактивный режим камеры")
    print("Команды: c - захват и инференс, q - выход")
    print("-" * 40)

    try:
        while True:
            cmd = input("\n> ").strip().lower()

            if cmd == "q":
                break
            elif cmd == "c":
                frame = camera.capture_single_frame()
                if frame is None:
                    logger.warning("Не удалось захватить кадр")
                    continue

                class_name, confidence = engine.predict(frame)
                logger.info(f"Результат: {class_name} ({confidence:.3f})")

                # Сохраняем кадр
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = settings.output_dir / f"{timestamp}_{class_name}.jpg"
                cv2.imwrite(str(filename), frame)
                logger.debug(f"Сохранено: {filename}")
            else:
                print("Неизвестная команда. Используйте 'c' или 'q'")

    except KeyboardInterrupt:
        logger.info("Прервано")
    finally:
        camera.close()


def parse_args():
    """Парсинг аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="Inference Service для классификации объектов"
    )
    parser.add_argument(
        "--camera",
        action="store_true",
        help="Интерактивный режим камеры (для тестирования)"
    )
    parser.add_argument(
        "--host",
        type=str,
        help="WebSocket хост (переопределяет .env)"
    )
    parser.add_argument(
        "--port",
        type=int,
        help="WebSocket порт (переопределяет .env)"
    )
    return parser.parse_args()


def main():
    """Точка входа."""
    args = parse_args()
    settings = get_settings()

    # Переопределяем настройки если указаны
    if args.host:
        settings.websocket_host = args.host
    if args.port:
        settings.websocket_port = args.port

    if args.camera:
        run_interactive_camera(settings)
    else:
        client = InferenceClient(settings)
        if client.initialize():
            try:
                asyncio.run(client.start())
            except KeyboardInterrupt:
                logger.info("Прервано пользователем")
                client.stop()


if __name__ == "__main__":
    main()
