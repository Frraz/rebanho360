/** Build via Tailwind CLI standalone (sem Node) — ver docker/web/Dockerfile.
 *
 * Paleta derivada do logotipo: azul-petróleo (marca), grafite (neutros) e
 * verde-sálvia (positivo). `gray`, `red`, `amber`, `green` e `blue` são
 * redefinidos de propósito: os templates já usam esses nomes, e assim todo o
 * sistema muda de tom sem reescrever classe por classe. A fonte de verdade
 * visual está em docs/ux/02-design-system.md. */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./apps/**/templatetags/*.py",
    // Classes montadas em JS (seletor com busca) também entram no CSS.
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "-apple-system", '"Segoe UI"', "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        brand: {
          50: "#eef5f7",
          100: "#d8e8ed",
          200: "#b3d0da",
          300: "#82afbf",
          400: "#4f8a9d",
          500: "#2f6d82",
          600: "#1f566b",
          700: "#194659",
          800: "#143949",
          900: "#0f2d3a",
          950: "#0a1d27",
        },
        sage: {
          50: "#f1f6f3",
          100: "#dfeae4",
          200: "#c0d6c9",
          300: "#98b9a6",
          400: "#729c85",
          500: "#58846a",
          600: "#46705a",
          700: "#395a49",
          800: "#2f493c",
          900: "#273d33",
        },
        gray: {
          50: "#f6f8f9",
          100: "#eef1f3",
          200: "#e1e6e9",
          300: "#cdd4d9",
          400: "#9ba6ae",
          500: "#66727b",
          600: "#4f5a63",
          700: "#3b454d",
          800: "#272f36",
          900: "#161c21",
        },
        green: {
          50: "#f1f6f3",
          100: "#dfeae4",
          200: "#c0d6c9",
          500: "#58846a",
          600: "#46705a",
          700: "#395a49",
          800: "#2f493c",
          900: "#273d33",
        },
        amber: {
          50: "#fdf7e8",
          100: "#faecc6",
          200: "#f2d58f",
          300: "#e8bb55",
          500: "#b7791f",
          600: "#9a6212",
          700: "#7f4f0e",
          800: "#68410f",
          900: "#553510",
        },
        red: {
          50: "#fcf1f0",
          100: "#f9dedc",
          200: "#f1bdb9",
          300: "#e59892",
          500: "#c4423a",
          600: "#ab342d",
          700: "#8f2b25",
          800: "#762520",
          900: "#5f201c",
        },
        blue: {
          50: "#eef5f7",
          100: "#d8e8ed",
          200: "#b3d0da",
          500: "#2f6d82",
          600: "#1f566b",
          700: "#194659",
          800: "#143949",
          900: "#0f2d3a",
        },
      },
      minHeight: {
        touch: "44px",
      },
      minWidth: {
        touch: "44px",
      },
      boxShadow: {
        // Elevação só onde algo flutua sobre o conteúdo (menu, toast, painel).
        float: "0 8px 24px -6px rgba(10, 29, 39, 0.18), 0 2px 6px -2px rgba(10, 29, 39, 0.10)",
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
};
