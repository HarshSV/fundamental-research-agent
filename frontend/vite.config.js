import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The FastAPI backend (uvicorn) runs on :8000 and owns /api and /exports.
// In Vite dev the app is served from :5173 and its API_BASE resolves to the
// same origin, so we proxy those prefixes through to the backend.
// The production build emits to ./dist. Locally, app.py serves ./frontend/dist/
// at / and mounts /assets; on Vercel, @vercel/static-build serves dist from the
// CDN. No backend business logic changes either way.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/exports': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/generate-report': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/test-flow': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
});
