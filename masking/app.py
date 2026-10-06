"""Локальный HTTP-сервис маскирования документов Word и Excel."""
import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from . import __version__
from .detectors import LABELS
from .docx_proc import mask_docx
from .masker import MODES, Masker
from .xlsx_proc import mask_xlsx

MAX_SIZE = 50 * 1024 * 1024
PROCESSORS = {".docx": mask_docx, ".xlsx": mask_xlsx}
MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

app = FastAPI(title="Masking service", version=__version__, docs_url="/docs", redoc_url=None)

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Маскирование документов</title>
<style>
body{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#222}
fieldset{margin:16px 0;border:1px solid #ccc;border-radius:6px}
label{display:inline-block;margin:2px 12px 2px 0}
button{padding:8px 20px;font-size:1rem;cursor:pointer}
#result{margin-top:16px;white-space:pre-wrap}
</style></head><body>
<h1>Маскирование персональных данных</h1>
<p>Файлы обрабатываются локально и не покидают ваш компьютер. Форматы: .docx, .xlsx</p>
<form id="f">
<input type="file" name="file" accept=".docx,.xlsx" required>
<fieldset><legend>Режим</legend>
<label><input type="radio" name="mode" value="tag" checked> [ФИО]</label>
<label><input type="radio" name="mode" value="pseudo"> [ФИО_1] (одинаковые значения — одинаковый номер)</label>
<label><input type="radio" name="mode" value="stars"> ***</label>
</fieldset>
<fieldset><legend>Что маскировать</legend>__KINDS__</fieldset>
<button type="submit">Замаскировать и скачать</button>
</form>
<div id="result"></div>
<script>
document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault();
  const out = document.getElementById('result');
  out.textContent = 'Обработка...';
  const resp = await fetch('/api/mask', {method:'POST', body:new FormData(e.target)});
  if (!resp.ok) { out.textContent = 'Ошибка: ' + ((await resp.json()).detail || resp.status); return; }
  const stats = JSON.parse(resp.headers.get('X-Masking-Stats') || '{}');
  const name = decodeURIComponent(resp.headers.get('Content-Disposition').split("filename*=UTF-8''")[1]);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await resp.blob()); a.download = name; a.click();
  const total = Object.values(stats).reduce((x, y) => x + y, 0);
  out.textContent = 'Готово: ' + name + '\\nЗамаскировано: ' + total +
    (total ? '\\n' + Object.entries(stats).map(([k, v]) => k + ': ' + v).join('\\n') : '');
});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    kinds = "".join(
        f'<label><input type="checkbox" name="kinds" value="{k}" checked> {v}</label>'
        for k, v in LABELS.items()
    )
    return PAGE.replace("__KINDS__", kinds)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/api/mask")
async def mask(
    file: UploadFile = File(...),
    mode: str = Form("tag"),
    kinds: Optional[list[str]] = Form(None),
) -> Response:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in PROCESSORS:
        raise HTTPException(415, "Поддерживаются только .docx и .xlsx (старые .doc/.xls сохраните в новом формате)")
    if mode not in MODES:
        raise HTTPException(400, f"mode должен быть одним из: {', '.join(MODES)}")
    selected = set(kinds) if kinds else None
    if selected and not selected <= set(LABELS):
        raise HTTPException(400, f"Неизвестные типы данных: {', '.join(sorted(selected - set(LABELS)))}")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "Файл больше 50 МБ")

    masker = Masker(mode, selected)
    try:
        result = PROCESSORS[ext](data, masker)
    except Exception as exc:  # битый или защищённый паролем файл
        raise HTTPException(422, f"Не удалось обработать файл: {exc}") from exc

    out_name = f"{Path(file.filename).stem}.masked{ext}"
    return Response(
        result,
        media_type=MEDIA_TYPES[ext],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(out_name)}",
            "X-Masking-Stats": json.dumps(dict(masker.stats)),
        },
    )
