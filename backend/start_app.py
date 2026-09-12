"""应用启动脚本 - pywebview 启动面板 + 主应用窗口"""
import sys
import os
import time
import threading
import asyncio
import json
import logging
import traceback
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

_server_thread = None
_server_started = threading.Event()
_server_error = None

# 日志缓冲区（供启动面板显示）
_log_buffer: deque = deque(maxlen=500)
_log_seq = 0

# ---- 首启模型引导状态（embedding 模型不再内置于安装包）----
_HOST = '127.0.0.1'
_PORT = 8000
_model_required = False        # True = 等待用户选择（下载/导入/跳过）
_model_busy = ""               # 非空 = 正在下载/导入（面板显示忙碌文案）
_model_worker_running = False  # 防止重复起下载/导入线程
_server_launched = False
_launch_lock = threading.Lock()

# 品牌图标（scripts/make_icon.py 由 frontend/public/logo.svg 生成）：
# 打包后位于 exe 旁的 _internal/assets，开发环境位于 backend/assets
_RESOURCE_DIR = (Path(sys.executable).parent / '_internal') if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
_ICON_PATH = _RESOURCE_DIR / 'assets' / 'app.ico'


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


def launch_server_once():
    """幂等启动后端服务（模型引导的任一分支完成后调用）。"""
    global _server_launched
    with _launch_lock:
        if _server_launched:
            return
        _server_launched = True
    ok, err = start_server_thread(_HOST, _PORT)
    if ok:
        _panel_log("INFO", f"✅ 服务器已启动: http://{_HOST}:{_PORT}")


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

        async def test():
            engine = create_async_engine(database_url, echo=False)
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
        asyncio.run(test())
        return True, None
    except Exception as e:
        return False, f"数据库连接失败：{e}"


def run_server(host, port):
    global _server_error
    try:
        import uvicorn
        from app.main import app

        # setup_logging() 会 clear 所有 handler，所以在 app 导入后重新挂载
        panel_handler = PanelLogHandler()
        panel_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(panel_handler)

        config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
        server = uvicorn.Server(config)
        _server_started.set()
        server.run()
    except Exception as e:
        _server_error = str(e)
        _server_started.set()


def start_server_thread(host='127.0.0.1', port=8000):
    global _server_thread
    _server_thread = threading.Thread(target=run_server, args=(host, port), daemon=True)
    _server_thread.start()
    _server_started.wait(timeout=30)
    if _server_error:
        return False, _server_error
    time.sleep(1)
    return True, None


