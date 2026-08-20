"""rawlab.tools.batch_render —— 批量渲染 (走新 Pipeline)。

Phase 4 T4.2。纯函数:
  - discover_raw_files  : 目录扫描 (排序/过滤/limit)
  - output_path_for     : 输出路径命名 (同名保序、不覆盖输入)
  - render_batch        : 用 pipeline_from_config(cfg, prof) 逐张 run_file,
                          resume=True 时输出已存在且非零字节则跳过 (断点续跑)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from rawlab.engine import pipeline_from_config

_DEFAULT_GLOBS = ("*.NEF", "*.nef", "*.DNG", "*.dng")


def discover_raw_files(directory, globs: tuple = _DEFAULT_GLOBS,
                       limit: Optional[int] = None) -> List[Path]:
    """扫描 directory 下匹配 globs 的原始文件, 按绝对路径去重并排序。

    limit>0 时只取前 limit 个 (可作 --limit N 预览批量)。
    """
    d = Path(directory)
    found = set()
    for g in globs:
        for p in d.glob(g):
            if p.is_file():
                found.add(p.resolve())
    files = sorted(found)
    if limit is not None and limit > 0:
        files = files[:limit]
    return files


def output_path_for(raw, out_dir, suffix: str = "_rawlux", ext: str = ".jpg") -> Path:
    """输出路径: <out_dir>/<raw_stem><suffix>.<ext>。

    与输入同名保序、写入独立 out_dir → 不覆盖输入文件。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(raw).stem
    return out / f"{stem}{suffix}.{ext.lstrip('.')}"


def render_batch(raw_files, out_dir, cfg: Optional[dict] = None,
                 prof=None, half_size: bool = True, resume: bool = True) -> Dict[str, str]:
    """逐张渲染 (新 Pipeline) 并返回 {stem: rendered|skipped|failed}。

    - cfg: pipeline_from_config 的参数配置 (None→默认链)。含 'dcp' 无妨
      (pipeline_from_config 只读 stages/params/output)。
    - resume=True: 输出已存在且非零字节 → skipped (断点续跑, 不重渲染)。
    - 单张失败不中断整体, 记 failed 继续。
    """
    import cv2
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pipe = pipeline_from_config(cfg or {}, prof=prof)
    results: Dict[str, str] = {}
    for raw in raw_files:
        raw = Path(raw)
        stem = raw.stem
        out = output_path_for(raw, out_dir)
        if resume and out.exists() and out.stat().st_size > 0:
            results[stem] = "skipped"
            continue
        try:
            rgb8 = pipe.run_file(raw, half_size=half_size)
            cv2.imwrite(str(out),
                        cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
            results[stem] = "rendered"
        except Exception:
            results[stem] = "failed"
    return results
