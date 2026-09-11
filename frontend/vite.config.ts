import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

// Docker 多阶段构建时设置 DOCKER_BUILD=1，输出到本阶段的 dist 目录；
// 本地开发/构建则输出到后端 static 目录供 FastAPI 直接托管。
const isDockerBuild = process.env.DOCKER_BUILD === '1'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: isDockerBuild ? 'dist' : '../backend/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },
  // vitest：被测逻辑全是纯函数 / store，node 环境即可，不引入 jsdom
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
