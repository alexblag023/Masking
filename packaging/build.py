"""Воспроизводимая сборка поставки Masking (по образцу packaging gu-ext).

Собирает в чистом виртуальном окружении из закреплённого списка зависимостей,
прогоняет тесты, вшивает отметку сборки (хэш коммита), пишет SHA-256 артефакта,
генерирует SBOM и собирает:
  - dist/masking-service/        — portable-папка приложения (onedir);
  - dist/Masking_<версия>.zip    — ЗИП с папкой Masking/ внутри (пакет оператора);
  - dist/Установить_Masking.exe  — GUI-установщик с вшитым пакетом.

    python packaging/build.py                 # обычная сборка
    python packaging/build.py --allow-dirty   # разрешить незакоммиченные правки
    python packaging/build.py --skip-tests    # пропустить pytest (для отладки сборки)

Пути ОТНОСИТЕЛЬНЫЕ: собирается на любой машине, не из site-packages разработчика.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

# UTF-8 stdout для Windows-консоли (cp1252 не вывозит кириллицу — иначе падает
# первый же print в CI с UnicodeEncodeError).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent              # корень репозитория
PKG = ROOT / "packaging"
APP_SPEC = ROOT / "masking-service.spec"                   # spec основного приложения
LOCK = ROOT / "requirements.lock"                          # закреплённые зависимости
LOCK_DEV = ROOT / "requirements-dev.lock"
BUILD_ENV = ROOT / ".build-venv"
DIST = ROOT / "dist"

# Публичный RFC3161-таймстамп (подпись остаётся валидной после истечения сертификата).
_DEFAULT_TSA = "http://timestamp.digicert.com"


def run(cmd, **kw) -> subprocess.CompletedProcess:
    print(">", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kw)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()


def _dist_version() -> str:
    """Номер дистрибутива из masking/version.py."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from masking.version import VERSION
    return VERSION


def sign(path: Path) -> None:
    """Authenticode-подпись exe, если задан сертификат.

    MASKING_SIGN_THUMBPRINT   — отпечаток сертификата в хранилище Windows, ИЛИ
    MASKING_SIGN_PFX (+ MASKING_SIGN_PFX_PASSWORD) — путь к .pfx и пароль.
    MASKING_SIGN_TSA          — URL RFC3161-таймстампа (по умолчанию DigiCert).
    Если не задано — сборка остаётся НЕподписанной, об этом громко сообщается.
    """
    thumb = os.environ.get("MASKING_SIGN_THUMBPRINT")
    pfx = os.environ.get("MASKING_SIGN_PFX")
    tsa = os.environ.get("MASKING_SIGN_TSA", _DEFAULT_TSA)
    if not thumb and not pfx:
        print(f"\n[ВНИМАНИЕ] Сертификат подписи не задан (MASKING_SIGN_THUMBPRINT/"
              f"MASKING_SIGN_PFX) — {path.name} НЕ подписан. SmartScreen/антивирус могут "
              "блокировать; целостность подтверждается только SHA256.txt, не аутентичность.",
              file=sys.stderr)
        return
    cmd = ["signtool", "sign", "/fd", "SHA256", "/tr", tsa, "/td", "SHA256"]
    if thumb:
        cmd += ["/sha1", thumb]
    else:
        cmd += ["/f", pfx]
        pwd = os.environ.get("MASKING_SIGN_PFX_PASSWORD")
        if pwd:
            print("[ВНИМАНИЕ] Пароль .pfx передаётся signtool /p и виден в списке "
                  "процессов. Рекомендуется MASKING_SIGN_THUMBPRINT.", file=sys.stderr)
            cmd += ["/p", pwd]
    run(cmd + [str(path)])
    run(["signtool", "verify", "/pa", "/v", str(path)])
    print(f"Подпись Authenticode OK: {path.name}")