class PanelAPI:
    """pywebview JavaScript 可调用的 API"""

    def get_logs(self, after_seq=0):
        entries = [e for e in _log_buffer if e["seq"] > after_seq]
        return json.dumps(entries[-100:], ensure_ascii=False)

    def open_app(self):
        import webbrowser
        port = int(os.getenv('APP_PORT', '8000'))
        webbrowser.open(f"http://127.0.0.1:{port}")

    def get_status(self):
        return json.dumps({
            "started": _server_started.is_set(),
            "error": _server_error,
            "url": f"http://{_HOST}:{_PORT}",
            "log_count": len(_log_buffer),
            # 首启模型引导状态
            "model_required": _model_required,
            "model_busy": _model_busy,
        }, ensure_ascii=False)

    # ---- 首启模型引导：三选一 ----

    def download_model(self):
        """选项1：在线下载（多镜像依次尝试，约 470MB）。后台线程执行，不阻塞面板。"""
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
        window = webview.windows[0]
        result = window.create_file_dialog(
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
        launch_server_once()
        return json.dumps({"ok": True})


# 面板样式与前端设计系统保持一致（frontend/src/globals.css、tailwind.config.js、BrandLogo.tsx）：
# 浅色玻璃质感、品牌蓝 #007aff、全局零圆角、Inter/Segoe/苹方/雅黑字体栈、lucide 线性图标
PANEL_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>文澜 AI - 启动控制台</title>
<style>
:root {
  --brand:#007aff; --brand-600:#0070eb;
  --surface:#f6f9fd; --border:#d9e4f3; --border-light:#e8eff8;
  --content:#0b1a33; --content-2:#5f7090; --content-3:#93a4be;
  --gold-50:#fff7e8; --gold-200:#ffd891; --gold-400:#dd9137; --gold-500:#bb7123;
  --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --mono: "Cascadia Code", "JetBrains Mono", Consolas, "Microsoft YaHei", monospace;
}
* { margin:0; padding:0; box-sizing:border-box; border-radius:0 !important; }
html, body { height:100%; }
body {
  font-family: var(--sans); color: var(--content); background-color: var(--surface);
  background-image:
    radial-gradient(ellipse 55% 45% at 10% 5%, rgba(0,122,255,.12), transparent 70%),
    radial-gradient(ellipse 50% 45% at 90% 95%, rgba(96,170,255,.14), transparent 70%),
    linear-gradient(180deg, #f6f9fd 0%, #eaf1fb 100%);
  display:flex; flex-direction:column; overflow:hidden; -webkit-font-smoothing:antialiased;
}
button, input, select { font:inherit; color:inherit; transition: color .2s ease, background-color .2s ease, border-color .2s ease, box-shadow .2s ease, transform .2s ease; }
button { cursor:pointer; border:0; background:none; -webkit-tap-highlight-color:transparent; }
::selection { background: rgba(0,122,255,.18); }
::-webkit-scrollbar { width:8px; height:8px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background: rgba(95,112,144,.28); }
::-webkit-scrollbar-thumb:hover { background: rgba(95,112,144,.45); }
.i { width:16px; height:16px; flex-shrink:0; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }

/* 玻璃面板 / 卡片（对应 .hh-glass / .hh-panel） */
.glass {
  position:relative; border:1px solid rgba(255,255,255,.78);
  background: linear-gradient(160deg, rgba(255,255,255,.74) 0%, rgba(255,255,255,.5) 100%);
  -webkit-backdrop-filter: blur(24px) saturate(1.5); backdrop-filter: blur(24px) saturate(1.5);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.95), 0 0 0 1px rgba(15,43,96,.05), 0 30px 80px -36px rgba(15,43,96,.35);
}
.panel {
  position:relative; border:1px solid rgba(255,255,255,.85);
  background: linear-gradient(160deg, rgba(255,255,255,.9) 0%, rgba(255,255,255,.72) 100%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.95), 0 0 0 1px rgba(15,43,96,.04), 0 18px 40px -28px rgba(15,43,96,.28);
}

/* 顶栏 */
.header { height:64px; flex-shrink:0; display:flex; align-items:center; gap:14px; padding:0 20px; border-width:0 0 1px 0; }
.logo {
  position:relative; width:40px; height:40px; flex-shrink:0; display:inline-flex; align-items:center; justify-content:center; overflow:hidden; color:#fff;
  background: linear-gradient(to bottom right, #007aff, #3a95ff, #8ec3ff); box-shadow: 0 12px 28px -12px rgba(0,122,255,.6);
}
.logo::before { content:""; position:absolute; inset:0; background: radial-gradient(circle at top left, rgba(255,255,255,.34), transparent 34%); }
.logo svg { position:relative; width:66%; height:66%; }
.brand { flex:1; min-width:0; }
.eyebrow { display:block; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.22em; color:var(--brand); line-height:1; }
.title { margin-top:5px; font-size:16px; font-weight:600; letter-spacing:-.01em; line-height:1.2; color:var(--content); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

/* 按钮（对应 .hh-btn-primary / -secondary / -ghost） */
.btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; height:36px; padding:0 14px; font-size:13px; font-weight:500; white-space:nowrap; }
.btn:disabled { cursor:not-allowed; opacity:.6; }
.btn .i { width:15px; height:15px; }
.btn-primary { background:var(--brand); color:#fff; box-shadow: 0 12px 28px -12px rgba(0,122,255,.55); }
.btn-primary:hover { background:var(--brand-600); }
.btn-primary:active { transform: scale(.98); }
.btn-secondary { border:1px solid var(--border); background: rgba(255,255,255,.7); color:var(--content); box-shadow: 0 1px 2px rgba(15,43,96,.04); }
.btn-secondary:hover { border-color: rgba(0,122,255,.4); background:#fff; }
.btn-ghost { padding:0 10px; color:var(--content-2); }
.btn-ghost:hover { background: rgba(0,122,255,.05); color:var(--content); }
.header .btn-primary { height:40px; padding:0 18px; font-size:14px; }

/* 内容区：工具栏 + 日志 合为一张卡片 */
.main { flex:1; min-height:0; display:flex; flex-direction:column; padding:12px 12px 0; }
.card { flex:1; min-height:0; display:flex; flex-direction:column; }
.toolbar { display:flex; align-items:center; gap:8px; padding:10px 12px; border-bottom:1px solid var(--border-light); flex-shrink:0; }
.field { position:relative; flex:1; min-width:140px; max-width:280px; }
.field .i, .select .i { position:absolute; top:50%; transform:translateY(-50%); color:var(--content-3); pointer-events:none; }
.field .i { left:10px; }
.select { position:relative; }
.select .i { right:9px; width:14px; height:14px; }
.field input, .select select {
  height:36px; font-size:13px; border:1px solid var(--border); background: rgba(255,255,255,.65); color:var(--content);
  box-shadow: 0 1px 2px rgba(15,43,96,.04); outline:none;
}
.field input { width:100%; padding:0 10px 0 32px; }
.field input::placeholder { color:var(--content-3); }
.select select { padding:0 30px 0 10px; appearance:none; -webkit-appearance:none; cursor:pointer; }
.field input:focus, .select select:focus { border-color:var(--brand); background: rgba(255,255,255,.95); box-shadow: 0 0 0 4px rgba(0,122,255,.16); }
.count { margin-left:auto; font-size:12px; color:var(--content-3); white-space:nowrap; font-variant-numeric: tabular-nums; }
.count b { font-weight:500; color:var(--content-2); }

/* 首启模型引导条（gold 警示色板） */
.model-bar { display:none; flex-shrink:0; align-items:center; gap:8px; flex-wrap:wrap; padding:10px 12px; border-bottom:1px solid var(--gold-200); background:var(--gold-50); color:var(--gold-500); font-size:13px; }
.model-bar.show { display:flex; }
.model-bar .lead { display:inline-flex; align-items:center; gap:8px; margin-right:auto; padding-right:8px; }
.model-bar .lead .i { color:var(--gold-400); }
.model-bar .btn { height:32px; font-size:12.5px; padding:0 12px; }
.model-bar .btn-ghost { color:var(--gold-500); }
.model-bar .btn-ghost:hover { background: rgba(187,113,35,.08); color:var(--gold-500); }

/* 日志列表 */
#logs { flex:1; min-height:0; overflow-y:auto; font-family:var(--mono); font-size:12px; line-height:1.75; }
.log-line { display:flex; align-items:baseline; gap:10px; padding:1px 12px; }
.log-line:first-child { margin-top:6px; }
.log-line:last-child { margin-bottom:6px; }
.log-line:hover { background: rgba(0,122,255,.04); }
.log-line.is-WARNING { background: rgba(217,119,6,.04); }
.log-line.is-ERROR, .log-line.is-CRITICAL { background: rgba(220,38,38,.04); }
.ts { flex-shrink:0; color:var(--content-3); user-select:none; font-variant-numeric: tabular-nums; }
.lv { flex-shrink:0; align-self:center; width:62px; text-align:center; font-family:var(--sans); font-size:10px; font-weight:600; letter-spacing:.06em; line-height:16px; user-select:none; }
.lv-DEBUG { color:var(--content-3); background: rgba(147,164,190,.12); }
.lv-INFO { color:#16a34a; background: rgba(22,163,74,.08); }
.lv-WARNING { color:#d97706; background: rgba(217,119,6,.10); }
.lv-ERROR { color:#dc2626; background: rgba(220,38,38,.08); }
.lv-CRITICAL { color:#7c3aed; background: rgba(124,58,237,.08); }
.mod { flex-shrink:0; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--content-2); user-select:none; }
.msg { color:var(--content); word-break:break-all; }
.is-DEBUG .msg { color:var(--content-2); }
.empty { height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; font-family:var(--sans); font-size:13px; color:var(--content-3); }
.empty .i { width:22px; height:22px; color:var(--brand); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 底部状态栏 */
.status { height:40px; flex-shrink:0; display:flex; align-items:center; gap:10px; margin-top:12px; padding:0 16px; font-size:12px; color:var(--content-2); border-width:1px 0 0 0; }
.dot { width:8px; height:8px; flex-shrink:0; }
.dot-ok { background:#16a34a; box-shadow: 0 0 0 3px rgba(22,163,74,.15); }
.dot-err { background:#dc2626; box-shadow: 0 0 0 3px rgba(220,38,38,.15); }
.dot-loading { background:var(--gold-400); box-shadow: 0 0 0 3px rgba(221,145,55,.18); animation: blink 1.2s ease-in-out infinite; }
@keyframes blink { 50% { opacity:.35; } }
.status .url { margin-left:auto; font-family:var(--mono); font-size:11.5px; color:var(--content-3); }
</style>
</head>
<body>
<svg style="display:none" xmlns="http://www.w3.org/2000/svg">
  <symbol id="ic-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></symbol>
  <symbol id="ic-chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>
  <symbol id="ic-pause" viewBox="0 0 24 24"><rect x="14" y="4" width="4" height="16"/><rect x="6" y="4" width="4" height="16"/></symbol>
  <symbol id="ic-play" viewBox="0 0 24 24"><polygon points="6 3 20 12 6 21 6 3"/></symbol>
  <symbol id="ic-trash" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></symbol>
  <symbol id="ic-arrow" viewBox="0 0 24 24"><path d="M7 7h10v10"/><path d="M7 17 17 7"/></symbol>
  <symbol id="ic-loader" viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></symbol>
  <symbol id="ic-alert" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></symbol>
  <symbol id="ic-download" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></symbol>
  <symbol id="ic-folder" viewBox="0 0 24 24"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></symbol>
  <symbol id="ic-skip" viewBox="0 0 24 24"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" x2="19" y1="5" y2="19"/></symbol>
  <symbol id="ic-back" viewBox="0 0 24 24"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></symbol>
  <symbol id="ic-inbox" viewBox="0 0 24 24"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></symbol>
</svg>

<header class="header glass">
  <span class="logo" aria-hidden="true">
    <svg viewBox="0 0 256 256" fill="none">
      <defs>
        <mask id="logo-not-stroke" maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">
          <rect width="256" height="256" fill="#fff"/>
          <path d="M74 156C100 132 118 158 136 136C154 114 176 90 212 60" stroke="#000" stroke-width="16" stroke-linecap="round"/>
        </mask>
        <mask id="logo-not-pages" maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">
          <rect width="256" height="256" fill="#fff"/>
          <path d="M48 84C76 72 104 76 122 94V196C104 178 76 174 48 186ZM208 84C180 72 152 76 134 94V196C152 178 180 174 208 186Z" fill="#000"/>
        </mask>
      </defs>
      <path d="M48 84C76 72 104 76 122 94V196C104 178 76 174 48 186ZM208 84C180 72 152 76 134 94V196C152 178 180 174 208 186Z" fill="currentColor" mask="url(#logo-not-stroke)"/>
      <path d="M74 156C100 132 118 158 136 136C154 114 176 90 212 60" stroke="currentColor" stroke-width="16" stroke-linecap="round" mask="url(#logo-not-pages)"/>
    </svg>
  </span>
  <div class="brand">
    <span class="eyebrow">启动控制台</span>
    <h1 class="title">文澜 AI</h1>
  </div>
  <button class="btn btn-primary" onclick="openApp()">进入应用<svg class="i"><use href="#ic-arrow"/></svg></button>
</header>

<main class="main">
  <section class="card panel">
    <div class="toolbar">
      <label class="field">
        <svg class="i"><use href="#ic-search"/></svg>
        <input id="search" placeholder="筛选运行日志…" oninput="render()" spellcheck="false">
      </label>
      <span class="select">
        <select id="levelFilter" onchange="render()">
          <option value="">全部级别</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <svg class="i"><use href="#ic-chevron"/></svg>
      </span>
      <button class="btn btn-secondary" id="pauseBtn" onclick="togglePause()"><svg class="i"><use href="#ic-pause"/></svg><span>暂停刷新</span></button>
      <button class="btn btn-secondary" onclick="allLogs=[];render()"><svg class="i"><use href="#ic-trash"/></svg>清空列表</button>
      <span class="count" id="logCount">0 条</span>
    </div>

    <div class="model-bar" id="modelBar">
      <div id="modelChoice" style="display:contents">
        <span class="lead"><svg class="i"><use href="#ic-alert"/></svg>首次运行：缺少 AI 记忆模型（约 470MB），请选择获取方式</span>
        <button class="btn btn-primary" onclick="dlModel()"><svg class="i"><use href="#ic-download"/></svg>在线下载</button>
        <button class="btn btn-secondary" onclick="importModel()"><svg class="i"><use href="#ic-folder"/></svg>导入本地模型包 (zip)</button>
        <button class="btn btn-ghost" onclick="skipModel()"><svg class="i"><use href="#ic-skip"/></svg>跳过（无记忆模式）</button>
      </div>
      <div id="modelBusy" style="display:none">
        <span class="lead"><svg class="i spin"><use href="#ic-loader"/></svg><span id="modelBusyText">处理中…</span>（进度见下方日志）</span>
        <button class="btn btn-ghost" onclick="cancelModelWait()"><svg class="i"><use href="#ic-back"/></svg>返回选择</button>
      </div>
    </div>

    <div id="logs"><div class="empty"><svg class="i spin"><use href="#ic-loader"/></svg>正在初始化，请稍候…</div></div>
  </section>
</main>

<footer class="status glass">
  <span class="dot dot-loading" id="statusDot"></span>
  <span id="statusText">正在启动服务…</span>
  <span class="url" id="statusUrl"></span>
</footer>

<script>
let allLogs = [], lastSeq = 0, paused = false, autoScroll = true;
const logsEl = document.getElementById('logs');
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const icon = (name, cls) => '<svg class="i' + (cls ? ' ' + cls : '') + '"><use href="#' + name + '"/></svg>';

function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.toTimeString().slice(0,8) + '.' + String(d.getMilliseconds()).padStart(3,'0');
}

function render() {
  const q = $('search').value.toLowerCase();
  const lv = $('levelFilter').value;
  const filtered = allLogs.filter(e => {
    if (lv && e.level !== lv) return false;
    if (q && !e.msg.toLowerCase().includes(q) && !e.name.toLowerCase().includes(q)) return false;
    return true;
  });
  $('logCount').innerHTML = '<b>' + filtered.length + '</b> / ' + allLogs.length + ' 条';
  if (filtered.length === 0) {
    logsEl.innerHTML = allLogs.length === 0
      ? '<div class="empty">' + icon('ic-loader', 'spin') + '等待日志输出…</div>'
      : '<div class="empty">' + icon('ic-inbox') + '没有匹配的日志记录</div>';
    return;
  }
  logsEl.innerHTML = filtered.slice(-500).map(e =>
    '<div class="log-line is-' + e.level + '">' +
    '<span class="ts">' + formatTime(e.ts) + '</span>' +
    '<span class="lv lv-' + e.level + '">' + e.level + '</span>' +
    '<span class="mod" title="' + esc(e.name) + '">' + esc(e.name) + '</span>' +
    '<span class="msg">' + esc(e.msg) + '</span>' +
    '</div>'
  ).join('');
  if (autoScroll) logsEl.scrollTop = logsEl.scrollHeight;
}

logsEl.addEventListener('scroll', () => {
  autoScroll = logsEl.scrollHeight - logsEl.scrollTop - logsEl.clientHeight < 40;
});

function togglePause() {
  paused = !paused;
  $('pauseBtn').innerHTML = paused
    ? icon('ic-play') + '<span>继续刷新</span>'
    : icon('ic-pause') + '<span>暂停刷新</span>';
}

async function poll() {
  if (paused) return;
  try {
    const raw = await pywebview.api.get_logs(lastSeq);
    const entries = JSON.parse(raw);
    if (entries.length > 0) {
      lastSeq = entries[entries.length - 1].seq;
      allLogs.push(...entries);
      if (allLogs.length > 2000) allLogs = allLogs.slice(-2000);
      render();
    }
  } catch(e) {}

  try {
    const raw = await pywebview.api.get_status();
    const st = JSON.parse(raw);
    const dot = $('statusDot'), txt = $('statusText');
    if (st.error) {
      dot.className = 'dot dot-err';
      txt.textContent = '服务启动失败：' + st.error;
    } else if (st.started) {
      dot.className = 'dot dot-ok';
      txt.textContent = '服务运行中';
    } else if (st.model_required || st.model_busy) {
      dot.className = 'dot dot-loading';
      txt.textContent = st.model_busy ? st.model_busy : '等待选择 AI 记忆模型获取方式…';
    }
    $('statusUrl').textContent = st.started && st.url ? st.url : '';
    // 首启模型引导条显隐
    const bar = $('modelBar'), choice = $('modelChoice'), busy = $('modelBusy');
    bar.classList.toggle('show', !!(st.model_busy || st.model_required));
    choice.style.display = st.model_busy ? 'none' : 'contents';
    busy.style.display = st.model_busy ? 'contents' : 'none';
    if (st.model_busy) $('modelBusyText').textContent = st.model_busy;
  } catch(e) {}
}

async function openApp() {
  try { await pywebview.api.open_app(); } catch(e) {}
}

async function dlModel() {
  try { await pywebview.api.download_model(); } catch(e) {}
}
async function importModel() {
  try { await pywebview.api.import_model_zip(); } catch(e) {}
}
async function skipModel() {
  try { await pywebview.api.skip_model(); } catch(e) {}
}
async function cancelModelWait() {
  try { await pywebview.api.cancel_model_wait(); } catch(e) {}
}

setInterval(poll, 1000);
setTimeout(poll, 500);
</script>
</body>
</html>"""


def main():
    import webview

    set_app_user_model_id()

    try:
        from config_loader import init_config
        init_config()
    except Exception as e:
        print(f"[WARN] 配置加载失败: {e}")

    # 安装日志捕获器（启动阶段用，app 导入后会在 run_server 中重新挂载）
    early_handler = PanelLogHandler()
    early_handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(early_handler)

    # 检查数据库
    db_ok, db_error = check_database_connection()
    if not db_ok:
        _log_buffer.append({"seq": 1, "ts": time.time(), "level": "ERROR", "name": "launcher", "msg": db_error})

    global _HOST, _PORT
    _PORT = int(os.getenv('APP_PORT', '8000'))
    _HOST = '127.0.0.1'

    # 创建控制面板窗口
    api = PanelAPI()
    panel = webview.create_window(
        title='文澜 AI - 启动控制台',
        html=PANEL_HTML,
        width=900,
        height=550,
        min_size=(700, 400),
        resizable=True,
        background_color='#f6f9fd',
        js_api=api,
    )

    def on_loaded():
        global _model_required
        if not db_ok:
            return
        # 首启引导：embedding 模型不再内置于安装包（体积 -470MB）。
        # 缺失时不自动下载——面板给出三选一（在线下载 / 导入本地 zip / 跳过降级），
        # 由用户决定后再启动服务
        try:
            from app.services.embedding_bootstrap import model_present
            if model_present():
                _panel_log("INFO", "✅ AI 记忆模型已就绪")
            else:
                _model_required = True
                _panel_log("WARNING", "首次运行：缺少 AI 记忆模型，请在上方选择获取方式（在线下载 / 导入本地模型包 / 跳过）")
                return  # 等用户选择，选择后由 PanelAPI 调 launch_server_once()
        except Exception as e:
            _panel_log("ERROR", f"模型检查异常（将降级运行）: {e}")

        launch_server_once()

    panel.events.shown += apply_window_icon
    panel.events.loaded += on_loaded

    webview.start(debug=False, private_mode=False)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        write_startup_error(e)
        raise
