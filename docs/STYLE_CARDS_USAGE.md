# 风格卡与场景预设使用说明（R22 F04/F05）

> 适用版本：R22 起。面向：使用 Pixo 修图的用户 + 调用本地 HTTP API 的集成方。
> 相关实现：`src/pixo/service/runtime.py`（装配）、`src/pixo/render/web/session.py`（参数栅栏）、
> `frontend/src/components/StyleAiPanel.tsx`（界面）、`frontend/src/constants/scenePresets.ts`（场景常量）。

## 1. 风格卡是什么

**风格卡是「参数卡」，不是 LUT 文件。**

- 位置：`configs/styles/films/*.json`（仓库内 25 张，界面按品牌/系列分组显示）。
- 结构：

  ```json
  {
    "stages":  ["exposure", "whitebalance", "tone", "..."],   // 该卡描述的渲染链段
    "params":  {"tone": {"contrast": 0.14}, "refine": {"chroma_denoise": 0.9}},  // 真正应用的东西
    "output":  {"quality": 95},
    "metadata": {"family": "Fuji", "label": "Astia 100F", "tags": ["portrait"]}
  }
  ```

  应用时被写入会话参数的是 **`params`**（`stages` 只作为卡自身声明的链段清单被校验，不改变渲染链）。
- **仓内没有任何 `.cube` 文件**（R22 实测 0 命中）。所以「套风格」= 把卡里的曝光/影调/色彩/精修参数
  深合并进当前会话参数，而不是加载 LUT 查表。`stylize.lut_path` 因此在本轮**一律被拒绝**（见 §4）。

## 2. 在界面里怎么用

打开右侧「风格 / AI」栏：

1. **场景预设**（最上面一行紧凑按钮，6 个）：人像 / 风光 / 夜景 / 街拍 / 美食 / 黑白。
   点一下即应用（按钮进入加载态）。
2. **风格卡列表**（按品牌分组）：点卡名展开详情（适用场景、渲染链段数）；
   点右侧 **「应用」** 按钮把该卡的参数写进当前会话。
3. 应用结果：
   - 成功 → 顶部出现「✓ 已应用：<名称>」；
   - **失败 → 顶部红色提示条显示失败原因**（含后端返回的具体原因，例如
     `未知风格卡 'xxx'`、`参数 'tone.contrast' 越域：5 大于上限 1.0`）。
     失败时**不会**有任何参数被写入，也不会静默跳过。

应用后可直接在「调整」栏看到参数变化（同一份会话参数），预览图按新的 generation 重渲染。

### 叠加语义（重要）

应用卡/预设是**深合并（叠加）**，只覆盖它自己声明的参数键：

- 应用 `黑白` 只写 `colorcal.saturation = -1.0`，其它调整（曝光、锐化…）保持不变；
- 连点两个预设，后一个只覆盖重叠键（例如先「风光」再「夜景」，`colorcal.saturation`
  仍是风光写入的值，因为夜景不声明该键）；
- 想回到基座默认，需要手动把对应滑杆调回，或逐键写入默认值（本轮未提供「重置」动作）。

## 3. 用 HTTP API 直接应用（集成方）

不需要新端点——复用既有的参数 patch 通道，用**控制键**声明来源：

```bash
# 应用一张风格卡（style_id = configs/styles/films 下的文件名，不含 .json）
curl -X PUT "http://127.0.0.1:8000/api/sessions/<session_id>/params" \
     -H "Content-Type: application/json" \
     -d '{"__style": "fujifilm_astia", "__source": "preset"}'

# 应用一个场景预设（6 个：portrait / landscape / night / street / food / mono）
curl -X PUT "http://127.0.0.1:8000/api/sessions/<session_id>/params" \
     -H "Content-Type: application/json" \
     -d '{"__scene": "mono"}'
```

- 同一个请求里还可以带普通 stage 参数，**显式参数优先**：
  `{"__style": "fujifilm_astia", "tone": {"contrast": 0.9}}` → 卡的其余键照写，`tone.contrast` 用 0.9。
- `__style` 与 `__scene` **不能同时提交**（一次装配一个来源），否则 400。
- 响应里 `params` 是会话当前覆盖，`canonical` 是「默认值 + 覆盖」的完整参数（可直接看应用结果）。
- 溯源：每次应用会在状态机 trace 里记 `param_patch` 事件（`param="__style"` / `"__scene"`
  以及每个被装配的 stage 桶），可用 `GET /api/photos/{photo_id}/timeline` 查。

