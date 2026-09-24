"""物件ボードの見張り役（board_watcher.ps1）を再起動する。ダブルクリックで実行（窓は出ない）。2026-09-24 追加。
動いている見張り役を止めてから、board_start.pyw で起動し直す。"""
import subprocess, time
from pathlib import Path
BASE = Path(__file__).resolve().parent
kill = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*board_watcher.ps1*' } "
        "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
subprocess.run(["powershell.exe", "-NoProfile", "-Command", kill], creationflags=subprocess.CREATE_NO_WINDOW)
time.sleep(3)
subprocess.Popen(
    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BASE / "board_watcher.ps1")],
    cwd=str(BASE), creationflags=subprocess.CREATE_NO_WINDOW,
)
