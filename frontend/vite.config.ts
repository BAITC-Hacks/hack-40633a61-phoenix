import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-режим: `npm run dev` поднимает Vite на :5173 и проксирует /api на
// backend (uvicorn, по умолчанию :8000) — чтобы не бороться с CORS при
// разработке. В проде (`npm run build` -> frontend/dist) proxy не участвует:
// FastAPI отдаёт собранный бандл и API с одного порта (см. backend/app.py).
const BACKEND_URL = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: true,
      },
    },
  },
})