想先看某张卡会写什么，用 `GET /api/styles/{style_id}`（返回完整卡），
列表用 `GET /api/styles`。

## 4. 参数栅栏：什么会被 400 拒绝

所有写参数都会经过一道**从各 Stage 的 `param_schema` 派生**的校验（不是写死的白名单，
所以 Stage 新增参数后栅栏自动跟随）。被拒绝的一律返回 **HTTP 400**，且**不写入任何一个键**：

| 拒绝项 | 例子 | 说明 |
|---|---|---|
| 路径类参数键（`*_path` / `*_file`） | `stylize.lut_path`、`whitebalance.warm_cal_file`、`huesat.oklch_points_file` | 防任意路径注入 |
| 值形如文件路径的字符串 | `{"compose": {"ratio": "..\\..\\x"}}`、`/etc/passwd`、`C:/x` | 任何含 `/`、`\`、盘符、`~` 的字符串 |
| `stylize.lut` 被赋值 | `{"stylize": {"lut": "velvia"}}` | 本轮不支持 LUT（仓内无 `.cube` 资产） |
| 未知 stage 名 | `{"s1": {...}}`、`{"render": {...}}` | 只接受已注册 Stage（见下表） |
| 未知参数键 | `{"tone": {"nope": 1}}` | 键必须在 `param_schema` 内 |
| 数值越域 | `{"tone": {"contrast": 5}}`（域 0..1）、`{"tone": {"highlights": -20}}`（域 ±1） | 见 `src/pixo/render/modules/*.py` 的 `param_schema` |
| 类型/枚举不符 | `{"tone": {"use_filmic": "yes"}}`、`{"colorcal": {"neutral_mode": "lab"}}` | 枚举见各 Stage schema |
| NaN / Infinity | `{"compose": {"rotation": NaN}}` | JSON 字面量也会被拒 |

合法 stage 名（18 个）：`exposure` `whitebalance` `compose` `huesat` `tone` `dehaze` `clarity`
`denoise` `sharpen` `vibrance` `colorcal` `calibration` `hsl` `split_tone` `skin` `region_adjust`
`stylize` `refine`。

**不受影响的既有操作**：「调整」栏的滑杆/开关（曝光、高光阴影、色温色调、清晰度、肤色、
HSL/分离色调、色彩校准、锐化降噪去朦胧、区域调整）提交的参数键与取值都在 schema 内，照常写入。
（R22 顺带把「清晰度」滑杆下界从 -1 对齐到后端域 0——负值在渲染 Stage 内本来就是
`s <= 0` 的静默无操作，现在滑杆不再产生域外值。）

### 为什么本轮拒绝 `lut_path`

1. 仓内**没有任何 `.cube`/`.3dl`/`.look` 资产**，LUT 目录回退指向**仓库外**路径，分发环境不可用
   （见 `THIRD_PARTY_NOTICES.md`）——放开 `lut_path` 等于允许把渲染管线指向任意文件；
2. 本轮 F04 的口径是「风格卡 = 参数卡」（见 §1），LUT 注入登记为未来扩展位。
   将来要放开时，需同时补：机制层路径栅栏（`render/core/lut.py`）+ 仓内 LUT 资产 + 许可登记。

## 5. 常见问题

**Q：界面上点「应用」提示失败，但参数好像没变？**
A：这是预期行为——栅栏拒绝时整批参数都不写入。提示条里有后端给出的具体原因，
按原因修正（例如换一张存在的卡 id、把数值改回域内）。

**Q：离线（没启后端）时点「应用」会怎样？**
A：会**显式报错**（不假装成功）。界面此时只显示 2 张离线占位卡，用来展示布局；
真正应用需要启动后端服务。

**Q：应用风格卡会不会影响 decide 的自动调整？**
A：不会。R22 F04 只做「参数注入」；另一条「内置卡 → decide 规则」的链路由
`SinglePhotoLoop.enable_style_cards` / 环境变量 `PIXO_STYLE_CARDS` 控制，R13 起缺省关闭，
本轮未改语义。

**Q：场景预设会不会重置我的调整？**
A：不会，它是叠加式深合并（见 §2「叠加语义」）。

**Q：一次能应用多张卡吗？**
A：按顺序应用即可（后一张覆盖重叠键）。同一请求提交 `__style` 两次不成立（JSON 键唯一）。
