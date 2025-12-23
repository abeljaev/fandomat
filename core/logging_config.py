"""
Конфигурация логирования для BottleClassifier.

Уровни логирования:
- DEBUG: детальная отладочная информация (состояния датчиков, etc.)
- INFO: основные события (подключения, распознавание, etc.)
- WARNING: предупреждения (таймауты, повторные попытки)
- ERROR: ошибки (исключения, сбои)

Использование:
    from logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("Сообщение")
    logger.debug("Детали для отладки")

Переменные окружения:
    LOG_LEVEL: уровень логирования (DEBUG, INFO, WARNING, ERROR)
    LOG_FORMAT: формат сообщений (simple, detailed)
"""

import logging
import os
from typing import Optional


def get_log_level() -> int:
    """Получить уровень логирования из переменной окружения."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return levels.get(level_name, logging.INFO)


def get_log_format() -> str:
    """Получить формат логирования."""
    format_type = os.getenv("LOG_FORMAT", "simple").lower()
    if format_type == "detailed":
        return "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s"
    return "[%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: Optional[int] = None) -> None:
    """
    Настроить базовое логирование для всего приложения.

    Args:
        level: Уровень логирования (если None, берётся из LOG_LEVEL).
    """
    if level is None:
        level = get_log_level()

    logging.basicConfig(
        level=level,
        format=get_log_format(),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Подавляем излишние логи от библиотек
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Получить логгер для модуля.

    Args:
        name: Имя модуля (обычно __name__).

    Returns:
        Настроенный логгер.
    """
    logger = logging.getLogger(name)

    # Устанавливаем уровень если не настроен глобально
    if not logging.root.handlers:
        setup_logging()

    return logger
