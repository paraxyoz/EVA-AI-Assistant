"""
OS Control and Execution Engine for Personal AI Assistant.
Provides direct command execution (PowerShell/CMD), process control, and file management.
"""

import subprocess
import os
import sys
import time
import psutil
import ctypes
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional


class OSController:
    """Executes arbitrary OS level commands and operations."""

    @staticmethod
    def execute_powershell(command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Executes a PowerShell command and returns output, errors, and returncode.
        """
        try:
            # Using -ExecutionPolicy Bypass and UTF-8 encoding
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "exit_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Превышено время ожидания ({timeout} сек)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute_cmd(command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Executes a standard Windows CMD command.
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="cp866", # Windows Russian OEM encoding fallback
                errors="replace",
                timeout=timeout
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "exit_code": result.returncode
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def execute_elevated_admin(command: str) -> Dict[str, Any]:
        """
        Executes a command with administrator privileges (triggers Windows UAC prompt).
        """
        try:
            # Using ShellExecuteW with 'runas'
            script_path = os.environ.get("TEMP", ".") + "\\temp_elevated.ps1"
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(command)

            params = f"-NoProfile -ExecutionPolicy Bypass -File \"{script_path}\""
            ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 1)
            if ret > 32:
                return {"success": True, "message": "Команда отправлена на выполнение от имени Администратора."}
            else:
                return {"success": False, "error": f"Ошибка UAC, код возврата: {ret}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def open_application_or_file(path_or_name: str) -> Dict[str, Any]:
        """
        Launches an application, opens a file or URL in the default browser.
        Handles Russian & English app names (e.g. 'стим'/'steam', 'телеграм'/'telegram', 'диспетчер задач' -> 'taskmgr').
        """
        target = path_or_name.strip()
        t_low = target.lower()

        name_map = {
            "диспетчер задач": "taskmgr",
            "диспетчер": "taskmgr",
            "таск менеджер": "taskmgr",
            "task manager": "taskmgr",
            "калькулятор": "calc",
            "блокнот": "notepad",
            "проводник": "explorer",
            "мой компьютер": "explorer",
            "папка": "explorer",
            "настройки": "ms-settings:",
            "параметры": "ms-settings:",
            "панель управления": "control",
            "командная строка": "cmd",
            "терминал": "powershell",
            "браузер": "chrome",
            "хром": "chrome",
            "paint": "mspaint",
            "паинт": "mspaint",
            "пейнт": "mspaint",
            "стим": "steam",
            "телеграм": "telegram",
            "телегу": "telegram",
            "тг": "telegram",
            "дискорд": "discord",
            "дс": "discord",
            "спотифай": "spotify",
        }
        resolved = name_map.get(t_low, target)
        r_low = resolved.lower()

        # Special fast-paths for common desktop apps on Windows
        app_Data = os.environ.get("APPDATA", "")
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        prog_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        prog_64 = os.environ.get("ProgramFiles", "C:\\Program Files")

        known_paths = {
            "steam": [
                os.path.join(prog_x86, "Steam", "steam.exe"),
                os.path.join(prog_64, "Steam", "steam.exe"),
                "steam://open/main",
            ],
            "telegram": [
                os.path.join(app_Data, "Telegram Desktop", "Telegram.exe"),
                os.path.join(local_appdata, "Telegram Desktop", "Telegram.exe"),
                "tg://",
            ],
            "discord": [
                os.path.join(local_appdata, "Discord", "Update.exe"),
                "discord://",
            ],
            "spotify": [
                os.path.join(app_Data, "Spotify", "Spotify.exe"),
                "spotify:",
            ],
        }

        if r_low in known_paths:
            for candidate in known_paths[r_low]:
                if candidate.endswith("Update.exe") and os.path.exists(candidate):
                    try:
                        subprocess.Popen(
                            [candidate, "--processStart", "Discord.exe"],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                        )
                        return {"success": True, "message": "Успешно запущено: Discord"}
                    except Exception:
                        pass
                elif "://" in candidate or candidate.endswith(":"):
                    try:
                        os.startfile(candidate)
                        return {"success": True, "message": f"Успешно запущено: {resolved}"}
                    except Exception:
                        pass
                elif os.path.exists(candidate):
                    try:
                        os.startfile(candidate)
                        return {"success": True, "message": f"Успешно запущено: {candidate}"}
                    except Exception:
                        pass

        try:
            os.startfile(resolved)
            return {"success": True, "message": f"Успешно запущено/открыто: {resolved}"}
        except Exception as e:
            # Try searching PC if direct start fails
            search_res = OSController.find_application_or_file_on_pc(resolved)
            if search_res.get("success") and search_res.get("matches"):
                found_exe = search_res["matches"][0]
                try:
                    os.startfile(found_exe)
                    return {"success": True, "message": f"Успешно запущено: {found_exe}"}
                except Exception:
                    pass

            # Fallback using powershell Start-Process
            ps_res = OSController.execute_powershell(f"Start-Process '{resolved}'")
            if ps_res.get("success"):
                return {"success": True, "message": f"Успешно запущено: {resolved}"}
            return {"success": False, "error": str(e)}

    @staticmethod
    def list_processes(filter_name: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
        """Lists running processes with CPU and RAM usage."""
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                info = p.info
                if filter_name and filter_name.lower() not in info['name'].lower():
                    continue
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'],
                    "ram_percent": round(info['memory_percent'] or 0, 1),
                    "cpu_percent": round(info['cpu_percent'] or 0, 1)
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs[:limit]

    @staticmethod
    def kill_process(name_or_pid: Any) -> Dict[str, Any]:
        """Terminates a process (and its child tree) by name (with or without .exe, Russian or English) or PID."""
        try:
            if isinstance(name_or_pid, int) or (isinstance(name_or_pid, str) and name_or_pid.strip().isdigit()):
                p = psutil.Process(int(str(name_or_pid).strip()))
                p.terminate()
                try:
                    p.wait(timeout=1.0)
                except Exception:
                    p.kill()
                return {"success": True, "message": f"Процесс PID {name_or_pid} завершен."}

            raw = str(name_or_pid or "").strip().lower()
            alias_targets = {
                "steam": ["steam.exe", "steamwebhelper.exe"],
                "steam.exe": ["steam.exe", "steamwebhelper.exe"],
                "стим": ["steam.exe", "steamwebhelper.exe"],
                "st": ["steam.exe", "steamwebhelper.exe"],
                "ст": ["steam.exe", "steamwebhelper.exe"],
                "telegram": ["telegram.exe"],
                "telegram.exe": ["telegram.exe"],
                "телеграм": ["telegram.exe"],
                "телегу": ["telegram.exe"],
                "тг": ["telegram.exe"],
                "discord": ["discord.exe"],
                "discord.exe": ["discord.exe"],
                "дискорд": ["discord.exe"],
                "дс": ["discord.exe"],
                "spotify": ["spotify.exe"],
                "spotify.exe": ["spotify.exe"],
                "спотифай": ["spotify.exe"],
                "chrome": ["chrome.exe"],
                "chrome.exe": ["chrome.exe"],
                "браузер": ["chrome.exe"],
                "хром": ["chrome.exe"],
                "notepad": ["notepad.exe"],
                "блокнот": ["notepad.exe"],
                "calc": ["calculatorapp.exe", "calc.exe"],
                "calculatorapp.exe": ["calculatorapp.exe", "calc.exe"],
                "калькулятор": ["calculatorapp.exe", "calc.exe"],
                "paint": ["mspaint.exe"],
                "mspaint.exe": ["mspaint.exe"],
                "пейнт": ["mspaint.exe"],
                "taskmgr": ["taskmgr.exe"],
                "taskmgr.exe": ["taskmgr.exe"],
                "диспетчер задач": ["taskmgr.exe"],
                "диспетчер": ["taskmgr.exe"],
                "obs": ["obs64.exe", "obs32.exe"],
                "обс": ["obs64.exe", "obs32.exe"],
                "blender": ["blender.exe"],
                "блендер": ["blender.exe"],
            }

            if raw in alias_targets:
                target_exes = alias_targets[raw]
            else:
                base_exe = raw if raw.endswith(".exe") else f"{raw}.exe"
                target_exes = [base_exe, raw]

            target_set = {t.lower() for t in target_exes}
            killed = 0
            my_pid = os.getpid()

            # 1. Terminate & kill via psutil (with per-process exception handling so AccessDenied never aborts the loop)
            matched_procs = []
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    p_pid = p.info.get('pid')
                    p_name = (p.info.get('name') or '').lower()
                    if not p_name or p_pid == my_pid:
                        continue
                    if p_name in target_set or any(p_name.startswith(t.replace(".exe", "")) for t in target_set if len(t) >= 4):
                        # Avoid killing steamservice.exe (protected service) when closing Steam client
                        if p_name == "steamservice.exe":
                            continue
                        p.terminate()
                        matched_procs.append(p)
                        killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                    continue

            for p in matched_procs:
                try:
                    p.wait(timeout=0.4)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass

            # 2. Also run taskkill /F /IM <exe> /T for guaranteed multi-process tree termination on Windows
            no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            for exe in target_exes:
                if exe.endswith(".exe"):
                    try:
                        r = subprocess.run(
                            ["taskkill", "/F", "/IM", exe, "/T"],
                            capture_output=True,
                            timeout=3,
                            creationflags=no_win
                        )
                        if r.returncode == 0:
                            killed = max(killed, 1)
                    except Exception:
                        pass

            return {"success": True, "killed": killed, "message": f"Завершено процессов ({name_or_pid}): {killed}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # File System Operations
    @staticmethod
    def read_file_content(path: str, max_lines: int = 500) -> Dict[str, Any]:
        """Reads content of a text file."""
        try:
            p = Path(path).resolve()
            if not p.exists():
                return {"success": False, "error": f"Файл не найден: {path}"}
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = [f.readline() for _ in range(max_lines)]
                return {"success": True, "content": "".join(lines), "total_lines_read": len(lines)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def write_file_content(path: str, content: str, append: bool = False) -> Dict[str, Any]:
        """Writes or appends text to a file."""
        try:
            p = Path(path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(p, mode, encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "message": f"Файл успешно записан: {path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def list_directory(path: str) -> Dict[str, Any]:
        """Lists files and folders inside a given path."""
        try:
            p = Path(path).resolve()
            if not p.exists():
                return {"success": False, "error": f"Папка не найдена: {path}"}
            items = []
            for item in p.iterdir():
                items.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size_bytes": item.stat().st_size if item.is_file() else None
                })
            return {"success": True, "path": str(p), "items": items}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def search_files(directory: str, pattern: str, limit: int = 20) -> List[str]:
        """Searches for files matching a glob pattern."""
        try:
            p = Path(directory).resolve()
            matches = list(p.rglob(pattern))
            return [str(m) for m in matches[:limit]]
        except Exception:
            return []

    # System Power / Lock
    @staticmethod
    def system_action(action: str) -> Dict[str, Any]:
        """Performs system power actions: lock, sleep, restart, shutdown."""
        act = action.lower().strip()
        if act == "lock":
            ctypes.windll.user32.LockWorkStation()
            return {"success": True, "message": "Рабочая станция заблокирована"}
        elif act == "shutdown":
            subprocess.run("shutdown /s /t 10", shell=True)
            return {"success": True, "message": "Запущено выключение ПК (через 10 сек)"}
        elif act == "restart":
            subprocess.run("shutdown /r /t 10", shell=True)
            return {"success": True, "message": "Запущена перезагрузка ПК"}
        elif act == "sleep":
            subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            return {"success": True, "message": "ПК переведен в спящий режим"}
        return {"success": False, "error": f"Неизвестное действие: {action}"}

    @staticmethod
    def set_system_volume(level: int) -> int:
        """Sets Windows master system volume to a specific percentage (0..100) across all active output endpoints."""
        target = max(0, min(100, int(level)))
        scalar = target / 100.0
        updated_any = False
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            try:
                speakers = AudioUtilities.GetSpeakers()
                interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(scalar, None)
                updated_any = True
            except Exception:
                pass
            try:
                for dev in AudioUtilities.GetAllDevices():
                    if getattr(dev, "state", None) and "Active" in str(dev.state):
                        ep = getattr(dev, "EndpointVolume", None)
                        if ep is not None:
                            ep.SetMasterVolumeLevelScalar(scalar, None)
                            updated_any = True
            except Exception:
                pass
            if updated_any:
                return target
        except Exception:
            pass

        try:
            # Fallback via Win32 virtual media volume keys (reset to 0 then step up by 2% increments)
            VK_VOLUME_DOWN = 0xAE
            VK_VOLUME_UP = 0xAF
            for _ in range(50):
                ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 2, 0)
            steps = round(target / 2.0)
            for _ in range(steps):
                ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 2, 0)
        except Exception:
            pass
        return target

    @staticmethod
    def get_system_time_info() -> Dict[str, Any]:
        """Returns exact current local system time, date, day of week, and uptime."""
        import datetime
        now = datetime.datetime.now()
        days_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        
        boot_time = psutil.boot_time()
        uptime_seconds = int(time.time() - boot_time)
        uptime_hours = uptime_seconds // 3600
        uptime_mins = (uptime_seconds % 3600) // 60

        return {
            "success": True,
            "time_24h": now.strftime("%H:%M:%S"),
            "time_short": now.strftime("%H:%M"),
            "date": f"{now.day} {months_ru[now.month-1]} {now.year} года",
            "day_of_week": days_ru[now.weekday()],
            "uptime": f"{uptime_hours} ч {uptime_mins} мин",
            "full_phrase": f"Сейчас {now.strftime('%H:%M')}, {days_ru[now.weekday()]}, {now.day} {months_ru[now.month-1]} {now.year} года."
        }

    @staticmethod
    def find_application_or_file_on_pc(query: str) -> Dict[str, Any]:
        """Searches across System PATH, Start Menu, Program Files, AppData, and User directories for any file or program."""
        found = []
        q_raw = query.lower().strip()
        q = q_raw.replace(".exe", "")

        # Russian friendly app aliases
        aliases = {
            "блокнот": "notepad",
            "калькулятор": "calc",
            "проводник": "explorer",
            "диспетчер задач": "taskmgr",
            "командная строка": "cmd",
            "браузер": "chrome",
            "телеграм": "telegram",
            "дискорд": "discord",
            "стим": "steam"
        }
        target_name = aliases.get(q, q)

        # 1. System PATH & standard Windows tools lookup
        for cand in [target_name, f"{target_name}.exe", q_raw]:
            p = shutil.which(cand)
            if p and p not in found:
                found.append(p)

        search_roots = [
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Documents"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
            r"C:\Program Files",
            r"C:\Program Files (x86)",
            r"C:\Windows\System32"
        ]

        for root in search_roots:
            if not os.path.exists(root):
                continue
            try:
                for dirpath, _, filenames in os.walk(root):
                    for f in filenames:
                        f_lower = f.lower()
                        if target_name in f_lower or q in f_lower:
                            full_p = os.path.join(dirpath, f)
                            if full_p not in found:
                                found.append(full_p)
                            if len(found) >= 10:
                                break
                    if len(found) >= 10:
                        break
            except Exception:
                continue

        return {
            "success": len(found) > 0,
            "query": query,
            "matches": found,
            "count": len(found)
        }
