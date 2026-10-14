"""桌面壳的纯逻辑（不依赖 pywebview）：同源判断、端口占用、窗口尺寸记忆、关窗确认文案。"""
from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

APP_TITLE = "文澜 AI"
LOGS_TITLE = "文澜 AI - 运行日志"
# pywebview 的窗口宽高按 96 DPI 逻辑像素算（WinForms 会按系统缩放放大）
MIN_SIZE = (1024, 640)
PREFERRED_SIZE = (1440, 900)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> Optional[tuple]:
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        return None
    return parts.scheme, parts.hostname, parts.port or _DEFAULT_PORTS.get(parts.scheme)


def same_origin(url: str, base: str) -> bool:
    """协议 + 主机 + 端口都相同。同源的新窗口留在应用里开（共享登录），其余交给系统浏览器。"""
    try:
        origin = _origin(url)
        return origin is not None and origin == _origin(base)
    except ValueError:  # 端口越界等非法地址
        return False


def port_in_use(host: str, port: int) -> bool:
    """按 uvicorn 在 Windows 上的方式（不带 SO_REUSEADDR）试绑一次，绑不上就是被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


@dataclass(frozen=True)
class WindowState:
    width: int
    height: int
    maximized: bool = False


def default_window_state(work_area: tuple[int, int]) -> WindowState:
    """首次启动：放得下就 1440×900 居中，放不下就最大化（还原尺寸取工作区九成）。"""
    work_w, work_h = work_area
    if work_w >= PREFERRED_SIZE[0] and work_h >= PREFERRED_SIZE[1]:
        return WindowState(*PREFERRED_SIZE)
    return WindowState(max(MIN_SIZE[0], int(work_w * 0.9)), max(MIN_SIZE[1], int(work_h * 0.9)), True)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, max(high, low)))


def load_window_state(path: Path, work_area: tuple[int, int]) -> WindowState:
    """上次关闭时的尺寸 / 是否最大化；文件缺失或内容不对用默认值，尺寸夹在最小值与工作区之间。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        width, height = int(data["width"]), int(data["height"])
        maximized = bool(data.get("maximized", False))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return default_window_state(work_area)
    work_w, work_h = work_area
    return WindowState(_clamp(width, MIN_SIZE[0], work_w), _clamp(height, MIN_SIZE[1], work_h), maximized)


def _write_json(path: Path, data: dict) -> None:
    """先写临时文件再替换，中途断电也不会留下半截 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def save_window_state(path: Path, state: WindowState) -> None:
    _write_json(path, asdict(state))


@dataclass(frozen=True)
class DesktopPrefs:
    close_to_tray: bool = True  # 点 × 隐藏到托盘；False = 关窗即退出（托盘菜单里可切换）
    tray_hint_shown: bool = False  # 第一次进托盘时的提示已经弹过


def load_prefs(path: Path) -> DesktopPrefs:
    """读桌面偏好：文件缺失或损坏用默认值，某一项类型不对只回退那一项。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return DesktopPrefs(**{
        f.name: data[f.name] if isinstance(data.get(f.name), bool) else f.default
        for f in fields(DesktopPrefs)
    })


def save_prefs(path: Path, prefs: DesktopPrefs) -> None:
    _write_json(path, asdict(prefs))


def system_scale() -> float:
    """系统缩放比（125% → 1.25）：WinForms 按它放大 pywebview 给的逻辑宽高。"""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # pywebview 建窗前本来也会调；先调才拿得到真实 DPI（否则系统按 96 虚拟化）
        user32.SetProcessDPIAware()
        hdc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88) or 96  # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
        return max(dpi / 96, 1.0)
    except Exception:  # noqa: BLE001 - 非 Windows
        return 1.0


def work_area() -> tuple[int, int]:
    """主屏工作区（去掉任务栏）的逻辑像素尺寸。"""
    try:
        import ctypes
        from ctypes import wintypes

        scale = system_scale()
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        return int((rect.right - rect.left) / scale), int((rect.bottom - rect.top) / scale)
    except Exception:  # noqa: BLE001 - 非 Windows / 取不到时给一个保守值
        return 1366, 728


def logical_size(requested: tuple[int, int], initial: tuple[int, int], current: tuple[int, int], scale: float) -> tuple[int, int]:
    """关窗时的物理尺寸折回建窗用的逻辑尺寸：建窗时 requested（逻辑）→ initial（物理，含不随缩放变化的边框），
    之后用户拖动的变化量按缩放比换算。直接拿物理尺寸除缩放比会把边框也算进去，每次启动差几像素、越积越多。"""
    return requested[0] + round((current[0] - initial[0]) / scale), requested[1] + round((current[1] - initial[1]) / scale)


def close_prompt(running_jobs: int, unsaved: bool) -> Optional[str]:
    """关主窗口前的确认文案；None = 没什么会丢，直接退出。"""
    lines = []
    if running_jobs:
        lines.append(f"有 {running_jobs} 个 AI 任务正在运行（如批量写作），退出会中断它们，已完成的部分会保留。")
    if unsaved:
        lines.append("当前页面有未保存的修改，退出后会丢失。")
    if not lines:
        return None
    ask = "确定要退出文澜 AI 吗？"
    if running_jobs:
        ask += "想让任务继续，请点「取消」。"
    return "\n".join(lines) + "\n\n" + ask
