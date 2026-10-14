"""pywebview / Edge WebView2 胶水：依赖 pythonnet 与真实窗口，不做单测，靠实机验证。

对 pywebview 5.3.2 的 EdgeChrome 打了两处补丁（requirements.txt 已锁版本，升级 pywebview 时要重新核对）：
- on_webview_ready：pywebview 非调试模式会关掉右键菜单和浏览器快捷键，这里按写作应用的需要重新打开并过滤菜单；
- on_new_window_request：默认把所有新窗口都丢给系统浏览器，而同源页面在浏览器里没有登录态，改为应用内开新窗口。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
import webbrowser
from typing import Callable, Optional

from desktop.shell import APP_TITLE, WindowState, logical_size, system_scale

WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/zh-cn/microsoft-edge/webview2/#download"
MB_ICONINFORMATION = 0x40
MB_YESNO_WARNING = 0x34  # MB_YESNO | MB_ICONWARNING
IDYES = 6
# 合成一次 beforeunload：页面（如世界地图）有未保存修改时会 preventDefault
UNSAVED_JS = "(function(){var e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented;})()"
# 右键菜单里去掉的浏览器条目；名称是英文标签的小驼峰（见 CoreWebView2ContextMenuItem.Name 文档）
_BROWSER_MENU_ITEMS = {"back", "forward", "reload", "saveAs", "print", "createQrCode", "share", "webCapture"}


def message_box(text: str, title: str = APP_TITLE, flags: int = MB_ICONINFORMATION) -> int:
    """还没有窗口时用的系统消息框。"""
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags)


def webview2_available() -> bool:
    """pywebview 找不到 WebView2 运行时会退回 IE 内核（MSHTML），前端在那里跑不起来。"""
    try:
        from webview.platforms import winforms

        return bool(winforms.is_chromium)
    except Exception:  # noqa: BLE001
        return False


def configure(is_app_url: Callable[[str], bool], open_app_window: Callable[[str], None]) -> None:
    """建窗前调用一次：允许下载（另存为对话框）并给 EdgeChrome 打补丁。"""
    import webview
    from webview.platforms import edgechromium

    webview.settings["ALLOW_DOWNLOADS"] = True
    original_ready = edgechromium.EdgeChrome.on_webview_ready

    # 以下回调都在 .NET 事件里执行：异常冒出去会变成 WinForms 的未处理异常对话框，一律兜住
    def on_webview_ready(self, sender, args):
        original_ready(self, sender, args)
        if not args.IsSuccess:
            return
        try:
            core = sender.CoreWebView2
            core.Settings.AreDefaultContextMenusEnabled = True  # 输入框 / 选中文字右键复制粘贴
            core.Settings.AreBrowserAcceleratorKeysEnabled = True  # Ctrl+F 查找、Ctrl+加减 缩放、F5 刷新
            core.ContextMenuRequested += _filter_context_menu
        except Exception:  # noqa: BLE001
            edgechromium.logger.exception("WebView2 设置失败")

    def on_new_window_request(self, sender, args):
        args.set_Handled(True)
        try:
            url = str(args.get_Uri())
            if is_app_url(url):
                threading.Thread(target=open_app_window, args=(url,), daemon=True).start()
            else:
                webbrowser.open(url)
        except Exception:  # noqa: BLE001
            edgechromium.logger.exception("新窗口请求处理失败")

    edgechromium.EdgeChrome.on_webview_ready = on_webview_ready
    edgechromium.EdgeChrome.on_new_window_request = on_new_window_request


def _filter_context_menu(sender, args) -> None:
    try:
        _trim_context_menu(args)
    except Exception:  # noqa: BLE001 - 过滤失败就保留默认菜单
        pass


def _trim_context_menu(args) -> None:
    """空白处右键不弹浏览器菜单；输入框、选中文字、链接、图片保留复制粘贴等，去掉后退 / 刷新 / 打印这类。"""
    from Microsoft.Web.WebView2.Core import CoreWebView2ContextMenuItemKind, CoreWebView2ContextMenuTargetKind

    target = args.ContextMenuTarget
    if not (target.IsEditable or target.HasSelection or target.HasLinkUri or target.Kind != CoreWebView2ContextMenuTargetKind.Page):
        args.Handled = True
        return
    items = args.MenuItems
    for index in range(items.Count - 1, -1, -1):
        if items[index].Name in _BROWSER_MENU_ITEMS:
            items.RemoveAt(index)
    separator = CoreWebView2ContextMenuItemKind.Separator
    index, previous_separator = 0, True  # 开头的分隔线也去掉
    while index < items.Count:
        is_separator = items[index].Kind == separator
        if is_separator and previous_separator:
            items.RemoveAt(index)
            continue
        previous_separator = is_separator
        index += 1
    if items.Count and items[items.Count - 1].Kind == separator:
        items.RemoveAt(items.Count - 1)
    if not items.Count:
        args.Handled = True


def _invoke(form, func: Callable[[], None]) -> None:
    """在窗口的 UI 线程上同步执行。"""
    from System import Func, Type

    form.Invoke(Func[Type](func))


def confirm(window, text: str) -> bool:
    """以窗口为父的「确定 / 取消」对话框，默认焦点在「取消」。"""
    from System.Windows.Forms import DialogResult, MessageBox, MessageBoxButtons, MessageBoxDefaultButton, MessageBoxIcon

    form = window.native
    result = []
    _invoke(form, lambda: result.append(MessageBox.Show(
        form, text, APP_TITLE, MessageBoxButtons.OKCancel, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2,
    )))
    return bool(result) and result[0] == DialogResult.OK


def page_has_unsaved(window, timeout: float = 1.5) -> bool:
    """页面卡死时 evaluate_js 会一直等，放到线程里限时。"""
    result = []

    def run():
        try:
            result.append(window.evaluate_js(UNSAVED_JS))
        except Exception:  # noqa: BLE001
            pass

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    return bool(result) and result[0] is True


def _normal_size(form) -> tuple[int, int]:
    """窗口「还原」状态下的物理尺寸（最大化 / 最小化时取 RestoreBounds）。须在 UI 线程调用。"""
    from System.Windows.Forms import FormWindowState

    bounds = form.Bounds if form.WindowState == FormWindowState.Normal else form.RestoreBounds
    return bounds.Width, bounds.Height


def read_window_state(form, requested: tuple[int, int], initial: Optional[tuple[int, int]]) -> Optional[WindowState]:
    """关窗时的逻辑尺寸与是否最大化；最小化着关掉的不记。须在 UI 线程调用。"""
    from System.Windows.Forms import FormWindowState

    if initial is None or form.WindowState == FormWindowState.Minimized:
        return None
    width, height = logical_size(requested, initial, _normal_size(form), system_scale())
    return WindowState(width, height, form.WindowState == FormWindowState.Maximized)


def reset_close_reason(form) -> None:
    """WinForms 取消关闭后不复位内部的 CloseReason：之后任务管理器 / 其他程序发来的 WM_CLOSE
    仍会被当成「用户点 ×」，托盘模式下就再也关不掉。取消关闭后手动复位成 None。"""
    import clr
    from System.Reflection import BindingFlags
    from System.Windows.Forms import CloseReason, Form

    prop = clr.GetClrType(Form).GetProperty("CloseReason", BindingFlags.Instance | BindingFlags.NonPublic)
    if prop is not None:
        prop.SetValue(form, getattr(CloseReason, "None"))  # None 是 Python 关键字


def show_window(window) -> None:
    """从托盘 / 最小化恢复窗口并切到前台（最小化前是最大化的，还原回最大化）。"""
    from System.Windows.Forms import FormWindowState

    form = window.native

    def show():
        form.Show()
        if form.WindowState == FormWindowState.Minimized:
            ctypes.windll.user32.ShowWindow(ctypes.wintypes.HWND(form.Handle.ToInt64()), 9)  # SW_RESTORE
        form.Activate()

    _invoke(form, show)


def install_close_guard(
    window,
    requested: tuple[int, int],
    get_prompt: Callable[[], Optional[str]],
    on_close: Callable[[Optional[WindowState]], None],
    close_to_tray: Callable[[], bool],
    on_hide: Callable[[], None],
) -> Callable[[], None]:
    """用户点 ×（含 Alt+F4、任务栏关闭）：close_to_tray() 为真只隐藏到托盘，on_hide 在后台线程调用；否则走退出流程。
    退出流程：后台线程算出要不要确认（AI 任务、未保存修改），需要确认时先把窗口叫出来，确认后再真正关掉。
    关机 / 注销等非用户触发的关闭直接放行；on_close 在真正关闭时于 UI 线程调用，带上窗口尺寸状态。
    requested 是建窗时给的逻辑宽高，用来把关窗时的物理尺寸折算回去。返回 request_quit，托盘「退出」也用它。"""
    state = {"allowed": False, "checking": False, "initial": None}

    def decide():
        try:
            prompt = get_prompt()
            if prompt:
                show_window(window)  # 可能是从托盘退出：窗口藏着，确认框没有依托
                if not confirm(window, prompt):
                    return
            state["allowed"] = True
            window.destroy()
        finally:
            state["checking"] = False

    def request_quit():
        if not state["checking"]:
            state["checking"] = True
            threading.Thread(target=decide, daemon=True).start()

    def on_form_closing(sender, args):
        from System.Windows.Forms import CloseReason

        if state["allowed"] or args.CloseReason != CloseReason.UserClosing:
            try:
                on_close(read_window_state(sender, requested, state["initial"]))
            except Exception:  # noqa: BLE001 - 记不住窗口尺寸也要照常关
                pass
            return
        args.Cancel = True
        try:
            reset_close_reason(sender)
        except Exception:  # noqa: BLE001 - 复位失败只影响之后的外部关闭请求
            pass
        if close_to_tray():
            sender.Hide()
            threading.Thread(target=on_hide, daemon=True).start()
        else:
            request_quit()

    def attach():
        form = window.native

        def subscribe():
            form.FormClosing += on_form_closing

        _invoke(form, subscribe)

    def remember_initial_size():
        form = window.native
        _invoke(form, lambda: state.update(initial=_normal_size(form)))  # 已按系统缩放放大后的物理尺寸

    window.events.before_show += attach
    window.events.shown += remember_initial_size
    return request_quit
