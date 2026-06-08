"""
TasteLab desktop entry point.

Double-click the built executable to start the local server and open the web UI.
No separate Python install or terminal commands are required for end users.
"""
from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

from app_paths import app_base_dir, ensure_data_files, ensure_env_file, load_app_env

HOST = "127.0.0.1"
PORT = 8000
APP_URL = f"http://{HOST}:{PORT}"
SERVER_FLAG = "--tastelab-server"


def _prepare_environment() -> None:
    base = app_base_dir()
    os.chdir(base)
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    ensure_data_files()
    ensure_env_file()
    load_app_env()


def _run_server_process() -> None:
    """Child process entry: run uvicorn only (no GUI)."""
    _prepare_environment()
    import uvicorn
    from main import app

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


def _spawn_server() -> subprocess.Popen:
    kwargs: dict = {
        "cwd": str(app_base_dir()),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return subprocess.Popen([sys.executable, SERVER_FLAG], **kwargs)


class TasteLabApp:
    def __init__(self) -> None:
        self._server_proc: subprocess.Popen | None = None
        self._root = tk.Tk()
        self._root.title("TasteLab 영화·음악 추천")
        self._root.geometry("420x220")
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._on_quit)

        frame = ttk.Frame(self._root, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="TasteLab", font=("Segoe UI", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(frame, text="영화·음악 추천 시스템", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 12))

        self._status = ttk.Label(frame, text="서버를 시작하는 중… (최초 실행은 1분 정도 걸릴 수 있습니다)", wraplength=360)
        self._status.pack(anchor=tk.W, pady=(0, 16))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X)
        self._open_btn = ttk.Button(btn_row, text="브라우저 열기", command=self._open_browser, state=tk.DISABLED)
        self._open_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="종료", command=self._on_quit).pack(side=tk.LEFT)

        ttk.Label(
            frame,
            text=f"주소: {APP_URL}\n종료하려면 이 창을 닫으세요.",
            font=("Segoe UI", 9),
            foreground="#555",
        ).pack(anchor=tk.W, pady=(16, 0))

    def _open_browser(self) -> None:
        webbrowser.open(APP_URL)

    def _on_quit(self) -> None:
        proc = self._server_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._root.destroy()

    def _wait_for_server(self) -> None:
        import urllib.error
        import urllib.request

        ready = False
        for _ in range(120):
            if self._server_proc is not None and self._server_proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(APP_URL, timeout=1):
                    ready = True
                    break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.5)
        if ready:
            self._root.after(0, self._on_server_ready)
        else:
            self._root.after(0, self._on_server_timeout)

    def _on_server_ready(self) -> None:
        self._status.config(text="실행 중 — 브라우저에서 추천을 이용하세요.")
        self._open_btn.config(state=tk.NORMAL)
        self._open_browser()

    def _on_server_timeout(self) -> None:
        self._status.config(text="서버 시작에 실패했습니다.")
        messagebox.showerror(
            "TasteLab",
            "로컬 서버를 시작하지 못했습니다. TasteLab.exe를 다시 실행해 보세요.",
        )

    def run(self) -> None:
        self._server_proc = _spawn_server()
        threading.Thread(target=self._wait_for_server, daemon=True, name="tastelab-wait").start()
        self._root.mainloop()


def main() -> None:
    if SERVER_FLAG in sys.argv:
        _run_server_process()
        return

    try:
        _prepare_environment()
        TasteLabApp().run()
    except Exception as exc:
        messagebox.showerror("TasteLab 시작 오류", f"앱을 시작하지 못했습니다.\n\n{exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
