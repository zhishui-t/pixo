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
