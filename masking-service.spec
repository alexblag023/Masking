# PyInstaller: один файл, консольное окно (в нём видно адрес и ошибки)
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("python_multipart")
    + ["multipart"]
)

a = Analysis(["main.py"], hiddenimports=hidden, excludes=["tkinter", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="masking-service",
    console=True,
    upx=False,
)
