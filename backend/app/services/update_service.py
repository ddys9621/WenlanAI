"""检查更新 / 应用更新 —— 三种运行形态：exe（Windows 安装版）/ docker / source（源码运行）。

- 更新源：GitHub Releases（settings.update_repo），tag `v*`，安装包资产 `WenlanAI-Setup-v{ver}.exe`（更新器按 .exe 后缀挑资产，名称仅示意）
- exe：下载安装包到临时目录 → 启动安装向导 → 应用自退出（安装结束页可勾选启动新版本）
- source：git pull / pip / npm 交给独立进程 `app.services.update_runner` 跑（uvicorn --reload 或服务重启都不打断），
  进度写在 data/update_job.json，本模块只负责启动它和读状态
- docker：镜像内没有 .git 也不能自更新，只给出 host 上要执行的命令

检查结果缓存 CHECK_CACHE_SECONDS，force=True 绕过。GitHub 不可达不会抛错：返回当前版本 + error 文案。
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx

from app.logger import get_logger

logger = get_logger(__name__)

CHECK_CACHE_SECONDS = 600
GITHUB_API = "https://api.github.com"
RUNNER_STALE_SECONDS = 180          # 独立更新进程心跳超时：超过视为异常退出
_EXIT_DELAY_SECONDS = 2.0           # exe：启动安装程序后等响应发完再退出
_PROCESS_STARTED_AT = time.time()   # 本进程启动时刻：早于它结束的源码更新任务已经"重启过了"，不再显示


class UpdateSourceError(Exception):
    """更新源（GitHub）不可用：限流 / 网络 / 无 Release。给用户看的文案。"""


class UpdateNotApplicable(Exception):
    """当前状态不能一键更新（无新版本 / docker / 工作区脏 …）。"""


class UpdateBusy(Exception):
    """已有更新任务在跑。"""


# ---------------- 运行模式 / 版本 ----------------

def detect_run_mode(
    *, frozen: Optional[bool] = None, environ: Optional[dict] = None, dockerenv: Path = Path("/.dockerenv")
) -> str:
    """exe（PyInstaller sys.frozen）> docker（MUMU_RUN_MODE=docker 或 /.dockerenv）> source。"""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return "exe"
    env = os.environ if environ is None else environ
    if (env.get("MUMU_RUN_MODE") or "").strip().lower() == "docker":
        return "docker"
    if dockerenv.exists():
        return "docker"
    return "source"


def parse_version(text: Any) -> tuple[int, ...]:
    """'v1.2.3' / '1.2.3-beta' / '0.0.0-f320acc' → (1,2,3)；无法解析 → (0,)。"""
    if not text:
        return (0,)
    core = str(text).strip().lstrip("vV").split("-")[0].split("+")[0]
    parts: list[int] = []
    for piece in core.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts) or (0,)


def is_newer(latest: Any, current: Any) -> bool:
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


# ---------------- 数据 ----------------

@dataclass
class ReleaseInfo:
    version: str
    tag: str
    name: str
    notes: str
    published_at: Optional[str]
    html_url: str
    installer_url: Optional[str]
    installer_name: Optional[str]
    installer_size: Optional[int]


@dataclass
class GitInfo:
    available: bool
    branch: Optional[str] = None
    commit: Optional[str] = None
    remote_commit: Optional[str] = None
    ahead: int = 0
    behind: int = 0
    commits: list[dict[str, str]] = field(default_factory=list)
    changed_files: int = 0
    backend_deps_changed: bool = False
    frontend_changed: bool = False
    dirty: bool = False
    error: Optional[str] = None


@dataclass
class UpdateCheckResult:
    enabled: bool
    run_mode: str
    current_version: str
    latest: Optional[ReleaseInfo]
    has_update: bool
    git: Optional[GitInfo]
    can_apply: bool
    apply_hint: str
    checked_at: Optional[str]
    cached: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ---------------- GitHub Release ----------------

def parse_release(payload: dict[str, Any], github_proxy: str = "") -> ReleaseInfo:
    tag = str(payload.get("tag_name") or "")
    installer = next(
        (a for a in payload.get("assets") or [] if str(a.get("name", "")).lower().endswith(".exe")),
        None,
    )
    url = installer.get("browser_download_url") if installer else None
    if url and github_proxy:
        url = github_proxy.rstrip("/") + "/" + url
    return ReleaseInfo(
        version=tag.lstrip("vV") or str(payload.get("name") or ""),
        tag=tag,
        name=str(payload.get("name") or tag),
        notes=str(payload.get("body") or "").strip(),
        published_at=payload.get("published_at"),
        html_url=str(payload.get("html_url") or ""),
        installer_url=url,
        installer_name=installer.get("name") if installer else None,
        installer_size=int(installer["size"]) if installer and installer.get("size") is not None else None,
    )


async def fetch_latest_release(
    repo: str, *, github_proxy: str = "", client: Optional[httpx.AsyncClient] = None, timeout: float = 10.0
) -> ReleaseInfo:
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "WenlanAI-Updater"}
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        try:
            resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise UpdateSourceError(f"无法连接 GitHub（{exc.__class__.__name__}），请检查网络或稍后再试") from exc
        if resp.status_code in (403, 429):
            raise UpdateSourceError("GitHub API 限流，请稍后再试（未登录 IP 每小时 60 次）")
        if resp.status_code == 404:
            raise UpdateSourceError(f"仓库 {repo} 没有任何 Release")
        if resp.status_code >= 400:
            raise UpdateSourceError(f"GitHub 返回 HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise UpdateSourceError("GitHub 返回了无法解析的内容") from exc
        return parse_release(payload, github_proxy)
    finally:
        if own:
            await client.aclose()


# ---------------- git 状态（source 模式） ----------------

GitRunner = Callable[..., Awaitable[tuple[int, str]]]


async def run_git(args: list[str], cwd: Path, timeout: float = 30.0) -> tuple[int, str]:
    """跑 git 子命令，返回 (returncode, stdout+stderr)。git 不存在抛 FileNotFoundError。"""
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"},
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"git {' '.join(args)} 超时（{timeout:.0f}s）"
    return proc.returncode or 0, out.decode("utf-8", errors="replace")


def _classify_changes(paths: list[str]) -> tuple[bool, bool]:
    deps = any(p in ("backend/requirements.txt", "requirements.txt") for p in paths)
    frontend = any(p.startswith("frontend/") for p in paths)
    return deps, frontend


async def inspect_git(repo_root: Path, *, run: GitRunner = run_git, fetch: bool = True) -> GitInfo:
    """fetch 后比较 HEAD 与 origin/<branch>。任何一步失败都写进 error 而不抛出。"""
    try:
        if fetch:
            code, out = await run(["fetch", "--quiet", "origin"], repo_root, 60)
            if code != 0:
                return GitInfo(available=True, error=f"git fetch 失败：{out.strip()[-300:]}")
        code, out = await run(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
        branch = out.strip() if code == 0 else None
        code, out = await run(["rev-parse", "--short", "HEAD"], repo_root)
        commit = out.strip() if code == 0 else None
        if not branch or branch == "HEAD":
            return GitInfo(available=True, branch=branch, commit=commit, error="当前处于分离 HEAD，无法判断落后进度")
        upstream = f"origin/{branch}"
        code, out = await run(["rev-parse", "--short", upstream], repo_root)
        if code != 0:
            return GitInfo(available=True, branch=branch, commit=commit, error=f"远端没有分支 {upstream}")
        remote_commit = out.strip()

        code, out = await run(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"], repo_root)
        ahead = behind = 0
        if code == 0:
            nums = out.strip().split()
            if len(nums) == 2 and all(n.isdigit() for n in nums):
                ahead, behind = int(nums[0]), int(nums[1])

        commits: list[dict[str, str]] = []
        changed: list[str] = []
        if behind > 0:
            code, out = await run(["log", "--oneline", "--no-decorate", "-n", "20", f"HEAD..{upstream}"], repo_root)
            if code == 0:
                for line in out.splitlines():
                    sha, _, msg = line.strip().partition(" ")
                    if sha:
                        commits.append({"sha": sha, "message": msg})
            code, out = await run(["diff", "--name-only", f"HEAD..{upstream}"], repo_root)
            if code == 0:
                changed = [p.strip() for p in out.splitlines() if p.strip()]

        code, out = await run(["status", "--porcelain"], repo_root)
        dirty = code == 0 and any(line and not line.startswith("??") for line in out.splitlines())
        deps, frontend = _classify_changes(changed)
        return GitInfo(
            available=True, branch=branch, commit=commit, remote_commit=remote_commit,
            ahead=ahead, behind=behind, commits=commits, changed_files=len(changed),
            backend_deps_changed=deps, frontend_changed=frontend, dirty=dirty,
        )
    except FileNotFoundError:
        return GitInfo(available=False, error="未找到 git 命令，无法检查源码更新")
    except Exception as exc:  # noqa: BLE001 - 检查更新不能把服务打挂
        return GitInfo(available=True, error=f"git 检查失败：{exc}")


def docker_apply_hint() -> str:
    return (
        "容器内无法自更新，请在宿主机项目目录执行：\n"
        "git pull\n"
        "docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build\n"
        "（或直接运行 ./deploy.sh）"
    )


def _source_apply_hint(git: GitInfo) -> str:
    steps = ["git pull --ff-only"]
    if git.backend_deps_changed:
        steps.append("pip install -r backend/requirements.txt")
    if git.frontend_changed:
        steps.append("npm run build（前端有改动）")
    return "一键更新将依次执行：" + " → ".join(steps) + "，完成后需重启后端服务。"


# ---------------- 服务 ----------------

class UpdateService:
    def __init__(
        self,
        *,
        current_version: str,
        repo: str,
        github_proxy: str,
        enabled: bool,
        run_mode: str,
        repo_root: Optional[Path],
        status_file: Optional[Path],
        runner_log: Optional[Path] = None,
    ):
        self.current_version = current_version
        self.repo = repo
        self.github_proxy = github_proxy
        self.enabled = enabled
        self.run_mode = run_mode
        self.repo_root = repo_root
        self.status_file = status_file
        self.runner_log = runner_log
        self._cache: Optional[UpdateCheckResult] = None
        self._cache_at = 0.0
        self._lock = asyncio.Lock()
        # exe 模式的下载任务状态（内存）；source 模式状态在 status_file
        self._exe_job: dict[str, Any] = {"status": "idle", "steps": [], "progress": None, "message": None, "error": None}
        self._exe_task: Optional[asyncio.Task] = None

    # 可被测试替换
    async def _fetch_release(self) -> ReleaseInfo:
        return await fetch_latest_release(self.repo, github_proxy=self.github_proxy)

    async def _inspect_git(self) -> Optional[GitInfo]:
        if self.repo_root is None:
            return GitInfo(available=False, error="未找到 .git 目录（不是 git 检出的源码）")
        return await inspect_git(self.repo_root)

    # ---- 检查 ----

    async def check(self, force: bool = False) -> UpdateCheckResult:
        if not self.enabled:
            return UpdateCheckResult(
                enabled=False, run_mode=self.run_mode, current_version=self.current_version, latest=None,
                has_update=False, git=None, can_apply=False,
                apply_hint="在线检查更新已由部署配置关闭（UPDATE_CHECK_ENABLED=false）", checked_at=None,
            )
        async with self._lock:
            if not force and self._cache and time.monotonic() - self._cache_at < CHECK_CACHE_SECONDS:
                cached = UpdateCheckResult(**{**asdict(self._cache), "latest": self._cache.latest, "git": self._cache.git})
                cached.cached = True
                return cached
            result = await self._do_check()
            self._cache, self._cache_at = result, time.monotonic()
            return result

    async def _do_check(self) -> UpdateCheckResult:
        error: Optional[str] = None
        latest: Optional[ReleaseInfo] = None
        try:
            latest = await self._fetch_release()
        except UpdateSourceError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("检查更新失败: %s", exc)
            error = f"检查更新失败：{exc}"

        release_newer = bool(latest and is_newer(latest.version, self.current_version))
        git: Optional[GitInfo] = None
        has_update = release_newer
        can_apply = False
        hint = ""

        if self.run_mode == "exe":
            if release_newer:
                can_apply = bool(latest and latest.installer_url)
                hint = ("下载安装包后将启动安装向导，应用会自动退出。" if can_apply
                        else "该版本 Release 未附带安装包，请前往发布页手动下载。")
            else:
                hint = "已是最新版本。" if latest else ""
        elif self.run_mode == "docker":
            hint = docker_apply_hint() if release_newer else ("已是最新版本。" if latest else "")
        else:
            git = await self._inspect_git()
            if git and git.available and git.error is None:
                has_update = git.behind > 0
                if has_update:
                    if git.dirty:
                        hint = "工作区有未提交的修改，一键更新已禁用：请先提交或还原改动（git stash），再重新检查。"
                    elif git.ahead > 0:
                        hint = (
                            f"本地有 {git.ahead} 个领先远端的提交，与远端已分叉，无法快进合并；"
                            f"请手动执行 git pull --rebase origin {git.branch}（或先推送本地提交）后重新检查。"
                        )
                    else:
                        can_apply = True
                        hint = _source_apply_hint(git)
                else:
                    hint = "源码已与远端同步。"
            else:
                has_update = release_newer
                hint = (git.error if git and git.error else "") + ("\n" if git and git.error else "") + (
                    "无法通过 git 判断落后进度，仅按 Release 版本比较。" if latest else "")

        return UpdateCheckResult(
            enabled=True, run_mode=self.run_mode, current_version=self.current_version, latest=latest,
            has_update=has_update, git=git, can_apply=can_apply, apply_hint=hint.strip(),
            checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), error=error,
        )

    # ---- 应用更新 ----

    async def start_apply(self) -> dict[str, Any]:
        result = await self.check(force=True)
        if not result.can_apply:
            raise UpdateNotApplicable(result.apply_hint or "当前没有可一键应用的更新")
        if self.run_mode == "exe":
            return await self._start_exe_update(result.latest)  # type: ignore[arg-type]
        if self.run_mode == "source":
            return await self._start_source_update(result.git)  # type: ignore[arg-type]
        raise UpdateNotApplicable(docker_apply_hint())

    async def status(self) -> dict[str, Any]:
        if self.run_mode == "exe":
            return {"mode": "exe", **self._exe_job, "restart_required": False}
        if self.run_mode == "source":
            return self._read_source_status()
        return {"mode": "docker", "status": "idle", "steps": [], "progress": None, "message": None, "error": None,
                "restart_required": False}

    # ---- exe：下载 + 启动安装向导 + 退出 ----

    async def _start_exe_update(self, release: ReleaseInfo) -> dict[str, Any]:
        if self._exe_task and not self._exe_task.done():
            raise UpdateBusy("安装包正在下载中")
        self._exe_job = {
            "status": "running", "message": f"正在下载 {release.installer_name}…", "error": None,
            "progress": {"downloaded": 0, "total": release.installer_size},
            "steps": [
                {"key": "download", "label": "下载安装包", "state": "running", "output": ""},
                {"key": "launch", "label": "启动安装向导", "state": "pending", "output": ""},
            ],
        }
        self._exe_task = asyncio.create_task(self._run_exe_update(release))
        return await self.status()

    def _set_step(self, key: str, state: str, output: str = "") -> None:
        for step in self._exe_job["steps"]:
            if step["key"] == key:
                step["state"] = state
                if output:
                    step["output"] = output

    async def _run_exe_update(self, release: ReleaseInfo) -> None:
        target_dir = Path(tempfile.gettempdir()) / "WenlanAI-Update"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            for old in target_dir.glob("*.exe"):
                try:
                    old.unlink()
                except OSError:
                    pass
            target = target_dir / (release.installer_name or f"WenlanAI-Setup-v{release.version}.exe")
            await self._download(release.installer_url or "", target, release.installer_size)
            self._set_step("download", "success", f"已保存到 {target}")
            self._set_step("launch", "running")
            self._exe_job["message"] = "安装程序已启动，应用将在 2 秒后退出；安装完成后可在结束页勾选启动新版本。"
            self._launch_installer(target)
            self._set_step("launch", "success")
            self._exe_job["status"] = "exiting"
            loop = asyncio.get_running_loop()
            loop.call_later(_EXIT_DELAY_SECONDS, self._exit_process)
        except Exception as exc:  # noqa: BLE001
            logger.error("exe 更新失败: %s", exc, exc_info=True)
            self._exe_job["status"] = "failed"
            self._exe_job["error"] = str(exc)
            self._exe_job["message"] = None
            for step in self._exe_job["steps"]:
                if step["state"] == "running":
                    step["state"] = "failed"

    async def _download(self, url: str, target: Path, expected_size: Optional[int]) -> None:
        if not url:
            raise UpdateNotApplicable("Release 未附带安装包")
        downloaded = 0
        timeout = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url, headers={"User-Agent": "WenlanAI-Updater"}) as resp:
                if resp.status_code >= 400:
                    raise UpdateSourceError(f"下载失败：HTTP {resp.status_code}")
                total = expected_size or (int(resp.headers["content-length"]) if resp.headers.get("content-length") else None)
                self._exe_job["progress"] = {"downloaded": 0, "total": total}
                tmp = target.with_suffix(".part")
                with tmp.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(1024 * 256):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        self._exe_job["progress"]["downloaded"] = downloaded
                tmp.replace(target)
        if expected_size and downloaded != expected_size:
            raise UpdateSourceError(f"安装包大小不符（期望 {expected_size} 字节，实际 {downloaded}），已放弃安装")

    @staticmethod
    def _launch_installer(path: Path) -> None:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        subprocess.Popen([str(path)], cwd=str(path.parent), close_fds=True, creationflags=flags)

    @staticmethod
    def _exit_process() -> None:
        logger.info("安装程序已启动，应用退出以便替换文件")
        os._exit(0)

    # ---- source：独立进程跑 git pull / pip / npm ----

    async def _start_source_update(self, git: GitInfo) -> dict[str, Any]:
        if self.repo_root is None or self.status_file is None:
            raise UpdateNotApplicable("未找到源码目录")
        current = self._read_source_status()
        if current.get("status") == "running":
            raise UpdateBusy("已有更新任务在运行")
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.status_file.write_text(json.dumps({
            "mode": "source", "status": "running", "steps": [], "progress": None, "message": "正在启动更新进程…",
            "error": None, "restart_required": False, "heartbeat": time.time(),
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "finished_at": None,
        }, ensure_ascii=False), encoding="utf-8")
        self._launch_runner(git.branch or "master")
        return self._read_source_status()

    def _launch_runner(self, branch: str) -> None:
        assert self.repo_root is not None and self.status_file is not None
        backend_dir = Path(__file__).resolve().parent.parent.parent
        args = [
            sys.executable, "-m", "app.services.update_runner",
            "--repo-root", str(self.repo_root), "--branch", branch,
            "--status-file", str(self.status_file), "--python", sys.executable,
        ]
        log_path = self.runner_log or (backend_dir / "logs" / "update_runner.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = log_path.open("ab")
        popen_kwargs: dict[str, Any] = {"cwd": str(backend_dir), "stdout": log_fh, "stderr": subprocess.STDOUT,
                                        "stdin": subprocess.DEVNULL, "close_fds": True}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            popen_kwargs["start_new_session"] = True
        subprocess.Popen(args, **popen_kwargs)
        log_fh.close()
        logger.info("已启动独立更新进程: %s", " ".join(args))

    def _read_source_status(self) -> dict[str, Any]:
        base = {"mode": "source", "status": "idle", "steps": [], "progress": None, "message": None, "error": None,
                "restart_required": False, "started_at": None, "finished_at": None}
        if self.status_file is None or not self.status_file.exists():
            return base
        try:
            data = json.loads(self.status_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return base
        if not isinstance(data, dict):
            return base
        merged = {**base, **data}
        merged.pop("pid", None)
        heartbeat = float(merged.pop("heartbeat", 0) or 0)
        if merged.get("status") == "running" and heartbeat and time.time() - heartbeat > RUNNER_STALE_SECONDS:
            merged["status"] = "failed"
            merged["error"] = merged.get("error") or "更新进程已无响应（可能被中断），请查看 logs/update_runner.log"
        if merged.get("status") in ("success", "failed") and self._finished_before_process_start(merged.get("finished_at")):
            return base  # 服务已在任务结束后重启过：结果（含"请重启"提示）已过时
        return merged

    @staticmethod
    def _finished_before_process_start(finished_at: Any) -> bool:
        if not finished_at:
            return False
        try:
            finished = datetime.fromisoformat(str(finished_at))
        except ValueError:
            return False
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        # finished_at 只精确到秒，留 1s 容差避免同一秒内误判
        return finished.timestamp() < _PROCESS_STARTED_AT - 1


# ---------------- 全局实例 ----------------

def _find_repo_root(backend_dir: Path) -> Optional[Path]:
    root = backend_dir.parent
    return root if (root / ".git").exists() else None


def build_default_service() -> UpdateService:
    from app.config import DATA_DIR, PROJECT_ROOT, settings

    mode = detect_run_mode()
    return UpdateService(
        current_version=settings.app_version,
        repo=settings.update_repo,
        github_proxy=settings.update_github_proxy,
        enabled=settings.update_check_enabled,
        run_mode=mode,
        repo_root=_find_repo_root(PROJECT_ROOT) if mode == "source" else None,
        status_file=DATA_DIR / "update_job.json",
        runner_log=PROJECT_ROOT / "logs" / "update_runner.log",
    )


update_service = build_default_service()
