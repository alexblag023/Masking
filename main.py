"""Точка входа: запускает локальный сервис и открывает его в браузере."""
import socket
import threading
import webbrowser

import uvicorn

from masking.app import app

HOST = "127.0.0.1"
PREFERRED_PORT = 8765


def _free_port() -> int:
    for port in (PREFERRED_PORT, 0):
        with socket.socket() as s:
            try:
                s.bind((HOST, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Нет свободного порта")


def main() -> None:
    port = _free_port()
    url = f"http://{HOST}:{port}/"
    print(f"Сервис маскирования запущен: {url}\nДля остановки закройте окно или нажмите Ctrl+C.")
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
