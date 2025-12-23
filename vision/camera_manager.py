"""
CameraManager - управление камерой с буферизацией кадров.

Обеспечивает:
- Открытие/закрытие камеры с retry
- Фоновый захват кадров в кольцевой буфер
- Thread-safe доступ к последнему кадру
"""
import threading
import time
from collections import deque
from typing import Optional

import cv2
import numpy as np

from core.config import Settings


class CameraManager:
    """
    Менеджер камеры с поддержкой фонового захвата кадров.

    Использование:
        manager = CameraManager(settings)
        if manager.open():
            manager.start_capture()
            ...
            frame = manager.get_frame()
            ...
            manager.stop_capture()
            manager.close()
    """

    def __init__(self, settings: Settings):
        """
        Инициализация менеджера камеры.

        Args:
            settings: Настройки приложения.
        """
        self._settings = settings
        self._cap: Optional[cv2.VideoCapture] = None
        self._is_open = False

        # Буфер кадров
        self._buffer: deque = deque(maxlen=settings.frame_buffer_size)
        self._buffer_lock = threading.Lock()

        # Поток захвата
        self._capture_thread: Optional[threading.Thread] = None
        self._capture_running = False
        self._capture_stop_event = threading.Event()

        # Статистика
        self._frames_captured = 0
        self._last_capture_time: Optional[float] = None

    def open(self, camera_index: Optional[int] = None) -> bool:
        """
        Открыть камеру с retry при ошибке.

        Args:
            camera_index: Индекс камеры. Если None, используется из настроек.

        Returns:
            True если камера успешно открыта, False иначе.
        """
        if self._is_open:
            return True

        # Используем переданный индекс или из настроек
        idx = camera_index if camera_index is not None else self._settings.camera_index

        for attempt in range(1, self._settings.retry_count + 1):
            try:
                self._cap = cv2.VideoCapture(idx)

                if not self._cap.isOpened():
                    print(f"[CameraManager] Попытка {attempt}/{self._settings.retry_count}: "
                          f"не удалось открыть камеру {idx}")
                    self._cap.release()
                    self._cap = None
                    time.sleep(self._settings.retry_delay)
                    continue

                # Настройка камеры
                fourcc = cv2.VideoWriter_fourcc(*self._settings.camera_fourcc)
                self._cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.camera_width)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.camera_height)
                self._cap.set(cv2.CAP_PROP_FPS, self._settings.camera_fps)

                # Даем камере время на инициализацию
                time.sleep(0.1)

                # Проверка захвата тестового кадра (несколько попыток)
                test_frame = None
                for read_attempt in range(5):  # До 5 попыток захвата тестового кадра
                    ret, test_frame = self._cap.read()
                    if ret and test_frame is not None and test_frame.size > 0:
                        break
                    time.sleep(0.1)  # Небольшая задержка между попытками
                
                if test_frame is None or test_frame.size == 0:
                    print(f"[CameraManager] Попытка {attempt}/{self._settings.retry_count}: "
                          f"не удалось захватить тестовый кадр (индекс {idx})")
                    self._cap.release()
                    self._cap = None
                    time.sleep(self._settings.retry_delay)
                    continue

                # Успешно
                actual_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = self._cap.get(cv2.CAP_PROP_FPS)
                if actual_fps <= 0:
                    actual_fps = self._settings.camera_fps

                print(f"[CameraManager] Камера открыта: {actual_width}x{actual_height} @ {actual_fps:.1f} fps")
                self._is_open = True
                return True

            except Exception as e:
                print(f"[CameraManager] Попытка {attempt}/{self._settings.retry_count}: ошибка - {e}")
                if self._cap:
                    self._cap.release()
                    self._cap = None
                time.sleep(self._settings.retry_delay)

        print(f"[CameraManager] Не удалось открыть камеру после {self._settings.retry_count} попыток")
        return False

    def close(self) -> None:
        """Закрыть камеру и освободить ресурсы."""
        self.stop_capture()

        if self._cap:
            self._cap.release()
            self._cap = None

        self._is_open = False
        self._clear_buffer()
        print("[CameraManager] Камера закрыта")

    def is_open(self) -> bool:
        """Проверить, открыта ли камера."""
        return self._is_open and self._cap is not None and self._cap.isOpened()

    def start_capture(self) -> bool:
        """
        Запустить фоновый поток захвата кадров.

        Returns:
            True если поток запущен, False если камера не открыта.
        """
        if not self.is_open():
            print("[CameraManager] Невозможно запустить захват: камера не открыта")
            return False

        if self._capture_running:
            return True

        self._capture_stop_event.clear()
        self._capture_running = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="CameraCapture",
            daemon=True
        )
        self._capture_thread.start()
        print("[CameraManager] Фоновый захват запущен")
        return True

    def stop_capture(self) -> None:
        """Остановить фоновый поток захвата кадров."""
        if not self._capture_running:
            return

        self._capture_running = False
        self._capture_stop_event.set()

        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)

        self._capture_thread = None
        print(f"[CameraManager] Фоновый захват остановлен (захвачено кадров: {self._frames_captured})")

    def get_frame(self) -> Optional[np.ndarray]:
        """
        Получить последний захваченный кадр из буфера.

        Returns:
            Кадр как numpy array или None если буфер пуст.
        """
        with self._buffer_lock:
            if not self._buffer:
                return None
            return self._buffer[-1].copy()

    def get_frame_with_timestamp(self) -> tuple[Optional[np.ndarray], Optional[float]]:
        """
        Получить последний кадр и время его захвата.

        Returns:
            Кортеж (кадр, timestamp) или (None, None).
        """
        with self._buffer_lock:
            if not self._buffer:
                return None, None
            return self._buffer[-1].copy(), self._last_capture_time

    def capture_single_frame(self) -> Optional[np.ndarray]:
        """
        Захватить один кадр напрямую (без буфера).
        Полезно когда фоновый захват не запущен.

        Returns:
            Кадр или None при ошибке.
        """
        if not self.is_open():
            return None

        try:
            ret, frame = self._cap.read()
            if ret and frame is not None:
                return frame.copy()
        except Exception as e:
            print(f"[CameraManager] Ошибка при захвате кадра: {e}")

        return None

    @property
    def frames_captured(self) -> int:
        """Количество захваченных кадров с момента запуска."""
        return self._frames_captured

    @property
    def buffer_size(self) -> int:
        """Текущий размер буфера."""
        with self._buffer_lock:
            return len(self._buffer)

    def _capture_loop(self) -> None:
        """Основной цикл захвата кадров (выполняется в отдельном потоке)."""
        consecutive_failures = 0
        max_failures = 10

        while self._capture_running and not self._capture_stop_event.is_set():
            try:
                if not self._cap or not self._cap.isOpened():
                    print("[CameraManager] Камера отключена, останавливаем захват")
                    break

                ret, frame = self._cap.read()

                if not ret or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        print(f"[CameraManager] Слишком много ошибок захвата ({max_failures}), останавливаем")
                        break
                    time.sleep(0.01)
                    continue

                # Успешный захват
                consecutive_failures = 0
                capture_time = time.time()

                with self._buffer_lock:
                    self._buffer.append(frame)
                    self._last_capture_time = capture_time

                self._frames_captured += 1

            except Exception as e:
                print(f"[CameraManager] Ошибка в цикле захвата: {e}")
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    break
                time.sleep(0.01)

        self._capture_running = False

    def _clear_buffer(self) -> None:
        """Очистить буфер кадров."""
        with self._buffer_lock:
            self._buffer.clear()
            self._last_capture_time = None
