import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        background: '#0a0a0a',
        foreground: '#ffffff',
        'wine': {
          900: '#7f1d1d',
          800: '#991b1b',
          700: '#b91c1c',
        },
        'khaki': {
          900: '#6b5d1f',
          800: '#8b7d3d',
          700: '#a89d5e',
        },
      },
    },
  },
  plugins: [],
}
export default config
