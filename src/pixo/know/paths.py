"""pixo.know.paths —— 仓库配置目录定位（去 CWD 化）。

此前 ``configs/knowledge`` 与 ``configs/styles/films`` 按 ``Path.cwd()`` 解析，
换目录启动会静默丢掉外部知识包/胶片卡。这里统一改为：

- 优先环境变量 ``PIXO_CONFIG_ROOT``（指向仓库根，即包含 ``configs/`` 的目录；
  也兼容直接指向 ``configs/`` 目录本身）；
- 否则从本文件位置向上查找 ``pyproject.toml`` 定位仓库根；
- 找不到时 ``logging.warning`` 说明少加载了什么，不再静默。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

__all__ = [
    "PIXO_CONFIG_ROOT_ENV",
    "resolve_config_root",
    "repo_configs_dir",
]

_LOGGER = logging.getLogger(__name__)

PIXO_CONFIG_ROOT_ENV = "PIXO_CONFIG_ROOT"


def resolve_config_root() -> Optional[Path]:
    """返回仓库根目录（包含 ``configs/``）；定位失败返回 None 并告警。"""
    env = os.environ.get(PIXO_CONFIG_ROOT_ENV)
    if env:
        root = Path(env).expanduser().resolve()
        if root.is_dir():
            return root
        _LOGGER.warning(
            "[pixo.know] %s=%s 不是有效目录，忽略该覆盖", PIXO_CONFIG_ROOT_ENV, env
        )
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    _LOGGER.warning(
        "[pixo.know] 未能从 %s 向上定位仓库根（pyproject.toml），"
        "仓库 configs/ 下的外部知识包/胶片卡将不加载", here.parent
    )
    return None


def repo_configs_dir() -> Optional[Path]:
    """返回仓库 ``configs/`` 目录；缺失返回 None 并告警。"""
    root = resolve_config_root()
    if root is None:
        return None
    cfg = root / "configs"
    if cfg.is_dir():
        return cfg
    # 兼容 PIXO_CONFIG_ROOT 直接指向 configs/ 目录本身的用法。
    if (root / "knowledge").is_dir() or root.name == "configs":
        return root
    _LOGGER.warning(
        "[pixo.know] 仓库根 %s 下未找到 configs/ 目录，"
        "configs/ 内的外部知识包/胶片卡将不加载", root
    )
    return None
