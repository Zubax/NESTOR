import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    proxy: {
      '/cf3d/api/v1': {
        target: 'https://cyphalcloud.zubax.com',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'esnext',
    outDir: 'dist',
  },
})
