# PyInstaller: onedir (папка с exe + _internal), данные пользователя — рядом с exe.
# Модели NER и статика встроены как data; pymorphy3 требует явного включения
# метаданных пакета словарей.
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("python_multipart")
    + ["multipart"]
)

datas = (
    # Модели slovnet + navec (~29 МБ)
    [("masking/models/slovnet_ner_news_v1.tar", "masking/models"),
     ("masking/models/navec_news_v1_1B_250K_300d_100q.tar", "masking/models")]
    # Веб-интерфейс
    + [("masking/static/index.html", "masking/static"),
       ("masking/static/app.css", "masking/static"),
       ("masking/static/app.js", "masking/static")]
    # Словарь pymorphy3 для русского (16 МБ)
    + collect_data_files("pymorphy3_dicts_ru")
    + copy_metadata("pymorphy3_dicts_ru")
)

a = Analysis(
    ["main.py"],
    hiddenimports=hidden,
    datas=datas,
    excludes=["tkinter", "pytest", "numpy.tests", "matplotlib"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="masking-service",
    console=True,
    upx=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="masking-service",
)
