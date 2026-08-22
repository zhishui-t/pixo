import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider, createTheme } from '@mantine/core';
import '@mantine/core/styles.css';
import App from './App';
import './styles.css';

const theme = createTheme({
  primaryColor: 'accent',
  primaryShade: { light: 5, dark: 5 },
  defaultRadius: 'md',
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif',
  headings: {
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif',
    fontWeight: '650',
  },
  colors: {
    accent: [
      '#eff4ff',
      '#dbe7ff',
      '#bcd2ff',
      '#9ab8ff',
      '#7aa0ff',
      '#5686fe',
      '#3f6ef0',
      '#2f57c9',
      '#233f9c',
      '#1b3073',
    ],
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
    md: '0 4px 16px rgba(0, 0, 0, 0.06)',
    lg: '0 10px 32px rgba(0, 0, 0, 0.08)',
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
    <MantineProvider theme={theme} defaultColorScheme="light">
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </React.StrictMode>,
);
