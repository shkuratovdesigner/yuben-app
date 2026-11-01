import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// The backend's port. `python yuben.py dev` sets YUBEN_PORT for both
// processes, so the proxy follows the backend when 8000 is busy. 127.0.0.1, not
// localhost: Node may resolve localhost to ::1 while uvicorn listens on IPv4.
const backendPort = process.env.YUBEN_PORT?.trim() || '8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
      // The shared contract fixtures, one level up. This used to be a
      // `frontend/fixtures` symlink, which git checks out as a 21-byte text
      // file on Windows without core.symlinks — breaking `dev` and `build`
      // outright. An alias resolves identically on every platform.
      '@fixtures': path.resolve(import.meta.dirname, '../contracts/fixtures'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // Convenience proxy so the app can call `/api/*` in dev without CORS.
    // The typed client also supports an absolute VITE_API_BASE (see lib/env.ts).
    proxy: {
      '/api': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
    },
  },
})
