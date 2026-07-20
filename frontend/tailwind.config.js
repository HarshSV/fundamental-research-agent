/** @type {import('tailwindcss').Config} */
// Colors resolve through CSS variables defined in src/theme/tokens.css, so every
// utility class themes automatically between light and dark with no JSX changes.
// The channel format `rgb(var(--x) / <alpha-value>)` preserves Tailwind opacity
// modifiers (e.g. bg-slate-950/90, bg-blue-500/10).
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Helvetica', 'Arial', 'sans-serif'],
        heading: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Helvetica', 'Arial', 'sans-serif'],
      },
      borderRadius: {
        xl: '16px',
        '2xl': '20px',
      },
      colors: {
        slate: {
          50: v('slate-50'),
          100: v('slate-100'),
          200: v('slate-200'),
          300: v('slate-300'),
          350: v('slate-350'),
          400: v('slate-400'),
          450: v('slate-450'),
          500: v('slate-500'),
          505: v('slate-505'),
          550: v('slate-550'),
          555: v('slate-555'),
          600: v('slate-600'),
          700: v('slate-700'),
          800: v('slate-800'),
          850: v('slate-850'),
          855: v('slate-855'),
          900: v('slate-900'),
          950: v('slate-950'),
          955: v('slate-955'),
        },
        blue: {
          200: v('blue-200'),
          300: v('blue-300'),
          400: v('blue-400'),
          500: v('blue-500'),
          550: v('blue-550'),
          600: v('blue-600'),
          700: v('blue-700'),
          950: v('blue-950'),
        },
        emerald: { 400: v('emerald-400'), 500: v('emerald-500') },
        green: { 400: v('green-400'), 500: v('green-500') },
        red: {
          200: v('red-200'),
          300: v('red-300'),
          400: v('red-400'),
          500: v('red-500'),
          900: v('red-900'),
          950: v('red-950'),
        },
        amber: { 400: v('amber-400'), 500: v('amber-500') },
        teal: { 400: v('teal-400'), 500: v('teal-500') },
        brand: { DEFAULT: '#2563eb', light: '#3b82f6', dark: '#1d4ed8' },
      },
    },
  },
  plugins: [],
};
