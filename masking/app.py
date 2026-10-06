"""Локальный HTTP-сервис маскирования документов. Проекты, разделы, история."""
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__, registry
from .docx_proc import mask_docx, unmask_docx
from .paths import base_dir, data_dir, writable_check
from .reversible import ReversibleMasker, ReversibleUnmasker
from .xlsx_proc import mask_xlsx, unmask_xlsx

MAX_SIZE = 50 * 1024 * 1024
MASK_PROCESSORS = {".docx": mask_docx, ".xlsx": mask_xlsx}
UNMASK_PROCESSORS = {".docx": unmask_docx, ".xlsx": unmask_xlsx}
MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Разрешённые хосты (анти-DNS-rebinding) и источники (анти-CSRF).
# Сервис слушает только loopback, но без проверки Host внешний домен,
# указавший на 127.0.0.1, мог бы отправлять запросы с чужой страницы.
# `testserver` — хост TestClient Starlette, оставляем ради тестов.
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Пути, которым разрешён POST без CSRF-проверки: это идемпотентные
# «браузер уходит» сигналы через navigator.sendBeacon (у sendBeacon нет
# Origin и Sec-Fetch-Site, но Host есть и loopback-check его отбивает,
# если запрос пришёл не от нас).
_CSRF_EXEMPT_PATHS = {"/api/closed"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Жёсткие проверки на изменяющих запросах + CSP/заголовки на ответах."""

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").split(":")[0]
        if host and host not in _ALLOWED_HOSTS:
            return Response("Host rejected", status_code=400)

        if request.method not in _SAFE_METHODS and request.url.path not in _CSRF_EXEMPT_PATHS:
            # Приемлем запросы либо от нашей же страницы (same-origin), либо
            # из тестового клиента (у TestClient Origin/Sec-Fetch-Site отсутствуют).
            sfs = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin") or request.headers.get("referer") or ""
            same_origin = False
            if origin:
                try:
                    o = urlparse(origin)
                    same_origin = o.hostname in _ALLOWED_HOSTS
                except Exception:
                    same_origin = False
            # Разрешаем, если:
            #  — явно same-origin (sec-fetch-site), либо
            #  — Origin/Referer с нашего же хоста, либо
            #  — ни того, ни другого нет (не-браузерный клиент; CORS-браузер
            #    всегда шлёт Origin на cross-origin запросах).
            if not (sfs == "same-origin" or same_origin or (not sfs and not origin)):
                return Response("CSRF check failed", status_code=403)

        response = await call_next(request)
        # Заголовки защиты ответов (CSP: только собственные ресурсы).
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


app = FastAPI(title="Masking service", version=__version__, docs_url="/docs", redoc_url=None)
app.add_middleware(SecurityHeadersMiddleware)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ----- Схемы запросов ------------------------------------------------------

class ProjectIn(BaseModel):
    name: str


# ----- Сервисные эндпоинты --------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health() -> dict:
    err = writable_check()
    return {
        "status": "ok" if not err else "error",
        "version": __version__,
        "data_dir": str(data_dir()),
        "base_dir": str(base_dir()),
        "error": err,
    }


# ----- Heartbeat ----------------------------------------------------------
#
# Открытый в браузере UI периодически бьёт сюда (см. masking/static/app.js).
# main.py запускает watchdog, который завершает процесс, если heartbeat
# пропал надолго: это закрытие окна/вкладки — и приложение должно уйти,
# иначе в фоне продолжит висеть uvicorn без клиента.
import time as _time
_last_heartbeat = {"at": _time.monotonic()}


def heartbeat_age() -> float:
    """Сколько секунд прошло с последнего heartbeat (для watchdog в main.py)."""
    return _time.monotonic() - _last_heartbeat["at"]


def mark_heartbeat_now() -> None:
    _last_heartbeat["at"] = _time.monotonic()


@app.post("/api/heartbeat")
def api_heartbeat() -> dict:
    """UI пингует этот эндпоинт раз в несколько секунд — пока вкладка открыта."""
    mark_heartbeat_now()
    return {"ok": True}


# ----- Shutdown -----------------------------------------------------------
#
# Установщик использует этот эндпоинт, чтобы корректно остановить
# запущенное приложение перед обновлением (вместо того чтобы просить
# пользователя закрыть exe вручную).
_shutdown_callbacks: list = []


def register_shutdown_callback(fn) -> None:
    """main.py регистрирует здесь функцию, которая устанавливает server.should_exit."""
    _shutdown_callbacks.append(fn)


@app.post("/api/shutdown")
def api_shutdown() -> dict:
    """Инициирует корректное завершение сервиса. Доступен только с loopback
    (host-check уже сделан SecurityHeadersMiddleware)."""
    for fn in _shutdown_callbacks:
        try:
            fn()
        except Exception:
            pass
    return {"ok": True}


@app.post("/api/closed")
def api_closed() -> dict:
    """UI сообщает о закрытии вкладки (navigator.sendBeacon на beforeunload).

    sendBeacon не добавляет Origin и шлёт text/plain, поэтому эндпоинт
    выведен из-под обычной CSRF-проверки через `_safe_paths` в middleware.
    По факту это тот же shutdown, что и /api/shutdown.
    """
    for fn in _shutdown_callbacks:
        try:
            fn()
        except Exception:
            pass
    return {"ok": True}


# ----- Проекты --------------------------------------------------------------

@app.get("/api/projects")
def projects_list() -> list[dict]:
    return registry.list_projects()


@app.post("/api/projects", status_code=201)
def projects_create(body: ProjectIn) -> dict:
    try:
        return registry.create_project(body.name)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Проект с таким названием уже существует")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects/{pid}")
def projects_get(pid: int) -> dict:
    try:
        return registry.get_project(pid)
    except LookupError:
        raise HTTPException(404, "Проект не найден")


@app.patch("/api/projects/{pid}")
def projects_rename(pid: int, body: ProjectIn) -> dict:
    try:
        return registry.rename_project(pid, body.name)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Название уже занято")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/projects/{pid}", status_code=204)
def projects_delete(pid: int) -> Response:
    try:
        registry.delete_project(pid)
    except LookupError:
        raise HTTPException(404, "Проект не найден")
    return Response(status_code=204)


# ----- Маскирование и демаскирование ---------------------------------------

def _ensure_project(pid: int) -> dict:
    try:
        return registry.get_project(pid)
    except LookupError:
        raise HTTPException(404, "Проект не найден")


def _validate_file(file: UploadFile, data: bytes) -> str:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in MASK_PROCESSORS:
        raise HTTPException(415, "Поддерживаются только .docx и .xlsx")
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "Файл больше 50 МБ")
    return ext


@app.post("/api/projects/{pid}/mask")
async def op_mask(pid: int, file: UploadFile = File(...)) -> Response:
    _ensure_project(pid)
    data = await file.read()
    ext = _validate_file(file, data)
    masker = ReversibleMasker(pid)
    try:
        result = MASK_PROCESSORS[ext](data, masker)
    except Exception as exc:
        raise HTTPException(422, f"Не удалось обработать файл: {exc}") from exc

    did_in = registry.add_document(pid, "mask", "in", file.filename, ext, data)
    out_name = f"{Path(file.filename).stem}.masked{ext}"
    did_out = registry.add_document(
        pid, "mask", "out", out_name, ext, result,
        parent_id=did_in, stats=masker.stats.as_dict(),
    )
    masker.flush(did_in)

    return Response(
        result,
        media_type=MEDIA_TYPES[ext],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(out_name)}",
            "X-Masking-Stats": json.dumps(masker.stats.as_dict()),
            "X-Document-Id": str(did_out),
        },
    )


@app.post("/api/projects/{pid}/unmask")
async def op_unmask(pid: int, file: UploadFile = File(...)) -> Response:
    _ensure_project(pid)
    data = await file.read()
    ext = _validate_file(file, data)
    unmasker = ReversibleUnmasker(pid)
    try:
        result = UNMASK_PROCESSORS[ext](data, unmasker)
    except Exception as exc:
        raise HTTPException(422, f"Не удалось обработать файл: {exc}") from exc

    stats = unmasker.stats.as_dict()
    did_in = registry.add_document(pid, "unmask", "in", file.filename, ext, data)
    out_name = f"{Path(file.filename).stem}.restored{ext}"
    did_out = registry.add_document(
        pid, "unmask", "out", out_name, ext, result,
        parent_id=did_in, stats=stats,
    )
    return Response(
        result,
        media_type=MEDIA_TYPES[ext],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(out_name)}",
            "X-Unmasking-Stats": json.dumps(stats),
            "X-Document-Id": str(did_out),
        },
    )


# ----- Сущности и история ---------------------------------------------------

@app.get("/api/projects/{pid}/entities")
def entities(pid: int, kind: str | None = None, q: str | None = None) -> list[dict]:
    _ensure_project(pid)
    if kind and kind not in ("FIO", "ADDR"):
        raise HTTPException(400, "kind: FIO | ADDR")
    return registry.list_entities(pid, kind, q)


@app.get("/api/projects/{pid}/history/{op}")
def history(pid: int, op: str) -> list[dict]:
    _ensure_project(pid)
    if op not in ("mask", "unmask"):
        raise HTTPException(400, "op: mask | unmask")
    return registry.list_history(pid, op)


@app.get("/api/documents/{did}/download")
def download(did: int) -> Response:
    try:
        meta, data = registry.document_data(did)
    except LookupError:
        raise HTTPException(404, "Документ не найден")
    return Response(
        data,
        media_type=MEDIA_TYPES.get(meta["ext"], "application/octet-stream"),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(meta['filename'])}",
        },
    )
