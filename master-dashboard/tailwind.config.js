/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        teal: {
          950: '#062F2E',
          900: '#0B4A47',
          850: '#083B38',
          800: '#0F5C58',
          700: '#14706B',
        },
        aqua: {
          300: '#6EE7D8',
          400: '#3FD2C0',
          500: '#20BFA9',
        },
        mint: {
          50: '#EAF6F4',
          100: '#E8F2F0',
          200: '#C9D8D6',
          300: '#B6D5D1',
        },
        emerald: {
          500: '#17A58F',
          600: '#0E7A69',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      letterSpacing: {
        micro: '0.125em',
      },
    },
  },
  plugins: [],
};
