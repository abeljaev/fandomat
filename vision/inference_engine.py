"""
InferenceEngine - обёртка над YOLO моделью для классификации.

Обеспечивает:
- Загрузку модели один раз при старте
- Прогрев модели для стабильного времени инференса
- Единый интерфейс для предсказаний
"""
import time
from pathlib import Path
from typing import Optional

import numpy as np

from core.config import Settings
from core.logging_config import get_logger

logger = get_logger(__name__)


class InferenceEngine:
    """
    Движок инференса на базе YOLO с RKNN ускорением.

    Использование:
        engine = InferenceEngine(settings)
        engine.load_model()
        engine.warmup()

        class_name, confidence = engine.predict(frame)
    """

    # Маппинг классов модели на выходные значения
    CLASS_MAPPING = {
        "PET": "plastic",
        "CAN": "aluminum",
        "FOREIGN": "none",
    }

    def __init__(self, settings: Settings):
        """
        Инициализация движка.

        Args:
            settings: Настройки приложения.
        """
        self._settings = settings
        self._model = None
        self._is_ready = False

    def load_model(self) -> bool:
        """
        Загрузить YOLO модель.

        Returns:
            True если модель успешно загружена.
        """
        try:
            # Импортируем здесь чтобы не замедлять импорт модуля
            from ultralytics import YOLO

            model_path = self._settings.model_path
            if not Path(model_path).exists():
                logger.error(f"Модель не найдена: {model_path}")
                return False

            logger.info(f"Загрузка модели из {model_path}...")
            start = time.perf_counter()

            self._model = YOLO(str(model_path), task="classify")

            elapsed = time.perf_counter() - start
            logger.info(f"Модель загружена за {elapsed:.2f} сек")
            return True

        except Exception as e:
            logger.error(f"Ошибка загрузки модели: {e}")
            return False

    def warmup(self, runs: Optional[int] = None) -> bool:
        """
        Прогреть модель для стабильного времени инференса.

        Args:
            runs: Количество прогревочных запусков. Если None, берётся из настроек.

        Returns:
            True если прогрев успешен.
        """
        if self._model is None:
            logger.error("Невозможно прогреть: модель не загружена")
            return False

        warmup_runs = runs if runs is not None else self._settings.warmup_runs
        if warmup_runs <= 0:
            self._is_ready = True
            return True

        logger.info(f"Прогрев модели ({warmup_runs} запусков)...")
        imgsz = self._settings.image_size

        try:
            for i in range(1, warmup_runs + 1):
                # Генерируем случайное изображение
                dummy = np.random.randint(0, 255, size=(imgsz, imgsz, 3), dtype=np.uint8)

                start = time.perf_counter()
                self._model.predict(source=dummy, imgsz=imgsz, verbose=False)
                elapsed_ms = (time.perf_counter() - start) * 1000

                logger.debug(f"Прогрев #{i}: {elapsed_ms:.1f} мс")

            self._is_ready = True
            logger.info("Прогрев завершён, модель готова")
            return True

        except Exception as e:
            logger.error(f"Ошибка при прогреве: {e}")
            return False

    def predict(self, frame: np.ndarray) -> tuple[str, float]:
        """
        Выполнить предсказание для кадра.

        Args:
            frame: Изображение как numpy array (BGR формат).

        Returns:
            Кортеж (class_name, confidence):
            - class_name: "PET", "CAN" или "NONE"
            - confidence: уверенность предсказания (0.0 - 1.0)
        """
        if not self._is_ready or self._model is None:
            logger.warning("Модель не готова к инференсу")
            return "NONE", 0.0

        try:
            start = time.perf_counter()

            results = self._model.predict(
                source=frame,
                imgsz=self._settings.image_size,
                verbose=False
            )

            elapsed_ms = (time.perf_counter() - start) * 1000

            if not results:
                logger.warning("Пустой результат предсказания")
                return "NONE", 0.0

            result = results[0]
            class_idx, confidence = self._get_top1(result)
            raw_class_name = result.names[int(class_idx)]

            # Маппинг на выходные значения
            class_name = self.CLASS_MAPPING.get(raw_class_name.upper(), "NONE")

            logger.debug(f"Предсказание: {class_name} ({confidence:.3f}) за {elapsed_ms:.1f} мс")
            return class_name, confidence

        except Exception as e:
            logger.error(f"Ошибка при предсказании: {e}")
            return "NONE", 0.0

    def is_ready(self) -> bool:
        """Проверить, готова ли модель к инференсу."""
        return self._is_ready and self._model is not None

    @staticmethod
    def _get_top1(result) -> tuple[int, float]:
        """
        Извлечь top-1 класс и уверенность из результата YOLO.

        Args:
            result: Результат предсказания YOLO.

        Returns:
            Кортеж (class_index, confidence).
        """
        probs = result.probs
        top1 = getattr(probs, "top1", int(probs.top5[0]))
        top1conf = getattr(probs, "top1conf", float(probs.top5conf[0]))
        return int(top1), float(top1conf)
