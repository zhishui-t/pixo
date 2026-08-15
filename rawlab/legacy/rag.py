"""RAG 鐭ヨ瘑搴?(闃舵6) 鈥斺€?杞婚噺鍚戦噺妫€绱? <100ms銆?
鐭ヨ瘑鏋勬垚 (璁″垝涔?搂闃舵6):
  - 椋庢牸鍗＄墖搴? 姣忎釜 LUT 鐨勬爣绛?鑹插僵鎸囩汗/褰辫皟鎸囩汗 (浠?LUT 瀹炴祴鐢熸垚)
  - 褰辫皟瑙勫垯搴? 涓嶅悓鍏夊満绫诲瀷鐨勬洕鍏夌瓥鐣?  - 鑹插僵瑙勫垯搴? 鑲よ壊鍋忚壊淇绛栫暐
  - 淇浘缁忛獙搴? 淇浘鎵嬪唽鎻愮偧鐨勮鍒?
妫€绱? 鍏抽敭璇?鈫?绋€鐤忓悜閲?(璇嶈) + cosine; 椋庢牸鎺ㄨ崘: 瑙嗚鐗瑰緛 鈫?椋庢牸鍗＄墖銆?"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

KB_DIR = Path(__file__).resolve().parent.parent / "kb"


@dataclass
class KbEntry:
    """鐭ヨ瘑鏉＄洰 (杞婚噺鐗? 瀵归綈璁″垝涔?4 鏉垮潡)銆?""
    id: str
    type: str                 # style / tone_rule / color_rule / experience
    title: str
    tags: List[str] = field(default_factory=list)
    text: str = ""            # 妫€绱㈢敤鏂囨湰
    content: dict = field(default_factory=dict)  # 缁撴瀯鍖栧唴瀹?    fingerprint: Optional[Dict[str, float]] = None  # 鑹插僵/褰辫皟鎸囩汗 (椋庢牸鍗?