def _build_env_python() -> Path:
    """Чистое окружение из закреплённого списка (защита от подмены пакетов)."""
    if not BUILD_ENV.exists():
        print("Создаю окружение сборки…")
        venv.create(BUILD_ENV, with_pip=True)
    py = BUILD_ENV / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    run([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    # --require-hashes защищает от подмены артефакта в индексе; если lock-файла нет,
    # ставим без хэшей из requirements.txt (но тогда предупреждаем).
    if LOCK.exists():
        run([py, "-m", "pip", "install", "-q", "--require-hashes", "-r", str(LOCK)])
        if LOCK_DEV.exists():
            run([py, "-m", "pip", "install", "-q", "--require-hashes", "-r", str(LOCK_DEV)])
    else:
        print("[ВНИМАНИЕ] requirements.lock отсутствует — ставлю из requirements.txt "
              "без проверки хэшей. Для продакшн-сборки сгенерируйте lock.", file=sys.stderr)
        run([py, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
        run([py, "-m", "pip", "install", "-q",
             "pytest", "httpx", "pyinstaller"])
    return py


def build_app(py: Path) -> Path:
    """Собирает основной exe приложения в onedir. Возвращает путь к папке."""
    if DIST.exists():
        shutil.rmtree(DIST)
    run([py, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
         str(APP_SPEC)], cwd=ROOT)
    folder = DIST / "masking-service"
    if not folder.is_dir():
        raise RuntimeError(f"Ожидалась папка {folder}")
    return folder


def generate_sbom(py: Path) -> Path | None:
    """SBOM (CycloneDX) состава зависимостей — к заявке на экспертизу ИБ."""
    sbom = DIST / "sbom.cdx.json"
    try:
        run([py, "-m", "pip", "install", "-q", "cyclonedx-bom"])
        source = LOCK if LOCK.exists() else (ROOT / "requirements.txt")
        run([py, "-m", "cyclonedx_py", "requirements", str(source),
             "--output-format", "JSON", "--output-file", str(sbom)])
        print(f"SBOM: {sbom}")
        return sbom
    except Exception as e:
        print(f"ВНИМАНИЕ: SBOM не сгенерирован ({e}). Приложите состав зависимостей вручную.")
        return None


def assemble_operator_package(py: Path, app_folder: Path, version: str, stamp: str,
                              sbom: Path | None) -> Path:
    """Собирает dist/package/Masking/ (копия app_folder + data + метаданные) и zip.

    data/ — чистая с пустой masking.db. compat.txt — для установщика. README,
    SHA256 и SBOM рядом.
    """
    pkg_root = DIST / "package"
    pkg = pkg_root / "Masking"
    if pkg_root.exists():
        shutil.rmtree(pkg_root)
    pkg.mkdir(parents=True)

    # Копируем целиком папку приложения (exe + _internal/).
    for name in os.listdir(app_folder):
        s = app_folder / name
        d = pkg / name
        if s.is_dir():
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)

    # Пустая рабочая база.
    data_dir = pkg / "data"
    data_dir.mkdir()
    run([py, str(PKG / "make_empty_db.py"), str(data_dir / "masking.db")])

    # README и compat.txt.
    shutil.copy2(PKG / "README_оператор.txt", pkg / "README_оператор.txt")
    from masking.version import SCHEMA_VERSION, MIN_COMPAT_SCHEMA
    (pkg / "compat.txt").write_text(
        f"schema={SCHEMA_VERSION}\nmin_compat={MIN_COMPAT_SCHEMA}\nversion={version}\n",
        encoding="utf-8")

    # SHA-256 основного исполняемого файла (имя зависит от ОС).
    exe = pkg / "masking-service.exe"
    if not exe.is_file():
        exe = pkg / "masking-service"
    if exe.is_file():
        digest = hashlib.sha256(exe.read_bytes()).hexdigest()
        (pkg / "SHA256.txt").write_text(
            f"{digest}  {exe.name}  (версия {version}, сборка {stamp})\n",
            encoding="utf-8")

    if sbom and sbom.exists():
        shutil.copy2(sbom, pkg / "sbom.cdx.json")

    base = DIST / f"Masking_{version}"
    zip_path = Path(shutil.make_archive(str(base), "zip", root_dir=pkg_root))
    return zip_path


def build_installer_exe(py: Path, zip_path: Path) -> Path:
    """Собирает GUI-установщик (onefile) с вшитым zip-пакетом."""
    name = "Установить_Masking"
    staged = ROOT / "build" / "app_package.zip"
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zip_path, staged)
    sep = ";" if os.name == "nt" else ":"
    cmd = [py, "-m", "PyInstaller", "--clean", "--noconfirm", "--onefile", "--noconsole",
           "--name", name,
           "--add-data", f"{staged}{sep}.",
           "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
           "--specpath", str(ROOT / "build"),
           str(PKG / "installer_app.py")]
    icon = PKG / "masking.ico"
    if icon.is_file():
        cmd += ["--icon", str(icon)]
    run(cmd, cwd=ROOT)
    installer = DIST / f"{name}.exe"
    sign(installer)
    return installer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-dirty", action="store_true",
                    help="разрешить сборку при незакоммиченных правках")
    ap.add_argument("--skip-tests", action="store_true",
                    help="не запускать pytest (быстрая отладка сборки)")
    ap.add_argument("--no-installer", action="store_true",
                    help="собрать только zip-пакет, без exe-установщика")
    args = ap.parse_args()

    rev = git("rev-parse", "--short", "HEAD") or "dev"
    dirty = bool(git("status", "--porcelain"))
    if dirty and not args.allow_dirty:
        print("Рабочее дерево не чисто: закоммитьте правки или запустите с --allow-dirty.",
              file=sys.stderr)
        return 1
    stamp = rev + ("+изменения" if dirty else "")
    (ROOT / "build_stamp.py").write_text(
        f"# Создаётся packaging/build.py; в git не хранится.\nBUILD_STAMP = {stamp!r}\n",
        encoding="utf-8")
    print(f"Отметка сборки: {stamp}")

    py = _build_env_python()

    if not args.skip_tests:
        print("Тесты…")
        run([py, "-m", "pytest", "-q"], cwd=ROOT)

    app_folder = build_app(py)
    # Подпишем основной exe ДО расчёта SHA-256 (контрольная сумма — по подписанному).
    exe = app_folder / "masking-service.exe"
    if exe.is_file():
        sign(exe)

    sbom = generate_sbom(py)

    version = _dist_version()
    zip_path = assemble_operator_package(py, app_folder, version, stamp, sbom)
    print(f"Пакет оператора: {zip_path}")

    installer = None
    if not args.no_installer:
        installer = build_installer_exe(py, zip_path)

    print(f"\nГотово. Версия: {version}  Отметка: {stamp}")
    print(f"Папка приложения: {app_folder}")
    print(f"Zip-пакет:        {zip_path}")
    if installer:
        print(f"Установщик:       {installer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
