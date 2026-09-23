"""真实 RAW 语料路径解析 —— 集中唯一入口, 避免多处硬编码各自失效。

## 为什么需要

语料目录在 2026-09 被重组: ``K:/data/photo/0711/`` 被并入
``K:/data/photo/西安/0711/``（顶层已无 ``0711``）。原先 9 处硬编码旧路径的
用例因此 **静默 skip** —— 全量跑仍显示全绿, 但那 5 个"真 RAW"用例实际一行
都没跑（假绿）。本模块把"语料在哪"收敛为唯一入口, 并在路径失效时报告
**已探测的候选目录**, 使语料搬家立刻可见, 而不是伪装成"环境不可达"。

## 解析优先级

1. ``PIXO_CORPUS_A_RAW``      直接给出 DSC_5236.NEF 的完整路径（最高优先）
2. ``PIXO_CORPUS_A_RAW_DIR``  直接给出 raw 目录
3. ``<root>/*/0711/raw``      新位置（如 ``西安/0711/raw``）, 通配一层
4. ``<root>/0711/raw``        旧位置（向后兼容, 语料搬回原地仍可用）
5. ``<repo>/data/photo/0711/raw``  仓内相对路径（干净克隆 / CI）

``<root>`` = ``PIXO_CORPUS_ROOT`` 或 ``K:/data/photo``。

## 与"权重缺失"类 skip 的区别

本模块只回答"**语料文件在不在**"。模型权重 / 网络不可用是另一类问题, 由各
用例自行 ``pytest.skip``（如 ``PIXO_SEGMENTER=multi`` 构造失败回退 mock）。
两类不可混淆: 前者是路径问题（本模块可诊断）, 后者是环境依赖。

## 用法

    from _corpus_paths import RAW_DIR, RAW_SKIP_REASON, raw_glob, raw_file

    @pytest.mark.skipif(RAW_DIR is None, reason=RAW_SKIP_REASON)
    def test_x():
        raws = raw_glob("DSC_526*.NEF")      # 无语料时返回 []
"""
from __future__ import annotations

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SET = "0711"
DEFAULT_ROOT = "K:/data/photo"


def _root() -> Path:
    return Path(os.environ.get("PIXO_CORPUS_ROOT") or DEFAULT_ROOT)


def _candidates() -> list[Path]:
    """按优先级列出候选 raw 目录（含不存在的, 供诊断打印）。"""
    cands: list[Path] = []

    env_file = os.environ.get("PIXO_CORPUS_A_RAW")
    if env_file:
        cands.append(Path(env_file).parent)
    env_dir = os.environ.get("PIXO_CORPUS_A_RAW_DIR")
    if env_dir:
        cands.append(Path(env_dir))

    root = _root()
    # 新位置: 语料被并入某个一级目录下 (如 西安/0711/raw)
    try:
        cands.extend(sorted(p for p in root.glob(f"*/{_SET}/raw") if p.is_dir()))
    except OSError:
        pass
    cands.append(root / _SET / "raw")                       # 旧位置
    cands.append(_REPO / "data" / "photo" / _SET / "raw")   # 仓内相对

    # 去重保序
    seen: set[str] = set()
    out: list[Path] = []
    for c in cands:
        k = str(c)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


_CANDIDATES = _candidates()
RAW_DIR: Path | None = next((c for c in _CANDIDATES if c.is_dir()), None)

RAW_SKIP_REASON = (
    f"真实 RAW 语料({_SET}/raw)不可达; 已探测: "
    + ", ".join(str(p) for p in _CANDIDATES)
    + "。可用 PIXO_CORPUS_A_RAW / PIXO_CORPUS_A_RAW_DIR / PIXO_CORPUS_ROOT 指定。"
)


def raw_file(name: str) -> Path | None:
    """取 raw 目录下的指定文件; 不存在（或语料不可达）返回 None。"""
    if RAW_DIR is None:
        return None
    p = RAW_DIR / name
    return p if p.is_file() else None


def raw_glob(pattern: str) -> list[Path]:
    """在 raw 目录内通配; 语料不可达时返回空列表（调用方据此 skip）。"""
    if RAW_DIR is None:
        return []
    return sorted(RAW_DIR.glob(pattern))


# 常用夹具: 全仓真 RAW 用例的事实标准锚点（sanity / e2e / 一致性巡检）
REAL_A = raw_file("DSC_5236.NEF")
