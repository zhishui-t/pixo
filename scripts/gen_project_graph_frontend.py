# -*- coding: utf-8 -*-
"""生成 docs/project_graph_frontend.json（前端+资产图谱，t14 --merge 输入格式）。

顶层严格只含 nodes / edges 两数组；节点 {id,type,label,...}，边 {id,from,to,relation,...}，
字段命名与 configs/knowledge/*.json 的图惯例一致，便于 t14 脚本按 id 合并。
films 卡统计全部由 configs/styles/films/*.json 现场计算，不手抄。
"""
from __future__ import annotations

import glob
import json
import os
from collections import Counter

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "docs", "project_graph_frontend.json")

nodes: list[dict] = []
edges: list[dict] = []


def n(id_: str, type_: str, label: str, **extra) -> None:
    node = {"id": id_, "type": type_, "label": label}
    node.update(extra)
    nodes.append(node)


def e(id_: str, frm: str, to: str, relation: str, **extra) -> None:
    edge = {"id": id_, "from": frm, "to": to, "relation": relation}
    edge.update(extra)
    edges.append(edge)


# ---------------------------------------------------------------- frontend --
n("fe:main", "component", "main.tsx（应用入口）", path="frontend/src/main.tsx",
  note="MantineProvider forceColorScheme=dark；accent 暖金主题（t74 暗房主题）")
n("fe:app", "component", "App（壳/顶栏/三页路由/导出轮询）", path="frontend/src/App.tsx",
  note="page 状态切换 workspace/review/settings；导出 1s 轮询最多 60 次")
n("fe:theme:tokens", "module", "DESIGN_TOKENS 暗房主题令牌", path="frontend/src/theme/tokens.ts",
  note="UI 取色唯一来源；WARNING_COLOR 供复核页")
n("fe:styles.css", "module", "全局样式", path="frontend/src/styles.css")
n("fe:types", "module", "前后端契约类型", path="frontend/src/types.ts",
  note="ParamPatch stage 键对齐 src/pixo/render/modules/* 的 param_schema；STATUS_FILTER_SETS 映射 src/pixo/state/machine.py 的 PhotoState")
n("fe:store", "store", "useAppStore（zustand 全局单 store）", path="frontend/src/store/useAppStore.ts",
  note="page/项目/照片/参数 patch/generation/会话 id/对话/建议/复核队列；patch 走 api 门面并回读 params+generation")
n("fe:api:index", "api", "api 门面（后端/mock 自动降级）", path="frontend/src/api/index.ts",
  note="backendAvailable 探测：fetchPhotos 试 GET /api/photos 定成败；失败后所有调用落 mock")
n("fe:api:client", "api", "REST 薄封装（pixo-service）", path="frontend/src/api/client.ts",
  note="API_BASE = VITE_PIXO_API_URL ?? http://localhost:8000；失败抛错，降级策略在 api/index")
n("fe:api:mock", "api", "本地 mock 数据", path="frontend/src/api/mock.ts",
  note="mock 照片 6 张/项目 2 个/风格卡 2 张（硬编码）")

comps = [
    ("fe:comp:ProjectList", "ProjectList（项目列表/新建）", "frontend/src/components/ProjectList.tsx",
     "左侧栏；本地新建项目 addProject"),
    ("fe:comp:PreviewViewer", "PreviewViewer（原图/对比/处理预览）", "frontend/src/components/PreviewViewer.tsx",
     "split clipPath 分割线拖动；原图 onError 回退 mock 占位；gen 徽标+渲染中/失败重试"),
    ("fe:comp:Filmstrip", "Filmstrip（胶片条：过滤/排序/星级/色标）", "frontend/src/components/Filmstrip.tsx",
     "数据源 photosByProject；缩略图未建会话时 CSS 占位卡"),
    ("fe:comp:StyleAiPanel", "StyleAiPanel（风格卡/AI 推荐/项目对话）", "frontend/src/components/StyleAiPanel.tsx",
     "风格卡按 family 分组（t86）；对话为本地 mock 应答"),
    ("fe:comp:AdjustmentsPanel", "AdjustmentsPanel（调整参数面板）", "frontend/src/components/AdjustmentsPanel.tsx",
     "基本/曲线/HSL/校准/细节/分离色调六组；hsl.bands 整组数组 patch；skin 掩码能力徽标（t91）"),
    ("fe:comp:ReviewQueue", "ReviewQueue（人工复核队列）", "frontend/src/components/ReviewQueue.tsx",
     "接受/拒绝/跳回工作区；ruleIds 徽标"),
    ("fe:comp:SettingsPanel", "SettingsPanel（渲染/输出设置）", "frontend/src/components/SettingsPanel.tsx",
     "本地 useState，未接 store/后端"),
    ("fe:comp:SliderParam", "SliderParam（通用滑杆+数值输入）", "frontend/src/components/SliderParam.tsx",
     "拖动防抖，onChangeEnd/onBlur 提交；支持 buildPatch 自定义整组 patch"),
    ("fe:comp:SectionLabel", "SectionLabel（小节微标签）", "frontend/src/components/SectionLabel.tsx", None),
]
for cid, label, path, note in comps:
    n(cid, "component", label, path=path, **({"note": note} if note else {}))

