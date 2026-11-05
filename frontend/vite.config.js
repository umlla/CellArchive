import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发时把 /api 代理到 Flask；构建产物由 Flask 直接托管
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:18600',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        // 固定文件名：index.html 引用的资源名保持稳定，
        // 避免浏览器缓存旧 index.html 后加载不到新的哈希文件而白屏
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name][extname]',
        manualChunks: {
          echarts: ['echarts'],
          element: ['element-plus', '@element-plus/icons-vue'],
          vendor: ['vue', 'vue-router', 'axios'],
        },
      },
    },
  },
})
