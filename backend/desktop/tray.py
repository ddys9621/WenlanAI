"""系统托盘图标：WinForms NotifyIcon，跑在 pywebview 的 UI 线程上（pythonnet 已在，不新增依赖）。

左键单击 = 显示主窗口；右键菜单：显示主窗口 / 运行日志 / 关闭窗口时最小化到托盘（可勾选）/ 退出。
菜单回调一律丢到新线程执行：回调会调 evaluate_js 这类要 UI 线程配合的接口，在 UI 线程上同步执行会死锁。
进程最后用 os._exit 结束，退出前必须 dispose，否则托盘里会留一个鼠标划过才消失的残影。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from desktop.shell import APP_TITLE
from desktop.webview2 import _invoke


class Tray:
    def __init__(
        self,
        icon_path: Path,
        *,
        on_show: Callable[[], None],
        on_logs: Callable[[], None],
        on_quit: Callable[[], None],
        close_to_tray: bool,
        on_close_to_tray_changed: Callable[[bool], None],
    ):
        self._icon_path = Path(icon_path)
        self._on_show = on_show
        self._on_logs = on_logs
        self._on_quit = on_quit
        self._close_to_tray = close_to_tray
        self._on_close_to_tray_changed = on_close_to_tray_changed
        self._form = None
        self._icon = None  # NotifyIcon，主窗口显示后在 UI 线程上创建

    def attach(self, window) -> None:
        """主窗口显示后创建托盘图标。"""
        window.events.shown += lambda: _invoke(window.native, lambda: self._build(window.native))

    def _build(self, form) -> None:
        from System.Drawing import Font, FontStyle, Icon
        from System.Windows.Forms import (
            ContextMenuStrip, MouseButtons, NotifyIcon, SystemInformation, ToolStripMenuItem, ToolStripSeparator,
        )

        def item(text: str, action: Callable[[], None]):
            menu_item = ToolStripMenuItem(text)
            menu_item.Click += lambda sender, args: self._spawn(action)
            return menu_item

        show = item("显示主窗口", self._on_show)
        show.Font = Font(show.Font, FontStyle.Bold)  # 粗体 = 左键单击的默认动作
        toggle = ToolStripMenuItem("关闭窗口时最小化到托盘")
        toggle.CheckOnClick = True
        toggle.Checked = self._close_to_tray
        toggle.CheckedChanged += lambda sender, args: self._spawn(self._on_close_to_tray_changed, bool(sender.Checked))
        menu = ContextMenuStrip()
        for menu_item in (show, item("运行日志", self._on_logs), ToolStripSeparator(), toggle, ToolStripSeparator(), item("退出文澜 AI", self._on_quit)):
            menu.Items.Add(menu_item)

        def on_click(sender, args):
            if args.Button == MouseButtons.Left:
                self._spawn(self._on_show)

        icon = NotifyIcon()
        icon.Icon = Icon(str(self._icon_path), SystemInformation.SmallIconSize) if self._icon_path.exists() else form.Icon
        icon.Text = APP_TITLE
        icon.ContextMenuStrip = menu
        icon.MouseClick += on_click
        icon.Visible = True
        self._form, self._icon = form, icon

    def notify(self, title: str, text: str) -> None:
        """托盘气泡（Win10/11 上显示为系统通知）。"""
        from System.Windows.Forms import ToolTipIcon

        icon = self._icon
        if icon is not None:
            _invoke(self._form, lambda: icon.ShowBalloonTip(5000, title, text, ToolTipIcon.Info))

    def dispose(self) -> None:
        """移除托盘图标；须在 UI 线程调用（主窗口真正关闭时）。"""
        icon, self._icon = self._icon, None
        if icon is not None:
            icon.Visible = False
            icon.Dispose()

    @staticmethod
    def _spawn(func: Callable, *args) -> None:
        threading.Thread(target=func, args=args, daemon=True).start()
