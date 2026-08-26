import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider, createTheme } from '@mantine/core';
import '@mantine/core/styles.css';
import { DESIGN_TOKENS as T, DARK_RAMP, ACCENT_RAMP } from './theme/tokens';
import App from './App';
import './styles.css';

// 暗房主题（t74）：forceColorScheme=dark；表面三层 canvas/panel/overlay 见 theme/tokens.ts。
const theme = createTheme({
  primaryColor: 'accent',
  primaryShade: { light: 5, dark: 5 },
  defaultRadius: T.radius,
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif',
  headings: {
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif',
    fontWeight: '700',
    // 字距由全局样式承担（Mantine headings 类型不含 letterSpacing）
  },
  colors: {
    dark: [...DARK_RAMP],
    accent: [...ACCENT_RAMP],
    gray: [
      '#f8f9fa',
      '#f1f3f5',
      '#e9ecef',
      '#dee2e6',
      '#ced4da',
      '#adb5bd',
      '#868e96',
      '#61666b',
      '#3b3f44',
      '#0f1115',
    ],
  },
  shadows: {
    md: T.shadowMd,
    lg: T.shadowLg,
  },
  spacing: {
    xs: '8px',
    sm: '12px',
    md: '16px',
    lg: '24px',
    xl: '32px',
  },
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} forceColorScheme="dark">
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </React.StrictMode>,
);
