# junior-dev 执行记录 · R31（F0 GPLv3 + F2 环境与批转）

状态：**F0 完成（已验收）；F2 全部完成**（安装由队长/用户放行 UAC 后落地，
批转 48/48 成功，消费自证通过）。更新时间：2026-09-22。

## F0 GPLv3 落地 —— 完成（队长已验收）

| 项 | 动作 | 结果 |
|---|---|---|
| LICENSE | 从 <https://www.gnu.org/licenses/gpl-3.0.txt> 下载全文（非手打）写入仓根 | `K:/work/project/pixo/LICENSE`，674 行，首尾行核对为标准 GPLv3 文本 |
| pyproject.toml | `license = {text = "Proprietary"}` → `license = {text = "GPL-3.0-or-later"}`（第 11 行，仅此一处改动） | 完成 |
| THIRD_PARTY_NOTICES.md | 末尾追加 §8「项目许可证变更（2026-09-22，R31/F0）」：登记三项事实（LICENSE 来源、pyproject 字段变更、GPL 血缘前提改变），并注明 NC 权重/DCP/clean-room 警示不受影响 | 完成 |

## F2 安装 —— 完成（提权由队长/用户放行）

- Adobe DNG Converter **18.6**（exe VersionInfo ProductVersion/FileVersion 均 18.6）：
  `C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe`
  （**exe 名带空格**，235,994,120 B——此前报告按 "DNGConverter.exe" 核验的说法以本行为准）。
- RawTherapee **5.13**：`C:\Program Files\RawTherapee\5.13\rawtherapee-cli.exe`
  （`--version` 实测 "RawTherapee, version 5.13, command line."，dev-2 RT 臂可用）。
- 半装残留 `C:\Program Files\Adobe\Adobe DNG Converter\`（仅 adobe_c2pa.dll）已随
  重装清掉；安装日志 `.artifacts/_r31_env_install.log` 两包均 SUCCESS。
- 插曲留痕：junior 侧两次 `Start-Process -Verb RunAs` 均被取消（详见 git 历史版本的
  本报告「阻塞」一节）；最终由用户放行 UAC 完成安装，junior 未绕过任何权限。

## F2 采样清单 —— 完成（dev-2 已复用）

- 语料 K:/data/photo 递归 `*.NEF`（大小写不敏感）：含 `._` AppleDouble 共 **5241**；
  剔 `._` 前缀后 **4053**（与 design §1「4053 张」口径吻合）。
- 排序 `sorted()` 全路径字典序，等步长 `idx_i = floor(i*4053/48)` 取 48 片；
  48 片 basename 无撞名；全部存在（missing=0）。
- 产物：`.artifacts/_r31_refs/picklist.json`（含算法字符串原文）。

## F2 批转 —— 完成 48/48

- 工具与参数：`"C:\Program Files\Adobe\Adobe DNG Converter\Adobe DNG Converter.exe"
  -d K:\work\project\pixo\.artifacts\_r31_refs <48 个 NEF 路径>`（DNG 18.6 默认转换
  选项：无损压缩、全分辨率；其余参数未传）。
- **口径实测说明**：`-h` 与无参运行均会开 GUI 挂死（实测超时），CLI 用法以
  **首张试转**验证——`-d <outdir> <1 张>` exit 0 / 4.8 s / .dng 落地，然后才全量。
- 结果：exit 0，**耗时 42.1 s**，48 个 .dng 全部产出；体积 19.6–36.1 MB
  （无异常小文件）。
- 消费自证：抽第 1 片 `DSC_0352.dng` 走 dev-1 `.artifacts/_r31_dng_render.py`
  （dng_validate.exe 完整默认渲染口径）→ 9.9 s 出 `_spotcheck.tif` 73,167,096 B，
  TIFF 魔数 `II*\0` 校验通过后已删除。**转换产物可被参照渲染链消费，链路闭合。**
- 交付：`.artifacts/_r31_refs/manifest.json`（顶层 session/generated_by/pick_algorithm/
  corpus/converter 块 + 48 items，每项 `name/nef_path/dng_path/session/dng_exists`，
  符合 design §6 与派单字段要求）。入库状态：`.gitignore:85 .artifacts/_*` 覆盖，
  批转产物不入库（符合红线）。

## 坑与备注

1. **Adobe DNG Converter 18.6 无可用 CLI help**：`-h`/无参都直接开 GUI；管道捕获
   （python subprocess）拿不到 usage。可靠口径验证法 = 首张试转看 exit code 与产物。
2. 转换 stdout 有 **sensei/WinML 初始化报错**（"Are DLLs missing?" / "GPU3 disabled"）
   ——Adobe AI 降噪组件缺失的非致命噪音，exit 0 且产物有效；已存
   `.artifacts/_r31_refs/_dng_converter_run.log` 备查，可忽略。
3. winget 装 Program Files 级包必须 UAC 提权，`--silent` 不豁免；弹窗 2 分钟无响应
   自动取消（前两次失败即此因，非 winget 失败）。
4. `.gitignore` 文件为非 UTF-8 编码（Read 工具读不了，需 iconv），未改动。
5. 命令行经 Git Bash 传给 `cmd /c` 时引号转义易碎（实测被吃引号），批转一律走
   python `subprocess` 列表参数，不走 shell 拼接。

## 隔离边界（2026-09-22 队长裁决 #1，已遵照）

工作树另有 20 个文件的并行工作流改动（enabled/wb 主题，src/tests/scripts）——本轮
junior **未触碰/未回滚/未清理**，仅操作了：LICENSE、pyproject.toml、
THIRD_PARTY_NOTICES.md、`.artifacts/_r31_*`、本报告。当日 git status 快照（非我域，
仅记录）：`scripts/_t102_smoke.py`、`scripts/run_ab_regression.py`、
`scripts/t93_segmenter_smoke.py`、`src/pixo/render/modules/{exposure,hsl,white_balance}.py`、
`src/pixo/render/pipeline/graph.py`、`src/pixo/render/web/session.py`、
`src/pixo/service/runtime.py`、`tests/conftest.py`、
`tests/integration/{test_region_session_api,test_region_supply,test_segmenter_warmup}.py`、
`tests/unit/{test_exposure_tier_consistency,test_huesat_oklch,test_service_runtime_fixes,
test_wb_manual_exposure,test_wb_temp_tint}.py`、
untracked：`tests/_corpus_paths.py`、`tests/unit/{test_param_intents_translate,
test_param_type_consistency}.py`、`.artifacts/R31_enabled_wiring.md`（§8 隔离声明在案）。
