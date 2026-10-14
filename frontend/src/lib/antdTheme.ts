import type { ThemeConfig } from 'antd';

/** antd 主题（与岚笺风格 token 对齐：墨绿主色、纸色界面、小圆角）。只有桥段规划页还在用 antd，ConfigProvider 随该页懒加载，不进主包。 */
export const ANTD_THEME: ThemeConfig = {
  token: {
    colorPrimary: '#285b4d',
    colorInfo: '#285b4d',
    colorSuccess: '#2f7a5f',
    colorWarning: '#c47a1e',
    colorError: '#a84337',
    colorText: '#1d2420',
    colorTextSecondary: '#46534b',
    colorTextTertiary: '#7d8780',
    colorBorder: '#d4dad6',
    colorBorderSecondary: '#e4e9e5',
    colorBgLayout: '#f3f5f3',
    colorBgContainer: '#ffffff',
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    borderRadius: 4,
    borderRadiusXS: 2,
    borderRadiusSM: 2,
    borderRadiusLG: 6,
    borderRadiusOuter: 4,
  },
};
