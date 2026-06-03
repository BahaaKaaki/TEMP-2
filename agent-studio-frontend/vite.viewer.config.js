import path from 'path'

import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Builds the standalone interactive deliverable viewer as a single self-contained
// HTML file (JS + CSS inlined). Output lands in `public/viewer.html` so the main
// app build copies it into `dist/`, where the HTML exporter fetches it at
// runtime, injects the deliverable JSON, and downloads a fully interactive file.
//
// publicDir:false + emptyOutDir:false so building into `public/` neither copies
// `public/` into itself nor wipes the app's other public assets.
export default defineConfig({
  plugins: [tailwindcss(), react(), viteSingleFile()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  publicDir: false,
  build: {
    outDir: 'public',
    emptyOutDir: false,
    cssCodeSplit: false,
    assetsInlineLimit: 100000000,
    rollupOptions: {
      input: path.resolve(__dirname, 'viewer.html'),
    },
  },
})
