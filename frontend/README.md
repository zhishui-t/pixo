# Pixo Frontend (Web UI v5)

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

## UI v5 浅色极简风

- 参考 DSH 主页浅色设计：白底、浅灰面板、极细边框、柔和阴影
- 颜色 token：
  - 背景 `#fff`，主文字 `#0f1115`，次级 `#61666b`
  - 强调蓝 `#5686fe`，成功/警告/错误 `#22c55e / #f59e0b / #ec1313`
- Mantine 切换 light 主题，预览画布保留深色对比
- 项目列表、底片条、预览工具栏、右侧 Tab 全部适配浅色
- 保留全部功能：项目切换、底片条、星级/颜色、风格/AI、对话、调整、预览

## 质量检查

```bash
npm run typecheck
npm run build
npm run test:e2e     # 先启动 npm run dev，再运行
```

截图输出：`frontend/screenshots/ui_v5.png`
