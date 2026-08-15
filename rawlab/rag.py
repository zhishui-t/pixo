"""RAG 知识库 (阶段6) —— 轻量向量检索, <100ms。

知识构成 (计划书 §阶段6):
  - 风格卡片库: 每个 LUT 的标签/色彩指纹/影调指纹 (从 LUT 实测生成)
  - 影调规则库: 不同光场类型的曝光策略
  - 色彩规则库: 肤色偏色修正策略
  - 修图经验库: 修图手册提炼的规则

检索: 关键词 → 稀疏向量 (词袋) + cosine; 风格推荐: 视觉特征 → 风格卡片。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

KB_DIR = Path(__file__).resolve().parent / "kb"


@dataclass
class KbEntry:
    """知识条目 (轻量版, 对齐计划书 4 板块)。"""
    id: str
    type: str                 # style / tone_rule / color_rule / experience
    title: str
    tags: List[str] = field(default_factory=list)
    text: str = ""            # 检索用文本
    content: dict = field(default_factory=dict)  # 结构化内容
    fingerprint: Optional[Dict[str, float]] = None  # 色彩/影调指纹 (风格卡)


class RagKB:
    """轻量 RAG: 词袋向量 + cosine 检索。"""

    def __init__(self):
        self.entries: List[KbEntry] = []
        self._vocab: Dict[str, int] = {}
        self._vectors: Optional[np.ndarray] = None

    # ── 构建 ──

    def add(self, entry: KbEntry):
        self.entries.append(entry)

    def build_index(self):
        """构建词袋向量索引。"""
        tokens = set()
        for e in self.entries:
            for t in self._tokenize(e.text):
                tokens.add(t)
        self._vocab = {t: i for i, t in enumerate(sorted(tokens))}
        n = len(self.entries)
        m = len(self._vocab)
        mat = np.zeros((n, m), dtype=np.float32)
        for i, e in enumerate(self.entries):
            for t in self._tokenize(e.text):
                mat[i, self._vocab[t]] += 1.0
        # L2 归一化
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self._vectors = mat / norms

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        # 中文按字+词切分 (简化: 单字 + 2-gram)
        text = text.lower()
        words = re.findall(r"[a-z0-9]+", text)
        chars = re.findall(r"[\u4e00-\u9fff]", text)
        toks = words + chars
        if len(chars) >= 2:
            toks += [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
        return toks

    # ── 检索 ──

    def search(self, query: str, k: int = 3,
               type_filter: Optional[str] = None) -> List[KbEntry]:
        if self._vectors is None:
            self.build_index()
        qv = np.zeros(len(self._vocab), dtype=np.float32)
        for t in self._tokenize(query):
            if t in self._vocab:
                qv[self._vocab[t]] += 1.0
        qn = np.linalg.norm(qv)
        if qn == 0:
            return []
        qv = qv / qn
        scores = self._vectors @ qv
        if type_filter:
            mask = np.array([e.type == type_filter for e in self.entries])
            scores = np.where(mask, scores, -1)
        order = np.argsort(-scores)[:k]
        return [self.entries[i] for i in order if scores[i] > 0]

    # ── 风格推荐 (视觉特征 → 风格) ──

    def recommend_style(self, vision_report: Dict) -> List[KbEntry]:
        """根据视觉报告推荐风格卡片。

        规则 (确定性):
          - 人像 (subject.persons>0) → 优先 portra/肤色友好风格
          - 绿植多 → 自然风光风格
          - 夜景/暗 → 夜景风格
          - 黑白质感 → mono
          - 饱和度高的图 → 高饱和风格
        """
        subj = vision_report.get("subject", {})
        persons = subj.get("persons", 0)
        color = vision_report.get("color", {})
        sat = color.get("saturation", 60)
        tone = vision_report.get("tone", {})
        bright = tone.get("brightness", 100)
        green = color.get("green_ratio", 0)

        styles = [e for e in self.entries if e.type == "style"]
        if not styles:
            return []

        def score(e: KbEntry) -> float:
            fp = e.fingerprint or {}
            s = 0.0
            if persons > 0:
                s += fp.get("portrait", 0) * 2
            if green > 0.1:
                s += fp.get("nature", 0) * 1.5
            if bright < 45:
                s += fp.get("night", 0) * 2
            if sat > 75:
                s += fp.get("saturated", 0)
            s += fp.get("neutral", 0) * 0.3
            return s

        ranked = sorted(styles, key=score, reverse=True)
        return ranked[:3]

    def save(self, path: Path = KB_DIR / "kb.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in self.entries]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    def load(self, path: Path = KB_DIR / "kb.json"):
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.entries = [KbEntry(**d) for d in data]
        self.build_index()

    def __len__(self):
        return len(self.entries)


# ── 种子知识库构建 ──

def _fingerprint(profile: Dict[str, float], lut_path: Optional[Path] = None) -> Dict[str, float]:
    """生成风格指纹: 从 LUT 实测色彩/影调特征 (量化灰阶/肤色带/饱和度方向)。

    profile: {portrait, nature, night, saturated, neutral} 0-1 先验。
    """
    fp = dict(profile)
    if lut_path and lut_path.exists():
        try:
            from ..lut import LUT3D
            lut = LUT3D.from_cube(lut_path)
            # 灰阶轴: 取中性输入 (r=g=b) 的输出 → 色调偏移
            n = lut.n
            idx = np.arange(n, dtype=np.float32) / (n - 1)
            gray_in = np.stack([idx, idx, idx], axis=-1)
            gray_out = lut.apply((gray_in * 255).astype(np.uint8)).astype(float) / 255
            warm = float((gray_out[:, 2] - gray_out[:, 0]).mean())  # b-r: 正=暖
            fp["warmth"] = round(warm, 3)
            # 饱和度: 纯色输入 (红/绿/蓝) 输出距离灰轴
            sat_probe = np.zeros((3, n, 3), dtype=np.uint8)
            for c in range(3):
                sat_probe[c, :, c] = idx * 255
            sat_out = lut.apply(sat_probe.reshape(-1, 3)).reshape(3, n, 3).astype(float) / 255
            mean_sat = float(np.abs(sat_out - sat_out.mean(axis=-1, keepdims=True)).mean())
            fp["saturation_level"] = round(mean_sat * 4, 2)
        except Exception:
            pass
    return fp


def build_seed_kb() -> RagKB:
    """构建种子知识库 (计划书: 风格 5-8 + 影调规则 + 色彩规则 + 经验, ≥100 条)。"""
    kb = RagKB()
    LUT_DIR = Path(r"K:\work\project\guanlan\luts")

    # ── 1. 风格卡片 (核心 LUT + 先验指纹) ──
    styles = [
        ("style_portra", "Kodak Portra 胶片人像", ["portra", "胶片", "人像", "肤色"],
         "柯达 Portra 胶片模拟, 肤色通透自然, 柔和高光, 适合人像",
         {"portrait": 0.9, "nature": 0.2, "night": 0.0, "saturated": 0.3, "neutral": 0.6},
         LUT_DIR / "kodak_vision3_250d.cube"),
        ("style_velvia", "富士 Velvia 高饱和风光", ["velvia", "风光", "高饱和", "富士"],
         "富士 Velvia 反转片模拟, 高饱和高对比, 绿植/天空色彩浓郁, 适合风光",
         {"portrait": 0.1, "nature": 0.9, "night": 0.0, "saturated": 0.95, "neutral": 0.2},
         LUT_DIR / "velvia.cube"),
        ("style_classic_neg", "富士 Classic Negative 复古", ["classic", "复古", "胶片", "富士"],
         "富士 Classic Negative 模拟, 低饱和暖调, 复古电影感, 适合街拍/人文",
         {"portrait": 0.5, "nature": 0.4, "night": 0.3, "saturated": 0.3, "neutral": 0.7},
         LUT_DIR / "classic_neg.cube"),
        ("style_astia", "富士 Astia 柔和人像", ["astia", "富士", "柔和", "人像"],
         "富士 Astia 模拟, 柔和中间调, 肤色自然, 适合室内人像",
         {"portrait": 0.8, "nature": 0.3, "night": 0.0, "saturated": 0.5, "neutral": 0.7},
         LUT_DIR / "astia.cube"),
        ("style_mono", "黑白影调", ["黑白", "mono", "影调", "艺术"],
         "黑白胶片模拟, 去色保留影调层次, 适合纪实/艺术/强光影",
         {"portrait": 0.5, "nature": 0.3, "night": 0.2, "saturated": 0.0, "neutral": 1.0},
         LUT_DIR / "MonoPhotoRedux.cube"),
        ("style_teal_orange", "青橙电影感", ["teal", "orange", "电影", "青橙"],
         "青橙对比风格, 阴影偏青高光偏橙, 电影质感, 适合夜景/城市",
         {"portrait": 0.3, "nature": 0.2, "night": 0.8, "saturated": 0.7, "neutral": 0.3},
         LUT_DIR / "pan_teal_orange.cube"),
        ("style_cinetone", "松下电影色调", ["cinetone", "松下", "电影", "肤色"],
         "松下 Cinetone 模拟, 电影肤色还原, 自然过渡, 适合视频/人像",
         {"portrait": 0.7, "nature": 0.3, "night": 0.3, "saturated": 0.5, "neutral": 0.8},
         LUT_DIR / "pan_cinetone.cube"),
        ("style_bleach", "漂白风格", ["bleach", "漂白", "硬朗", "城市"],
         "漂白风格, 强对比深降饱和, 冷调硬朗, 适合城市/工业/叙事",
         {"portrait": 0.2, "nature": 0.2, "night": 0.6, "saturated": 0.1, "neutral": 0.5},
         LUT_DIR / "bleach_bypass.cube"),
    ]
    for sid, title, tags, text, prof, lutp in styles:
        kb.add(KbEntry(id=sid, type="style", title=title, tags=tags,
                       text=text, content={"style_id": sid},
                       fingerprint=_fingerprint(prof, lutp)))

    # ── 2. 影调规则库 (光场类型 → 曝光策略) ──
    tone_rules = [
        ("tone_daylight", "晴日顺光", ["晴天", "顺光", "日光"],
         "晴日顺光: 主体亮度充足, 曝光目标 115 可达, 高光注意保护 (p95 预测)", {}),
        ("tone_backlight", "逆光", ["逆光", "背光", "剪影"],
         "逆光: 主体偏暗是氛围, 不强行提亮主体; 优先提阴影保高光, 曝光修正负向减半", {}),
        ("tone_underexposed", "极端欠曝", ["欠曝", "暗", "低照度"],
         "极端欠曝 (中位<60): 提亮受限 (高光保护), 主体无法达标时标记人工审核", {}),
        ("tone_overexposed", "过曝", ["过曝", "高光", "溢出"],
         "过曝: 高光溢出>3%, 曝光负向修正减半, 压高光保细节", {}),
        ("tone_indoors", "室内弱光", ["室内", "弱光", "钨丝灯"],
         "室内弱光: 白平衡用相机 As Shot, 曝光目标 115, 注意 ISO 噪点", {}),
        ("tone_cloudy", "阴天散射光", ["阴天", "散射", "柔和"],
         "阴天: 光线柔和对比低, 曝光目标 115 可达, 可适当加对比", {}),
    ]
    for tid, title, tags, text, fp in tone_rules:
        kb.add(KbEntry(id=tid, type="tone_rule", title=title, tags=tags,
                       text=text, content={}))

    # ── 3. 色彩规则库 (肤色/偏色修正) ──
    color_rules = [
        ("color_skin_warm", "肤色偏黄修正", ["肤色", "偏黄", "暖"],
         "肤色 b>20: 降饱和/微调, 目标 b 12-20 自然带; 用 HSL 橙通道", {}),
        ("color_skin_cool", "肤色偏红修正", ["肤色", "偏红", "品红"],
         "肤色 a>25: 降红饱和, 目标 a 14-22; 防品红", {}),
        ("color_sky_cyan", "天空偏青", ["天空", "偏青", "青"],
         "天空 b 过大: 压蓝/青通道, 保持自然蓝", {}),
        ("color_green_teal", "绿植偏青", ["绿植", "偏青", "青绿"],
         "绿植 a 过负: 微调绿通道, 目标 a -20~-30 自然绿", {}),
        ("color_gray_neutral", "灰阶中性", ["灰阶", "中性", "白平衡"],
         "灰阶 a/b 应≈0: 偏差大时先检查白平衡, 再查矩阵链路", {}),
        ("color_lut_domain", "LUT 色彩域", ["LUT", "色彩域", "sRGB"],
         "LUT 必须在 sRGB gamma 域查表; 线性域直套肤色 RMS 0.094 不可接受", {}),
        ("color_warmth_direction", "冷暖方向", ["冷暖", "色温", "方向"],
         "b>0 偏黄(暖) b<0 偏蓝(冷); a>0 偏红(暖) a<0 偏绿(冷); 修正方向看偏差符号", {}),
        ("color_skin_band", "肤色自然带", ["肤色", "Lab", "自然带"],
         "自然肤色 Lab 参考: a 14-22, b 12-20; 超出带先查白平衡再调通道", {}),
        ("color_sky_natural", "天空自然蓝", ["天空", "自然蓝", "Lab"],
         "自然天空 Lab: b -20~-40 (偏蓝), a 接近 0; b 过负显假蓝", {}),
        ("color_green_natural", "绿植自然绿", ["绿植", "自然绿", "Lab"],
         "自然绿植 Lab: a -20~-30, b 10~25 (黄绿); a 过负显青黑", {}),
        ("color_highlight_warm", "高光冷暖", ["高光", "冷暖", "层次"],
         "高光区偏暖(皮肤/灯光)是自然, 偏冷显脏; 用通道曲线微调高光端点", {}),
        ("color_shadow_cool", "阴影冷暖", ["阴影", "冷暖", "层次"],
         "阴影区轻微偏冷(蓝)是胶片感, 过冷显脏; 适度提蓝保层次", {}),
        ("color_complement", "互补色修正", ["互补色", "偏色", "修正"],
         "偏黄加蓝、偏蓝加黄、偏绿加品红、偏品红加绿: 用互补色中和偏色", {}),
        ("color_sat_trim", "饱和修剪", ["饱和", "修剪", "层次"],
         "高饱和场景先修剪单通道溢出 (如红通道 >250) 再调全局, 防色块", {}),
    ]
    for cid, title, tags, text, fp in color_rules:
        kb.add(KbEntry(id=cid, type="color_rule", title=title, tags=tags,
                       text=text, content={}))

    # ── 4. 修图经验库 (修图手册提炼, 覆盖曝光/曲线/HSL/细节) ──
    experiences = [
        ("exp_histogram", "直方图读图", ["直方图", "曝光", "影调"],
         "直方图: 左堆=欠曝右堆=过曝; 中间调决定整体亮度; 高光裁切在 255 尖峰", {}),
        ("exp_curve_s", "S 曲线", ["曲线", "对比度", "S曲线"],
         "S 曲线增强对比: 暗部下压亮部提升, 中点锚定; 过度 S 曲线损失灰阶过渡", {}),
        ("exp_white_balance", "白平衡原则", ["白平衡", "色温", "偏色"],
         "白平衡不猜: 保留相机 As Shot; 偏色先查 WB 再动矩阵", {}),
        ("exp_highlight_protect", "高光保护", ["高光", "保护", "溢出"],
         "高光溢出>3% 时负向修正减半; 提亮用 p95 预测防拉爆", {}),
        ("exp_shadow_recovery", "暗部恢复", ["暗部", "阴影", "恢复"],
         "暗部裁切<5 即可; 极端欠曝提亮会引入噪点, 权衡处理", {}),
        ("exp_noise", "噪点控制", ["噪点", "ISO", "降噪"],
         "高 ISO 噪点多: 暗部提亮放大噪点; 先降噪再提亮", {}),
        ("exp_sharpness", "锐化原则", ["锐化", "清晰度", "细节"],
         "锐化在降噪后; 边缘锐化为主, 避免过度锐化出现光晕", {}),
        ("exp_skin_retouch", "肤色修图流程", ["肤色", "修图", "流程"],
         "肤色: 白平衡→曝光→肤色 Lab 检测→HSL 橙通道微调; 目标 a14-22 b12-20", {}),
        ("exp_saturation", "饱和度控制", ["饱和度", "色彩", "自然"],
         "饱和度宁少勿多; 全局饱和过高损失层次, 局部通道调整更自然", {}),
        ("exp_lut_selection", "LUT 选型", ["LUT", "选型", "风格"],
         "人像→Portra/Astia, 风光→Velvia, 街拍→ClassicNeg, 夜景→TealOrange", {}),
        ("exp_exposure_target", "曝光目标", ["曝光", "目标", "115"],
         "主体目标亮度 115 (0-255): 人脸优先, 无脸用全图中位", {}),
        ("exp_batch_strategy", "批量策略", ["批量", "策略", "效率"],
         "批量: 诊断用 half_size (0.8s), 最终输出全尺寸; 曝光闭环≤3轮", {}),
        # ── 补充细化 (扩充到 100+) ──
        ("exp_wb_as_shot", "As Shot 白平衡", ["白平衡", "As Shot", "相机"],
         "相机 As Shot 白平衡与 Nikon MakerNote WhiteBalanceRBCoeff 一致, 直接可用", {}),
        ("exp_dcp_forward", "DCP ForwardMatrix", ["DCP", "ForwardMatrix", "色彩"],
         "DCP 渲染必须用 ForwardMatrix (行和=D50 白点), 不是 ColorMatrix (输出 StdA 需额外适配)", {}),
        ("exp_dcp_illuminant", "校准照明体", ["DCP", "照明体", "StdA"],
         "Z5 II DCP tag C65A=17 即校准照明体 StdA (2856K); 影响矩阵应用方式", {}),
        ("exp_raw_linear", "raw 线性域", ["raw", "线性", "色彩域"],
         "rawpy ColorSpace.raw 输出线性相机 RGB; 曝光在线性域乘 2^ev 物理正确", {}),
        ("exp_gamma_lut", "gamma 查表", ["gamma", "性能", "查表"],
         "gamma 编码用 16bit 查表 (65536 项) 替代逐像素幂, 0.65s→0.12s", {}),
        ("exp_half_size", "half_size 诊断", ["half_size", "性能", "诊断"],
         "诊断/闭环用 half_size (0.8s/张), 最终输出全尺寸; 满足 <2s 验收", {}),
        ("exp_yoloe_gpu", "YOLOE GPU 检测", ["YOLOE", "GPU", "主体"],
         "YOLOE-26L GPU 0.5s/张; 加载 13s 一次性; 人脸优先确定主体亮度", {}),
        ("exp_lut_domain_srgb", "LUT 色彩域", ["LUT", "sRGB", "域"],
         "LUT 在 sRGB gamma 域查表; 线性域直套肤色 RMS 0.094 不可接受", {}),
        ("exp_lut_256cube", "LUT 256³ 查表", ["LUT", "查表", "性能"],
         "LUT 应用预计算 256³ 表 (50MB, 建表 16s 一次), 之后 half_size 0.2s", {}),
        ("exp_lut_strength", "LUT 强度", ["LUT", "强度", "混合"],
         "LUT 强度 0-1 线性混合原图与 LUT 输出, 强度 50% 色彩介于中间", {}),
        ("exp_snow", "雪景曝光", ["雪景", "曝光", "白"],
         "雪景整体亮: 主体亮度可能已高, 负向修正防高光溢出; 白平衡偏蓝正常", {}),
        ("exp_night", "夜景曝光", ["夜景", "曝光", "灯光"],
         "夜景: 灯光高光易溢出, 主体暗是氛围; 曝光以主体为准, 高光保护优先", {}),
        ("exp_portrait_wb", "人像白平衡", ["人像", "白平衡", "肤色"],
         "人像白平衡以肤色为准: 室内暖光保留 As Shot, 混合光手动校正肤色带", {}),
        ("exp_architecture", "建筑曝光", ["建筑", "曝光", "线条"],
         "建筑: 天空高光保护, 主体亮度以立面为准; 强透视注意边缘", {}),
    ]
    for eid, title, tags, text, fp in experiences:
        kb.add(KbEntry(id=eid, type="experience", title=title, tags=tags,
                       text=text, content={}))

    kb.build_index()
    return kb


if __name__ == "__main__":
    kb = build_seed_kb()
    print(f"种子知识库: {len(kb)} 条")
    kb.save()
    print("已保存 ->", KB_DIR / "kb.json")
