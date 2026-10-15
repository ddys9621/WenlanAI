"""应用启动脚本 - 桌面版单窗口应用（pywebview / Edge WebView2）

双击即打开「文澜 AI」窗口：先显示启动画面（首启模型引导、出错提示），后端就绪后在同一窗口进入主界面，
全程不需要浏览器。运行日志在单独的小窗口里，从启动画面底部或主界面侧栏「运行日志」打开。
点 × 默认收进系统托盘（AI 任务继续跑），托盘右键「退出」才真正退出；托盘菜单里可改成关窗即退出。
"""
import sys
import os
import time
import threading
import asyncio
import json
import logging
import traceback
import webbrowser
from pathlib import Path
from collections import deque

if getattr(sys, 'frozen', False):
    _exe_dir = Path(sys.executable).parent
    _internal_dir = _exe_dir / '_internal'
    if _internal_dir.exists():
        sys.path.insert(0, str(_internal_dir))

# Windows 编码修复：防止 emoji/Unicode 字符导致 GBK 编码错误
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# pythonw.exe 没有 stdout/stderr，需要创建 devnull 替代
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

from dataclasses import replace  # noqa: E402

from desktop.shell import (  # noqa: E402 - 须在上面的路径 / 编码修复之后导入
    APP_TITLE, LOGS_TITLE, MIN_SIZE, DesktopPrefs, close_prompt, default_window_state,
    load_prefs, load_window_state, same_origin, save_prefs, save_window_state, work_area,
)

# 日志缓冲区（供启动画面 / 运行日志窗口显示）
_log_buffer: deque = deque(maxlen=500)
_log_seq = 0

# ---- 首启模型引导状态（embedding 模型不再内置于安装包）----
_HOST = '127.0.0.1'
_PORT = 8000
_model_required = False        # True = 等待用户选择（下载/导入/跳过）
_model_busy = ""               # 非空 = 正在下载/导入（启动画面显示忙碌文案）
_model_worker_running = False  # 防止重复起下载/导入线程
_launch_lock = threading.Lock()

# ---- 桌面窗口状态 ----
_server = None                 # desktop.server.BackendServer，模型引导结束后创建
_startup_error = None          # 启动前置检查（数据库）失败的原因，显示在启动画面
_main_window = None
_logs_window = None
_windows_lock = threading.Lock()
_instance_mutex = None         # 单实例互斥量句柄，持有到进程退出
_show_listener = None          # desktop.instance.ShowListener：第二个实例请求显示主窗口
_tray = None                   # desktop.tray.Tray
_prefs = DesktopPrefs()        # 点 × 进托盘等桌面偏好（data/desktop_settings.json）

# 品牌图标（scripts/make_icon.py 由 frontend/public/logo.svg 生成）：
# 打包后位于 exe 旁的 _internal/assets，开发环境位于 backend/assets
_RESOURCE_DIR = (Path(sys.executable).parent / '_internal') if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
_ICON_PATH = _RESOURCE_DIR / 'assets' / 'app.ico'
_WINDOW_BG = '#f3f5f3'


def set_app_user_model_id():
    """任务栏图标。开发模式下进程是 python.exe，任务栏会把窗口归到 Python 的开始菜单快捷方式上、
    显示 Python 图标；给进程一个独立的 AppUserModelID 后，任务栏才会改用窗口自身的图标。
    必须在创建任何窗口之前调用。打包后的 exe 自带图标资源、任务栏按 exe 路径匹配快捷方式即可，
    不额外设置，以免和安装包生成的快捷方式归组不一致（固定到任务栏会出现两个按钮）。"""
    if sys.platform != 'win32' or getattr(sys, 'frozen', False):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Wenlan.NovelStudio.Launcher')
    except Exception:
        pass


def apply_window_icon(window):
    """Windows 下 pywebview 只会从 sys.executable 提取图标（开发模式即 Python 图标），
    这里改为项目品牌图标。WinForms 控件属性须在 UI 线程上修改。"""
    if sys.platform != 'win32' or not _ICON_PATH.exists():
        return
    try:
        from System import Func, Type
        from System.Drawing import Icon
        form = window.native

        def _set_icon():
            form.Icon = Icon(str(_ICON_PATH))

        form.Invoke(Func[Type](_set_icon))
    except Exception as e:
        _panel_log("DEBUG", f"窗口图标设置失败: {e}")


