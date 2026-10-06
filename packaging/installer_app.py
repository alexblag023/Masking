"""Установщик Masking — .exe с окном выбора папки (PyInstaller, без внешних зависимостей).

Пакет приложения (zip с папкой Masking/ внутри) вшивается в exe при сборке
через `--add-data`. Оператор выбирает папку установки (по умолчанию — рабочий
стол) и жмёт «Установить». Логика:
  - папки нет → распаковка приложения в <папка>/Masking;
  - есть, версии совместимы → обновление программы с СОХРАНЕНИЕМ data/
    (карта соответствий, проекты, файлы);
  - есть, версии несовместимы (откат схемы) → ПОЛНАЯ переустановка:
    прежняя установка уходит в бэкап рядом, ставится свежая, data/ переносится,
    но программа предупреждает, что старые токены могут не демаскироваться.

Совместимость определяется по compat.txt (версия схемы данных) в пакете и в
установленной папке. GUI — Tkinter (stdlib). Для автоматизации/теста:
`--target <папка>`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime

APP_TITLE = "Установка Masking"

# Палитра: сдержанный синий как в веб-интерфейсе Masking (--accent #1f5fd6).
_BLUE = "#1F5FD6"
_BLUE_DEEP = "#1A4FB3"
_RED = "#B3261E"
_INK = "#1B1F27"
_MUTED = "#505968"
_FIELD = "#F3F6FC"
_WHITE = "#FFFFFF"
_UI_FONT = "Segoe UI"

# Пакет вшивается под фиксированным именем — чтобы installer не путал его с
# PyInstaller base_library.zip в onefile-архиве.
_EMBED_NAME = "app_package.zip"


def _base_dir() -> str:
    """Каталог с вшитым пакетом: _MEIPASS в собранном exe, иначе каталог скрипта."""
    return getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))


def _embedded_zip() -> str:
    """Путь к вшитому zip-пакету. MASKING_INSTALLER_ZIP переопределяет (для dev)."""
    env = os.environ.get("MASKING_INSTALLER_ZIP")
    if env and os.path.isfile(env):
        return env
    base = _base_dir()
    fixed = os.path.join(base, _EMBED_NAME)
    if os.path.isfile(fixed):
        return fixed
    for fn in os.listdir(base):
        if fn.lower().endswith(".zip") and fn.lower() != "base_library.zip":
            return os.path.join(base, fn)
    raise RuntimeError("встроенный пакет приложения (zip) не найден")


def desktop_dir() -> str:
    """Путь к рабочему столу с учётом переноса в OneDrive (из реестра)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        try:
            val, _ = winreg.QueryValueEx(k, "Desktop")
        finally:
            winreg.CloseKey(k)
        path = os.path.expandvars(val)
        if os.path.isdir(path):
            return path
    except Exception:
        pass
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")


def _parse_compat(text: str) -> dict:
    out = {"schema": 1, "min_compat": 1, "version": ""}
    for ln in (text or "").splitlines():
        if "=" in ln:
            k, _, v = ln.partition("=")
            k = k.strip(); v = v.strip()
            if k in ("schema", "min_compat") and v.isdigit():
                out[k] = int(v)
            elif k == "version":
                out["version"] = v
    return out


def _read_compat(folder: str) -> dict:
    try:
        with open(os.path.join(folder, "compat.txt"), encoding="utf-8") as f:
            return _parse_compat(f.read())
    except OSError:
        return _parse_compat("")


def _package_info() -> tuple:
    """(имя_папки_приложения, compat) из вшитого пакета без распаковки на диск."""
    with zipfile.ZipFile(_embedded_zip()) as z:
        names = z.namelist()
        top = names[0].split("/")[0] if names else "Masking"
        try:
            txt = z.read(f"{top}/compat.txt").decode("utf-8")
        except KeyError:
            txt = ""
    return top, _parse_compat(txt)


def _is_installed(folder: str) -> bool:
    """Папка выглядит как установленная версия Masking."""
    return (
        os.path.isfile(os.path.join(folder, "masking-service.exe"))
        or os.path.isdir(os.path.join(folder, "data"))
        or os.path.isfile(os.path.join(folder, "compat.txt"))
    )


