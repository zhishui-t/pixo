import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // R14 B2（队长裁决 proxy 方案）：dev 前端同源请求 /api 由 vite 转发到
    // pixo-service（__main__.py 默认 127.0.0.1:8000）——免 CORS，浏览器级
    // 前后端联调可用。后端端口变化时仅改此处。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
