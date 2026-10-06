"""Точка входа: запускает локальный сервис и открывает собственное окно.

Окно даёт pywebview поверх системного браузерного движка (на Windows — WebView2
Runtime, который есть в Windows 10/11 по умолчанию). Закрытие окна = выход
приложения: uvicorn получает `should_exit = True`, фоновый поток завершается.
Это ровно та же схема, что в проекте gu-ext (orchestrator/run_web.py).
"""
from __future__ import annotations
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

# Делаем import корректным при запуске `python main.py` из любой папки.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# В сборке PyInstaller `--noconsole` sys.stdout / sys.stderr равны None, из-за
# чего падает uvicorn.logging (`sys.stdout.isatty()` → AttributeError на None).
# Подставляем devnull до любого импорта, который может их читать.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", buffering=1)
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", buffering=1)

# UTF-8 stdout: Windows-консоль (если --console) по умолчанию cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import uvicorn

from masking.app import app, register_shutdown_callback
from masking.paths import base_dir, port_file, writable_check
from masking.version import VERSION

HOST = "127.0.0.1"
PREFERRED_PORT = 8765

_log = logging.getLogger("masking.main")


def _free_port() -> int:
    for port in (PREFERRED_PORT, 0):
        with socket.socket() as s:
            try:
                s.bind((HOST, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Нет свободного порта")


def _wait_ready(port: int, timeout: float = 10.0) -> bool:
    """Ждём, пока uvicorn начнёт принимать соединения."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _setup_logging() -> None:
    """Лог в data/masking.log (в режиме --noconsole иначе ошибки некуда писать)."""
    log_dir = base_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "masking.log", encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def _run_server(server: uvicorn.Server) -> None:
    try:
        server.run()
    except Exception:
        _log.exception("uvicorn упал")


def _start_watchdog(server: uvicorn.Server, timeout_s: float = 30.0,
                    grace_s: float = 60.0, poll_s: float = 2.0) -> threading.Thread:
    """Фоновый поток: завершает процесс, если UI долго не слал heartbeat.

    Нужен, если pywebview-окно открыть не удалось и приложение показалось в
    системном браузере — тогда закрытие вкладки программе не видно, и без
    watchdog процесс остаётся висеть. С pywebview это тоже страхует: когда
    окно закрывают, браузер в окне перестаёт пинговать, и мы точно выходим.

    `grace_s` — время с момента старта, в которое выход по тишине запрещён
    (пользователю надо успеть открыть UI). `timeout_s` — после этого.
    """
    from masking.app import heartbeat_age, mark_heartbeat_now

    def loop() -> None:
        mark_heartbeat_now()                     # обнуляем для grace-периода
        started = time.monotonic()
        while not server.should_exit:
            time.sleep(poll_s)
            if time.monotonic() - started < grace_s:
                continue
            age = heartbeat_age()
            if age > timeout_s:
                _log.info("Нет heartbeat %.1fс (> %.0fс) — выходим", age, timeout_s)
                server.should_exit = True
                # Если открыто окно pywebview — закроем и его, чтобы процесс завершился.
                try:
                    import webview
                    for w in list(getattr(webview, "windows", [])):
                        try: w.destroy()
                        except Exception: pass
                except Exception:
                    pass
                return

    t = threading.Thread(target=loop, daemon=True, name="watchdog")
    t.start()
    return t


def main() -> int:
    _setup_logging()
    err = writable_check()
    if err:
        _log.error("Папка данных недоступна: %s", err)
        print(err, file=sys.stderr)
        _show_error_dialog("Masking", err)
        return 2

    port = _free_port()
    url = f"http://{HOST}:{port}/"
    _log.info("Старт сервиса на %s", url)

    # log_config=None убирает дефолтную конфигурацию логирования uvicorn,
    # которая в noconsole-сборке падала на отсутствующем sys.stdout.
    config = uvicorn.Config(app, host=HOST, port=port,
                            log_level="warning", access_log=False, log_config=None)
    server = uvicorn.Server(config)
    t = threading.Thread(target=_run_server, args=(server,), daemon=True, name="uvicorn")
    t.start()

    if not _wait_ready(port):
        _log.error("Сервис не стартовал за 10 секунд")
        _show_error_dialog("Masking", "Сервис не стартовал за 10 секунд. "
                           "Подробности — в logs/masking.log рядом с программой.")
        server.should_exit = True
        t.join(timeout=5)
        return 3

    # Регистрируем две вещи:
    # 1) порт — установщик прочтёт его, чтобы послать /api/shutdown;
    # 2) callback, который устанавливает should_exit и закрывает окно pywebview.
    try:
        port_file().write_text(str(port), encoding="utf-8")
    except OSError:
        pass

    def _stop() -> None:
        server.should_exit = True
        try:
            import webview
            for w in list(getattr(webview, "windows", [])):
                try: w.destroy()
                except Exception: pass
        except Exception:
            pass
    register_shutdown_callback(_stop)

    # Watchdog: если UI не пингует heartbeat ~30 секунд (окно/вкладка закрыты),
    # выходим. Это основной механизм автозавершения, когда pywebview не
    # удалось открыть и UI крутится в системном браузере.
    _start_watchdog(server)

    # Пробуем своё окно (pywebview). Закрытие окна → should_exit → выход.
    # Если окно не поднялось — fallback на системный браузер; тогда watchdog
    # завершит процесс, когда пользователь закроет вкладку.
    try:
        _run_window(url)
    except Exception as e:
        _log.exception("pywebview не открылся (%s), fallback: системный браузер", e)
        import webbrowser
        webbrowser.open(url)
        # Ждём, пока watchdog не выставит should_exit.
        while not server.should_exit:
            time.sleep(0.5)
    finally:
        server.should_exit = True
        t.join(timeout=5)
        try:
            port_file().unlink(missing_ok=True)
        except OSError:
            pass
        _log.info("Приложение закрыто")
    return 0


def _run_window(url: str) -> None:
    """Собственное окно через pywebview. На Windows использует WebView2 Runtime."""
    import webview   # отложенный импорт: тяжёлая зависимость только когда действительно нужно
    icon = Path(__file__).resolve().parent / "masking" / "static" / "logo-256.png"
    kwargs = {"width": 1200, "height": 820, "min_size": (720, 480), "title": f"Masking {VERSION}"}
    if icon.is_file():
        # pywebview поддерживает icon только на некоторых платформах;
        # на Windows иконка exe берётся из .ico, собранного PyInstaller'ом.
        try:
            kwargs["icon"] = str(icon)
        except Exception:
            pass
    webview.create_window(url=url, **kwargs)
    # webview.start блокирует главный поток до закрытия ВСЕХ окон.
    webview.start()


def _show_error_dialog(title: str, text: str) -> None:
    """Показать окно с ошибкой: нам нечего больше показать, если даже сервис не стартовал."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        messagebox.showerror(title, text)
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
