import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const proxy = { '/api': {
  target: process.env.ECHOMIND_BACKEND_URL || 'http://127.0.0.1:8000',
  changeOrigin: true,
  rewrite: path => path.replace(/^\/api/, ''),
  timeout: 0,
  proxyTimeout: 0,
} }
export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
})
