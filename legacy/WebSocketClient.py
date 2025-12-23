import asyncio
import websockets
import time

async def main():
    uri = "ws://localhost:8765"
    
    async with websockets.connect(uri) as websocket:
        # Отправляем сообщение
        message = "vision"
        await websocket.send(message)
        while True:
            message = "none"
            response = await websocket.recv()
            if response == "bottle_exist":
                message = "bottle"
                print("BOTTLE")
            elif response == "bank_exist":
                message = "bank"
                print("BANK")
            elif response == "none":
                message = "none"
                print("NONE")
            # print(f"Получено от сервера: {response}")
            await websocket.send(message)
            time.sleep(0.1)

if __name__ == "__main__":
    asyncio.run(main())