n("fe:page:workspace", "page", "工作区", note="App 主布局：Navbar=项目列表 / Main=预览+胶片条 / Aside=风格AI|调整")
n("fe:page:review", "page", "审核队列", note="顶栏 pill 导航进入")
n("fe:page:settings", "page", "设置", note="顶栏齿轮进入，再点返回工作区")

# frontend import edges
e("imp:main-app", "fe:main", "fe:app", "imports")
e("imp:main-tokens", "fe:main", "fe:theme:tokens", "imports")
e("imp:main-css", "fe:main", "fe:styles.css", "imports")

e("imp:app-store", "fe:app", "fe:store", "imports")
e("imp:app-api", "fe:app", "fe:api:index", "imports", symbols=["fetchPhotos", "getMockSessionId", "pollExport", "submitExport", "toPhotoView"])
e("imp:app-tokens", "fe:app", "fe:theme:tokens", "imports")
for cid, _, _, _ in comps[:7]:
    e(f"imp:app-{cid.split(':')[-1]}", "fe:app", cid, "imports")

e("imp:projectlist-store", "fe:comp:ProjectList", "fe:store", "imports")
e("imp:projectlist-tokens", "fe:comp:ProjectList", "fe:theme:tokens", "imports")
e("imp:preview-store", "fe:comp:PreviewViewer", "fe:store", "imports")
e("imp:preview-tokens", "fe:comp:PreviewViewer", "fe:theme:tokens", "imports")
e("imp:preview-api", "fe:comp:PreviewViewer", "fe:api:index", "imports", symbols=["getMockOriginalSource", "getMockSessionId", "getOriginalSource", "getPreviewSource"])
e("imp:filmstrip-store", "fe:comp:Filmstrip", "fe:store", "imports")
e("imp:filmstrip-tokens", "fe:comp:Filmstrip", "fe:theme:tokens", "imports")
e("imp:filmstrip-types", "fe:comp:Filmstrip", "fe:types", "imports", symbols=["STATUS_FILTER_SETS"])
e("imp:styleai-store", "fe:comp:StyleAiPanel", "fe:store", "imports")
e("imp:styleai-tokens", "fe:comp:StyleAiPanel", "fe:theme:tokens", "imports")
e("imp:adjust-store", "fe:comp:AdjustmentsPanel", "fe:store", "imports")
e("imp:adjust-tokens", "fe:comp:AdjustmentsPanel", "fe:theme:tokens", "imports")
e("imp:adjust-api", "fe:comp:AdjustmentsPanel", "fe:api:index", "imports", symbols=["health"])
e("imp:adjust-sectionlabel", "fe:comp:AdjustmentsPanel", "fe:comp:SectionLabel", "imports")
e("imp:adjust-sliderparam", "fe:comp:AdjustmentsPanel", "fe:comp:SliderParam", "imports")
e("imp:adjust-types", "fe:comp:AdjustmentsPanel", "fe:types", "imports", symbols=["HslBand", "ParamPatch"])
e("imp:review-store", "fe:comp:ReviewQueue", "fe:store", "imports")
e("imp:review-tokens", "fe:comp:ReviewQueue", "fe:theme:tokens", "imports")
e("imp:settings-tokens", "fe:comp:SettingsPanel", "fe:theme:tokens", "imports")
e("imp:sliderparam-tokens", "fe:comp:SliderParam", "fe:theme:tokens", "imports")
e("imp:sliderparam-types", "fe:comp:SliderParam", "fe:types", "imports", symbols=["ParamPatch", "Source"])

