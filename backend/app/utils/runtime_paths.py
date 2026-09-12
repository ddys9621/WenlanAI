"""运行时可写目录（embedding 模型等）的统一计算。

- 源码 / 容器：backend/（即 app/ 的上一级）
- exe（PyInstaller）：安装目录 {app}（WenlanAI.exe 所在处），**不是** _internal——
  安装包升级时会整目录替换 _internal（installer.iss [InstallDelete]），放在里面的用户数据会被清掉。
  1.1.0 及更早版本把模型下载在 _internal\\embedding，安装程序升级时会先把它挪到 {app}\\embedding。
"""
from __future__ import annotations

import os
import sys


def runtime_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # app/utils → backend


def embedding_dir() -> str:
    return os.path.join(runtime_base_dir(), "embedding")
