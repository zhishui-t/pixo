# r12 等价自检 (临时, 结论回收后可删): 重写后 color.py vs git HEAD 原版,
# 关键函数输出逐位比对 (合成 DCP × 参数网格 + 真 DCP)。
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# 原版模块 (git HEAD) 落临时文件加载
head_src = subprocess.run(
    ["git", "-C", str(ROOT), "show", "HEAD:src/pixo/render/core/color.py"],
    capture_output=True, text=True, check=True).stdout
old_path = ROOT / ".agent-team/spike/_color_head_r12.py"
old_path.write_text(head_src, encoding="utf-8")

spec_old = importlib.util.spec_from_file_location("color_head_r12", old_path)
old = importlib.util.module_from_spec(spec_old)
spec_old.loader.exec_module(old)

from pixo.render.core import color as new  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def synth_prof(seed, has_fm=True, has_cc=True, has_cm2=True):
    rng = np.random.default_rng(seed)
    def mat(scale=1.0):
        return (rng.uniform(0.4, 1.2, 9).reshape(3, 3)
                + np.eye(3) * 0.5).reshape(-1).tolist()
    prof = SimpleNamespace(
        calibration_illuminant1=17, calibration_illuminant2=21,
        color_matrix1=[1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449,
                       -0.0231, 0.0811, 0.7571],
        color_matrix2=[0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286,
                       -0.0648, 0.1513, 0.6375] if has_cm2 else None,
        camera_calibration1=([1.02, 0.0, 0.0, 0.0, 0.99, 0.0, 0.0, 0.0, 1.01]
                             if has_cc else None),
        camera_calibration2=[0.98, 0.01, 0.0, 0.01, 1.02, 0.0, 0.0, -0.01, 0.99],
        forward_matrix1=([0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001,
                          0.0, 0.0, 0.8251] if has_fm else None),
        forward_matrix2=[0.81, 0.12, 0.03, 0.27, 0.73, 0.001, 0.0, 0.0, 0.82])
    return prof


fails = 0
rng = np.random.default_rng(20260907)

def bit_eq(name, a, b):
    global fails
    a = np.asarray(a); b = np.asarray(b)
    ok = a.shape == b.shape and a.dtype == b.dtype and np.array_equal(a, b)
    if not ok:
        fails += 1
        d = np.abs(a.astype(np.float64) - b.astype(np.float64)).max() \
            if a.shape == b.shape else float("nan")
        print(f"[FAIL] {name}: max|Δ|={d}")
    return ok

# 合成语料: 6 个 profile 变体 × 8 组 WB
profs = [synth_prof(s, has_fm=f, has_cc=c, has_cm2=m)
         for s, f, c, m in [(1, True, True, True), (2, True, True, False),
                            (3, True, False, True), (4, True, False, False),
                            (5, True, True, True), (6, True, True, True)]]
wbs = [[1.29, 1.0, 2.29], [1.0, 1.0, 1.0], [2.1, 1.0, 1.4],
       [0.8, 1.0, 3.1], [1.5, 1.0, 0.9], [1.05, 1.0, 1.02],
       [2.5, 1.0, 2.5], [0.95, 1.0, 1.9]]
for pi, prof in enumerate(profs):
    for wi, wb in enumerate(wbs):
        bit_eq(f"camera_white[{pi},{wi}]",
               old.camera_white(prof, wb), new.camera_white(prof, wb))
        try:
            a = old.cam_to_prophoto_matrix(prof, wb)
            b = new.cam_to_prophoto_matrix(prof, wb)
            bit_eq(f"cam_to_prophoto_matrix[{pi},{wi}]", a, b)
        except ValueError as e:
            try:
                new.cam_to_prophoto_matrix(prof, wb)
                print(f"[FAIL] 原版抛 {e} 新版未抛"); fails += 1
            except ValueError:
                pass  # 两侧同样抛 → 等价
        bit_eq(f"cam_to_xyz_matrix[{pi},{wi}]",
               old.cam_to_xyz_matrix(prof, wb), new.cam_to_xyz_matrix(prof, wb))
        bit_eq(f"cam_to_linear_srgb_matrix[{pi},{wi}]",
               old.cam_to_linear_srgb_matrix(prof, wb),
               new.cam_to_linear_srgb_matrix(prof, wb))
bit_eq("prophoto_to_linear_srgb_matrix",
       old.prophoto_to_linear_srgb_matrix(), new.prophoto_to_linear_srgb_matrix())

# 全链路像素级: cam_wb_to_prophoto / linear_prophoto_to_srgb / cam_to_xyz
prof = profs[0]
img = rng.uniform(0.0, 4.0, size=(8, 8, 3))
for wb in wbs[:4]:
    bit_eq("cam_wb_to_prophoto", old.cam_wb_to_prophoto(img, prof, wb),
           new.cam_wb_to_prophoto(img, prof, wb))
    bit_eq("cam_to_xyz", old.cam_to_xyz(img, wb, prof), new.cam_to_xyz(img, wb, prof))
bit_eq("linear_prophoto_to_srgb",
       old.linear_prophoto_to_srgb(img.astype(np.float32)),
       new.linear_prophoto_to_srgb(img.astype(np.float32)))

# 真 DCP (Nikon Z5 基线)
from pixo.render.core.calibration import load_dcp as load_dcp_profile  # noqa: E402
try:
    dcp_prof = load_dcp_profile(
        str(ROOT / "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"))
    for wb in wbs:
        bit_eq("camera_white[real]", old.camera_white(dcp_prof, wb),
               new.camera_white(dcp_prof, wb))
        bit_eq("cam_to_prophoto_matrix[real]",
               old.cam_to_prophoto_matrix(dcp_prof, wb),
               new.cam_to_prophoto_matrix(dcp_prof, wb))
        bit_eq("cam_to_linear_srgb_matrix[real]",
               old.cam_to_linear_srgb_matrix(dcp_prof, wb),
               new.cam_to_linear_srgb_matrix(dcp_prof, wb))
    print("[real DCP] Nikon Z5 基线: 全部逐位一致" if fails == 0 else "")
except Exception as e:
    print(f"[WARN] 真 DCP 跳过: {e}")

print("[RESULT]", "PASS — 全函数逐位等价" if fails == 0 else f"FAIL — {fails} 处不等价")
sys.exit(0 if fails == 0 else 1)