# pages
e("render:workspace", "fe:app", "fe:page:workspace", "renders", note="page==='workspace'")
e("render:review", "fe:app", "fe:page:review", "renders", note="page==='review'")
e("render:settings", "fe:app", "fe:page:settings", "renders", note="其余值")
for cid in ["fe:comp:ProjectList", "fe:comp:PreviewViewer", "fe:comp:Filmstrip", "fe:comp:StyleAiPanel", "fe:comp:AdjustmentsPanel"]:
    e(f"page:workspace-{cid.split(':')[-1]}", "fe:page:workspace", cid, "contains",
      note="StyleAiPanel/AdjustmentsPanel 由 rightTab 二选一")
e("page:review-queue", "fe:page:review", "fe:comp:ReviewQueue", "contains")
e("page:settings-panel", "fe:page:settings", "fe:comp:SettingsPanel", "contains")

# store -> api
e("imp:store-types", "fe:store", "fe:types", "imports")
e("imp:store-api", "fe:store", "fe:api:index", "imports",
  symbols=["ensureSession", "fetchProjects", "fetchStyleCards", "getMockPhotoList", "getMockSessionId", "patchParams"])
# api/index -> client/mock/types
e("imp:api-client", "fe:api:index", "fe:api:client", "imports")
e("imp:api-mock", "fe:api:index", "fe:api:mock", "imports")
e("imp:api-types", "fe:api:index", "fe:types", "imports")
e("imp:client-types", "fe:api:client", "fe:types", "imports")
e("imp:mock-types", "fe:api:mock", "fe:types", "imports")

# ---------------------------------------------------------------- endpoints --
eps = [
    ("ep:health", "GET /api/health", "getHealth"),
    ("ep:photos_list", "GET /api/photos", "listPhotos"),
    ("ep:photo_get", "GET /api/photos/{photo_id}", "getPhoto"),
    ("ep:photo_create", "POST /api/photos", "createPhoto"),
    ("ep:session_create", "POST /api/photos/{photo_id}/sessions", "createSession"),
    ("ep:params_put", "PUT /api/sessions/{session_id}/params", "updateParams"),
    ("ep:measurements", "GET /api/sessions/{session_id}/measurements", "getMeasurements"),
    ("ep:export_submit", "POST /api/sessions/{session_id}/exports", "submitExport"),
    ("ep:export_status", "GET /api/exports/{task_id}", "getExportStatus"),
    ("ep:timeline", "GET /api/photos/{photo_id}/timeline", "getTimeline"),
    ("ep:decide", "POST /api/photos/{photo_id}/decide", "decidePhoto"),
    ("ep:image", "GET /api/sessions/{session_id}/image", "previewUrl/originalUrl"),
]
for eid, label, fn in eps:
    unused = eid in ("ep:photo_get", "ep:photo_create", "ep:measurements", "ep:timeline", "ep:decide")
    n(eid, "endpoint", label, client_fn=fn,
      **({"note": "client 已封装，UI 尚未接线（导出未用）"} if unused else {}))

n("be:service:app", "backend", "pixo-service 路由（FastAPI）", path="src/pixo/service/app.py")

for eid, _, _ in eps:
    e(f"serves:{eid.split(':')[1]}", "be:service:app", eid, "serves")
for eid, _, fn in eps:
    e(f"wraps:{eid.split(':')[1]}", "fe:api:client", eid, "wraps", note=f"client.{fn}()")

# 实际触发的调用边（谁在什么时机打这个端点）
e("call:app-photos_list", "fe:app", "ep:photos_list", "calls",
  note="挂载时 fetchPhotos 探测后端；成功 setPhotos+backend=true，失败降级 mock")
e("call:app-export_submit", "fe:app", "ep:export_submit", "calls", note="顶栏下载按钮 submitExport(sessionId,'jpeg',88)")
e("call:app-export_status", "fe:app", "ep:export_status", "calls", note="1s 轮询至 completed/failed 或 60 次")
e("call:preview-image", "fe:comp:PreviewViewer", "ep:image", "calls",
  note="处理图 gen=N 预览 + 原图 original=1（契约端点，404 回退 mock 占位）")
e("call:thumb-image", "fe:api:index", "ep:image", "builds_url",
  note="toPhotoView：Filmstrip 缩略图 long_edge=512，gen 省略由服务端按会话当前代渲染")
e("call:adjust-health", "fe:comp:AdjustmentsPanel", "ep:health", "calls",
  note="挂载探测 segmenter.part_prompts 是否含 skin → skinMaskReady")
e("call:store-params_put", "fe:store", "ep:params_put", "calls",
  note="patchParam/patchProjectParam → updateParams（深合并+generation+1），回读 params/canonical")