def app_running(dest_exe: str | None) -> bool:
    """True, если masking-service.exe в целевой папке запущен (заблокирован Windows)."""
    if not dest_exe or not os.path.isfile(dest_exe):
        return False
    try:
        with open(dest_exe, "r+b"):   # запущенный exe не откроется на запись
            pass
    except OSError:
        return True
    return False


def _ver_tuple(s: str) -> tuple:
    """'2026.10.1' → (2026, 10, 1). Нечисловые/пустые сегменты → 0."""
    return tuple(int(p) if p.strip().isdigit() else 0 for p in str(s or "").split("."))


def _cmp_ver(a: str, b: str) -> int:
    return (_ver_tuple(a) > _ver_tuple(b)) - (_ver_tuple(a) < _ver_tuple(b))


def preview_action(target_parent: str) -> str:
    """Короткая подсказка, что произойдёт при установке в target_parent (для GUI)."""
    try:
        app, new = _package_info()
        dest = os.path.join(target_parent, app)
        if not _is_installed(dest):
            return f"Будет установлено в {dest}"
        inst = _read_compat(dest)
        c = _cmp_ver(new["version"], inst["version"])
        if c == 0:
            return f'Будет переустановка (версия {new["version"]}), данные сохранятся'
        if c > 0:
            return f'Будет обновление {inst["version"]} → {new["version"]}, данные сохранятся'
        return f'Внимание: откат {inst["version"]} → {new["version"]} — запросит согласие'
    except Exception:
        return ""


def _copy_tree_overwrite(src: str, dest: str) -> None:
    """Копирует папку src ПОВЕРХ dest (dirs_exist_ok=True), файлы перезаписывает."""
    shutil.copytree(src, dest, dirs_exist_ok=True)


def _extract(tmp: str):
    """Распаковывает вшитый пакет в tmp/ext, восстанавливает Unix-права (+x)
    на исполняемый файл (zip их теряет), возвращает (src_dir, new_compat)."""
    ext = os.path.join(tmp, "ext")
    with zipfile.ZipFile(_embedded_zip()) as z:
        z.extractall(ext)
        if os.name != "nt":
            # external_attr у zip-записи хранит Unix-mode в старших битах. Восстановим +x,
            # чтобы на macOS/Linux установленный masking-service запускался.
            for info in z.infolist():
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    try:
                        os.chmod(os.path.join(ext, info.filename), mode)
                    except OSError:
                        pass
    subdirs = [d for d in os.listdir(ext) if os.path.isdir(os.path.join(ext, d))]
    if not subdirs:
        raise RuntimeError("в пакете не найдена папка приложения")
    src = os.path.join(ext, subdirs[0])
    return src, _read_compat(src)


# Программные файлы: эти папки/файлы заменяются при обновлении.
# Папка data/ в этот список НЕ входит — её мы бережём.
_PROGRAM_ITEMS = {
    "masking-service.exe", "_internal",
    "compat.txt", "SHA256.txt", "sbom.cdx.json", "README_оператор.txt",
}


