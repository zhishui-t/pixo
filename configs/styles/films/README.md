# films —— 胶片风格卡库（t86 骨架）

schema = 渲染卡 `{stages,params,output}` + 元数据节：

```json
"metadata": {
  "family": "Kodak",          // 分组键（品牌/系列），前端按此分组浏览
  "label": "Portra 400",      // 展示名
  "tags": ["portrait"],       // 自由标签
  "scenes": ["golden_hour"],  // 适用场景
  "character": "一句话风格描述",
  "year": 1998
}
```

- 渲染管线 `pipeline_from_config` 只读 stages/params/output，`metadata`
  为未知键自然忽略，不阻塞加载。
- 加载器：`StyleCard.from_films_dir()`（pixo.know.cards），目录缺省
  `configs/styles/films`；空目录返回空列表，坏 JSON/缺 stages 跳过并告警。

## t88 —— Fujifilm 批次（开发4）

| 卡 | 说明 |
|---|---|
| fujifilm_classic_chrome | 哑光低饱和纪实 |
| fujifilm_velvia_50 | 风光高饱和高反差（肤色保护关） |
| fujifilm_provia_100f | 标准彩正均衡 |
| fujifilm_acros_100 | 黑白近似：saturation=-1 全去色（原生 mono Stage 待 P4） |
| fujifilm_pro_neg_hia | 人向低饱和偏高对比 |
| fujifilm_pro_neg_std | 人向低饱和软调 |
| fujifilm_community_lab_scan | **社区冲扫风 3515/3510 合卡**：暖肤/青绿影调/低对比，社区近似非官方（metadata.official=false） |


## t96 完成 第三批 8 张（经典卷扩充）

| 卡 | 说明 |
|---|---|
| kodak_portra_160nc | Portra 160NC 自然色版：低饱和柔和、肤色细腻，反差温柔颗粒极细 |
| kodak_portra_400nc | Portra 400NC 自然色版：略暖略饱和，中等细腻颗粒适合人像 |
| kodak_ultramax_400 | Ultramax 400 消费级彩负：色彩浓艳暖调、红黄突出，反差强颗粒可辨 |
| kodak_e100 | Ektachrome E100 专业反转片：色彩准确浓烈、红青突出，反差干净颗粒极细 |
| fujifilm_reala_100 | Reala 100 真实色负片：肤色精度标杆、整体中性低饱和，颗粒极致细腻 |
| fujifilm_astia | Astia 100F 专业人像反转片：低饱和柔和灰度，肤色过渡细腻 |
| fujifilm_provia_400x | Provia 400X 专业反转片：400度超细粒、色彩鲜活准确、反差稍高适动态题材 | 专业人像反转片：低饱和柔和灰度，肤色过渡细腻 |
| cinestill_50d | CineStill 50D 日光型电影卷转拍：忠实色彩、中性清洁、高光滚降平滑，颗粒极细 |
| agfa_vista_200 | Agfa Vista 200 消费级彩负：暖而柔和的欧陆色调，反差适中，肤色奶油感 |

约定：Kodak / CineStill / Agfa 卡走 12 段全管线（含 hsl 波段），
Fuji 卡走精简 8 段管线（huesat）；grain_proxy 一律落 metadata（近零值=极细颗粒）。
