"""拆书抽取的跨进程运行锁。

ai_jobs 的互斥只在进程内。同一 data 目录被两个后端进程共用时（桌面版 + 终端里的开发服务、
应用被启动了两次），另一个进程看不到 job：/cancel 的兜底分支会把 running 直接改成 cancelled，
再点重新抽取就有两条流水线同时往 book_dissect_chapter_facts 写同一 task，撞 UNIQUE(task_id, chapter_number)。

这里按 task 用 OS 文件锁（Windows msvcrt.locking / POSIX flock）互斥：锁随进程退出自动释放，
不需要心跳列和过期阈值，进程崩溃后新进程可立即接管（Windows 对终止进程遗留的锁是异步回收，
通常毫秒级）。锁文件放在数据库文件旁边，共用 DB 的进程必然共用锁目录；锁文件不删除
（Windows 下被别的进程持有时删不掉，留着也无害）。

锁只是双实例这种误用场景的安全网：锁目录建不出来 / 文件系统不支持锁时记 warning 并退化为不互斥，
绝不能让抽取功能因此永远 409。
"""
from __future__ import annotations

import errno
import logging
import os
import sys
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

logger = logging.getLogger(__name__)

# 非阻塞加锁失败且原因是"已被持有"时的 errno：Windows _locking 报 EACCES / EDEADLOCK，POSIX flock 报 EWOULDBLOCK
_HELD_ERRNOS = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}


class RunLock:
    """已持有的运行锁；release() 幂等。fd=None 表示退化模式（没有真正加锁）。"""

    def __init__(self, path: Path, fd: Optional[int]) -> None:
        self.path = path
        self._fd = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if sys.platform == "win32":
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _lock_dir() -> Path:
    from sqlalchemy.engine import make_url

    from app.config import DATA_DIR, settings

    db_path = make_url(settings.database_url).database
    base = Path(db_path).resolve().parent if db_path and db_path != ":memory:" else DATA_DIR
    return base / "locks"


def _lock_nonblocking(fd: int) -> None:
    if sys.platform == "win32":
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def try_acquire_run_lock(task_id: str, *, lock_dir: Optional[Path] = None) -> Optional[RunLock]:
    """非阻塞获取某 task 的运行锁；已被任一进程（含本进程）持有时返回 None。"""
    path = (lock_dir or _lock_dir()) / f"book_dissect_{task_id}.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        logger.warning("[拆书运行锁] 无法创建锁文件 %s：%s，本次不做跨进程互斥", path, exc)
        return RunLock(path, None)
    try:
        _lock_nonblocking(fd)
    except OSError as exc:
        os.close(fd)
        if exc.errno in _HELD_ERRNOS:
            return None
        logger.warning("[拆书运行锁] 文件系统不支持文件锁 %s：%s，本次不做跨进程互斥", path, exc)
        return RunLock(path, None)
    return RunLock(path, fd)


def is_run_locked(task_id: str, *, lock_dir: Optional[Path] = None) -> bool:
    """探测某 task 是否有流水线在跑（任一进程）。探测本身不会留下锁。"""
    lock = try_acquire_run_lock(task_id, lock_dir=lock_dir)
    if lock is None:
        return True
    lock.release()
    return False
