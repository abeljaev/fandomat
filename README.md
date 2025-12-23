# BottleClassifier

Автомат для приема тары (Reverse Vending Machine) на базе Radxa RK3588.

## Описание

Система классификации контейнеров с помощью нейросети YOLO11s и управления сортировкой через ПЛК по Modbus RTU.

**Классы объектов:**
- **PET** — пластиковые бутылки → сброс влево
- **CAN** — алюминиевые банки → сброс вправо
- **FOREIGN** — посторонний предмет → отклонение

## Структура проекта

```
BottleClassifier/
├── plc/                        # Модуль PLC + State Machine
│   ├── application.py          # State Machine, WebSocket сервер
│   ├── plc.py                  # Modbus RTU интерфейс
│   └── modbus_register.py      # Абстракция регистра
│
├── vision/                     # Модуль Vision
│   ├── inference_service.py    # WebSocket клиент для инференса
│   ├── camera_manager.py       # Потокобезопасная камера
│   └── inference_engine.py     # YOLO обёртка
│
├── websocket/                  # WebSocket сервер
│   └── server.py               # Async сервер для клиентов
│
├── core/                       # Общие модули
│   ├── config.py               # Settings из .env
│   └── logging_config.py       # Настройка логирования
│
├── tools/                      # Утилиты
│   ├── backend_simulator.py    # Симулятор backend
│   └── terminal.py             # Интерактивный терминал
│
├── tests/                      # Тесты (pytest)
├── docs/                       # Документация
└── weights/                    # Веса моделей
```

## Установка

### Системные зависимости (Rockchip RK3588)
```bash
sudo apt update
sudo apt install -y rknpu2-rk3588 python3-rknnlite2
```

### Python зависимости
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Переменные окружения
Создайте файл `.env`:
```env
MODEL_PATH=/path/to/best_11s_rknn_model
CAMERA_INDEX=0
WEBSOCKET_HOST=localhost
WEBSOCKET_PORT=8765
SAVE_FRAMES=true
OUTPUT_DIR=real_time
```

## Запуск

### Сервис ПЛК (основной)
```bash
python -m plc.application
```

### Сервис инференса (отдельный процесс)
```bash
python -m vision.inference_service
```

### Интерактивный режим камеры (тестирование)
```bash
python -m vision.inference_service --camera
```

### Симулятор backend (тестирование WebSocket API)
```bash
python -m tools.backend_simulator
```

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                     WebSocket Server                         │
│                    (ws://localhost:8765)                     │
├─────────────────────────────────────────────────────────────┤
│                    plc/application.py                        │
│  ├── State Machine (5 состояний)                            │
│  ├── Event Manager (события → app клиент)                   │
│  └── PLC Interface (Modbus RTU @ /dev/ttyUSB0)              │
└─────────────────────────────────────────────────────────────┘
           ▲                              ▲
           │ WebSocket                    │ WebSocket
           │ (client: "vision")           │ (client: "app")
           ▼                              ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│ vision/inference_service│    │   Backend Service       │
│  ├── CameraManager      │    │   (tools/backend_       │
│  └── InferenceEngine    │    │    simulator.py)        │
└─────────────────────────┘    └─────────────────────────┘
```

## Документация

Подробная документация находится в папке [docs/](docs/):
- [COMMANDS.md](docs/COMMANDS.md) — WebSocket API команды и события
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектура системы
- [BACKLOG.md](docs/BACKLOG.md) — запланированные задачи

## Тестирование

```bash
pytest tests/ -v
```

## Лицензия

MIT
