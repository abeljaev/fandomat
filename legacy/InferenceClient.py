"""
InferenceClient - TCP клиент для связи с inference_service.py

Протокол:
    START\n  → OK\n или ERROR:reason\n
    INFER\n  → PET\n, CAN\n, NONE\n или ERROR:reason\n
    STOP\n   → OK\n
"""
import socket
import threading
from typing import Optional


class InferenceClient:
    """
    TCP клиент для управления inference сервисом.

    Использование:
        client = InferenceClient(host='localhost', port=8081)

        # При пересечении вуали
        if client.start_capture():
            # При появлении объекта
            result = client.request_inference()  # 'PET', 'CAN', 'NONE' или 'ERROR'

            # Когда каретка в центре
            client.stop_capture()
    """

    def __init__(self, host: str = 'localhost', port: int = 8081, timeout: float = 10.0):
        """
        Инициализация клиента.

        Args:
            host: Хост inference сервера.
            port: Порт inference сервера.
            timeout: Таймаут для TCP операций (секунды).
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._lock = threading.Lock()

    def start_capture(self) -> bool:
        """
        Отправить команду START - открыть камеру и начать захват.

        Returns:
            True если команда выполнена успешно.
        """
        response = self._send_command("START")
        if response == "OK":
            print(f"[InferenceClient] START: камера открыта")
            return True
        else:
            print(f"[InferenceClient] START failed: {response}")
            return False

    def request_inference(self) -> str:
        """
        Отправить команду INFER - выполнить инференс.

        Returns:
            Результат: 'PET', 'CAN', 'NONE' или 'ERROR'.
        """
        response = self._send_command("INFER")

        if response in ('PET', 'CAN', 'NONE'):
            print(f"[InferenceClient] INFER: {response}")
            return response
        elif response.startswith("ERROR"):
            print(f"[InferenceClient] INFER failed: {response}")
            return "NONE"
        else:
            print(f"[InferenceClient] INFER неожиданный ответ: {response}")
            return "NONE"

    def stop_capture(self) -> bool:
        """
        Отправить команду STOP - остановить захват и закрыть камеру.

        Returns:
            True если команда выполнена успешно.
        """
        response = self._send_command("STOP")
        if response == "OK":
            print(f"[InferenceClient] STOP: камера закрыта")
            return True
        else:
            print(f"[InferenceClient] STOP failed: {response}")
            return False

    def _send_command(self, command: str) -> str:
        """
        Отправить команду на сервер и получить ответ.

        Args:
            command: Команда для отправки (START, INFER, STOP).

        Returns:
            Ответ сервера или 'ERROR:...' при ошибке.
        """
        with self._lock:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)

                sock.connect((self.host, self.port))

                # Отправляем команду
                sock.sendall(f"{command}\n".encode('utf-8'))

                # Получаем ответ
                response = self._recv_line(sock)
                sock.close()

                return response.strip().upper() if response else "ERROR:empty_response"

            except socket.timeout:
                print(f"[InferenceClient] Timeout при выполнении {command}")
                return "ERROR:timeout"
            except ConnectionRefusedError:
                print(f"[InferenceClient] Не удалось подключиться к {self.host}:{self.port}")
                return "ERROR:connection_refused"
            except Exception as e:
                print(f"[InferenceClient] Ошибка при выполнении {command}: {e}")
                return f"ERROR:{str(e)}"

    def _recv_line(self, sock: socket.socket, max_size: int = 1024) -> str:
        """
        Прочитать строку из сокета.

        Args:
            sock: Сокет.
            max_size: Максимальный размер данных.

        Returns:
            Прочитанная строка.
        """
        data = b""
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
            if b"\n" in chunk or len(data) >= max_size:
                break
        return data.decode('utf-8')

    def ping(self) -> bool:
        """
        Проверить доступность сервера.

        Returns:
            True если сервер доступен.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((self.host, self.port))
            sock.close()
            return True
        except:
            return False
