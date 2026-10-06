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
# Multi-frame .ico он разбирает нестабильно (seek по кадрам в Pillow —
# всегда возвращает основной), поэтому держим отдельный .ico для каждого
# размера, и Windows Explorer сам выберет подходящий из RT_GROUP_ICON.
_ICON_DIR = pathlib.Path(ROOT, "packaging", "icon")
ICON = sorted(str(p) for p in _ICON_DIR.glob("masking-*.ico")) \
       or [os.path.join(ROOT, "packaging", "masking.ico")]
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
