"""源码运行版的独立更新进程（仅标准库，不 import app.*，依赖坏了也能跑）。

由 update_service 以 detached 子进程启动：
    python -m app.services.update_runner --repo-root <dir> --branch <name> --status-file <json> [--python <exe>]

步骤：脏检查 → fetch + 计算变更文件 → git pull --ff-only → （requirements 变了）pip install -r
      → （frontend/ 变了）npm install（package.json / lock 变了才装）+ npm run build
进度实时写入 status-file（JSON，含 heartbeat）；uvicorn --reload 因代码变动重启服务也不影响本进程。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

OUTPUT_TAIL_LINES = 60
HEARTBEAT_SECONDS = 10

STEP_LABELS = {
    "git_pull": "拉取代码",
    "pip_install": "安装后端依赖",
    "npm_install": "安装前端依赖",
    "npm_build": "构建前端",
}
STEP_TIMEOUTS = {"git_pull": 600, "pip_install": 1800, "npm_install": 900, "npm_build": 900}

# (args, cwd, on_line, timeout) -> returncode
CommandRunner = Callable[[list, Path, Callable[[str], None], int], int]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _step(key: str, state: str = "pending", output: str = "") -> dict:
    return {"key": key, "label": STEP_LABELS[key], "state": state, "output": output}


def plan_steps(changed: list[str], npm_available: bool) -> list[dict]:
    """按远端变更文件决定要跑哪些步骤。没有 npm 时前端构建标记 skipped 并给手动命令。"""
    steps = [_step("git_pull")]
    if any(p in ("backend/requirements.txt", "requirements.txt") for p in changed):
        steps.append(_step("pip_install"))
    frontend = [p for p in changed if p.startswith("frontend/")]
    if frontend:
        if npm_available:
            if any(p in ("frontend/package.json", "frontend/package-lock.json") for p in frontend):
                steps.append(_step("npm_install"))
            steps.append(_step("npm_build"))
        else:
            steps.append(_step("npm_build", "skipped", "未检测到 npm，请手动执行：cd frontend && npm install && npm run build"))
    return steps


class RunnerState:
    """状态文件的唯一写入方；每次变更整体重写（先写临时文件再替换，读方不会读到半截）。"""

    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "mode": "source", "status": "idle", "steps": [], "progress": None, "message": None, "error": None,
            "restart_required": False, "started_at": None, "finished_at": None, "heartbeat": time.time(), "pid": os.getpid(),
        }
        self._lock = threading.Lock()

    def save(self) -> None:
        with self._lock:
            self.data["heartbeat"] = time.time()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def touch(self) -> None:
        self.save()

    def start(self, message: str) -> None:
        self.data.update(status="running", message=message, error=None, started_at=_now(), finished_at=None)
        self.save()

    def set_steps(self, steps: list[dict]) -> None:
        self.data["steps"] = steps
        self.save()

    def _find(self, key: str) -> dict:
        return next(s for s in self.data["steps"] if s["key"] == key)

    def step_running(self, key: str) -> None:
        step = self._find(key)
        step["state"] = "running"
        self.data["message"] = f"正在{step['label']}…"
        self.save()

    def step_output(self, key: str, line: str) -> None:
        step = self._find(key)
        lines = step["output"].splitlines() if step["output"] else []
        lines.append(line.rstrip("\r\n"))
        step["output"] = "\n".join(lines[-OUTPUT_TAIL_LINES:])
        self.save()

    def step_done(self, key: str, state: str) -> None:
        self._find(key)["state"] = state
        self.save()

    def finish_success(self, message: str) -> None:
        self.data.update(status="success", message=message, restart_required=True, finished_at=_now())
        self.save()

    def fail(self, error: str) -> None:
        self.data.update(status="failed", error=error, message=None, finished_at=_now())
        self.save()


@dataclass
class UpdateContext:
    repo_root: Path
    branch: str
    status_file: Path
    python: str
    npm: Optional[str]          # npm 可执行文件路径；None = 未安装


def run_command(args: list, cwd: Path, on_line: Callable[[str], None], timeout: int) -> int:
    """执行命令并逐行回传输出；超时 kill 并返回 124。"""
    proc = subprocess.Popen(
        [str(a) for a in args], cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "PYTHONUTF8": "1", "CI": "1"},
    )
    deadline = time.monotonic() + timeout
    assert proc.stdout is not None
    for line in proc.stdout:
        on_line(line)
        if time.monotonic() > deadline:
            proc.kill()
            on_line(f"[超时 {timeout}s，已终止]")
            proc.wait()
            return 124
    return proc.wait()


class _Heartbeat:
    """长时间无输出的步骤（pip 下载大包）也要定期刷心跳，避免被读方判为失联。"""

    def __init__(self, state: RunnerState):
        self.state = state
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                self.state.touch()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        return False


def _dirty_tracked(porcelain: str) -> bool:
    return any(line and not line.startswith("??") for line in porcelain.splitlines())


def run_update(ctx: UpdateContext, run_command: CommandRunner = run_command) -> bool:
    state = RunnerState(ctx.status_file)
    state.start("正在检查工作区…")
    collected: list[str] = []

    def collect(line: str) -> None:
        collected.append(line.rstrip("\r\n"))

    def git(*args: str, timeout: int = 120) -> tuple[int, str]:
        collected.clear()
        code = run_command(["git", *args], ctx.repo_root, collect, timeout)
        return code, "\n".join(collected)

    try:
        with _Heartbeat(state):
            code, out = git("status", "--porcelain")
            if code != 0:
                state.fail(f"git status 失败：{out[-300:]}")
                return False
            if _dirty_tracked(out):
                state.fail("工作区有未提交的修改，已放弃更新：请先提交或还原改动（git stash）后重试")
                return False

            code, out = git("fetch", "--quiet", "origin", timeout=300)
            if code != 0:
                state.fail(f"git fetch 失败：{out[-300:]}")
                return False
            code, out = git("diff", "--name-only", f"HEAD..origin/{ctx.branch}")
            changed = [p.strip() for p in out.splitlines() if p.strip()] if code == 0 else []

            steps = plan_steps(changed, ctx.npm is not None)
            state.set_steps(steps)

            commands = {
                "git_pull": (["git", "pull", "--ff-only", "origin", ctx.branch], ctx.repo_root),
                "pip_install": ([ctx.python, "-m", "pip", "install", "-r", str(ctx.repo_root / "backend" / "requirements.txt")], ctx.repo_root),
                "npm_install": ([ctx.npm or "npm", "install"], ctx.repo_root / "frontend"),
                "npm_build": ([ctx.npm or "npm", "run", "build"], ctx.repo_root / "frontend"),
            }
            for step in steps:
                if step["state"] == "skipped":
                    continue
                key = step["key"]
                args, cwd = commands[key]
                state.step_running(key)
                code = run_command(args, cwd, lambda line, k=key: state.step_output(k, line), STEP_TIMEOUTS[key])
                if code != 0:
                    state.step_done(key, "failed")
                    state.fail(f"{STEP_LABELS[key]}失败（退出码 {code}），详见该步骤输出；可停止服务后手动重跑对应命令")
                    return False
                state.step_done(key, "success")

        skipped = [s for s in steps if s["state"] == "skipped"]
        message = "更新完成，请重启后端服务以加载新代码。"
        if skipped:
            message += " 注意：未检测到 npm，前端未重新构建，请手动执行 cd frontend && npm install && npm run build。"
        state.finish_success(message)
        return True
    except Exception as exc:  # noqa: BLE001
        state.fail(f"更新进程异常：{exc}")
        return False


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="WenlanAI 源码更新进程")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--branch", default="master")
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--python", default=sys.executable)
    ns = parser.parse_args(argv)
    ctx = UpdateContext(
        repo_root=Path(ns.repo_root), branch=ns.branch, status_file=Path(ns.status_file),
        python=ns.python, npm=shutil.which("npm"),
    )
    return 0 if run_update(ctx) else 1


if __name__ == "__main__":
    sys.exit(main())
