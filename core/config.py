"""
Конфигурация inference сервиса.
Загружает параметры из .env файла с fallback на значения по умолчанию.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def _get_env_path(key: str, default: str) -> Path:
    """Получить путь из переменной окружения."""
    return Path(os.getenv(key, default))


def _get_env_int(key: str, default: int) -> int:
    """Получить целое число из переменной окружения."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_float(key: str, default: float) -> float:
    """Получить число с плавающей точкой из переменной окружения."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass
class Settings:
    """Настройки inference сервиса."""

    # Модель
    model_path: Path = field(default_factory=lambda: Path("weights/best_11s_rknn_model"))
    image_size: int = 1280
    warmup_runs: int = 2

    # Камера (2K разрешение)
    camera_index: int = 0
    camera_width: int = 2560
    camera_height: int = 1440
    camera_fps: int = 30
    camera_fourcc: str = "MJPG"

    # Буфер кадров
    frame_buffer_size: int = 3

    # TCP сервер (deprecated, используется WebSocket)
    tcp_host: str = "0.0.0.0"
    tcp_port: int = 8081
    tcp_timeout: float = 30.0

    # WebSocket клиент
    websocket_host: str = "localhost"
    websocket_port: int = 8765
    websocket_reconnect_delay: float = 5.0

    # Retry настройки для камеры
    retry_count: int = 3
    retry_delay: float = 0.5

    # Вывод
    output_dir: Path = field(default_factory=lambda: Path("real_time"))
    save_frames: bool = True

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> "Settings":
        """
        Загрузить настройки из .env файла.

        Args:
            env_path: Путь к .env файлу. Если None, ищет в текущей директории.

        Returns:
            Settings с загруженными значениями.
        """
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()

        return cls(
            # Модель
            model_path=_get_env_path("MODEL_PATH", "weights/best_11s_rknn_model"),
            image_size=_get_env_int("IMAGE_SIZE", 1280),
            warmup_runs=_get_env_int("WARMUP_RUNS", 2),

            # Камера (2K разрешение)
            camera_index=_get_env_int("CAMERA_INDEX", 0),
            camera_width=_get_env_int("CAMERA_WIDTH", 2560),
            camera_height=_get_env_int("CAMERA_HEIGHT", 1440),
            camera_fps=_get_env_int("CAMERA_FPS", 30),
            camera_fourcc=os.getenv("CAMERA_FOURCC", "MJPG"),

            # Буфер
            frame_buffer_size=_get_env_int("FRAME_BUFFER_SIZE", 3),

            # TCP (deprecated)
            tcp_host=os.getenv("TCP_HOST", "0.0.0.0"),
            tcp_port=_get_env_int("TCP_PORT", 8081),
            tcp_timeout=_get_env_float("TCP_TIMEOUT", 30.0),

            # WebSocket
            websocket_host=os.getenv("WEBSOCKET_HOST", "localhost"),
            websocket_port=_get_env_int("WEBSOCKET_PORT", 8765),
            websocket_reconnect_delay=_get_env_float("WEBSOCKET_RECONNECT_DELAY", 5.0),

            # Retry
            retry_count=_get_env_int("RETRY_COUNT", 3),
            retry_delay=_get_env_float("RETRY_DELAY", 0.5),

            # Вывод
            output_dir=_get_env_path("OUTPUT_DIR", "real_time"),
            save_frames=os.getenv("SAVE_FRAMES", "true").lower() in ("true", "1", "yes"),
        )


# Глобальный экземпляр настроек (lazy loading)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Получить глобальный экземпляр настроек.
    При первом вызове загружает из .env.
    """
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings




def reload_settings(env_path: Optional[Path] = None) -> Settings:
    """
    Перезагрузить настройки из .env файла.

    Args:
        env_path: Путь к .env файлу.

    Returns:
        Новый экземпляр Settings.
    """
    global _settings
    _settings = Settings.from_env(env_path)
    return _settings
