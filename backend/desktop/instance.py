"""单实例（Windows 命名互斥量）与唤起已打开的窗口。

互斥量名带端口：端口才是真正独占的资源，开发时换个 APP_PORT 就能和安装版同时运行。
进程退出时系统自动遗弃互斥量，等待方会拿到 WAIT_ABANDONED，按获取成功处理。
主窗口可能藏在托盘里，第二个实例经命名事件通知第一个实例自己把窗口叫出来（ShowListener / request_show）。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Optional

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0x0
WAIT_ABANDONED = 0x80
INFINITE = 0xFFFFFFFF
EVENT_MODIFY_STATE = 0x0002
ASFW_ANY = 0xFFFFFFFF
SW_SHOW = 5
SW_RESTORE = 9

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
_user32.FindWindowW.restype = wintypes.HWND
_user32.IsIconic.argtypes = (wintypes.HWND,)
_user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
_user32.AllowSetForegroundWindow.argtypes = (wintypes.DWORD,)


def acquire(name: str, wait: float = 0.0) -> Optional[int]:
    """拿到互斥量返回句柄（持有到进程退出即可），被别的实例占着、等 wait 秒仍拿不到返回 None。"""
    handle = _kernel32.CreateMutexW(None, True, name)
    if not handle:
        return None
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return handle
    if _kernel32.WaitForSingleObject(handle, int(wait * 1000)) in (WAIT_OBJECT_0, WAIT_ABANDONED):
        return handle
    _kernel32.CloseHandle(handle)
    return None


def release(handle: Optional[int]) -> None:
    if handle:
        _kernel32.ReleaseMutex(handle)
        _kernel32.CloseHandle(handle)


class ShowListener:
    """在后台线程等「把主窗口叫出来」的命名事件（自动复位），收到就调 on_show。"""

    def __init__(self, name: str, on_show: Callable[[], None]):
        self._on_show = on_show
        self._closed = False
        self._handle = _kernel32.CreateEventW(None, False, False, name)
        self._thread = threading.Thread(target=self._run, name="wenlan-show-listener", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while _kernel32.WaitForSingleObject(self._handle, INFINITE) == WAIT_OBJECT_0 and not self._closed:
            try:
                self._on_show()
            except Exception:  # noqa: BLE001 - 唤起失败不能让监听线程退出
                pass
        _kernel32.CloseHandle(self._handle)  # 由等待的线程自己关句柄：别处关正在被等待的句柄行为未定义

    def close(self) -> None:
        """不再认领唤起请求（主窗口关闭时调用）。"""
        self._closed = True
        _kernel32.SetEvent(self._handle)
        self._thread.join(2)


def request_show(name: str) -> bool:
    """通知已在运行的实例显示主窗口；对方没在监听（旧版本 / 正在退出）返回 False。"""
    handle = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not handle:
        return False
    try:
        _user32.AllowSetForegroundWindow(ASFW_ANY)  # 刚被用户启动的本进程有前台权，转让给对方
        return bool(_kernel32.SetEvent(handle))
    finally:
        _kernel32.CloseHandle(handle)


def bring_to_front(title: str) -> bool:
    """按标题找到已打开的主窗口，还原（若最小化）并切到前台。"""
    hwnd = _user32.FindWindowW(None, title)
    if not hwnd:
        return False
    _user32.ShowWindow(hwnd, SW_RESTORE if _user32.IsIconic(hwnd) else SW_SHOW)
    _user32.SetForegroundWindow(hwnd)
    return True
