// ============================================================
// Ant Design 主题配置
// ============================================================

import type { ThemeConfig } from 'antd';

/** 暗色主题 */
export const darkTheme: ThemeConfig = {
  token: {
    colorPrimary: '#1677ff',
    colorSuccess: '#52c41a',
    colorWarning: '#faad14',
    colorError: '#ff4d4f',
    colorInfo: '#1677ff',
    borderRadius: 6,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
  },
  components: {
    Layout: {
      bodyBg: '#0d1117',
      headerBg: '#161b22',
      siderBg: '#0d1117',
      triggerBg: '#161b22',
    },
    Menu: {
      darkItemBg: '#0d1117',
      darkSubMenuItemBg: '#0d1117',
      darkItemSelectedBg: '#1f2937',
      darkItemHoverBg: '#1f2937',
    },
    Card: {
      colorBgContainer: '#161b22',
      colorBorderSecondary: '#30363d',
    },
    Table: {
      colorBgContainer: '#161b22',
      colorBorderSecondary: '#30363d',
      headerBg: '#161b22',
      rowHoverBg: '#1f2937',
    },
  },
};

/** 亮色主题 */
export const lightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#1677ff',
    colorSuccess: '#52c41a',
    colorWarning: '#faad14',
    colorError: '#ff4d4f',
    colorInfo: '#1677ff',
    borderRadius: 6,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
  },
  components: {
    Layout: {
      bodyBg: '#f5f5f5',
      headerBg: '#ffffff',
      siderBg: '#001529',
      triggerBg: '#001529',
    },
  },
};
