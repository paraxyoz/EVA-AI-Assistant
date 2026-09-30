"""
System Profiler for EVA AI Assistant.
Gathers hardware specs, Windows version, disk partitions, and installed applications.
Caches static hardware & registry lookups in memory for 0ms per-message prompt building.
"""

import platform
import os
import time
import psutil
import subprocess
import winreg
import datetime
from typing import Dict, Any, List, Optional


class SystemProfiler:
    """Collects detailed information about the user's Windows environment with in-memory caching."""

    _os_cache: Optional[Dict[str, str]] = None
    _hw_static_cache: Optional[Dict[str, str]] = None
    _apps_cache: Optional[List[str]] = None
    _disks_cache: Optional[List[Dict[str, Any]]] = None
    _disks_cache_ts: float = 0.0

    @classmethod
    def get_user_and_os(cls) -> Dict[str, str]:
        """Returns OS version, architecture, and username (cached)."""
        if cls._os_cache is None:
            try:
                username = os.getlogin()
            except Exception:
                username = os.environ.get("USERNAME", "User")
            cls._os_cache = {
                "username": username,
                "hostname": platform.node(),
                "os": f"{platform.system()} {platform.release()} (Build {platform.version()})",
                "architecture": platform.machine(),
                "python_version": platform.python_version()
            }
        return cls._os_cache

    @classmethod
    def get_hardware_info(cls) -> Dict[str, Any]:
        """Returns CPU, RAM, and GPU specs (static parts cached, RAM updated in <0.1ms)."""
        if cls._hw_static_cache is None:
            cpu_count_physical = psutil.cpu_count(logical=False)
            cpu_count_logical = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq()

            gpu_names = []
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"'
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2, creationflags=creationflags)
                if res.returncode == 0:
                    gpu_names = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
            except Exception:
                gpu_names = ["GPU"]

            cls._hw_static_cache = {
                "processor": platform.processor(),
                "cpu_cores": f"{cpu_count_physical} физических / {cpu_count_logical} логических",
                "cpu_frequency": f"{cpu_freq.current:.1f} MHz" if cpu_freq else "Н/Д",
                "gpu": ", ".join(gpu_names) if gpu_names else "Интегрированная / Не определена"
            }

        ram = psutil.virtual_memory()
        ram_total_gb = round(ram.total / (1024 ** 3), 2)
        ram_avail_gb = round(ram.available / (1024 ** 3), 2)

        return {
            **cls._hw_static_cache,
            "ram": f"{ram_avail_gb} GB свободно из {ram_total_gb} GB",
        }

    @classmethod
    def get_disks_info(cls) -> List[Dict[str, Any]]:
        """Returns list of all disks, drive letters, and free space (cached for 60s)."""
        now = time.time()
        if cls._disks_cache is not None and (now - cls._disks_cache_ts) < 60.0:
            return cls._disks_cache

        disks = []
        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                total_gb = round(usage.total / (1024 ** 3), 1)
                free_gb = round(usage.free / (1024 ** 3), 1)
                disks.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "fstype": partition.fstype,
                    "total_gb": total_gb,
                    "free_gb": free_gb,
                    "percent_used": usage.percent
                })
            except Exception:
                continue
        cls._disks_cache = disks
        cls._disks_cache_ts = now
        return disks

    @classmethod
    def get_installed_apps(cls, limit: int = 40) -> List[str]:
        """Reads installed applications from Windows Registry (cached in memory)."""
        if cls._apps_cache is not None:
            return cls._apps_cache[:limit]

        apps = set()
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]

        for root, subkey in registry_paths:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            app_key_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, app_key_name) as app_key:
                                try:
                                    name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                                    if name and len(name.strip()) > 1:
                                        apps.add(name.strip())
                                except FileNotFoundError:
                                    pass
                        except Exception:
                            continue
            except Exception:
                continue

        cls._apps_cache = sorted(list(apps))
        return cls._apps_cache[:limit]

    @classmethod
    def get_full_system_context(cls) -> str:
        """Formats system profile into a fast, concise context block for the LLM (0ms after warm-up)."""
        os_info = cls.get_user_and_os()
        hw_info = cls.get_hardware_info()
        disks = cls.get_disks_info()

        now = datetime.datetime.now()
        days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        current_time_str = f"{now.strftime('%H:%M:%S')}, {now.day} {months_ru[now.month-1]} {now.year} ({days_ru[now.weekday()]})"

        user_home = os.path.expanduser("~")
        desktop = os.path.join(user_home, "Desktop")
        downloads = os.path.join(user_home, "Downloads")

        disks_str = ", ".join([f"{d['mountpoint']} ({d['free_gb']}GB свободно)" for d in disks])

        return (
            f"- Время на ПК: {current_time_str}\n"
            f"- Пользователь: {os_info['username']} (Дом: {user_home}, Рабочий стол: {desktop}, Загрузки: {downloads})\n"
            f"- ОС: {os_info['os']} | ОЗУ: {hw_info['ram']} | GPU: {hw_info['gpu']} | Диски: {disks_str}\n"
        )
