# Pixo Frontend (Web UI v3)

React 18 + Vite + TypeScript + Mantine 的本地开发版 Pixo 修图工作台。
当前不打包、不做安装包；默认使用 mock 数据，配置 `VITE_PIXO_API_URL`
后可对接 `pixo-service`。

## 启动

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173

## 可选：对接 pixo-service

默认 API 地址为 `http://localhost:8000`。如服务跑在其他端口：

```bash
# Windows PowerShell
$env:VITE_PIXO_API_URL="http://localhost:9777"
npm run dev
```

或创建 `frontend/.env.local`：

```env
VITE_PIXO_API_URL=http://localhost:9777
```

## UI v3

- 使用 **Mantine** 专业组件库重构（`@mantine/core` + `@mantine/hooks` + Emotion）
- `MantineProvider` 暗色主题，主色 indigo，统一字体/圆角/间距
- `AppShell` 布局：Header / Navbar（项目列表）/ Main（预览 + 底片条）/ Aside（右侧双 Tab）
- 项目列表：搜索、新建、切换
- 底片条：缩略图、0-5 星、红/黄/绿/蓝/紫标签、过滤与排序
- 风格 / AI：Mantine Card + Badge + 推荐卡 + 每项目独立聊天
- 调整：Mantine Accordion / Slider / NumberInput 分组（直方图、基本、曲线、HSL、色彩校准、细节、分离色调）
- 预览：Mantine SegmentedControl / ActionIcon 工具栏，保留 before/after、缩放、拖拽

## 质量检查

```bash
npm run typecheck
npm run build
npm run test:e2e     # 先启动 npm run dev，再运行
```

截图输出：`frontend/screenshots/ui_v3.png`