e("call:store-session_create", "fe:store", "ep:session_create", "calls",
  note="patchProjectParam 惰性 ensureSession（后端在线且 sessionId 为空时）")

# ------------------------------------------------------------------ assets --
# films 卡统计（现场计算）
films = []
stage_freq: Counter = Counter()
fam_freq: Counter = Counter()
pipeline_freq: Counter = Counter()
for fp in sorted(glob.glob(os.path.join(ROOT, "configs", "styles", "films", "*.json"))):
    with open(fp, encoding="utf-8") as fh:
        d = json.load(fh)
    stages = d.get("stages", [])
    md = d.get("metadata", {})
    for s in stages:
        stage_freq[s] += 1
    fam_freq[md.get("family", "?")] += 1
    pipeline_freq[len(stages)] += 1
    films.append({
        "file": f"configs/styles/films/{os.path.basename(fp)}",
        "style_id": os.path.splitext(os.path.basename(fp))[0],
        "family": md.get("family", "?"),
        "label": md.get("label", ""),
        "stage_count": len(stages),
        "stages": stages,
    })

n("asset:films_dir", "asset", "configs/styles/films/（胶片风格卡库）",
  path="configs/styles/films", format="json",
  card_count=len(films),
  family_counts=dict(fam_freq),
  pipeline_counts={f"{k} 段": v for k, v in sorted(pipeline_freq.items())},
  stage_frequency=dict(stage_freq.most_common()),
  cards=films,
  note="schema={stages,params,output}+metadata；加载器 pixo.know.cards.StyleCard.from_films_dir；坏 JSON/缺 stages 跳过告警")

e("load:films-cards", "be:know:cards", "asset:films_dir", "loads",
  note="StyleCard.from_films_dir()，pipeline_from_config 只读 stages/params/output，metadata 自然忽略")

# stage 键 → render/modules 映射
stage_map = {
    "exposure": ("be:mod:exposure", "src/pixo/render/modules/exposure.py"),
    "whitebalance": ("be:mod:white_balance", "src/pixo/render/modules/white_balance.py"),
    "tone": ("be:mod:tone_map", "src/pixo/render/modules/tone_map.py"),
    "hsl": ("be:mod:hsl", "src/pixo/render/modules/hsl.py"),
    "huesat": ("be:mod:huesat", "src/pixo/render/modules/huesat.py"),
    "dehaze": ("be:mod:dehaze", "src/pixo/render/modules/dehaze.py"),
    "clarity": ("be:mod:clarity", "src/pixo/render/modules/clarity.py"),
    "colorcal": ("be:mod:color_cal", "src/pixo/render/modules/color_cal.py"),
    "split_tone": ("be:mod:split_tone", "src/pixo/render/modules/split_tone.py"),
    "skin": ("be:mod:skin", "src/pixo/render/modules/skin.py"),
    "stylize": ("be:mod:style", "src/pixo/render/modules/style.py"),
    "refine": ("be:mod:refine", "src/pixo/render/modules/refine.py"),
}
stage_core = {
    "exposure": "core/curves.py + calibration_store",
    "whitebalance": "core/color.py + core/calibration.py",
    "tone": "core/curves.py（filmic LUT）",
    "hsl": "core/hsl.py + core/hsl_oklch.py（OKLCh 8 带）",
    "huesat": "core/huesat.py（DCP HueSatMap 移植）",
    "split_tone": "core/split_tone.py",
    "skin": "core/skin.py（掩码+磨皮）",
}
for stage, (mid, mpath) in stage_map.items():
    n(mid, "backend", f"render/modules/{os.path.basename(mpath)}（stage: {stage}）", path=mpath,
      **({"core": stage_core[stage]} if stage in stage_core else {}))
    e(f"stage:{stage}", "asset:films_dir", mid, "stage_key",
      note=f"{stage_freq[stage]}/{len(films)} 张卡含 {stage} 键")

# 其余 styles 预设（现场统计 stages）
for fp in sorted(glob.glob(os.path.join(ROOT, "configs", "styles", "*.json"))):
    base = os.path.basename(fp)
    with open(fp, encoding="utf-8") as fh:
        d = json.load(fh)
    aid = f"asset:styles:{base[:-5]}"
    if base == "scenes.json":
        n(aid, "asset", "configs/styles/scenes.json（场景预设映射）", path=f"configs/styles/{base}",
          format="json", scene_keys=sorted(d.keys()),
          note="scene→{params,lut}；mono 用 saturation=-1 全去色")
    else:
        n(aid, "asset", f"configs/styles/{base}", path=f"configs/styles/{base}",
          format="json", stage_keys=d.get("stages", []),
          note="渲染预设：pipeline_from_config 消费 stages/params/output")
    if base == "scenes.json":
        e(f"load:styles-{base[:-5]}", "be:render:scene_apply", aid, "loads",
          note="render/pipeline/scene_apply.py load_scene_presets（进程内缓存）")
    else:
        e(f"load:styles-{base[:-5]}", "be:render:presets", aid, "loads",
          note="render/pipeline/presets.py pipeline_from_config")

