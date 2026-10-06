# PyInstaller: onedir (папка с exe + _internal), данные пользователя — рядом с exe.
# Модели NER и статика встроены как data; pymorphy3 требует явного включения
# метаданных пакета словарей.
import os
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

# SPECPATH — папка самого .spec. Все пути строим от неё, чтобы сборка не
# зависела от текущего каталога (в CI это важно).
import pathlib

ROOT = SPECPATH
# PyInstaller включает в exe по одному RT_ICON на каждый .ico в списке.
# Multi-frame .ico он не разворачивает: Pillow seek() по кадрам ICO всегда
# возвращает только основной. Поэтому держим ОТДЕЛЬНЫЙ .ico на размер и
# передаём PyInstaller явный список путей.
_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICON = [os.path.join(ROOT, "packaging", "icon", f"masking-{s}.ico") for s in _SIZES]
_missing = [p for p in ICON if not os.path.isfile(p)]
if _missing:
    raise SystemExit(f"spec: отсутствуют файлы иконок: {_missing}")
print(f"[spec] ICON ({len(ICON)}): " + ", ".join(os.path.basename(p) for p in ICON))
VERINFO = os.path.join(ROOT, "packaging", "version_info.txt")

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("python_multipart")
    + ["multipart"]
    # pywebview на Windows использует edgechromium (WebView2 Runtime).
    + ["webview", "webview.platforms.winforms", "webview.platforms.edgechromium"]
)

datas = (
    # Модели slovnet + navec (~29 МБ)
    [("masking/models/slovnet_ner_news_v1.tar", "masking/models"),
     ("masking/models/navec_news_v1_1B_250K_300d_100q.tar", "masking/models")]
    # Веб-интерфейс (включая логотип).
    + [("masking/static/index.html", "masking/static"),
       ("masking/static/app.css", "masking/static"),
       ("masking/static/app.js", "masking/static"),
       ("masking/static/logo.svg", "masking/static"),
       ("masking/static/logo-32.png", "masking/static"),
       ("masking/static/logo-64.png", "masking/static"),
       ("masking/static/logo-128.png", "masking/static"),
       ("masking/static/logo-256.png", "masking/static")]
    # Словарь pymorphy3 для русского (16 МБ)
    + collect_data_files("pymorphy3_dicts_ru")
    + copy_metadata("pymorphy3_dicts_ru")
)

a = Analysis(
    ["main.py"],
    hiddenimports=hidden,
    datas=datas,
    excludes=["pytest", "numpy.tests", "matplotlib"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="masking-service",
    console=False,            # без чёрного окна консоли
    icon=ICON,
    version=VERINFO,          # Properties → Details (CompanyName/Copyright/...)
    upx=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="masking-service",
)
