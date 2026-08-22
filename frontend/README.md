# Pixo Frontend (Web UI v4)

React 18 + Vite + TypeScript + Mantine + Lucide 的现代修图工作台。
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

## UI v4 现代感精修

- 视觉主题：深邃近黑 `#0B0F14`，面板 `#121821 / #161D28`，电光蓝 `#6C8CFF`
- 引入 **lucide-react** 图标，Button / ActionIcon / 操作区改为图标 + 文字
- Mantine 全局主题：Inter 优先字体、大圆角、柔和阴影、更大留白
- AppShell：毛玻璃 Header，项目列表渐变激活条，右侧 segmented pill Tab
- 底片条：星级 Star 图标、颜色圆点、hover 放大、选中发光环
- 预览区：悬浮毛玻璃工具栏、软阴影画布、Lucide 缩放/定位图标
- 风格/AI：渐变作品卡、渐变推荐卡、现代聊天气泡
- 调整：Mantine Accordion + Slider + NumberInput 分组，精致直方图
- 保留全部功能：项目切换、底片条、星级/颜色、风格/AI、对话、调整、预览

## 质量检查

```bash
npm run typecheck
npm run build
npm run test:e2e     # 先启动 npm run dev，再运行
```

截图输出：`frontend/screenshots/ui_v4.png`
