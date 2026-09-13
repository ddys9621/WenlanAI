import type { ThemeConfig } from 'antd';

/** antd 主题（与 hh-* 设计系统对齐）。只有桥段规划页还在用 antd，ConfigProvider 随该页懒加载，不进主包。 */
export const ANTD_THEME: ThemeConfig = {
  token: {
    colorPrimary: '#007aff',
    colorText: '#0b1a33',
    colorTextSecondary: '#5f7090',
    colorTextTertiary: '#93a4be',
    colorBorder: '#d9e4f3',
    colorBorderSecondary: '#e8eff8',
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
    borderRadius: 0,
    borderRadiusXS: 0,
    borderRadiusSM: 0,
    borderRadiusLG: 0,
    borderRadiusOuter: 0,
  },
};
