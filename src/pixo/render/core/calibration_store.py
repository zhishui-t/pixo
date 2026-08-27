"""render.core.calibration_store —— 标定 JSON 统一加载/缓存 (深审 L4/L5 治理收敛)。

此前标定文件加载有四种路径口径、三套缓存并存:
  - exposure: 包内 render/target_offset.json, 模块级 None 哨兵 (缺失缓存 0.0);
  - tone:     包内 render/lr_tone_curve.json (默认不存在), 无负缓存 → 每次调用
              都 stat 探测;
  - whitebalance: 仓库根 configs/calibration/warmth_curve.json, mtime+size 键
    缓存 (每次调用 stat)。
本模块统一为单一加载器, 语义:
  - **绝对路径解析交给调用方** (包内资源用 ``Path(__file__).parent``, 仓库根
    configs 用 :func:`resolve_repo_root`);
  - **mtime+size 失效**: 已缓存文件每次调用 stat 一次, (mtime_ns, size) 变化
    即重读 (保留 wb 的即时生效语义);
  - **负缓存**: 缺失文件缓存失败结果 —— 后续调用不再 stat/重读 (修复 tone 的
    每次 stat)。代价: 进程运行**中途新建**的文件不会被自动感知 (标定文件视为
    进程级静态资源), 需 :func:`reset` 或 ``refresh=True`` 后生效; 损坏文件
    按 stat 态缓存, 修复落盘 (mtime/size 变化) 后自动重读;
  - **线程安全**: 一把模块锁覆盖 缓存读写/stat/文件读取;
  - **损坏回退 + 一次性 warning**: JSON 解析失败/顶层非 object → 返回调用方
    ``default`` 并按路径记一次 logging.warning (缺失文件是合法常态, 不告警);
  - ``reset()``: 清全部缓存与告警记录 (测试隔离钩子, 各 Stage 模块的
    ``_reset_caches()`` 会一并调用)。

返回值约定: 成功返回**共享的** dict (缓存对象直返, 不做防御拷贝 —— 调用方
不得原地修改); 失败 (缺失/损坏) 返回本次调用传入的 ``default``。

路径解析辅助 :func:`resolve_repo_root` 与 ``pixo.know.paths.resolve_config_root``
同法 (PIXO_CONFIG_ROOT 环境变量优先, 否则向上找 pyproject.toml); 此处自实现
一份 —— render 反向 import know 属跨包依赖倒置, 不取。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional, Union

__all__ = ["load_json", "resolve_repo_root", "reset", "PIXO_CONFIG_ROOT_ENV"]

_LOGGER = logging.getLogger(__name__)

PIXO_CONFIG_ROOT_ENV = "PIXO_CONFIG_ROOT"

# 一把锁覆盖: _ENTRIES/_WARNED 读写、stat、文件读取与解析 (标定文件均为 KB 级,
# 串行化加载换取简单正确)。
_LOCK = threading.RLock()

# path -> (state, ok, doc):
#   state: (mtime_ns, size) 元组 = 文件存在的 stat 态; None = 已知缺失 (负缓存);
#   ok:    True → doc 为已解析 dict; False → doc 无效 (缺失/损坏, 返回 default)。
# 同一 stat 态下 doc 为同一对象直返 (见"返回值约定")。
_ENTRIES: dict[str, tuple] = {}

# 损坏文件一次性告警的去重集 (按路径; reset 时清空)。
_WARNED: set[str] = set()


def _stat_state(key: str) -> Optional[tuple]:
    """stat → (mtime_ns, size); 失败 (缺失/权限) → None。"""
    try:
        st = os.stat(key)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def load_json(path: Union[str, Path], default: Any = None, *,
              refresh: bool = False) -> Optional[dict]:
    """读标定 JSON → dict; 缺失/损坏 → 调用方 ``default``。

    参数:
      path     已解析的绝对路径 (解析职责在调用方, 见模块 docstring)
      default  失败回退值 (每次调用各自生效, 不缓存进 store)
      refresh  True = 绕过缓存强制重读磁盘并更新缓存条目 (供调用方自身的
               模块级 memo 失效语义使用, 如 exposure 的 _cached_* 重置后
               必须读到最新落盘内容)

    缓存语义 (见模块 docstring): 存在文件按 (mtime_ns, size) 失效; 缺失文件
    负缓存 (不再 stat); 损坏文件按 stat 态缓存 + 每路径一次 warning。
    """
    key = os.fspath(path)
    with _LOCK:
        entry = _ENTRIES.get(key)
        if not refresh and entry is not None and entry[0] is None:
            return default          # 负缓存: 已知缺失, 不再 stat/重读
        state = _stat_state(key)
        if state is None:
            _ENTRIES[key] = (None, False, None)
            return default
        if not refresh and entry is not None and entry[0] == state:
            return entry[2] if entry[1] else default
        # refresh=True 或 stat 态变化 → 读盘重解析 (读后重取 stat 态: 读取期间
        # 文件可能又被改写, 以读后态作缓存键更贴近所读内容)。
        doc: Any = None
        try:
            with open(key, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if not isinstance(doc, dict):
                raise ValueError(f"顶层不是 JSON object 而是 {type(doc).__name__}")
            _ENTRIES[key] = (_stat_state(key), True, doc)
            return doc
        except Exception as e:
            if key not in _WARNED:
                _WARNED.add(key)
                _LOGGER.warning(
                    "[calibration_store] 标定文件损坏, 回退默认值 (%s): %s", key, e)
            _ENTRIES[key] = (_stat_state(key), False, None)
            return default


def resolve_repo_root() -> Optional[Path]:
    """仓库根目录 (含 ``configs/``); 定位失败返回 None。

    与 ``pixo.know.paths.resolve_config_root`` 同法: ``PIXO_CONFIG_ROOT``
    环境变量优先 (指向仓库根或 configs/ 目录本身均可), 否则从本文件向上
    查找 ``pyproject.toml``。此处自实现而非 import know —— render ← know
    的跨包依赖方向不雅 (见模块 docstring)。
    """
    env = os.environ.get(PIXO_CONFIG_ROOT_ENV)
    if env:
        root = Path(env).expanduser().resolve()
        if root.is_dir():
            return root
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def reset() -> None:
    """清空全部缓存条目与损坏告警记录 (测试隔离钩子)。

    重置后, 此前缺失的文件若已落盘将被重新感知 (负缓存随之清除)。
    """
    with _LOCK:
        _ENTRIES.clear()
        _WARNED.clear()
