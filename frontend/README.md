# Pixo Frontend (Web UI v1)

React 18 + Vite + TypeScript 的本地开发版 Pixo 修图工作台。
当前不打包、不做桌面/手机安装包；默认使用 mock 数据，配置 `VITE_PIXO_API_URL`
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

## 功能

- PhotoLibrary：导入入口、缩略图网格、筛选、排序/搜索、连拍分组占位
- PreviewViewer：原图 / Split / 处理切换、before/after 滑块、缩放、拖拽、generation 展示
- SliderParam + NumberInput 双向联动、source 徽标、锁定禁用
- InspectorTabs：参数 / 测量 / 溯源 / Agent
- AgentPanel / DSH Chat：消息、推荐卡应用/忽略/编辑
- ReviewQueue、Settings 基础壳
- API client 层：`src/api/client.ts` 直连 pixo-service REST；无服务时自动降级 mock