# knowledge 包
know_meta = [
    ("photography_capture_post", "拍摄×后期", 11, 4, "前期手段与后期代价（capture/light/noise/action）"),
    ("photography_tone", "影调", 15, 13, "曝光/影调策略与工序（tone/strategy/side_effect）"),
    ("photography_hue", "色相", 14, 11, "色偏病因→调色动作→边界（color_issue/action/boundary）"),
    ("photography_post2", "后期方法论", 9, 9, "流程方法/方案对照/场景风险（action/boundary/side_effect）"),
    ("photography_composition", "构图", 10, 9, "场景→策略→禁忌链、二次构图边界（scene/strategy/boundary）"),
]
for name, theme, nn, ne, desc in know_meta:
    aid = f"asset:knowledge:{name}"
    n(aid, "asset", f"configs/knowledge/{name}.json", path=f"configs/knowledge/{name}.json",
      format="json", theme=theme, node_count=nn, edge_count=ne, note=desc)
    e(f"load:know-{name}", "be:know:registry", aid, "loads",
      note="pixo.know.registry 自动扫描 configs/knowledge/；graph.py/rag.py 供 agent 检索")

# rules
rules_meta = [
    ("color_rules", ["vibrance_low_rule", "saturation_high_rule"], "色彩规则（阈值取 t41 实测分位 p25/p75）"),
    ("exposure_rule_001", ["exposure_rule_001"], "曝光规则"),
    ("highlight_protect_rule_002", ["highlight_protect_rule_002"], "高光保护规则"),
    ("crop_suggest_rule_003", ["crop_suggest_rule_003"], "裁剪建议规则"),
    ("tone_clarity_rules", ["dehaze_rule_030", "clarity_flat_rule_031", "shadow_open_rule_032", "highlight_recover_rule_033"], "影调/清晰度规则组"),
]
for name, ids_, desc in rules_meta:
    aid = f"asset:rules:{name}"
    n(aid, "asset", f"configs/rules/{name}.yaml", path=f"configs/rules/{name}.yaml",
      format="yaml", rule_ids=ids_, note=desc)
    e(f"load:rules-{name}", "be:decide:rules", aid, "loads",
      note="src/pixo/decide/rules/ 与 configs/rules/ 双维护镜像；RULES_DIR 显式列 color_rules.yaml")

# calibration / color
n("asset:calibration:warmth_curve", "asset", "configs/calibration/warmth_curve.json",
  path="configs/calibration/warmth_curve.json", format="json",
  note="逐机暖度曲线 [[wb_B,r,g,b],...]；scripts/fit_warmth_curve.py --write 产物")
e("load:warmth-store", "be:core:calibration_store", "asset:calibration:warmth_curve", "loads",
  note="mtime+size 键负缓存统一治理；文件存在时其 knots 作为 warmth_curve 生效，显式参数优先")
e("load:warmth-wb", "be:mod:white_balance", "asset:calibration:warmth_curve", "consumes",
  note="whitebalance stage 经 calibration_store 读曲线")

n("asset:color:rp_ccm_nikon_z5_2", "asset", "configs/color/rp_ccm_nikon_z5_2.json",
  path="configs/color/rp_ccm_nikon_z5_2.json", format="json",
  note="RP CCM 系数（Nikon Z5² 语料弱监督拟合）；scripts/fit_rp_ccm.py 产物")
e("load:rpccm", "be:core:rp_ccm", "asset:color:rp_ccm_nikon_z5_2", "loads",
  note="render/core/rp_ccm.py 约定 configs/color/rp_ccm_<camera>.json")

# manifests
n("asset:manifest:vision_models", "asset", "src/pixo/manifests/vision_models.json",
  path="src/pixo/manifests/vision_models.json", format="json",
  note="Pixo Vision 模型清单（登记不拷贝大文件；license/publishable/pixo_status 字段）")
e("load:vision-models", "be:manifests", "asset:manifest:vision_models", "loads",
  note="pixo.manifests.load_vision_models / load_all_manifests，含字段完整性校验")

