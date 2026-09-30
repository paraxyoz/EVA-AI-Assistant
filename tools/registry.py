"""
Tool Registry and Schema Definitions for LLM Function Calling.
Maps LLM tool requests to local Python execution functions.
"""

import json
from typing import Dict, Any, List
from tools.os_control import OSController
from tools.gui_control import GUIController
from memory.db import memory_db


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "execute_powershell",
            "description": "Выполняет команду PowerShell на компьютере пользователя с полными правами. Используй для любых системных задач, установки софта, поиска, настройки сети, изменения реестра и т.д.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Команда PowerShell для выполнения (например: 'Get-Process | Sort-Object CPU -Descending | Select -First 5' или 'mkdir C:\\test')"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_cmd",
            "description": "Выполняет классическую команду Windows CMD / батник.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Команда CMD (например: 'dir /s', 'ping 8.8.8.8')"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_application_or_file",
            "description": "Запускает установленную программу (например 'notepad', 'chrome', 'calc', 'telegram', 'code'), открывает файл или переходит по ссылке URL в браузере.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path_or_name": {
                        "type": "string",
                        "description": "Имя программы, путь к .exe, путь к файлу или URL (например: 'chrome', 'https://youtube.com', 'calc', 'D:\\movie.mp4')"
                    }
                },
                "required": ["path_or_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_processes",
            "description": "Возвращает список запущенных процессов с потреблением RAM и CPU.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_name": {
                        "type": "string",
                        "description": "Необязательный фильтр по названию процесса (например: 'chrome', 'python')"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kill_process",
            "description": "Принудительно закрывает/убивает процесс по его имени или PID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_pid": {
                        "type": "string",
                        "description": "Имя процесса (например 'notepad.exe') или PID (например '1234')"
                    }
                },
                "required": ["name_or_pid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_content",
            "description": "Считывает содержимое текстового файла с диска.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Абсолютный или относительный путь к файлу"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file_content",
            "description": "Создает или перезаписывает текстовый файл на диске с указанным содержимым.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Путь к файлу (например 'C:\\Users\\...\\script.py')"
                    },
                    "content": {
                        "type": "string",
                        "description": "Полный текст/код для записи"
                    },
                    "append": {
                        "type": "boolean",
                        "description": "Если true — добавляет в конец файла вместо перезаписи"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Показывает список файлов и подпапок в указанной директории.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Путь к директории (например: 'C:\\Users' или '.')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Ищет файлы по маске/паттерну в указанной папке (рекурсивно).",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Папка для поиска (например: 'C:\\Users\\paraxyoz\\Downloads')"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Маска файла (например: '*.pdf', '*report*.docx', '*.py')"
                    }
                },
                "required": ["directory", "pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "system_action",
            "description": "Управление питанием и состоянием ПК.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["lock", "sleep", "restart", "shutdown"],
                        "description": "Действие: lock (блокировка), sleep (сон), restart (перезагрузка), shutdown (выключение)"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click_mouse",
            "description": "Кликает мышью в указанные координаты экрана X, Y.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Координата X"},
                    "y": {"type": "integer", "description": "Координата Y"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Кнопка мыши"},
                    "clicks": {"type": "integer", "description": "Количество кликов (1 или 2)"}
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Вводит текст с клавиатуры (поддерживает русский и английский) и может нажать Enter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Текст для ввода"},
                    "press_enter": {"type": "boolean", "description": "Нажать ли клавишу Enter после ввода"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "press_hotkey",
            "description": "Нажимает комбинацию клавиш (например: ['ctrl', 'c'], ['alt', 'tab'], ['win', 'r'], ['ctrl', 'shift', 'esc']).",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список клавиш для одновременного нажатия"
                    }
                },
                "required": ["keys"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_windows",
            "description": "Возвращает список всех открытых видимых окон на экране.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "Выводит на передний план и фокусирует окно по части его заголовка.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title_query": {
                        "type": "string",
                        "description": "Часть заголовка окна (например: 'Chrome', 'Visual Studio', 'Telegram', 'Блокнот')"
                    }
                },
                "required": ["title_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember_user_fact",
            "description": "Запоминает важный факт о пользователе, его привычках, предпочтениях, именах или путях к проектам в постоянную память.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Категория (например: 'preference', 'identity', 'work', 'system')"},
                    "key": {"type": "string", "description": "Ключ факта (например: 'favorite_browser', 'project_path', 'pet_name')"},
                    "value": {"type": "string", "description": "Значение факта"}
                },
                "required": ["category", "key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_time_info",
            "description": "Возвращает текущее точное системное время на компьютере, дату, день недели и время работы ПК (uptime). Вызывай ВСЕГДА, когда пользователь спрашивает сколько времени, который час или какая сегодня дата.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_application_or_file_on_pc",
            "description": "Ищет программу, ярлык, папку или файл на всем компьютере (включая Меню Пуск, Program Files, Рабочий стол, Загрузки, Документы) и возвращает точные пути к файлам.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Имя программы, файла или расширения для поиска (например: 'discord', 'steam', 'word', 'отчет.docx')"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


class ToolDispatcher:
    """Executes tools dispatched by LLM."""

    @staticmethod
    def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
        """Runs the corresponding tool function and returns JSON string."""
        try:
            if tool_name == "execute_powershell":
                res = OSController.execute_powershell(arguments.get("command", ""))
            elif tool_name == "execute_cmd":
                res = OSController.execute_cmd(arguments.get("command", ""))
            elif tool_name == "open_application_or_file":
                res = OSController.open_application_or_file(arguments.get("path_or_name", ""))
            elif tool_name == "list_processes":
                res = OSController.list_processes(arguments.get("filter_name"))
            elif tool_name == "kill_process":
                res = OSController.kill_process(arguments.get("name_or_pid", ""))
            elif tool_name == "read_file_content":
                res = OSController.read_file_content(arguments.get("path", ""))
            elif tool_name == "write_file_content":
                res = OSController.write_file_content(
                    arguments.get("path", ""),
                    arguments.get("content", ""),
                    arguments.get("append", False)
                )
            elif tool_name == "list_directory":
                res = OSController.list_directory(arguments.get("path", "."))
            elif tool_name == "search_files":
                res = OSController.search_files(arguments.get("directory", "."), arguments.get("pattern", "*"))
            elif tool_name == "system_action":
                res = OSController.system_action(arguments.get("action", ""))
            elif tool_name == "click_mouse":
                res = GUIController.click(
                    arguments.get("x", 0),
                    arguments.get("y", 0),
                    arguments.get("button", "left"),
                    arguments.get("clicks", 1)
                )
            elif tool_name == "type_text":
                res = GUIController.type_text(
                    arguments.get("text", ""),
                    arguments.get("press_enter", False)
                )
            elif tool_name == "press_hotkey":
                res = GUIController.press_hotkey(arguments.get("keys", []))
            elif tool_name == "list_windows":
                res = GUIController.list_visible_windows()
            elif tool_name == "focus_window":
                res = GUIController.focus_window_by_title(arguments.get("title_query", ""))
            elif tool_name == "get_system_time_info":
                res = OSController.get_system_time_info()
            elif tool_name == "find_application_or_file_on_pc":
                res = OSController.find_application_or_file_on_pc(arguments.get("query", ""))
            elif tool_name == "remember_user_fact":
                memory_db.remember_fact(
                    arguments.get("category", "general"),
                    arguments.get("key", ""),
                    arguments.get("value", "")
                )
                res = {"success": True, "message": f"Факт '{arguments.get('key')}' успешно сохранен в память."}
            else:
                res = {"error": f"Неизвестный инструмент: {tool_name}"}

            return json.dumps(res, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Исключение при вызове {tool_name}: {str(e)}"}, ensure_ascii=False)
