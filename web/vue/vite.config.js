import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物输出到 web/dist（server.py 静态服务目录）
export default defineConfig({
  plugins: [vue()],
  base: './',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    port: 5199,
    proxy: {
      // 开发模式代理到后端桥（与生产同源 API）
      '/api': 'http://127.0.0.1:18889',
      '/video': 'http://127.0.0.1:18889',
    },
  },
})
