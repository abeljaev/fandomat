# Архитектура системы

## Обзор

BottleClassifier — система классификации контейнеров для автомата приема тары, построенная на двухпроцессной архитектуре с WebSocket-коммуникацией.

## Компоненты

### 1. Application.py — Сервис ПЛК

**Ответственность:**
- Управление state machine (5 состояний)
- Коммуникация с ПЛК через Modbus RTU
- WebSocket сервер для клиентов (vision, app)
- Координация процесса сортировки
- Event-driven коммуникация с backend

**State Machine:**
```
IDLE → WAITING_VISION → DUMPING_PLASTIC → IDLE
                      → DUMPING_ALUMINUM → IDLE
                      → ERROR (при таймауте)
```

| Состояние | Описание | Таймаут |
|-----------|----------|---------|
| IDLE | Ожидание контейнера | - |
| WAITING_VISION | Ожидание ответа от vision | 2с |
| DUMPING_PLASTIC | Движение каретки влево (PET) | 3с |
| DUMPING_ALUMINUM | Движение каретки вправо (CAN) | 3с |
| ERROR | Аппаратная ошибка | - |

**Триггер инференса:**
- Завеса освобождается (1→0)
- Контейнер появляется (bottle_exist=1 или bank_exist=1)
- Отправляется запрос vision

**Потоки:**
- Main thread — state machine loop
- PLC thread — непрерывный опрос Modbus (0.1с)
- WebSocket thread — asyncio event loop

### 2. inference_service.py — Сервис инференса

**Ответственность:**
- Захват кадров с камеры
- Классификация объектов (YOLO11n)
- Отправка результатов в Application
- Мульти-инференс для повышения точности

**Мульти-инференс:**
- Захватывается 3 кадра подряд
- Голосование по большинству (Counter.most_common)
- Возвращается класс с максимальным количеством голосов

**Компоненты:**
- `CameraManager` — потокобезопасная камера с кольцевым буфером
- `InferenceEngine` — обёртка над YOLO моделью

### 3. Backend Service

**Ответственность:**
- Пользовательский интерфейс
- Статистика и отчёты
- Удалённое управление

**Инструменты:**
- `backend_simulator.py` — симулятор для тестирования WebSocket API

## Протоколы

### WebSocket (ws://localhost:8765)

**Клиент "vision":**
```
→ "vision"              # регистрация
← "bottle_exist"        # запрос классификации (3 кадра)
→ "bottle" | "bank" | "none"  # результат (большинство)
```

**Клиент "app":**
```
→ "app"                 # регистрация
→ {"command": "dump_container", "param": "plastic"}  # JSON команда
← {"event": "container_dumped", "data": {...}, "timestamp": "..."}  # событие
```

**Поддерживаемые команды:**
- `get_device_info` — информация об устройстве
- `get_photo` — фото с камеры
- `dump_container` (param: plastic/aluminium) — сброс контейнера
- `container_unloaded` (param: plastic/aluminium) — мешок выгружен
- `cmd_restore_device` — восстановление из ERROR
- `cmd_full_clear_register` — очистка регистра

**События (Application → app):**
| Событие | Описание | Data |
|---------|----------|------|
| container_detected | Контейнер обнаружен | plc_type |
| container_recognized | Контейнер распознан | type, confidence |
| container_accepted | Контейнер принят | type, counter |
| hardware_error | Аппаратная ошибка | error_code, message |
| device_info | Информация | bottle_count, bank_count, state |
| photo_ready | Фото готово | filename |

### Modbus RTU (/dev/ttyUSB0, 115200 baud)

**Command Register (25):**
| Bit | Назначение |
|-----|------------|
| 7 | radxa_detected_bottle |
| 6 | radxa_detected_bank |
| 5 | force_move_carriage_right |
| 4 | force_move_carriage_left |

**Status Register (26):**
| Bit | Назначение |
|-----|------------|
| 7 | bottle_exist |
| 6 | bank_exist |
| 3 | right_sensor_carriage |
| 2 | center_sensor_carriage |
| 1 | left_sensor_carriage |

## Поток данных

```
1. Человек кладёт контейнер (завеса пересекается, veil=1)
2. Человек убирает руку (завеса освобождается, veil: 1→0)
3. Датчик контейнера срабатывает (bottle_exist=1 или bank_exist=1)
4. Application:
   - Детектирует переход завесы + контейнер
   - Переходит в WAITING_VISION
   - Отправляет "bottle_exist" в vision
5. inference_service:
   - Захватывает 3 кадра с камеры
   - Выполняет инференс YOLO для каждого
   - Голосование по большинству
   - Возвращает "bottle"/"bank"/"none"
6. Application:
   - Получает ответ от vision
   - Устанавливает radxa_detected_bottle/bank в ПЛК
   - Переходит в DUMPING_PLASTIC или DUMPING_ALUMINUM
7. ПЛК перемещает каретку влево/вправо
8. Датчик каретки фиксирует завершение → возврат в IDLE
9. При таймауте → переход в ERROR
```

## Камера

- **Разрешение:** 2K (2560×1440)
- Камера работает в максимальном разрешении
- Кадр ресайзится до 1280×1280 перед инференсом

## Модель

- **Архитектура:** YOLO11s classification
- **Вход:** 1280×1280 RGB
- **Классы:** CAN (0), FOREIGN (1), PET (2)
- **Платформа:** RKNN (Rockchip NPU RK3588)
- **Веса:** `weights/best_11s_rknn_model/` (папка с RKNN моделью)
