import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
    allowedHosts: [
        'livapi.local',
        '192.168.0.179'],
    hmr: {
        protocol: 'wss',
        host: 'livapi.local'},
  },
})
