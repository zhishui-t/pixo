"""engine.rp_ccm —— 根多项式 CCM (Root-Polynomial Colour Correction Matrix)。

权威依据:
  - G. Finlayson, R. Xu, "Root-Polynomial Colour Correction", IS&T CIC23, 2015;
  - G. Finlayson, M. Mackiewicz, A. Hurlbert, "Color Correction Using
    Root-Polynomial Regression", IEEE TIP 24(5), 2015 —— 项集与曝光不变性论证出处。

原理 (为何"根多项式"):
  普通多项式回归 (r², rg, r³ …) 不保曝光: 线性 RGB 乘 a 后各项按 a²/a³ 不一致缩放,
  同一色块在不同曝光下拟合出不同矩阵。根多项式把交叉项开方:
    degree 1:  r, g, b                                (3 项)
    degree 2:  r, g, b, √(rg), √(rb), √(gb)           (6 项)
  线性 RGB 乘 a (a≥0) 时每个根项都恰好乘 a (√(ar·ag) = a√(rg)),
  故 out = M @ f(a·x) = a·(M @ f(x)) —— 输出随输入精确等比缩放, 色度不变
  (线性 CC 的查表/亮度管线不受矩阵系数随曝光漂移影响)。
  纯平方项 (r², g², b²) 不进项集: √(r²) = r (线性 RGB 非负) 与线性项重复,
  无信息增益还破坏项独立性 (Finlayson 2015 的项集构造规则)。

用法 (阶段一并联, 设计 §4):
  拟合:  scripts/fit_rp_ccm.py  语料弱监督 (相机 JPEG 参考) → configs/color/*.json
  评估:  scripts/eval_rp_ccm_ab.py  DCP vs DCP+RP-CCM 双轨 ΔE2000 报告
  运行时: apply_rp_ccm(linear_rgb, coeff) 作用于 DCP 渲染后的**线性 sRGB**。

纪律 (对齐 OWN_PIPELINE_STAGE1_DESIGN §1.3 / 隔离纪律):
  - 运行时仅依赖 numpy (json 为标准库); sklearn 等重依赖只进 scripts/;
  - 恒等系数走快路径逐位 no-op (原样返回, 连矩阵乘都不做);
  - 拟合 fit_rp_ccm 为纯函数 (numpy lstsq, 无 I/O), 供单测直接验证;
  - apply 出口 float32、值域 [0,1] (线性显示域, 对齐 linear_prophoto_to_srgb);
  - 纯函数除 save/load 两个显式 JSON I/O 入口, 无全局可变状态。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

__all__ = [
    "RP_DEGREE_MAX", "RP_TERMS", "RPCCM",
    "rp_features", "n_terms", "identity_rp_ccm", "apply_rp_ccm",
    "fit_rp_ccm", "save_rp_ccm", "load_rp_ccm",
]

# 支持的根多项式阶数: 1 (仅线性) / 2 (线性 + √交叉项)
RP_DEGREE_MAX = 2

# 项集命名 (JSON 序列化用, 与 rp_features 列序一一对应)
RP_TERMS: dict[int, tuple[str, ...]] = {
    1: ("r", "g", "b"),
    2: ("r", "g", "b", "sqrt(rg)", "sqrt(rb)", "sqrt(gb)"),
}


def n_terms(degree: int) -> int:
    """根多项式项数: degree 1 → 3, degree 2 → 6。"""
    if degree not in RP_TERMS:
        raise ValueError(f"degree 只支持 {sorted(RP_TERMS)}, 实际 {degree!r}")
    return len(RP_TERMS[degree])


def rp_features(linear_rgb, degree: int = 2) -> np.ndarray:
    """线性 RGB (..., 3) → 根多项式特征 (..., n_terms), float64。

    负输入按 0 处理 (线性 RGB 非负契约的防御, 对齐 oklab._srgb_to_linear 纪律,
    保证 √ 项无 NaN)。曝光缩放 (×a, a≥0) 下每个特征精确等比缩放 ——
    这是 apply_rp_ccm 曝光不变性的数值根基。
    """
    if degree not in RP_TERMS:
        raise ValueError(f"degree 只支持 {sorted(RP_TERMS)}, 实际 {degree!r}")
    rgb = np.asarray(linear_rgb, dtype=np.float64)
    if rgb.ndim == 0 or rgb.shape[-1] != 3:
        raise ValueError(f"linear_rgb 最后一维需为 3 (实际 shape={rgb.shape})")
    # 负值 clip 到 0: 防负×正乘积为负 (√ → NaN) 与负×负乘积为正 (√ → 伪正值)
    rgb = np.clip(rgb, 0.0, None)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    if degree == 1:
        return np.stack([r, g, b], axis=-1)
    return np.stack([r, g, b,
                     np.sqrt(r * g), np.sqrt(r * b), np.sqrt(g * b)], axis=-1)


# ---------------------------------------------------------------------------
# RPCCM 系数对象
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RPCCM:
    """根多项式 CCM 系数 (不可变)。

    matrix: (3, n_terms) float64, 行向量语义 out = features @ matrix.T
            (与 oklab/_M1 的 out = in @ M.T 一致, 便于 @ 批量应用)。
    degree: 1 或 2 (项集见 RP_TERMS)。
    camera/source/meta: 元数据 (相机标识 / 拟合来源 / 拟合统计), 不参与运算。
    """
    matrix: np.ndarray
    degree: int = 2
    camera: str = ""
    source: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.degree not in RP_TERMS:
            raise ValueError(f"degree 只支持 {sorted(RP_TERMS)}, 实际 {self.degree!r}")
        m = np.asarray(self.matrix, dtype=np.float64)
        expect = (3, n_terms(self.degree))
        if m.shape != expect:
            raise ValueError(f"matrix 形状需为 {expect}, 实际 {m.shape}")
        if not np.isfinite(m).all():
            raise ValueError("matrix 含 NaN/Inf")
        object.__setattr__(self, "matrix", m)

    @property
    def identity_target(self) -> np.ndarray:
        """恒等系数目标矩阵: degree1 → I; degree2 → [I | 0] (只取线性三项)。"""
        target = np.zeros((3, n_terms(self.degree)), dtype=np.float64)
        target[:, :3] = np.eye(3)
        return target

    @property
    def is_identity(self) -> bool:
        """是否恒等系数 (out(x) = x)。判定阈值 1e-12 (冻结容差, 非参数)。"""
        return bool(np.allclose(self.matrix, self.identity_target,
                                rtol=0.0, atol=1e-12))

    def to_dict(self) -> dict:
        """JSON 可序列化 dict (save_rp_ccm 的载荷)。"""
        return {
            "type": "pixo_rp_ccm",
            "version": 1,
            "degree": int(self.degree),
            "terms": list(RP_TERMS[self.degree]),
            "matrix": [[float(x) for x in row] for row in self.matrix],
            "camera": self.camera,
            "source": self.source,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RPCCM":
        """to_dict 的逆; 缺元数据键容忍, 类型/结构非法报 ValueError。"""
        if not isinstance(d, dict) or d.get("type") != "pixo_rp_ccm":
            raise ValueError("JSON 缺少 type='pixo_rp_ccm', 不是 RP-CCM 系数文件")
        if int(d.get("version", 0)) != 1:
            raise ValueError(f"不支持的 RP-CCM 版本 {d.get('version')!r}")
        return cls(matrix=d["matrix"], degree=int(d["degree"]),
                   camera=str(d.get("camera", "")),
                   source=str(d.get("source", "")),
                   meta=dict(d.get("meta") or {}))


def identity_rp_ccm(degree: int = 2, **meta) -> RPCCM:
    """恒等系数 RPCCM (out(x) = x, apply 走逐位 no-op 快路径)。"""
    target = np.zeros((3, n_terms(degree)), dtype=np.float64)
    target[:, :3] = np.eye(3)
    return RPCCM(matrix=target, degree=degree, **meta)


# ---------------------------------------------------------------------------
# 应用 (运行时入口)
# ---------------------------------------------------------------------------

def apply_rp_ccm(linear_rgb, coeff: RPCCM) -> np.ndarray:
    """线性 sRGB (..., 3) 经根多项式 CCM 校正。出口 float32、值域 [0,1]。

    - 恒等系数 (coeff.is_identity): 原样返回输入对象 —— 逐位 no-op 快路径
      (对齐 hsl_adjust_rgb "全 0 快路径连转换都不做" 纪律), 零拷贝;
    - 负输入按 0 处理 (非物理值防御); 输出线性域 clip 到 [0,1]
      (对齐 linear_prophoto_to_srgb, 本阶段 CCM 面向显示域校正);
    - 纯线性映射: 曝光不变 —— 输入 ×k (k≥0) 时输出 ×k (clip 不触发的前提下),
      与根多项式的曝光等比缩放性质一致。
    """
    if not isinstance(coeff, RPCCM):
        raise TypeError(f"coeff 需为 RPCCM, 实际 {type(coeff).__name__}")
    if coeff.is_identity:
        return linear_rgb
    feats = rp_features(linear_rgb, coeff.degree)
    out = feats @ coeff.matrix.T
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# 拟合 (纯 numpy 最小二乘; 语料 I/O 与弱监督采样在 scripts/fit_rp_ccm.py)
# ---------------------------------------------------------------------------

def fit_rp_ccm(src_linear, dst_linear, degree: int = 2,
               weights=None, **meta) -> RPCCM:
    """最小二乘拟合: dst ≈ apply(src) 的系数矩阵 (纯函数, 无 I/O)。

    src_linear/dst_linear: (N, 3) float 线性 RGB 样本 (同一线性映射的两域观测)。
    weights: (N,) 非负样本权重 (弱监督里压低不可靠样本; None 等权)。
    返回 RPCCM。解为加权 LS: min Σ w_i ||dst_i - M @ f(src_i)||²,
    numpy lstsq (SVD) 求解, 列秩亏 (如样本全灰) 时取最小范数解不崩溃。

    元数据经 **meta 传入 (camera/source/n_samples …), 纯函数不做统计 ——
    由调用方计算并按需附加 (拟合质量与样本域相关, 不在核心层臆断)。
    """
    src = np.asarray(src_linear, dtype=np.float64)
    dst = np.asarray(dst_linear, dtype=np.float64)
    if src.ndim != 2 or src.shape[-1] != 3 or dst.shape != src.shape:
        raise ValueError(f"样本需为 (N,3) 且两域同形, 实际 src={src.shape} dst={dst.shape}")
    if src.shape[0] == 0:
        raise ValueError("样本数为 0, 无法拟合")
    f = rp_features(src, degree)                       # (N, n_terms)
    if weights is not None:
        w = np.asarray(weights, dtype=np.float64).reshape(-1)
        if w.shape[0] != src.shape[0]:
            raise ValueError(f"weights 长度需为 N={src.shape[0]}, 实际 {w.shape[0]}")
        if bool((w < 0).any()) or not np.isfinite(w).all():
            raise ValueError("weights 需非负且有限")
        f = f * np.sqrt(w)[:, None]
        dst = dst * np.sqrt(w)[:, None]
    # R Fern Technology: lstsq 以 features 为自变量解 matrix.T (n_terms, 3);
    # rcond=None 奇异值截断 → 秩亏时最小范数解 (样本退化不崩溃)。
    solution, _, _, _ = np.linalg.lstsq(f, dst, rcond=None)
    return RPCCM(matrix=solution.T, degree=degree, **meta)


# ---------------------------------------------------------------------------
# JSON I/O (显式入口; 标准库 json, 运行时安全)
# ---------------------------------------------------------------------------

def save_rp_ccm(coeff: RPCCM, path: str | Path) -> Path:
    """系数落盘 JSON (configs/color/rp_ccm_<camera>.json 约定)。返回写入路径。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(coeff.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def load_rp_ccm(path: str | Path) -> RPCCM:
    """读取系数 JSON → RPCCM (缺文件/非法结构报 FileNotFoundError/ValueError)。"""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"RP-CCM 系数文件不存在: {path}")
    return RPCCM.from_dict(json.loads(path.read_text(encoding="utf-8")))
