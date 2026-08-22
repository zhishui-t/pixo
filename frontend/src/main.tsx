import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider, createTheme } from '@mantine/core';
import '@mantine/core/styles.css';
import App from './App';
import './styles.css';

const theme = createTheme({
  primaryColor: 'electric',
  primaryShade: { light: 5, dark: 5 },
  defaultRadius: 'lg',
  fontFamily:
    'Inter, "Segoe UI", "-apple-system", BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif',
  headings: {
    fontFamily:
      'Inter, "Segoe UI", "-apple-system", BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif',
    fontWeight: '700',
  },
  colors: {
    electric: [
      '#eef2ff',
      '#dce5ff',
      '#bfcfff',
      '#a3b8ff',
      '#8ba5ff',
      '#6C8CFF',
      '#4f6ef0',
      '#3f57c9',
      '#2f429f',
      '#233070',
    ],
    dark: [
      '#C1C7D0',
      '#A6AFBB',
      '#7A8494',
      '#5A6472',
      '#3B4452',
      '#242D3B',
      '#161D28',
      '#121821',
      '#0B0F14',
      '#070A0E',
    ],
  },
  shadows: {
    md: '0 10px 32px rgba(0, 0, 0, 0.38)',
    lg: '0 18px 48px rgba(0, 0, 0, 0.45)',
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
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </React.StrictMode>,
);