class RagKB:
    """杞婚噺 RAG: 璇嶈鍚戦噺 + cosine 妫€绱€?""

    def __init__(self):
        self.entries: List[KbEntry] = []
        self._vocab: Dict[str, int] = {}
        self._vectors: Optional[np.ndarray] = None

    # 鈹€鈹€ 鏋勫缓 鈹€鈹€

    def add(self, entry: KbEntry):
        self.entries.append(entry)

    def build_index(self):
        """鏋勫缓璇嶈鍚戦噺绱㈠紩銆?""
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
        # L2 褰掍竴鍖?        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self._vectors = mat / norms

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        # 涓枃鎸夊瓧+璇嶅垏鍒?(绠€鍖? 鍗曞瓧 + 2-gram)
        text = text.lower()
        words = re.findall(r"[a-z0-9]+", text)
        chars = re.findall(r"[\u4e00-\u9fff]", text)
        toks = words + chars
        if len(chars) >= 2:
            toks += [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
        return toks

    # 鈹€鈹€ 妫€绱?鈹€鈹€

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

    # 鈹€鈹€ 椋庢牸鎺ㄨ崘 (瑙嗚鐗瑰緛 鈫?椋庢牸) 鈹€鈹€

    def recommend_style(self, vision_report: Dict) -> List[KbEntry]:
        """鏍规嵁瑙嗚鎶ュ憡鎺ㄨ崘椋庢牸鍗＄墖銆?
        瑙勫垯 (纭畾鎬?:
          - 浜哄儚 (subject.persons>0) 鈫?浼樺厛 portra/鑲よ壊鍙嬪ソ椋庢牸
          - 缁挎澶?鈫?鑷劧椋庡厜椋庢牸
          - 澶滄櫙/鏆?鈫?澶滄櫙椋庢牸
          - 榛戠櫧璐ㄦ劅 鈫?mono
          - 楗卞拰搴﹂珮鐨勫浘 鈫?楂橀ケ鍜岄鏍?        """
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


# 鈹€鈹€ 绉嶅瓙鐭ヨ瘑搴撴瀯寤?鈹€鈹€

def _fingerprint(profile: Dict[str, float], lut_path: Optional[Path] = None) -> Dict[str, float]:
    """鐢熸垚椋庢牸鎸囩汗: 浠?LUT 瀹炴祴鑹插僵/褰辫皟鐗瑰緛 (閲忓寲鐏伴樁/鑲よ壊甯?楗卞拰搴︽柟鍚?銆?
    profile: {portrait, nature, night, saturated, neutral} 0-1 鍏堥獙銆?    """
    fp = dict(profile)
    if lut_path and lut_path.exists():
        try:
            from ..lut import LUT3D
            lut = LUT3D.from_cube(lut_path)
            # 鐏伴樁杞? 鍙栦腑鎬ц緭鍏?(r=g=b) 鐨勮緭鍑?鈫?鑹茶皟鍋忕Щ
            n = lut.n
            idx = np.arange(n, dtype=np.float32) / (n - 1)
            gray_in = np.stack([idx, idx, idx], axis=-1)
            gray_out = lut.apply((gray_in * 255).astype(np.uint8)).astype(float) / 255
            warm = float((gray_out[:, 2] - gray_out[:, 0]).mean())  # b-r: 姝?鏆?            fp["warmth"] = round(warm, 3)
            # 楗卞拰搴? 绾壊杈撳叆 (绾?缁?钃? 杈撳嚭璺濈鐏拌酱
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
    """鏋勫缓绉嶅瓙鐭ヨ瘑搴?(璁″垝涔? 椋庢牸 5-8 + 褰辫皟瑙勫垯 + 鑹插僵瑙勫垯 + 缁忛獙, 鈮?00 鏉?銆?""
    kb = RagKB()
    LUT_DIR = Path(r"K:\work\project\guanlan\luts")

    # 鈹€鈹€ 1. 椋庢牸鍗＄墖 (鏍稿績 LUT + 鍏堥獙鎸囩汗) 鈹€鈹€
    styles = [
        ("style_portra", "Kodak Portra 鑳剁墖浜哄儚", ["portra", "鑳剁墖", "浜哄儚", "鑲よ壊"],
         "鏌揪 Portra 鑳剁墖妯℃嫙, 鑲よ壊閫氶€忚嚜鐒? 鏌斿拰楂樺厜, 閫傚悎浜哄儚",
         {"portrait": 0.9, "nature": 0.2, "night": 0.0, "saturated": 0.3, "neutral": 0.6},
         LUT_DIR / "kodak_vision3_250d.cube"),
        ("style_velvia", "瀵屽＋ Velvia 楂橀ケ鍜岄鍏?, ["velvia", "椋庡厜", "楂橀ケ鍜?, "瀵屽＋"],
         "瀵屽＋ Velvia 鍙嶈浆鐗囨ā鎷? 楂橀ケ鍜岄珮瀵规瘮, 缁挎/澶╃┖鑹插僵娴撻儊, 閫傚悎椋庡厜",
         {"portrait": 0.1, "nature": 0.9, "night": 0.0, "saturated": 0.95, "neutral": 0.2},
         LUT_DIR / "velvia.cube"),
        ("style_classic_neg", "瀵屽＋ Classic Negative 澶嶅彜", ["classic", "澶嶅彜", "鑳剁墖", "瀵屽＋"],
         "瀵屽＋ Classic Negative 妯℃嫙, 浣庨ケ鍜屾殩璋? 澶嶅彜鐢靛奖鎰? 閫傚悎琛楁媿/浜烘枃",
         {"portrait": 0.5, "nature": 0.4, "night": 0.3, "saturated": 0.3, "neutral": 0.7},
         LUT_DIR / "classic_neg.cube"),
        ("style_astia", "瀵屽＋ Astia 鏌斿拰浜哄儚", ["astia", "瀵屽＋", "鏌斿拰", "浜哄儚"],
         "瀵屽＋ Astia 妯℃嫙, 鏌斿拰涓棿璋? 鑲よ壊鑷劧, 閫傚悎瀹ゅ唴浜哄儚",
         {"portrait": 0.8, "nature": 0.3, "night": 0.0, "saturated": 0.5, "neutral": 0.7},
         LUT_DIR / "astia.cube"),
        ("style_mono", "榛戠櫧褰辫皟", ["榛戠櫧", "mono", "褰辫皟", "鑹烘湳"],
         "榛戠櫧鑳剁墖妯℃嫙, 鍘昏壊淇濈暀褰辫皟灞傛, 閫傚悎绾疄/鑹烘湳/寮哄厜褰?,
         {"portrait": 0.5, "nature": 0.3, "night": 0.2, "saturated": 0.0, "neutral": 1.0},
         LUT_DIR / "MonoPhotoRedux.cube"),
        ("style_teal_orange", "闈掓鐢靛奖鎰?, ["teal", "orange", "鐢靛奖", "闈掓"],
         "闈掓瀵规瘮椋庢牸, 闃村奖鍋忛潚楂樺厜鍋忔, 鐢靛奖璐ㄦ劅, 閫傚悎澶滄櫙/鍩庡競",
         {"portrait": 0.3, "nature": 0.2, "night": 0.8, "saturated": 0.7, "neutral": 0.3},
         LUT_DIR / "pan_teal_orange.cube"),
        ("style_cinetone", "鏉句笅鐢靛奖鑹茶皟", ["cinetone", "鏉句笅", "鐢靛奖", "鑲よ壊"],
         "鏉句笅 Cinetone 妯℃嫙, 鐢靛奖鑲よ壊杩樺師, 鑷劧杩囨浮, 閫傚悎瑙嗛/浜哄儚",
         {"portrait": 0.7, "nature": 0.3, "night": 0.3, "saturated": 0.5, "neutral": 0.8},
         LUT_DIR / "pan_cinetone.cube"),
        ("style_bleach", "婕傜櫧椋庢牸", ["bleach", "婕傜櫧", "纭湕", "鍩庡競"],
         "婕傜櫧椋庢牸, 寮哄姣旀繁闄嶉ケ鍜? 鍐疯皟纭湕, 閫傚悎鍩庡競/宸ヤ笟/鍙欎簨",
         {"portrait": 0.2, "nature": 0.2, "night": 0.6, "saturated": 0.1, "neutral": 0.5},
         LUT_DIR / "bleach_bypass.cube"),
    ]
    for sid, title, tags, text, prof, lutp in styles:
        kb.add(KbEntry(id=sid, type="style", title=title, tags=tags,
                       text=text, content={"style_id": sid},
                       fingerprint=_fingerprint(prof, lutp)))

    # 鈹€鈹€ 2. 褰辫皟瑙勫垯搴?(鍏夊満绫诲瀷 鈫?鏇濆厜绛栫暐) 鈹€鈹€
    tone_rules = [
        ("tone_daylight", "鏅存棩椤哄厜", ["鏅村ぉ", "椤哄厜", "鏃ュ厜"],
         "鏅存棩椤哄厜: 涓讳綋浜害鍏呰冻, 鏇濆厜鐩爣 115 鍙揪, 楂樺厜娉ㄦ剰淇濇姢 (p95 棰勬祴)", {}),
        ("tone_backlight", "閫嗗厜", ["閫嗗厜", "鑳屽厜", "鍓奖"],
         "閫嗗厜: 涓讳綋鍋忔殫鏄皼鍥? 涓嶅己琛屾彁浜富浣? 浼樺厛鎻愰槾褰变繚楂樺厜, 鏇濆厜淇璐熷悜鍑忓崐", {}),
        ("tone_underexposed", "鏋佺娆犳洕", ["娆犳洕", "鏆?, "浣庣収搴?],
         "鏋佺娆犳洕 (涓綅<60): 鎻愪寒鍙楅檺 (楂樺厜淇濇姢), 涓讳綋鏃犳硶杈炬爣鏃舵爣璁颁汉宸ュ鏍?, {}),
        ("tone_overexposed", "杩囨洕", ["杩囨洕", "楂樺厜", "婧㈠嚭"],
         "杩囨洕: 楂樺厜婧㈠嚭>3%, 鏇濆厜璐熷悜淇鍑忓崐, 鍘嬮珮鍏変繚缁嗚妭", {}),
        ("tone_indoors", "瀹ゅ唴寮卞厜", ["瀹ゅ唴", "寮卞厜", "閽ㄤ笣鐏?],
         "瀹ゅ唴寮卞厜: 鐧藉钩琛＄敤鐩告満 As Shot, 鏇濆厜鐩爣 115, 娉ㄦ剰 ISO 鍣偣", {}),
        ("tone_cloudy", "闃村ぉ鏁ｅ皠鍏?, ["闃村ぉ", "鏁ｅ皠", "鏌斿拰"],
         "闃村ぉ: 鍏夌嚎鏌斿拰瀵规瘮浣? 鏇濆厜鐩爣 115 鍙揪, 鍙€傚綋鍔犲姣?, {}),
    ]
    for tid, title, tags, text, fp in tone_rules:
        kb.add(KbEntry(id=tid, type="tone_rule", title=title, tags=tags,
                       text=text, content={}))

    # 鈹€鈹€ 3. 鑹插僵瑙勫垯搴?(鑲よ壊/鍋忚壊淇) 鈹€鈹€
    color_rules = [
        ("color_skin_warm", "鑲よ壊鍋忛粍淇", ["鑲よ壊", "鍋忛粍", "鏆?],
         "鑲よ壊 b>20: 闄嶉ケ鍜?寰皟, 鐩爣 b 12-20 鑷劧甯? 鐢?HSL 姗欓€氶亾", {}),
        ("color_skin_cool", "鑲よ壊鍋忕孩淇", ["鑲よ壊", "鍋忕孩", "鍝佺孩"],
         "鑲よ壊 a>25: 闄嶇孩楗卞拰, 鐩爣 a 14-22; 闃插搧绾?, {}),
        ("color_sky_cyan", "澶╃┖鍋忛潚", ["澶╃┖", "鍋忛潚", "闈?],
         "澶╃┖ b 杩囧ぇ: 鍘嬭摑/闈掗€氶亾, 淇濇寔鑷劧钃?, {}),
        ("color_green_teal", "缁挎鍋忛潚", ["缁挎", "鍋忛潚", "闈掔豢"],
         "缁挎 a 杩囪礋: 寰皟缁块€氶亾, 鐩爣 a -20~-30 鑷劧缁?, {}),
        ("color_gray_neutral", "鐏伴樁涓€?, ["鐏伴樁", "涓€?, "鐧藉钩琛?],
         "鐏伴樁 a/b 搴斺増0: 鍋忓樊澶ф椂鍏堟鏌ョ櫧骞宠　, 鍐嶆煡鐭╅樀閾捐矾", {}),
        ("color_lut_domain", "LUT 鑹插僵鍩?, ["LUT", "鑹插僵鍩?, "sRGB"],
         "LUT 蹇呴』鍦?sRGB gamma 鍩熸煡琛? 绾挎€у煙鐩村鑲よ壊 RMS 0.094 涓嶅彲鎺ュ彈", {}),
        ("color_warmth_direction", "鍐锋殩鏂瑰悜", ["鍐锋殩", "鑹叉俯", "鏂瑰悜"],
         "b>0 鍋忛粍(鏆? b<0 鍋忚摑(鍐?; a>0 鍋忕孩(鏆? a<0 鍋忕豢(鍐?; 淇鏂瑰悜鐪嬪亸宸鍙?, {}),
        ("color_skin_band", "鑲よ壊鑷劧甯?, ["鑲よ壊", "Lab", "鑷劧甯?],
         "鑷劧鑲よ壊 Lab 鍙傝€? a 14-22, b 12-20; 瓒呭嚭甯﹀厛鏌ョ櫧骞宠　鍐嶈皟閫氶亾", {}),
        ("color_sky_natural", "澶╃┖鑷劧钃?, ["澶╃┖", "鑷劧钃?, "Lab"],
         "鑷劧澶╃┖ Lab: b -20~-40 (鍋忚摑), a 鎺ヨ繎 0; b 杩囪礋鏄惧亣钃?, {}),
        ("color_green_natural", "缁挎鑷劧缁?, ["缁挎", "鑷劧缁?, "Lab"],
         "鑷劧缁挎 Lab: a -20~-30, b 10~25 (榛勭豢); a 杩囪礋鏄鹃潚榛?, {}),
        ("color_highlight_warm", "楂樺厜鍐锋殩", ["楂樺厜", "鍐锋殩", "灞傛"],
         "楂樺厜鍖哄亸鏆?鐨偆/鐏厜)鏄嚜鐒? 鍋忓喎鏄捐剰; 鐢ㄩ€氶亾鏇茬嚎寰皟楂樺厜绔偣", {}),
        ("color_shadow_cool", "闃村奖鍐锋殩", ["闃村奖", "鍐锋殩", "灞傛"],
         "闃村奖鍖鸿交寰亸鍐?钃?鏄兌鐗囨劅, 杩囧喎鏄捐剰; 閫傚害鎻愯摑淇濆眰娆?, {}),
        ("color_complement", "浜掕ˉ鑹蹭慨姝?, ["浜掕ˉ鑹?, "鍋忚壊", "淇"],
         "鍋忛粍鍔犺摑銆佸亸钃濆姞榛勩€佸亸缁垮姞鍝佺孩銆佸亸鍝佺孩鍔犵豢: 鐢ㄤ簰琛ヨ壊涓拰鍋忚壊", {}),
        ("color_sat_trim", "楗卞拰淇壀", ["楗卞拰", "淇壀", "灞傛"],
         "楂橀ケ鍜屽満鏅厛淇壀鍗曢€氶亾婧㈠嚭 (濡傜孩閫氶亾 >250) 鍐嶈皟鍏ㄥ眬, 闃茶壊鍧?, {}),
    ]
    for cid, title, tags, text, fp in color_rules:
        kb.add(KbEntry(id=cid, type="color_rule", title=title, tags=tags,
                       text=text, content={}))

    # 鈹€鈹€ 4. 淇浘缁忛獙搴?(淇浘鎵嬪唽鎻愮偧, 瑕嗙洊鏇濆厜/鏇茬嚎/HSL/缁嗚妭) 鈹€鈹€
    experiences = [
        ("exp_histogram", "鐩存柟鍥捐鍥?, ["鐩存柟鍥?, "鏇濆厜", "褰辫皟"],
         "鐩存柟鍥? 宸﹀爢=娆犳洕鍙冲爢=杩囨洕; 涓棿璋冨喅瀹氭暣浣撲寒搴? 楂樺厜瑁佸垏鍦?255 灏栧嘲", {}),
        ("exp_curve_s", "S 鏇茬嚎", ["鏇茬嚎", "瀵规瘮搴?, "S鏇茬嚎"],
         "S 鏇茬嚎澧炲己瀵规瘮: 鏆楅儴涓嬪帇浜儴鎻愬崌, 涓偣閿氬畾; 杩囧害 S 鏇茬嚎鎹熷け鐏伴樁杩囨浮", {}),
        ("exp_white_balance", "鐧藉钩琛″師鍒?, ["鐧藉钩琛?, "鑹叉俯", "鍋忚壊"],
         "鐧藉钩琛′笉鐚? 淇濈暀鐩告満 As Shot; 鍋忚壊鍏堟煡 WB 鍐嶅姩鐭╅樀", {}),
        ("exp_highlight_protect", "楂樺厜淇濇姢", ["楂樺厜", "淇濇姢", "婧㈠嚭"],
         "楂樺厜婧㈠嚭>3% 鏃惰礋鍚戜慨姝ｅ噺鍗? 鎻愪寒鐢?p95 棰勬祴闃叉媺鐖?, {}),
        ("exp_shadow_recovery", "鏆楅儴鎭㈠", ["鏆楅儴", "闃村奖", "鎭㈠"],
         "鏆楅儴瑁佸垏<5 鍗冲彲; 鏋佺娆犳洕鎻愪寒浼氬紩鍏ュ櫔鐐? 鏉冭　澶勭悊", {}),
        ("exp_noise", "鍣偣鎺у埗", ["鍣偣", "ISO", "闄嶅櫔"],
         "楂?ISO 鍣偣澶? 鏆楅儴鎻愪寒鏀惧ぇ鍣偣; 鍏堥檷鍣啀鎻愪寒", {}),
        ("exp_sharpness", "閿愬寲鍘熷垯", ["閿愬寲", "娓呮櫚搴?, "缁嗚妭"],
         "閿愬寲鍦ㄩ檷鍣悗; 杈圭紭閿愬寲涓轰富, 閬垮厤杩囧害閿愬寲鍑虹幇鍏夋檿", {}),
        ("exp_skin_retouch", "鑲よ壊淇浘娴佺▼", ["鑲よ壊", "淇浘", "娴佺▼"],
         "鑲よ壊: 鐧藉钩琛♀啋鏇濆厜鈫掕偆鑹?Lab 妫€娴嬧啋HSL 姗欓€氶亾寰皟; 鐩爣 a14-22 b12-20", {}),
        ("exp_saturation", "楗卞拰搴︽帶鍒?, ["楗卞拰搴?, "鑹插僵", "鑷劧"],
         "楗卞拰搴﹀畞灏戝嬁澶? 鍏ㄥ眬楗卞拰杩囬珮鎹熷け灞傛, 灞€閮ㄩ€氶亾璋冩暣鏇磋嚜鐒?, {}),
        ("exp_lut_selection", "LUT 閫夊瀷", ["LUT", "閫夊瀷", "椋庢牸"],
         "浜哄儚鈫扨ortra/Astia, 椋庡厜鈫扸elvia, 琛楁媿鈫扖lassicNeg, 澶滄櫙鈫扵ealOrange", {}),
        ("exp_exposure_target", "鏇濆厜鐩爣", ["鏇濆厜", "鐩爣", "115"],
         "涓讳綋鐩爣浜害 115 (0-255): 浜鸿劯浼樺厛, 鏃犺劯鐢ㄥ叏鍥句腑浣?, {}),
        ("exp_batch_strategy", "鎵归噺绛栫暐", ["鎵归噺", "绛栫暐", "鏁堢巼"],
         "鎵归噺: 璇婃柇鐢?half_size (0.8s), 鏈€缁堣緭鍑哄叏灏哄; 鏇濆厜闂幆鈮?杞?, {}),
        # 鈹€鈹€ 琛ュ厖缁嗗寲 (鎵╁厖鍒?100+) 鈹€鈹€
        ("exp_wb_as_shot", "As Shot 鐧藉钩琛?, ["鐧藉钩琛?, "As Shot", "鐩告満"],
         "鐩告満 As Shot 鐧藉钩琛′笌 Nikon MakerNote WhiteBalanceRBCoeff 涓€鑷? 鐩存帴鍙敤", {}),
        ("exp_dcp_forward", "DCP ForwardMatrix", ["DCP", "ForwardMatrix", "鑹插僵"],
         "DCP 娓叉煋蹇呴』鐢?ForwardMatrix (琛屽拰=D50 鐧界偣), 涓嶆槸 ColorMatrix (杈撳嚭 StdA 闇€棰濆閫傞厤)", {}),
        ("exp_dcp_illuminant", "鏍″噯鐓ф槑浣?, ["DCP", "鐓ф槑浣?, "StdA"],
         "Z5 II DCP tag C65A=17 鍗虫牎鍑嗙収鏄庝綋 StdA (2856K); 褰卞搷鐭╅樀搴旂敤鏂瑰紡", {}),
        ("exp_raw_linear", "raw 绾挎€у煙", ["raw", "绾挎€?, "鑹插僵鍩?],
         "rawpy ColorSpace.raw 杈撳嚭绾挎€х浉鏈?RGB; 鏇濆厜鍦ㄧ嚎鎬у煙涔?2^ev 鐗╃悊姝ｇ‘", {}),
        ("exp_gamma_lut", "gamma 鏌ヨ〃", ["gamma", "鎬ц兘", "鏌ヨ〃"],
         "gamma 缂栫爜鐢?16bit 鏌ヨ〃 (65536 椤? 鏇夸唬閫愬儚绱犲箓, 0.65s鈫?.12s", {}),
        ("exp_half_size", "half_size 璇婃柇", ["half_size", "鎬ц兘", "璇婃柇"],
         "璇婃柇/闂幆鐢?half_size (0.8s/寮?, 鏈€缁堣緭鍑哄叏灏哄; 婊¤冻 <2s 楠屾敹", {}),
        ("exp_yoloe_gpu", "YOLOE GPU 妫€娴?, ["YOLOE", "GPU", "涓讳綋"],
         "YOLOE-26L GPU 0.5s/寮? 鍔犺浇 13s 涓€娆℃€? 浜鸿劯浼樺厛纭畾涓讳綋浜害", {}),
        ("exp_lut_domain_srgb", "LUT 鑹插僵鍩?, ["LUT", "sRGB", "鍩?],
         "LUT 鍦?sRGB gamma 鍩熸煡琛? 绾挎€у煙鐩村鑲よ壊 RMS 0.094 涓嶅彲鎺ュ彈", {}),
        ("exp_lut_256cube", "LUT 256鲁 鏌ヨ〃", ["LUT", "鏌ヨ〃", "鎬ц兘"],
         "LUT 搴旂敤棰勮绠?256鲁 琛?(50MB, 寤鸿〃 16s 涓€娆?, 涔嬪悗 half_size 0.2s", {}),
        ("exp_lut_strength", "LUT 寮哄害", ["LUT", "寮哄害", "娣峰悎"],
         "LUT 寮哄害 0-1 绾挎€ф贩鍚堝師鍥句笌 LUT 杈撳嚭, 寮哄害 50% 鑹插僵浠嬩簬涓棿", {}),
        ("exp_snow", "闆櫙鏇濆厜", ["闆櫙", "鏇濆厜", "鐧?],
         "闆櫙鏁翠綋浜? 涓讳綋浜害鍙兘宸查珮, 璐熷悜淇闃查珮鍏夋孩鍑? 鐧藉钩琛″亸钃濇甯?, {}),
        ("exp_night", "澶滄櫙鏇濆厜", ["澶滄櫙", "鏇濆厜", "鐏厜"],
         "澶滄櫙: 鐏厜楂樺厜鏄撴孩鍑? 涓讳綋鏆楁槸姘涘洿; 鏇濆厜浠ヤ富浣撲负鍑? 楂樺厜淇濇姢浼樺厛", {}),
        ("exp_portrait_wb", "浜哄儚鐧藉钩琛?, ["浜哄儚", "鐧藉钩琛?, "鑲よ壊"],
         "浜哄儚鐧藉钩琛′互鑲よ壊涓哄噯: 瀹ゅ唴鏆栧厜淇濈暀 As Shot, 娣峰悎鍏夋墜鍔ㄦ牎姝ｈ偆鑹插甫", {}),
        ("exp_architecture", "寤虹瓚鏇濆厜", ["寤虹瓚", "鏇濆厜", "绾挎潯"],
         "寤虹瓚: 澶╃┖楂樺厜淇濇姢, 涓讳綋浜害浠ョ珛闈负鍑? 寮洪€忚娉ㄦ剰杈圭紭", {}),
    ]
    for eid, title, tags, text, fp in experiences:
        kb.add(KbEntry(id=eid, type="experience", title=title, tags=tags,
                       text=text, content={}))

    kb.build_index()
    return kb


if __name__ == "__main__":
    kb = build_seed_kb()
    print(f"绉嶅瓙鐭ヨ瘑搴? {len(kb)} 鏉?)
    kb.save()
    print("宸蹭繚瀛?->", KB_DIR / "kb.json")
