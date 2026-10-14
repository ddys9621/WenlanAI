/** @type {import('tailwindcss').Config} */
// 设计系统：参考岚笺「青舟」配色 —— 墨绿主色、纸色界面、朱砂信号色、扁平线框（小圆角、轻阴影）

// 页面里直接用的 Tailwind 默认色板（emerald / red / amber / blue / violet / gray …）统一换成岚笺的低饱和色，
// 语义不变（绿 = 成功、红 = 危险、琥珀 = 提醒），整站色调一致
const jade = { 50: '#eef6f2', 100: '#d9ebe2', 200: '#b5d6c6', 300: '#86b9a2', 400: '#4f9579', 500: '#2f7a5f', 600: '#2a6a55', 700: '#22574a', 800: '#1c463c', 900: '#15352e' }
const cinnabarScale = { 50: '#fbefec', 100: '#f6dcd6', 200: '#ecb8ad', 300: '#de8f80', 400: '#cc6a58', 500: '#b8513f', 600: '#a84337', 700: '#8a362c', 800: '#6e2b24', 900: '#55211c' }
const amberScale = { 50: '#fbf5e9', 100: '#f5e7c8', 200: '#ecd092', 300: '#e2b660', 400: '#d69c3c', 500: '#c0832a', 600: '#9c6a1f', 700: '#80561a', 800: '#654416', 900: '#4d3412' }
const inkBlue = { 50: '#f0f4f7', 100: '#dde6ed', 200: '#bccbd8', 300: '#94aabd', 400: '#6d88a0', 500: '#536f88', 600: '#4d657b', 700: '#3e5265', 800: '#31404f', 900: '#25303c' }
const plum = { 50: '#f6f0f4', 100: '#ebdde6', 200: '#d7bccd', 300: '#bd95ad', 400: '#a2708e', 500: '#8a5878', 600: '#744866', 700: '#5e3a53', 800: '#4a2e42', 900: '#382331' }
const neutral = { 50: '#f6f7f6', 100: '#eceeec', 200: '#dde1de', 300: '#c5ccc7', 400: '#9aa39d', 500: '#737d76', 600: '#59635d', 700: '#46534b', 800: '#2f3833', 900: '#1d2420' }

export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    borderRadius: {
      none: '0px',
      sm: '2px',
      DEFAULT: '4px',
      md: '4px',
      lg: '6px',
      xl: '8px',
      '2xl': '10px',
      '3xl': '12px',
      full: '9999px',
      btn: '4px',
      card: '4px',
      modal: '6px',
      pill: '9999px',
    },
    extend: {
      colors: {
        emerald: jade, green: jade, teal: jade,
        red: cinnabarScale, rose: cinnabarScale,
        amber: amberScale, yellow: amberScale, orange: amberScale,
        blue: inkBlue, sky: inkBlue, indigo: inkBlue, cyan: inkBlue,
        violet: plum, purple: plum, pink: plum, fuchsia: plum,
        gray: neutral, slate: neutral, zinc: neutral, stone: neutral,
        // 主色：墨绿（jade）
        brand: {
          DEFAULT: '#285b4d',
          50: '#f0f6f3',
          100: '#ddebe5',
          200: '#bdd8cc',
          300: '#8fbaa8',
          400: '#4f8a76',
          500: '#285b4d',
          600: '#204a3e',
          700: '#1b3e34',
          800: '#15322a',
          900: '#0f251f',
        },
        // 暖色强调：琥珀
        gold: {
          DEFAULT: '#e99a35',
          50: '#fdf5e8',
          100: '#fae7c8',
          200: '#f5cf92',
          300: '#efa348',
          400: '#e99a35',
          500: '#c47a1e',
        },
        // 信号色：朱砂（选中条 / 标题下划线 / 需要注意）
        signal: {
          DEFAULT: '#d15b3d',
          soft: '#f6e1da',
        },
        cinnabar: {
          DEFAULT: '#a84337',
          deep: '#87362c',
          wash: '#faeae7',
        },
        // 墨绿图标栏
        sidebar: {
          DEFAULT: '#202825',
          hover: '#28322e',
          active: '#2f3a35',
          border: '#323d38',
          text: '#b4c1b9',
          'text-active': '#f3f5f3',
        },
        surface: {
          DEFAULT: '#f3f5f3',
          card: '#ffffff',
          hover: '#e9eeea',
          border: '#d4dad6',
          'border-light': '#e4e9e5',
          paper: '#faf9f5',
          muted: '#e9eeea',
        },
        content: {
          DEFAULT: '#1d2420',
          secondary: '#46534b',
          tertiary: '#7d8780',
          inverse: '#ffffff',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'sans-serif'],
        serif: ['"Noto Serif SC"', '"Source Han Serif SC"', '"Songti SC"', '"STSong"', '"SimSun"', 'serif'],
      },
      boxShadow: {
        xs: '0 1px 2px rgba(29, 36, 32, 0.06)',
        card: '0 1px 2px rgba(29, 36, 32, 0.05), 0 10px 24px -18px rgba(29, 36, 32, 0.22)',
        md: '0 12px 32px -20px rgba(29, 36, 32, 0.28)',
        lg: '0 20px 48px -28px rgba(29, 36, 32, 0.32)',
        xl: '0 28px 72px -36px rgba(29, 36, 32, 0.38)',
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.25s ease-out',
        'slide-down': 'slideDown 0.2s ease-out',
        'scale-in': 'scaleIn 0.16s ease-out',
        'float-soft': 'floatSoft 6s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          '0%': { opacity: '0', transform: 'translateY(-6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.98)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        floatSoft: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
      },
    },
  },
  plugins: [],
}