n("asset:manifest:dcp", "asset", "resources/dcp/manifest.json",
  path="resources/dcp/manifest.json", format="json",
  note="相机→DCP/预设映射注册表（camera/default_lr_preset/targets{preset,dcp,truth,camera_profile}）")
e("load:dcp", "be:core:calibration", "asset:manifest:dcp", "loads",
  note="注册表元数据；.dcp 本体由 render/core/calibration.py load_dcp/find_camera_dcp 消费")

n("asset:manifest:goldens_render_bench", "asset", "data/golden/reference/render_bench/goldens/*/manifest.json",
  path="data/golden/reference/render_bench/goldens", format="json",
  note="gate / gate_defaults / gate_smoke2 三套 golden 清单")
n("asset:manifest:goldens_tests", "asset", "tests/regression/goldens/gate/manifest.json",
  path="tests/regression/goldens/gate/manifest.json", format="json",
  note="回归测试 golden 清单")
for gid in ("goldens_render_bench", "goldens_tests"):
    e(f"load:{gid}", "be:harness:goldens", f"asset:manifest:{gid}", "loads",
      note="harness/goldens/manifest.py 读写校验；gate_golden.py 产出")

# backend 汇总节点
n("be:know:cards", "backend", "pixo.know.cards（胶片卡加载器）", path="src/pixo/know/cards.py")
n("be:know:registry", "backend", "pixo.know.registry/graph/rag（知识包注册与检索）", path="src/pixo/know/registry.py")
n("be:decide:rules", "backend", "pixo.decide.rules（规则引擎加载）", path="src/pixo/decide/rules/__init__.py")
n("be:render:presets", "backend", "render/pipeline/presets（pipeline_from_config）", path="src/pixo/render/pipeline/presets.py")
n("be:render:scene_apply", "backend", "render/pipeline/scene_apply（场景预设应用）", path="src/pixo/render/pipeline/scene_apply.py")
n("be:core:calibration_store", "backend", "render/core/calibration_store（标定负缓存）", path="src/pixo/render/core/calibration_store.py")
n("be:core:rp_ccm", "backend", "render/core/rp_ccm（RP CCM 系数）", path="src/pixo/render/core/rp_ccm.py")
n("be:manifests", "backend", "pixo.manifests（模型清单加载/校验）", path="src/pixo/manifests/__init__.py")
n("be:core:calibration", "backend", "render/core/calibration（DCP 解析/查找）", path="src/pixo/render/core/calibration.py")
n("be:harness:goldens", "backend", "pixo.harness.goldens（golden 清单工具）", path="src/pixo/harness/goldens/manifest.py")

# 前端 ↔ 资产/后端 的镜像与对齐（非 import，属契约关系）
e("mirror:mock-films", "fe:api:mock", "asset:films_dir", "mirrors",
  note="前端风格卡目前为 mock 硬编码 2 张（kodak_portra_400/fuji_pro_400h）；后端 24 张胶片卡尚未接线到前端（无 GET /api/styles 端点）")
e("align:types-modules", "fe:types", "be:mod:hsl", "aligns",
  note="ParamPatch.hsl（HslBand 五字段×8 段）与 render/modules/hsl.py DEFAULT_BANDS schema 对齐")
e("align:types-machine", "fe:types", "be:service:app", "aligns",
  note="PhotoState 枚举/各端点响应类型以 service/app.py + state/machine.py + runtime.py 为事实来源")
e("mirror:adjust-hsl", "fe:comp:AdjustmentsPanel", "be:mod:hsl", "mirrors",
  note="DEFAULT_HSL_BANDS 常量镜像 render/core/hsl.py DEFAULT_BANDS（8 段），避免悬空键 patch")

# ------------------------------------------------------------------- write --
graph = {"nodes": nodes, "edges": edges}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(graph, fh, ensure_ascii=False, indent=2)
    fh.write("\n")

ids = [x["id"] for x in nodes]
assert len(ids) == len(set(ids)), "duplicate node ids"
edge_ids = [x["id"] for x in edges]
assert len(edge_ids) == len(set(edge_ids)), "duplicate edge ids"
known = set(ids)
bad = [x["id"] for x in edges if x["from"] not in known or x["to"] not in known]
assert not bad, f"dangling edges: {bad}"
print(f"OK {OUT}: {len(nodes)} nodes, {len(edges)} edges; films={len(films)} cards, stage_freq={dict(stage_freq)}")
