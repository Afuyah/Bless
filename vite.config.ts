// vite.config.ts

import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    tailwindcss(),  // ← This integrates Tailwind with Vite
    // ...any other plugins like react(), vue(), etc.
  ],
})
