# -*- coding: utf-8 -*-
"""t96 生成器：LUT 第三批 8 张胶片卡（一次性脚本）。"""
import json, os

D = "configs/styles/films"

def bands(*overrides):
    default = [
        {"name": n, "hue_center": hc, "width": 45.0, "hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0}
        for n, hc in [("red",0),("orange",30),("yellow",60),("green",120),
                      ("aqua",180),("blue",240),("purple",270),("magenta",300)]
    ]
    by = {d["name"]: d for d in default}
    for ov in overrides:
        by[ov["name"]].update({k: v for k, v in ov.items() if k != "name"})
    order = [d["name"] for d in default]
    return [by[n] for n in order]

KODAK_STAGES = ["exposure","whitebalance","tone","hsl","huesat","dehaze","clarity","colorcal","split_tone","skin","stylize","refine"]
FUJI_STAGES  = ["exposure","whitebalance","tone","huesat","colorcal","skin","stylize","refine"]

def full_card(band_over, **kw):
    return {
        "stages": KODAK_STAGES,
        "params": {
            "exposure": {"mode": "auto"},
            "whitebalance": {"mode": "as_shot", "trim": kw["trim"]},
            "tone": {"use_filmic": True, "contrast": kw["contrast"], "toe": kw["toe"],
                     "shoulder": kw["shoulder"], "brightness": kw["brightness"]},
            "hsl": {"enabled": True, "smooth": kw.get("smooth", 0.8), "bands": json.dumps(bands(*band_over))},
            "huesat": {"enabled": False},
            "dehaze": {"enabled": False, "strength": 0.3, "radius": 15},
            "clarity": {"enabled": True, "strength": kw.get("clarity", 0.3)},
            "colorcal": {"vibrance": kw["vibrance"], "saturation": kw.get("sat", 0.0),
                         **(kw.get("ccextra") or {})},
            "split_tone": {"enabled": True,
                           "highlights_hue": kw.get("hl_hue", 45), "highlights_sat": kw.get("hl_sat", 4),
                           "shadows_hue": kw.get("sh_hue", 40), "shadows_sat": kw.get("sh_sat", 2),
                           "balance": kw.get("bal", 0.55), "strength": kw.get("st_str", 0.45)},
            "skin": {"enabled": kw.get("skin", True), "strength": kw.get("skin_str", 0.4)},
            "stylize": {},
            "refine": {"sharpen": kw.get("sharpen", 0.3), "chroma_denoise": kw.get("chroma", 1.0),
                       "highlight_desat": kw.get("hl_desat", 0.55)},
        },
        "output": {"quality": 95},
    }

def fuji_card(**kw):
    return {
        "stages": FUJI_STAGES,
        "params": {
            "exposure": {"mode": "auto"},
            "whitebalance": {"mode": "as_shot", "trim": kw["trim"]},
            "tone": {"use_filmic": True, "contrast": kw["contrast"], "toe": kw["toe"],
                     "shoulder": kw["shoulder"], "brightness": kw["brightness"]},
            "huesat": {"enabled": True, "strength": kw.get("hs", 0.3)},
            "colorcal": {"vibrance": kw["vibrance"], "saturation": kw.get("sat", 0.0)},
            "skin": {"enabled": kw.get("skin", True), "strength": kw.get("skin_str", 0.5)},
            "stylize": {},
            "refine": {"sharpen": kw.get("sharpen", 0.3), "chroma_denoise": kw.get("chroma", 0.9),
                       "highlight_desat": kw.get("hl_desat", 0.5)},
        },
        "output": {"quality": 95},
    }

def write(name, card, meta):
    card["metadata"] = meta
    path = os.path.join(D, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("wrote", name)

# 1 Portra 160NC
c = full_card(
    [{"name":"red","saturation":2}, {"name":"orange","saturation":3,"luminance":2}],
    trim=[1.006,1.0,0.994], contrast=0.06, toe=0.16, shoulder=0.3, brightness=0.3,
    vibrance=0.05, sat=-0.06, ccextra={"skin_protect":0.65}, smooth=0.9,
    hl_sat=3, sh_sat=2, st_str=0.35, skin_str=0.65, sharpen=0.26, chroma=1.2, hl_desat=0.6)
write("kodak_portra_160nc.json", c, dict(family="Kodak", label="Portra 160NC",
    tags=["portrait","pastel","neutral"], scenes=["portrait","wedding","still_life"],
    character="Portra 160NC 自然色版：低饱和、柔和过渡、肤色细腻，反差温柔颗粒极细。",
    year=2002, grain_proxy=0.12))

# 2 Portra 400NC
c = full_card(
    [{"name":"red","saturation":3}, {"name":"orange","saturation":4,"luminance":2}],
    trim=[1.008,1.0,0.992], contrast=0.1, toe=0.15, shoulder=0.3, brightness=0.32,
    vibrance=0.08, sat=-0.04, ccextra={"skin_protect":0.6}, smooth=0.85,
    hl_sat=4, sh_sat=2, st_str=0.4, skin_str=0.55, sharpen=0.28, chroma=1.1, hl_desat=0.58)
write("kodak_portra_400nc.json", c, dict(family="Kodak", label="Portra 400NC",
    tags=["portrait","neutral","soft"], scenes=["portrait","wedding","indoor"],
    character="Portra 400NC 自然色版：媲美 160NC 的低饱和柔和，略暖、反差略增，中等细腻颗粒适合人像。",
    year=2002, grain_proxy=0.2))

# 3 Ultramax 400
c = full_card(
    [{"name":"red","saturation":7},{"name":"orange","saturation":8,"luminance":2},
     {"name":"yellow","saturation":6},{"name":"green","saturation":4}],
    trim=[1.015,1.0,0.985], contrast=0.2, toe=0.12, shoulder=0.28, brightness=0.34,
    vibrance=0.3, sat=0.22, smooth=0.75,
    hl_hue=48, hl_sat=8, sh_hue=42, sh_sat=4, bal=0.6, st_str=0.6,
    skin=False, skin_str=0.0, sharpen=0.34, chroma=0.8, hl_desat=0.4, clarity=0.35)
write("kodak_ultramax_400.json", c, dict(family="Kodak", label="Ultramax 400",
    tags=["vivid","warm","consumer"], scenes=["street","travel","everyday"],
    character="Ultramax 400 消费级彩负：色彩浓艳暖调、红黄突出，反差偏强颗粒可辨，典型快拍便签感。",
    year=2007, grain_proxy=0.35))

# 4 Ektachrome E100
c = full_card(
    [{"name":"red","saturation":6},{"name":"orange","saturation":4},
     {"name":"aqua","saturation":5}, {"name":"blue","saturation":6}],
    trim=[0.998,1.0,1.002], contrast=0.26, toe=0.1, shoulder=0.24, brightness=0.3,
    vibrance=0.25, sat=0.24, smooth=0.7,
    hl_hue=40, hl_sat=3, sh_hue=210, sh_sat=3, bal=0.5, st_str=0.3,
    skin=False, skin_str=0.0, sharpen=0.4, chroma=0.7, hl_desat=0.3, clarity=0.35)
write("kodak_e100.json", c, dict(family="Kodak", label="Ektachrome E100",
    tags=["slide","accurate","vivid","fine_grain"], scenes=["landscape","nature","general"],
    character="Ektachrome E100 专业反转片：色彩准确浓烈、红与青蓝突出，反差干净锐利颗粒极细，宽容度有限。",
    year=2018, grain_proxy=0.1))

# 5 Reala 100
c = fuji_card(
    trim=[1.0,1.0,1.0], contrast=0.12, toe=0.18, shoulder=0.3, brightness=0.3,
    hs=0.22, vibrance=0.05, sat=-0.1, skin_str=0.6, sharpen=0.26, chroma=1.2, hl_desat=0.6)
write("fujifilm_reala_100.json", c, dict(family="Fuji", label="Reala 100",
    tags=["portrait","neutral","fine_grain","accurate"], scenes=["portrait","wedding","travel"],
    character="Reala 100 真实色负片：肤色精度标杆、整体中性低饱和，反差柔和颗粒极致细腻，曾是日系人像代名词。",
    year=1993, grain_proxy=0.1))

# 6 Astia 100F
c = fuji_card(
    trim=[0.999,1.0,1.001], contrast=0.14, toe=0.18, shoulder=0.32, brightness=0.3,
    hs=0.3, vibrance=0.12, sat=-0.06, skin_str=0.45, sharpen=0.3, chroma=0.9, hl_desat=0.5)
write("fujifilm_astia.json", c, dict(family="Fuji", label="Astia 100F",
    tags=["portrait","soft","low_saturation","slide"], scenes=["portrait","fashion","studio"],
    character="Astia 100F 专业人像反转片：比普通反转片更低饱和、柔顺灰度，肤色过渡细腻，颗粒精细。",
    year=2005, grain_proxy=0.1))

# 7 CineStill 50D
c = full_card(
    [{"name":"red","saturation":3},{"name":"orange","saturation":4,"luminance":2},
     {"name":"blue","saturation":4}],
    trim=[1.0,1.0,1.0], contrast=0.18, toe=0.14, shoulder=0.35, brightness=0.32,
    vibrance=0.18, sat=0.1, smooth=0.8,
    hl_hue=45, hl_sat=4, sh_hue=210, sh_sat=2, bal=0.5, st_str=0.3,
    skin=True, skin_str=0.35, sharpen=0.3, chroma=1.2, hl_desat=0.6)
write("cinestill_50d.json", c, dict(family="CineStill", label="CineStill 50D",
    tags=["motion","clean","neutral","fine_grain"], scenes=["daylight","portrait","city"],
    character="CineStill 50D 日光型电影卷转拍：忠实色彩、中性清洁、高光滚降平滑，颗粒极细适合大场景。",
    year=2015, grain_proxy=0.08))

# 8 Agfa Vista 200
c = full_card(
    [{"name":"red","saturation":4},{"name":"orange","saturation":5,"luminance":2},
     {"name":"green","saturation":3}],
    trim=[1.012,1.0,0.988], contrast=0.16, toe=0.16, shoulder=0.28, brightness=0.32,
    vibrance=0.18, sat=0.12, ccextra={"skin_protect":0.4}, smooth=0.8,
    hl_hue=47, hl_sat=5, sh_hue=40, sh_sat=3, bal=0.55, st_str=0.5,
    skin=True, skin_str=0.3, sharpen=0.32, chroma=0.9, hl_desat=0.45)
write("agfa_vista_200.json", c, dict(family="Agfa", label="Agfa Vista 200",
    tags=["vintage","warm","consumer"], scenes=["street","travel","daily"],
    character="Agfa Vista 200 消费级彩负：暖而柔和的欧陆色调，反差适中颗粒略增，肤色带一点奶油感。",
    year=2002, grain_proxy=0.32))

print("DONE")