def do_install(target_parent: str, confirm=None, allow_downgrade: bool = False, log=print) -> str:
    """Устанавливает/переустанавливает/обновляет Masking в target_parent/<app>.

    Данные (папка data/) сохраняются при совместимой схеме. При несовместимой
    schema всё дерево уходит в бэкап, затем ставится новая версия, а data/
    переносится из бэкапа — но при этом демаскирование по старой схеме может
    не работать (пользователю это сказано в тексте бэкап-сообщения).
    """
    tmp = tempfile.mkdtemp(prefix="masking_inst_")
    try:
        src, new = _extract(tmp)
        app_name = os.path.basename(src)
        dest = os.path.join(target_parent, app_name)
        exists = _is_installed(dest)
        inst = _read_compat(dest) if exists else None

        if not exists:
            mode = "install"
        else:
            c = _cmp_ver(new["version"], inst["version"])
            mode = "reinstall" if c == 0 else ("update" if c > 0 else "downgrade")

        # Откат версии — только с согласия оператора.
        if mode == "downgrade":
            warn = (f'Устанавливаемая версия ({new["version"] or "?"}) НИЖЕ установленной '
                    f'({inst["version"] or "?"}).\nОткат может сделать данные нечитаемыми — '
                    f'прежняя установка уйдёт в резервную копию.\nПродолжить?')
            ok = allow_downgrade or (bool(confirm(warn)) if confirm else False)
            if not ok:
                msg = f'Отменено: откат версии ({inst["version"]} → {new["version"]}) не подтверждён.'
                log(msg)
                return msg

        compatible = (not exists) or (new["min_compat"] <= inst["schema"] <= new["schema"])
        prefix = {"install": "Установка", "reinstall": "Переустановка",
                  "update": "Обновление", "downgrade": "Откат версии"}[mode]

        # Несовместимая схема — переустанавливаем начисто, data переносим из бэкапа.
        if exists and not compatible:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = os.path.join(target_parent, f"{app_name}_backup_{stamp}")
            os.rename(dest, backup)
            os.makedirs(dest)
            _copy_tree_overwrite(src, dest)
            backup_data = os.path.join(backup, "data")
            if os.path.isdir(backup_data):
                shutil.copytree(backup_data, os.path.join(dest, "data"), dirs_exist_ok=True)
            msg = (f'{prefix}: полная переустановка (схема {inst["schema"]} → '
                   f'{new["schema"]} несовместима).\nПрежняя установка сохранена: {backup}\n'
                   f"ВНИМАНИЕ: демаскирование документов, созданных старой версией, может\n"
                   f"не работать с новой схемой данных. При проблемах — вернитесь к\n"
                   f"резервной копии вручную.")
            log(msg)
            return msg

        # Обычный путь: программу заменяем, data/ не трогаем.
        os.makedirs(dest, exist_ok=True)
        existing_data = os.path.isdir(os.path.join(dest, "data"))
        for name in os.listdir(src):
            s = os.path.join(src, name)
            d = os.path.join(dest, name)
            low = name.lower()
            if low == "data":
                # Данные в пакете пустые (пустая БД). Если у пользователя уже есть
                # data/ — не трогаем. Если нет (чистая установка) — копируем пустую.
                if not existing_data:
                    shutil.copytree(s, d)
                continue
            if low not in _PROGRAM_ITEMS and os.path.isfile(d):
                # Непрограммный файл (напр. ярлык, лог оператора) — не перезаписываем.
                continue
            if os.path.isdir(s):
                # _internal/ полностью заменяем: там библиотеки, их частичное обновление
                # опаснее полного.
                if os.path.isdir(d) and low in _PROGRAM_ITEMS:
                    shutil.rmtree(d)
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
        # Гарантируем, что data/ существует даже если в пакете её не было.
        os.makedirs(os.path.join(dest, "data"), exist_ok=True)

        if mode == "install":
            msg = f"Установка: {dest}"
        elif mode == "update":
            msg = f'Обновление {inst["version"]} → {new["version"]} (данные сохранены): {dest}'
        elif mode == "downgrade":
            msg = f'Откат {inst["version"]} → {new["version"]} (данные сохранены): {dest}'
        else:
            msg = f'Переустановка версии {new["version"]} (данные сохранены): {dest}'
        log(msg)
        return msg
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    try:
        app_name, pkg = _package_info()
        pkg_ver = pkg["version"]
    except Exception:
        app_name, pkg_ver = "Masking", ""

    def _dest_exe():
        p = target.get().strip()
        return os.path.join(p, app_name, "masking-service.exe") if p else None

    root = tk.Tk()
    root.title(APP_TITLE)
    root.resizable(False, False)
    root.geometry("760x480")
    root.configure(bg=_WHITE)
    try:
        ico = os.path.join(_base_dir(), "masking.ico")
        if os.path.isfile(ico):
            root.iconbitmap(ico)
    except Exception:
        pass

    # Левая брендовая панель.
    panel = tk.Frame(root, bg=_BLUE, width=260, height=480)
    panel.pack(side="left", fill="y")
    panel.pack_propagate(False)
    tk.Frame(panel, bg=_BLUE, height=56).pack()
    tk.Label(panel, text="🛡", bg=_BLUE, fg=_WHITE, font=(_UI_FONT, 72)).pack()
    tk.Label(panel, text="Masking", bg=_BLUE, fg=_WHITE,
             font=(_UI_FONT, 22, "bold")).pack(pady=(16, 0))
    tk.Label(panel, text="Установщик приложения", bg=_BLUE, fg="#CFE0FF",
             font=(_UI_FONT, 12)).pack(pady=(6, 0))
    if pkg_ver:
        tk.Label(panel, text=f"версия {pkg_ver}", bg=_BLUE, fg="#CFE0FF",
                 font=(_UI_FONT, 11)).pack(side="bottom", pady=(0, 20))
    tk.Frame(root, bg=_BLUE_DEEP, width=2, height=480).pack(side="left", fill="y")

    # Контент.
    content = tk.Frame(root, bg=_WHITE)
    content.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(content, bg=_WHITE)
    inner.pack(fill="both", expand=True, padx=36, pady=(32, 28))

    def hr(parent, pady):
        tk.Frame(parent, bg="#D6DEEA", height=1).pack(fill="x", pady=pady)

    tk.Label(inner, text="Установка Masking", bg=_WHITE, fg=_INK,
             font=(_UI_FONT, 20, "bold")).pack(anchor="w")
    tk.Label(inner, text="Выберите папку и нажмите «Установить».", bg=_WHITE, fg=_MUTED,
             font=(_UI_FONT, 12)).pack(anchor="w", pady=(8, 0))
    hr(inner, (20, 0))

    bottom = tk.Frame(inner, bg=_WHITE)
    bottom.pack(side="bottom", fill="x")
    status = tk.Label(bottom, text="", bg=_WHITE, fg=_MUTED, font=(_UI_FONT, 11),
                      wraplength=430, justify="left", anchor="w")
    status.pack(side="bottom", anchor="w", pady=(12, 0))
    btnrow = tk.Frame(bottom, bg=_WHITE)
    btnrow.pack(side="bottom", fill="x")

    tk.Label(inner, text="Папка установки", bg=_WHITE, fg=_INK,
             font=(_UI_FONT, 11, "bold")).pack(anchor="w", pady=(20, 0))
    frow = tk.Frame(inner, bg=_WHITE)
    frow.pack(fill="x", pady=(6, 0))
    fieldwrap = tk.Frame(frow, bg="#D6DEEA")
    fieldwrap.pack(side="left", fill="x", expand=True)
    target = tk.StringVar(value=desktop_dir())
    entry = tk.Entry(fieldwrap, textvariable=target, font=(_UI_FONT, 11),
                     relief="flat", bd=0, bg=_FIELD, fg=_INK)
    entry.pack(fill="both", expand=True, padx=1, pady=1, ipady=5)

    def _sec_hover(w, on, base=_FIELD):
        w.config(bg="#E6EDF9" if on else base)

    browse = tk.Button(frow, text="Обзор…", font=(_UI_FONT, 11), relief="flat", bd=0,
                       highlightthickness=0, bg=_FIELD, fg=_INK, activebackground="#E6EDF9",
                       cursor="hand2", padx=18, pady=9)
    browse.pack(side="left", padx=(8, 0))
    browse.bind("<Enter>", lambda e: _sec_hover(browse, True))
    browse.bind("<Leave>", lambda e: _sec_hover(browse, False))

    hintrow = tk.Frame(inner, bg=_WHITE)
    hintrow.pack(anchor="w", fill="x", pady=(16, 0))
    dot = tk.Canvas(hintrow, width=10, height=10, bg=_WHITE, highlightthickness=0)
    dot.pack(side="left", pady=(3, 0))
    dot_id = dot.create_oval(1, 1, 9, 9, fill=_WHITE, outline="")
    hint = tk.Label(hintrow, text="", bg=_WHITE, fg=_MUTED, font=(_UI_FONT, 11),
                    wraplength=400, justify="left", anchor="w")
    hint.pack(side="left", padx=(6, 0))

    def refresh_hint(*_a):
        p = target.get().strip()
        txt = preview_action(p) if p and os.path.isdir(p) else ""
        low = txt.lower()
        color = _RED if ("откат" in low or "внимание" in low) else (
            _BLUE_DEEP if "обновление" in low else _BLUE)
        hint.config(text=txt, fg=color)
        dot.itemconfig(dot_id, fill=color if txt else _WHITE)

    def pick():
        d = filedialog.askdirectory(initialdir=target.get() or desktop_dir(),
                                    title="Выберите папку установки")
        if d:
            target.set(d)
    browse.config(command=pick)
    target.trace_add("write", refresh_hint)

    close_job = {"id": None}
    state = {"installing": False}

    def install():
        parent = target.get().strip()
        if not parent or not os.path.isdir(parent):
            messagebox.showwarning(APP_TITLE, "Выберите существующую папку установки.")
            return
        if app_running(_dest_exe()):
            status.config(text="Masking запущен — закройте приложение и повторите установку.", fg=_RED)
            messagebox.showwarning(APP_TITLE,
                "Masking запущен.\n\nЗакройте masking-service.exe и браузер,\n"
                "затем нажмите «Установить» снова.")
            return
        state["installing"] = True
        btn.config(state="disabled", bg="#9FB3E6")
        status.config(text="Устанавливаю…", fg=_MUTED)
        root.update()
        if close_job["id"] is not None:
            root.after_cancel(close_job["id"]); close_job["id"] = None
        try:
            msg = do_install(parent, confirm=lambda m: messagebox.askyesno(APP_TITLE, m))
            ok = not msg.startswith("Отменено")
            if ok:
                status.config(text=msg + "\nГотово. Окно закроется через минуту.", fg=_BLUE)
                messagebox.showinfo(APP_TITLE, msg)
                close_job["id"] = root.after(60000, root.destroy)
            else:
                status.config(text=msg, fg="#9A6A00")
                messagebox.showwarning(APP_TITLE, msg)
            refresh_hint()
        except Exception as e:
            status.config(text=f"Ошибка: {e}", fg=_RED)
            messagebox.showerror(APP_TITLE, f"Ошибка установки:\n{e}")
        finally:
            state["installing"] = False
            btn.config(state="normal", bg=_BLUE)

    _WARN_RUN = "Masking запущен — закройте приложение, чтобы установить."

    def check_running():
        if not state["installing"]:
            try:
                running = app_running(_dest_exe())
            except Exception:
                running = False
            if running:
                btn.config(state="disabled", bg="#9FB3E6")
                if status.cget("text") in ("", _WARN_RUN):
                    status.config(text=_WARN_RUN, fg=_RED)
            elif str(btn.cget("state")) == "disabled":
                btn.config(state="normal", bg=_BLUE)
                if status.cget("text") == _WARN_RUN:
                    status.config(text="", fg=_MUTED)
        root.after(1500, check_running)

    btn = tk.Button(btnrow, text="Установить", command=install, font=(_UI_FONT, 11, "bold"),
                    relief="flat", bd=0, highlightthickness=0, bg=_BLUE, fg=_WHITE,
                    activebackground=_BLUE_DEEP, activeforeground=_WHITE, cursor="hand2",
                    width=14, padx=18, pady=9)
    btn.pack(side="right")
    btn.bind("<Enter>", lambda e: btn.config(bg=_BLUE_DEEP))
    btn.bind("<Leave>", lambda e: btn.config(bg=_BLUE))
    close_btn = tk.Button(btnrow, text="Закрыть", command=root.destroy, font=(_UI_FONT, 11),
                          relief="flat", bd=0, highlightthickness=0, bg=_FIELD, fg=_INK,
                          activebackground="#E6EDF9", cursor="hand2", padx=18, pady=9)
    close_btn.pack(side="right", padx=(0, 10))
    close_btn.bind("<Enter>", lambda e: _sec_hover(close_btn, True))
    close_btn.bind("<Leave>", lambda e: _sec_hover(close_btn, False))
    hr(bottom, (0, 12))

    refresh_hint()
    check_running()
    root.update_idletasks()
    try:
        w, h = root.winfo_width(), root.winfo_height()
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 3
        root.geometry(f"760x480+{x}+{y}")
    except Exception:
        pass
    root.mainloop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Установщик Masking")
    ap.add_argument("--target", default="", help="тихая установка в указанную папку (без GUI)")
    ap.add_argument("--allow-downgrade", action="store_true",
                    help="в тихом режиме разрешить откат на более старую версию")
    args, _ = ap.parse_known_args()
    if args.target:
        print(do_install(args.target, allow_downgrade=args.allow_downgrade))
        return 0
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
