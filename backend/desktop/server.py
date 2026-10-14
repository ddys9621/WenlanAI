"""后端（uvicorn）线程：lifespan 跑完、端口真正在监听才算就绪；关窗后请求退出并等它收尾。"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from desktop.shell import port_in_use


def port_taken_message(port: int) -> str:
    return (
        f"端口 {port} 已被占用：可能有其他程序（或旧版文澜 AI）正在使用它。"
        f"请关闭占用的程序后重新打开，或在 config.ini 的 [app] 段把 port 改成其他端口。"
    )


class BackendServer:
    def __init__(self, load_app: Callable[[], Any], host: str, port: int):
        self._load_app = load_app
        self.host = host
        self.port = port
        self._server = None  # uvicorn.Server，应用加载完才创建
        self._error: Optional[str] = None
        self._stopping = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def ready(self) -> bool:
        server = self._server
        return bool(server is not None and server.started and not server.should_exit and self.running)

    @property
    def error(self) -> Optional[str]:
        return self._error

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="wenlan-backend", daemon=True)
        self._thread.start()

    def wait(self, timeout: float) -> bool:
        """就绪返回 True；出错、线程已结束或超时返回 False。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ready:
                return True
            if self._error or not self.running:
                return False
            time.sleep(0.05)
        return self.ready

    def stop(self, timeout: float = 15.0) -> None:
        """请求退出（lifespan shutdown 会停掉 AI 任务、关闭数据库），最多等 timeout 秒。
        应用还在导入时没有要收尾的东西，不等它导入完（线程看到 _stopping 就不再启动服务）。"""
        self._stopping.set()
        server = self._server
        if server is None:
            return
        server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            if port_in_use(self.host, self.port):
                self._error = port_taken_message(self.port)
                return
            app = self._load_app()
            if self._stopping.is_set():
                return
            import uvicorn

            # log_config=None：不另起一套 stderr 日志，uvicorn 的日志冒泡到根 logger，运行日志窗口和 app.log 都看得到
            config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info", access_log=False, log_config=None)
            self._server = uvicorn.Server(config)
            if self._stopping.is_set():  # stop() 恰好发生在创建 Server 之前
                return
            self._server.run()
            if not self._server.started and not self._stopping.is_set():
                self._error = "服务未能启动，详见运行日志"
        except SystemExit:  # uvicorn 绑定端口失败时 sys.exit(1)
            self._error = port_taken_message(self.port)
        except BaseException as exc:  # noqa: BLE001 - 线程里的任何异常都要变成界面上的错误
            self._error = f"{type(exc).__name__}: {exc}"
