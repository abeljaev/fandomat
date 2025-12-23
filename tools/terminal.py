import asyncio
import websockets
import time

command_list = {
    "0": "cmd_lock_and_block_carriage",
    "1": "cmd_weight_error_reset",
    "2": "cmd_reset_bank_counters",
    "3": "cmd_reset_bottle_counters",
    "4": "cmd_force_move_carriage_left",
    "5": "cmd_force_move_carriage_right",
    "6": "cmd_radxa_detected_bank",
    "7": "cmd_radxa_detected_bottle",
    "8": "cmd_full_clear_register",
    "q": "get_photo",
    "w": "get_device_info",
    "e": "enter_service_mode",
    "r": "dump_container:plastic"
}

async def receive_messages(websocket):
    """Асинхронно получаем сообщения от сервера"""
    try:
        while True:
            response = await websocket.recv()
            print(f"\n[Сервер] {response}")
            print("Введите команду: ", end='', flush=True)
    except Exception as e:
        print(f"\n[Ошибка получения]: {e}")

async def send_commands(websocket):
    """Асинхронно отправляем команды на сервер"""
    loop = asyncio.get_event_loop()
    while True:
        try:
            message = await loop.run_in_executor(None, input, "Введите команду: ")
            
            if message in command_list:
                command = command_list[message]
                print(f"→ Отправляем: {command}")
                await websocket.send(command)
            else:
                print("Неизвестная команда")
        except Exception as e:
            print(f"[Ошибка отправки]: {e}")
            break

async def main():
    uri = "ws://localhost:8765"
    
    async with websockets.connect(uri) as websocket:
        # Регистрируемся как клиент "app"
        await websocket.send("app")
        print("[Terminal] Подключен к серверу как 'app'")
        
        # Запускаем два таска одновременно
        await asyncio.gather(
            receive_messages(websocket),
            send_commands(websocket)
        )

if __name__ == "__main__":
    asyncio.run(main())