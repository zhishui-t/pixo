# Pixo Frontend (Web UI v2)

React 18 + Vite + TypeScript 的本地开发版 Pixo 修图工作台。
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

## UI v2 布局

- 左侧：项目列表，支持搜索、新建、切换项目
- 中间上部：大图预览（原图 / Split / 处理，缩放拖拽，before/after）
- 中间下部：底片条 Filmstrip
  - 缩略图、0-5 星、颜色标签
  - 按星级 / 颜色 / 状态 / 场景过滤，支持排序
- 右侧 Tab：
  - 「风格 / AI」：风格卡片、AI 推荐、当前项目独立对话
  - 「调整」：直方图、基本、曲线、HSL、色彩校准、细节、分离色调等类 LR 分组
- 项目切换时，底片条、预览、右侧参数、对话全部跟随当前项目
- 星级 / 颜色标签实时保存到 Zustand store；后端接口层已预留

## 质量检查

```bash
npm run typecheck
npm run test:e2e     # 先启动 npm run dev，再运行
```

截图输出：`frontend/screenshots/ui_v2.png`
