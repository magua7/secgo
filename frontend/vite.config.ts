import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

const entries = {
  index: 'index.html',
  login: 'login.html',
  setup: 'setup.html',
} as const

export default defineConfig(({ mode }) => {
  const entryName = mode in entries ? mode as keyof typeof entries : 'index'
  return {
    plugins: [react(), viteSingleFile()],
    base: './',
    build: {
      outDir: resolve(import.meta.dirname, '../secgo/web/static'),
      emptyOutDir: false,
      assetsInlineLimit: 100_000_000,
      cssCodeSplit: false,
      rollupOptions: { input: resolve(import.meta.dirname, entries[entryName]) },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
    },
  }
})