def _panel_log(level, msg):
    """启动器自身的日志（写入面板缓冲区）。"""
    global _log_seq
    _log_seq += 1
    _log_buffer.append({
        "seq": _log_seq, "ts": time.time(), "level": level,
        "name": "launcher", "msg": msg,
    })


def write_startup_error(exc):
    """Persist fatal startup errors because pythonw has no visible stderr."""
    try:
        log_dir = Path(__file__).resolve().parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "startup_error.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            f.write(f"{type(exc).__name__}: {exc}\n")
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass


class PanelLogHandler(logging.Handler):
    """捕获日志到内存缓冲区"""
    def emit(self, record):
        global _log_seq
        try:
            _log_seq += 1
            _log_buffer.append({
                "seq": _log_seq,
                "ts": record.created,
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
            })
        except Exception:
            pass


def ensure_sqlite_database_dir(database_url):
    """Create the parent directory for file-based SQLite databases."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return

    database_path = url.database
    if not database_path or database_path == ":memory:":
        return

    db_file = Path(database_path)
    if not db_file.is_absolute():
        db_file = Path.cwd() / db_file

    db_file.parent.mkdir(parents=True, exist_ok=True)


def check_database_connection():
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            return False, "环境变量 DATABASE_URL 未配置"

        ensure_sqlite_database_dir(database_url)
        from app.utils.legacy_db import legacy_schema_reason

        async def test():
            engine = create_async_engine(database_url, echo=False)
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                    return await conn.run_sync(legacy_schema_reason)
            finally:
                await engine.dispose()
        legacy = asyncio.run(test())
        # 1.x 的旧库：启动画面直接说明，不启动后端（也就不会在旧库上建表）
        return (False, legacy) if legacy else (True, None)
    except Exception as e:
        return False, f"数据库连接失败：{e}"


def _data_dir() -> Path:
    """运行时可写目录下的 data（exe 旁 / backend 下，与 embedding 同一基准）。"""
    from app.utils.runtime_paths import runtime_base_dir
    return Path(runtime_base_dir()) / 'data'


def _app_url():
    return f"http://{_HOST}:{_PORT}"


def _load_app():
    from app.main import app

    # setup_logging() 会 clear 所有 handler，所以在 app 导入后重新挂载
    panel_handler = PanelLogHandler()
    panel_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(panel_handler)
    return app


def launch_server_once():
    """幂等启动后端服务（模型引导的任一分支完成后调用）；就绪后启动画面会自己进入主界面。"""
    global _server
    from desktop.server import BackendServer

    with _launch_lock:
        if _server is not None:
            return
        _server = BackendServer(_load_app, _HOST, _PORT)
        _server.start()
    if _server.wait(600):
        _panel_log("INFO", f"✅ 服务器已启动: {_server.url}")
    elif _server.error:
        _panel_log("ERROR", f"❌ 服务启动失败：{_server.error}")


def _latest_hint():
    """启动画面上的一行进度：最近一条 INFO 及以上的日志。"""
    for entry in reversed(list(_log_buffer)):
        if entry["level"] != "DEBUG":
            return entry["msg"][:120]
    return ""


def _status():
    from app import __version__

    started = bool(_server and _server.ready)
    return json.dumps({
        "started": started,
        "error": _startup_error or (_server.error if _server else None),
        "url": _app_url(),
        "log_count": len(_log_buffer),
        # 首启模型引导状态
        "model_required": _model_required,
        "model_busy": _model_busy,
        "hint": "" if started else _latest_hint(),
        "version": __version__,
    }, ensure_ascii=False)


class MainAPI:
    """主窗口（启动画面 → 主界面）可调用的 API；主界面只用到 open_logs（侧栏「运行日志」）。"""

    def get_status(self):
        return _status()

    def open_logs(self):
        open_logs_window()

    # ---- 首启模型引导：三选一 ----

    def download_model(self):
        """选项1：在线下载（多镜像依次尝试，约 470MB）。后台线程执行，不阻塞界面。"""
        global _model_busy, _model_worker_running
        if not _model_required:
            return json.dumps({"ok": False})
        if _model_worker_running:
            # 已有任务在跑（可能被"返回选择"隐藏过）：只恢复忙碌显示
            _model_busy = _model_busy or "正在在线下载模型（约 470MB）…"
            return json.dumps({"ok": True})
        _model_worker_running = True
        _model_busy = "正在在线下载模型（约 470MB）…"

        def worker():
            global _model_busy, _model_required, _model_worker_running
            try:
                from app.services.embedding_bootstrap import ensure_embedding_model
                ok = ensure_embedding_model(_panel_log)
            except Exception as e:
                _panel_log("ERROR", f"❌ 下载异常：{e}")
                ok = False
            _model_worker_running = False
            _model_busy = ""
            if ok:
                _model_required = False
                launch_server_once()
            else:
                _panel_log("WARNING", "可重新选择：在线下载 / 导入本地模型包 / 跳过")

        threading.Thread(target=worker, daemon=True).start()
        return json.dumps({"ok": True})

    def import_model_zip(self):
        """选项2：选择本地模型 zip（离线分发包）导入。"""
        global _model_busy, _model_worker_running
        if not _model_required or _model_worker_running:
            return json.dumps({"ok": False})

        import webview
        result = _main_window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("模型压缩包 (*.zip)",),
        )
        if not result:
            return json.dumps({"ok": False, "cancelled": True})
        zip_path = result[0] if isinstance(result, (list, tuple)) else str(result)

        _model_worker_running = True
        _model_busy = "正在导入本地模型包…"

        def worker():
            global _model_busy, _model_required, _model_worker_running
            try:
                from app.services.embedding_bootstrap import import_model_zip
                ok = import_model_zip(zip_path, _panel_log)
            except Exception as e:
                _panel_log("ERROR", f"❌ 导入异常：{e}")
                ok = False
            _model_worker_running = False
            _model_busy = ""
            if ok:
                _model_required = False
                launch_server_once()
            else:
                _panel_log("WARNING", "可重新选择：在线下载 / 导入本地模型包 / 跳过")

        threading.Thread(target=worker, daemon=True).start()
        return json.dumps({"ok": True})

    def cancel_model_wait(self):
        """「返回选择」：隐藏忙碌条回到三选一（后台任务不中断，成功仍会自动启动）。"""
        global _model_busy
        _model_busy = ""
        if _model_worker_running:
            _panel_log("INFO", "已返回选择界面；后台下载仍在继续，若成功会自动启动服务（也可改选导入/跳过）")
        return json.dumps({"ok": True})

    def skip_model(self):
        """选项3：跳过——以「无向量记忆」降级模式启动。"""
        global _model_required
        if not _model_required:
            return json.dumps({"ok": False})
        _model_required = False
        _panel_log("WARNING", "⚠️ 已跳过模型安装：语义检索/伏笔追踪等记忆功能不可用，其余功能正常")
        try:
            from app.services.embedding_bootstrap import EMBEDDING_PATH
            _panel_log("INFO", f"💡 之后可在此界面重开应用前放入模型，或将模型放到 {EMBEDDING_PATH} 后重启")
        except Exception:
            pass
        threading.Thread(target=launch_server_once, daemon=True).start()
        return json.dumps({"ok": True})


class LogsAPI:
    """运行日志窗口可调用的 API。"""

    def get_logs(self, after_seq=0):
        entries = [e for e in list(_log_buffer) if e["seq"] > after_seq]
        return json.dumps(entries[-100:], ensure_ascii=False)

    def get_status(self):
        return _status()

    def open_in_browser(self):
        """备用通道：用系统浏览器打开（浏览器里需要另外登录）。"""
        if _server and _server.ready:
            webbrowser.open(_app_url())


_main_api = MainAPI()


def open_logs_window():
    """运行日志窗口：已打开就切到前台，否则新建（关掉即销毁，重开时从缓冲区回放）。"""
    global _logs_window
    import webview
    from desktop import instance
    from desktop.pages import LOGS_HTML

    with _windows_lock:
        if _logs_window is not None and _logs_window in webview.windows:
            instance.bring_to_front(LOGS_TITLE)
            return
        _logs_window = webview.create_window(
            LOGS_TITLE, html=LOGS_HTML, js_api=LogsAPI(),
            width=900, height=560, min_size=(640, 380), text_select=True, background_color=_WINDOW_BG,
        )
        _logs_window.events.shown += apply_window_icon


def open_app_window(url):
    """同源的新窗口请求（target=_blank / window.open）：在应用里另开一个窗口，共享登录状态。"""
    import webview

    state = default_window_state(work_area())
    window = webview.create_window(
        APP_TITLE, url=url, js_api=_main_api,
        width=state.width, height=state.height, maximized=state.maximized, min_size=MIN_SIZE,
        text_select=True, zoomable=True, background_color=_WINDOW_BG,
    )
    window.events.shown += apply_window_icon


def _close_prompt():
    """关主窗口前要不要确认：运行中的 AI 任务 + 各应用窗口里未保存的修改。"""
    import webview
    from desktop.webview2 import page_has_unsaved

    running = 0
    if _server is not None and _server.ready:
        try:
            from app.services.ai_jobs import ai_jobs
            running = ai_jobs.running_count()
        except Exception as e:
            _panel_log("WARNING", f"统计运行中的 AI 任务失败: {e}")
    unsaved = any(page_has_unsaved(w) for w in list(webview.windows) if w is not _logs_window)
    return close_prompt(running, unsaved)


def show_main_window():
    from desktop.webview2 import show_window
    show_window(_main_window)


def _update_prefs(**changes):
    global _prefs
    _prefs = replace(_prefs, **changes)
    try:
        save_prefs(_data_dir() / 'desktop_settings.json', _prefs)
    except OSError as e:
        _panel_log("WARNING", f"桌面设置保存失败: {e}")


def _set_close_to_tray(enabled):
    _update_prefs(close_to_tray=enabled)
    _panel_log("INFO", f"关闭窗口时：{'最小化到托盘' if enabled else '退出程序'}")


def _on_hidden_to_tray():
    """点 × 收进托盘：第一次弹个通知，说明程序还在运行、怎么找回和退出。"""
    if not _prefs.tray_hint_shown:
        _tray.notify("文澜 AI 仍在运行", "已收到托盘，AI 任务会继续。单击托盘图标重新打开，右键托盘图标可以退出。")
        _update_prefs(tray_hint_shown=True)


def _on_main_close(state):
    """主窗口真正关闭时（UI 线程）：移除托盘图标、不再认领唤起请求、记住窗口尺寸 / 最大化。"""
    if _tray is not None:
        _tray.dispose()
    if _show_listener is not None:
        threading.Thread(target=_show_listener.close, daemon=True).start()
    if state is None:
        return
    try:
        save_window_state(_data_dir() / 'desktop_window.json', state)
    except OSError as e:
        _panel_log("WARNING", f"窗口尺寸保存失败: {e}")


def _close_other_windows():
    """主窗口关了，日志窗口和应用内新开的窗口一起关，进程才能退出。"""
    import webview

    for window in list(webview.windows):
        if window is not _main_window:
            try:
                window.destroy()
            except Exception:
                pass


def _bootstrap():
    """GUI 起来后的后台线程：缺模型就等用户在启动画面三选一，否则直接启动后端。"""
    global _model_required
    if _startup_error:
        return
    # 首启引导：embedding 模型不再内置于安装包（体积 -470MB）。
    # 缺失时不自动下载——启动画面给出三选一（在线下载 / 导入本地 zip / 跳过降级），
    # 由用户决定后再启动服务
    try:
        from app.services.embedding_bootstrap import model_present
        if model_present():
            _panel_log("INFO", "✅ AI 记忆模型已就绪")
        else:
            _model_required = True
            _panel_log("WARNING", "首次运行：缺少 AI 记忆模型，请在启动画面选择获取方式（在线下载 / 导入本地模型包 / 跳过）")
            return  # 等用户选择，选择后由 MainAPI 调 launch_server_once()
    except Exception as e:
        _panel_log("ERROR", f"模型检查异常（将降级运行）: {e}")

    launch_server_once()


def _show_signal_name():
    return f"Local\\WenlanAI.Desktop.Show.{_PORT}"


def _ensure_single_instance():
    """已经开着就让那个实例把主窗口叫出来（可能藏在托盘里）并返回 False。
    上个实例可能正在退出（窗口已关、后端还在收尾），等它一会儿。"""
    global _instance_mutex
    from desktop import instance
    from desktop.webview2 import message_box

    name = f"Local\\WenlanAI.Desktop.{_PORT}"
    _instance_mutex = instance.acquire(name)
    if _instance_mutex is not None:
        return True
    if instance.request_show(_show_signal_name()) or instance.bring_to_front(APP_TITLE):
        return False
    _instance_mutex = instance.acquire(name, wait=15)
    if _instance_mutex is not None:
        return True
    message_box("文澜 AI 已在运行，但没有找到它的窗口。\n请稍后再试，或在任务管理器里结束 WenlanAI 进程后重新打开。")
    return False


def main():
    import webview
    from desktop import instance
    from desktop.pages import SPLASH_HTML
    from desktop.tray import Tray
    from desktop.webview2 import (
        IDYES, MB_YESNO_WARNING, WEBVIEW2_DOWNLOAD_URL,
        configure, install_close_guard, message_box, webview2_available,
    )

    set_app_user_model_id()

    try:
        from config_loader import init_config
        init_config()
    except Exception as e:
        print(f"[WARN] 配置加载失败: {e}")

    global _HOST, _PORT, _main_window, _startup_error, _prefs, _tray, _show_listener
    _PORT = int(os.getenv('APP_PORT', '8000'))
    _HOST = '127.0.0.1'

    if not _ensure_single_instance():
        return

    if not webview2_available():
        answer = message_box(
            "没有检测到 Microsoft Edge WebView2 运行时（Windows 10/11 通常自带），文澜 AI 需要它来显示界面。\n\n"
            "是否现在打开下载页面？安装「常青引导程序」后重新打开文澜 AI 即可。",
            flags=MB_YESNO_WARNING,
        )
        if answer == IDYES:
            webbrowser.open(WEBVIEW2_DOWNLOAD_URL)
        return

    # 安装日志捕获器（启动阶段用，app 导入后会在 _load_app 中重新挂载）
    early_handler = PanelLogHandler()
    early_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(early_handler)

    # 检查数据库
    db_ok, db_error = check_database_connection()
    if not db_ok:
        _startup_error = db_error
        _panel_log("ERROR", db_error)

    configure(lambda url: same_origin(url, _app_url()), open_app_window)

    data_dir = _data_dir()
    _prefs = load_prefs(data_dir / 'desktop_settings.json')
    state = load_window_state(data_dir / 'desktop_window.json', work_area())
    _main_window = webview.create_window(
        APP_TITLE, html=SPLASH_HTML, js_api=_main_api,
        width=state.width, height=state.height, maximized=state.maximized, min_size=MIN_SIZE,
        text_select=True, zoomable=True, background_color=_WINDOW_BG,
    )
    _main_window.events.shown += apply_window_icon
    _main_window.events.closed += _close_other_windows
    request_quit = install_close_guard(
        _main_window, (state.width, state.height), _close_prompt, _on_main_close,
        close_to_tray=lambda: _prefs.close_to_tray, on_hide=_on_hidden_to_tray,
    )
    _tray = Tray(
        _ICON_PATH, on_show=show_main_window, on_logs=open_logs_window, on_quit=request_quit,
        close_to_tray=_prefs.close_to_tray, on_close_to_tray_changed=_set_close_to_tray,
    )
    _tray.attach(_main_window)
    _show_listener = instance.ShowListener(_show_signal_name(), show_main_window)

    # 独立的 WebView2 用户数据目录：登录状态、界面偏好跨次启动保留
    webview.start(_bootstrap, private_mode=False, storage_path=str(data_dir / 'webview'))

    # 窗口都关了：请求后端退出（停掉 AI 任务、关闭数据库），最多等 15 秒
    if _server is not None:
        _server.stop(15)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        write_startup_error(e)
        raise
    # 后端已优雅停止、窗口尺寸已保存。正常退出时 pythonnet 还要卸载 .NET 运行时（实测约 10 秒），
    # 这段时间进程仍在、重新打开会被单实例挡住干等；日志落盘后直接结束进程
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
