/** Build via Tailwind CLI standalone (sem Node) — ver docker/web/Dockerfile.
 *
 * Paleta derivada do logotipo: azul-petróleo (marca), grafite (neutros) e
 * verde-sálvia (positivo). `gray`, `red`, `amber`, `green` e `blue` são
 * redefinidos de propósito: os templates já usam esses nomes, e assim todo o
 * sistema muda de tom sem reescrever classe por classe. Os valores ficam em
 * variáveis CSS (static/css/input.css), uma paleta por tema: é isso que permite
 * o tema escuro sem tocar nos templates. A fonte de verdade visual está em
 * docs/ux/02-design-system.md. */
const token = (nome) => `rgb(var(--${nome}) / <alpha-value>)`;
const scale = (nome, passos) => Object.fromEntries(passos.map((n) => [n, token(`${nome}-${n}`)]));

module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./apps/**/templatetags/*.py",
    // Classes de largura dos gráficos do dashboard vêm do Python.
    "./apps/dashboards/bi/*.py",
    // Classes montadas em JS (seletor com busca) também entram no CSS.
    "./static/js/**/*.js",
  ],
  // Classes de estado do dashboard montadas por interpolação no template
  // (`kpi-{{ kpi.estado }}`): o Tailwind não as enxerga no texto.
  safelist: [
    ...["bom", "atencao", "ruim"].flatMap((e) => [`kpi-${e}`, `mark-${e}`]),
    ...["bom", "ruim", "neutro"].map((e) => `delta-${e}`),
    ...["alerta", "atencao", "positivo", "info"].flatMap((n) => [`insight-${n}`, `insight-kind-${n}`]),
    // Miniaturas de tema da página Conta: `theme-preview-{{ valor }}`.
    "theme-preview-light",
    "theme-preview-dark",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "-apple-system", '"Segoe UI"', "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Todas as cores vêm de variáveis CSS (canais "R G B"), definidas em
        // static/css/input.css: o tema claro em `:root`, o escuro em
        // `[data-theme="dark"]`. O nome da classe não muda entre os temas; muda
        // o valor. `<alpha-value>` mantém funcionando `bg-brand-950/60`, `ring-brand-500/25`…
        brand: scale("brand", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]),
        sage: scale("sage", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
        gray: scale("gray", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
        green: scale("sage", [50, 100, 200, 500, 600, 700, 800, 900]),
        amber: scale("amber", [50, 100, 200, 300, 500, 600, 700, 800, 900]),
        red: scale("red", [50, 100, 200, 300, 500, 600, 700, 800, 900]),
        blue: scale("brand", [50, 100, 200, 500, 600, 700, 800, 900]),
        // Papéis que não são uma escala: superfície de cartão, fundo de campo,
        // botões sólidos (primário e destrutivo) e a cor de marcação (checkbox, barras).
        surface: token("surface"),
        field: token("field"),
        action: { DEFAULT: token("action"), hover: token("action-hover"), active: token("action-active"), edge: token("action-edge") },
        danger: { DEFAULT: token("danger"), hover: token("danger-hover"), active: token("danger-active"), edge: token("danger-edge") },
      },
      minHeight: {
        touch: "44px",
      },
      minWidth: {
        touch: "44px",
      },
      boxShadow: {
        // Elevação só onde algo flutua sobre o conteúdo (menu, toast, painel).
        float: "var(--shadow-float)",
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
};
