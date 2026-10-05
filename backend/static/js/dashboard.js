/* Dashboard analítico — desenha os gráficos que o servidor especificou.
 *
 * O servidor decide O QUE mostrar (apps/dashboards/bi/specs.py: dados já
 * calculados, rótulos, tabela equivalente); este arquivo só DESENHA, sobre o
 * ECharts hospedado em static/vendor. Nada aqui recalcula indicador.
 *
 * Regras de desenho (skill dataviz, docs/ux/02-design-system.md#13):
 *  - um eixo de valor só (nunca eixo duplo);
 *  - cor segue a entidade, paleta categórica validada, ordem fixa, nunca ciclada;
 *  - magnitude = uma matiz (petróleo, clara → escura); polaridade = azul ↔ vermelho;
 *  - barras finas com ponta arredondada, linhas de 2 px, grade em fio contínuo;
 *  - tooltip nunca é o único caminho: todo gráfico tem tabela equivalente;
 *  - texto nunca usa a cor da série.
 */
(() => {
  "use strict";
  if (window.__rebanhoDash) return;
  window.__rebanhoDash = true;

  // ------------------------------------------------------------------ tokens
  // Dois temas, cada um com a paleta validada para a sua superfície (no escuro
  // não é inversão: os mesmos oito matizes com passos próprios, ver validador
  // `--mode dark`). O tema vem do <html data-theme>, que o servidor grava; ele só
  // muda na página Conta, e a página recarrega ao salvar.
  //
  // Categórica claro: validada com scripts/validate_palette.js (fundo branco):
  // lightness, croma, separação CVD ≥ 8 e piso de visão normal ≥ 15 passam. Três
  // cores ficam abaixo de 3:1 no branco — por isso há rótulo direto, legenda e
  // tabela equivalente em todo gráfico (alívio obrigatório). Escura: passa todos os
  // portões sobre #101a21 (CVD adjacente 8,4 · visão normal 19,3 · contraste ≥ 3:1).
  const DARK = document.documentElement.dataset.theme === "dark";
  const TEMA = DARK
    ? {
        cat: ["#3a9bc4", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
        token: { marca: "#5ab8d6", positivo: "#4fa8c9", negativo: "#e5675f", neutro: "#76899a", alerta: "#e0a63a", total: "#8fa3b0" },
        // Magnitude no escuro: o pouco some no fundo e o muito acende.
        seq: ["#14303d", "#1f5a70", "#2f87a6", "#5ab8d6", "#a9e0ee"],
        ord: ["#2a5a6e", "#34748c", "#3f8ea9", "#52a7c3", "#6dbdd8", "#8fd0e6", "#b4e2f0"],
        tree: ["#27758f", "#205f74", "#194b5c", "#133a48"],
        ink: "#eef3f6", ink2: "#adbcc5", muted: "#93a4af", grid: "#1d2b35", axis: "#2c3d48", surface: "#111b22",
        tipBg: "#172229", tipBorder: "#2d3f4b", tipShadow: "0 12px 32px -8px rgba(0,0,0,.65)",
        crumb: "#17232b", vazio: "#0f1a21", destaque: "rgba(90,184,214,0.10)", sombra: "rgba(255,255,255,0.05)",
        hover: "rgba(255,255,255,0.10)", sobreClaro: "#06222d",
      }
    : {
        cat: ["#1a78a0", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
        token: { marca: "#1f566b", positivo: "#2f6d82", negativo: "#c4423a", neutro: "#9ba6ae", alerta: "#eda100", total: "#3b454d" },
        // Sequencial (magnitude) e ordinal (etapas ordenadas): a matiz petróleo da marca.
        seq: ["#eef5f7", "#b3d0da", "#4f8a9d", "#1f566b", "#0f2d3a"],
        ord: ["#82afbf", "#4f8a9d", "#2f6d82", "#1f566b", "#194659", "#143949", "#0f2d3a"],
        tree: ["#2f6d82", "#1f566b", "#143949", "#0f2d3a"],
        ink: "#161c21", ink2: "#4f5a63", muted: "#66727b", grid: "#e1e6e9", axis: "#cdd4d9", surface: "#ffffff",
        tipBg: "#ffffff", tipBorder: "#e1e6e9", tipShadow: "0 8px 24px -6px rgba(10,29,39,.18)",
        crumb: "#eef1f3", vazio: "#f6f8f9", destaque: "rgba(47,109,130,0.08)", sombra: "rgba(22,28,33,0.05)",
        hover: "rgba(22,28,33,0.08)", sobreClaro: "#ffffff",
      };
  const CAT = TEMA.cat;
  const TOKEN = TEMA.token;
  const SEQ = TEMA.seq;
  const ORD = TEMA.ord;
  const TREE = TEMA.tree;
  const INK = TEMA.ink;
  const INK2 = TEMA.ink2;
  const MUTED = TEMA.muted;
  const GRID = TEMA.grid;
  const AXIS = TEMA.axis;
  const SURFACE = TEMA.surface;
  const FONT = '"IBM Plex Sans", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';
  const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const state = { texturas: false };
  try { state.texturas = localStorage.getItem("dashTexturas") === "1"; } catch (e) { /* sem storage */ }

  // --------------------------------------------------------------- formatação
  const nfs = {};
  const nf = (d) => (nfs[d] = nfs[d] || new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const ok = (v) => v !== null && v !== undefined && !Number.isNaN(v);

  function fmt(v, f) {
    if (!ok(v)) return "—";
    switch (f) {
      case "brl": return "R$ " + nf(2).format(v);
      case "pct": return nf(1).format(v) + "%";
      case "pct2": return nf(2).format(v) + "%";
      case "kg": return nf(0).format(v) + " kg";
      case "kg2": return nf(2).format(v) + " kg";
      case "kgdia": return nf(3).format(v) + " kg/dia";
      case "arroba": return nf(2).format(v) + " @";
      case "dias": return nf(0).format(v) + " dias";
      case "cb": return nf(0).format(v) + " cb";
      case "ha": return nf(2).format(v) + " cb/ha";
      case "num1": return nf(1).format(v);
      case "num2": return nf(2).format(v);
      default: return nf(0).format(v);
    }
  }
  // Compacto, para eixo e rótulo: "R$ 1,2 mi", "R$ 850 mil".
  function short(v, f) {
    if (!ok(v)) return "—";
    const a = Math.abs(v);
    if (f === "brl") {
      const sinal = v < 0 ? "−" : "";
      if (a >= 1e6) return sinal + "R$ " + nf(a >= 1e7 ? 1 : 2).format(a / 1e6) + " mi";
      if (a >= 1e3) return sinal + "R$ " + nf(a >= 1e5 ? 0 : 1).format(a / 1e3) + " mil";
      return sinal + "R$ " + nf(a < 100 ? 2 : 0).format(a);
    }
    if (f === "pct" || f === "pct2") return nf(a >= 10 ? 0 : 1).format(v) + "%";
    if (f === "kgdia") return nf(2).format(v);
    if (f === "num2" || f === "ha") return nf(2).format(v);
    if (f === "kg") return nf(0).format(v);
    if (a >= 1e6) return nf(1).format(v / 1e6) + " mi";
    if (a >= 1e4) return nf(0).format(v / 1e3) + " mil";
    return nf(0).format(v);
  }
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // -------------------------------------------------------------------- cores
  function ordCor(i, n) {
    const idx = n <= 1 ? 3 : Math.round((i * (ORD.length - 1)) / (n - 1));
    return ORD[idx];
  }
  function colorOf(c, i) {
    if (typeof c === "number") return CAT[Math.min(c, CAT.length - 1)];
    if (typeof c === "string") return TOKEN[c] || c;
    return CAT[Math.min(i, CAT.length - 1)];
  }
  // Textura (opt-in, 45° / 135°): só quando o usuário liga.
  const DECAL = (i) => ({
    symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: i % 2 ? Math.PI / 4 : -Math.PI / 4,
    color: "rgba(255,255,255,0.55)", symbolSize: 1,
  });
  const PREVISTO = { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [3, 3], rotation: Math.PI / 4, color: "rgba(255,255,255,0.7)", symbolSize: 1 };

  // ------------------------------------------------------------------ tooltip
  function tip(titulo, linhas) {
    const corpo = linhas
      .map((l) => {
        const chave = l.cor
          ? `<span style="display:inline-block;width:12px;height:3px;border-radius:2px;margin-right:7px;vertical-align:middle;background:${esc(l.cor)}"></span>`
          : "";
        return `<div style="display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin-top:3px">` +
          `<span style="color:${INK2}">${chave}${esc(l.nome)}</span>` +
          `<span style="font-weight:600;color:${INK};font-variant-numeric:tabular-nums">${esc(l.valor)}</span></div>` +
          (l.extra ? `<div style="color:${MUTED};font-size:11px;text-align:right">${esc(l.extra)}</div>` : "");
      })
      .join("");
    return `<div style="font-weight:600;color:${INK}">${esc(titulo)}</div>${corpo}`;
  }

  function base(compact) {
    return {
      backgroundColor: "transparent",
      animation: !reduced,
      animationDuration: 350,
      textStyle: { fontFamily: FONT, color: INK2, fontSize: compact ? 11 : 12 },
      aria: { enabled: true, label: { enabled: false }, decal: { show: state.texturas } },
      tooltip: {
        confine: true,
        backgroundColor: TEMA.tipBg,
        borderColor: TEMA.tipBorder,
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { color: INK, fontSize: 12, fontFamily: FONT },
        extraCssText: `box-shadow:${TEMA.tipShadow};border-radius:8px;max-width:min(320px,86vw);white-space:normal;`,
        transitionDuration: 0.1,
      },
    };
  }

  // ------------------------------------------------------------- cartesiano
  function cartesiano(o, ctx) {
    const f = o.formato;
    const horiz = !!o.horizontal;
    const series = o.series;
    const compact = ctx.compact;
    const numericoX = o.x_tipo === "valor";
    const rotuloLongo = !numericoX && o.x.some((x) => String(x).length > 9);
    // Muitas categorias de rótulo longo: gira em vez de esconder metade delas.
    const girar = !horiz && !numericoX && o.x.length > 5 && rotuloLongo && o.x.length <= 24;
    const multi = series.filter((s) => !s.fundo).length > 1;
    const ranking = !!o.ranking;
    const fmtDe = (nome) => (o.formatos_series && o.formatos_series[nome]) || f;

    const valorAxis = {
      type: "value",
      name: horiz ? "" : o.titulo_y || "",
      nameTextStyle: { color: MUTED, align: "left", padding: [0, 0, 0, -4] },
      axisLabel: { color: MUTED, formatter: (v) => short(v, f) },
      splitLine: { lineStyle: { color: GRID, width: 1, type: "solid" } },
      axisLine: { show: false },
      axisTick: { show: false },
    };
    // Ranking: todas as barras têm o valor na ponta; eixo numérico só poluiria.
    if (ranking) valorAxis.axisLabel.show = false;
    // Barra negativa com rótulo na ponta: folga à esquerda para o texto não
    // encostar no nome da categoria.
    if (horiz && series.some((s) => s.por_sinal)) {
      valorAxis.min = (v) => (v.min < 0 ? v.min * 1.3 : v.min);
      valorAxis.max = (v) => (v.max > 0 ? v.max * 1.15 : v.max);
    }
    if (o.faixa) {
      valorAxis.scale = true;
      valorAxis.min = (v) => Math.floor(Math.min(v.min, o.faixa.de) - 1);
      valorAxis.max = (v) => Math.ceil(Math.max(v.max, o.faixa.ate) + 1);
    }
    const categoriaAxis = numericoX
      ? {
          type: "value", scale: true, name: o.titulo_x || "", nameLocation: "middle", nameGap: 28,
          nameTextStyle: { color: MUTED }, axisLabel: { color: MUTED },
          splitLine: { show: false }, axisLine: { lineStyle: { color: AXIS } }, axisTick: { show: false },
        }
      : {
          type: "category",
          data: o.x,
          inverse: horiz,
          axisLine: { lineStyle: { color: AXIS }, onZero: !(horiz && series.some((s) => s.por_sinal)) },
          axisTick: { show: false },
          axisLabel: horiz
            ? { color: INK2, width: compact ? 92 : 128, overflow: "truncate", hideOverlap: false }
            : girar
              ? { color: MUTED, rotate: 32, interval: 0, hideOverlap: false }
              : { color: MUTED, hideOverlap: true, interval: "auto" },
          name: !horiz && o.titulo_x ? o.titulo_x : "",
          nameLocation: "middle", nameGap: girar ? 52 : 30, nameTextStyle: { color: MUTED },
        };

    const rotulado = series.some((s) => s.rotulo);
    const echSeries = series.map((s, i) => {
      const cor = s.fundo ? TOKEN.neutro : colorOf(s.cor, i);
      const barra = s.tipo === "bar";
      const area = s.tipo === "area";
      const pilha = s.pilha ? "p-" + (barra ? "b" : "l") : undefined;
      let ultimo = -1;
      if (!barra) s.dados.forEach((d, k) => { if (ok(Array.isArray(d) ? d[1] : d)) ultimo = k; });

      const dados = s.dados.map((d, k) => {
        const v = Array.isArray(d) ? d[1] : d;
        if (barra) {
          const item = { value: d };
          let c = cor;
          if (s.ordinal) c = ordCor(k, s.dados.length);
          if (s.por_sinal) c = ok(v) && v < 0 ? TOKEN.negativo : TOKEN.positivo;
          if (ok(s.por_limite)) c = ok(v) && v > s.por_limite ? TOKEN.negativo : TOKEN.marca;
          item.itemStyle = { color: c };
          if (s.rotulo) {
            const neg = ok(v) && v < 0;
            // Barra negativa na horizontal: o rótulo vai para o lado do zero (vazio), longe do nome da categoria.
            item.label = { show: true, position: horiz ? "right" : neg ? "bottom" : "top" };
          }
          return item;
        }
        if (k === ultimo && !s.fundo) {
          return { value: d, symbol: "circle", symbolSize: 8, itemStyle: { color: cor, borderColor: SURFACE, borderWidth: 2 } };
        }
        return d;
      });

      const e = {
        name: s.nome,
        type: barra ? "bar" : "line",
        data: dados,
        stack: pilha,
        z: s.fundo ? 1 : 3,
        emphasis: { focus: "none" },
        itemStyle: { color: cor },
        tooltip: {},
      };
      if (barra) {
        e.barMaxWidth = 24;
        e.barGap = "12%";
        e.barCategoryGap = "38%";
        const raio = horiz ? [0, 4, 4, 0] : [4, 4, 0, 0];
        e.itemStyle = Object.assign({ color: cor, borderRadius: pilha ? 0 : raio }, pilha ? { borderColor: SURFACE, borderWidth: 1 } : {});
        if (s.previsto) e.itemStyle.decal = PREVISTO;
        else if (state.texturas) e.itemStyle.decal = DECAL(i);
        if (s.rotulo) {
          e.label = {
            show: true, color: INK, fontSize: compact ? 10 : 11, fontFamily: FONT, distance: 4,
            formatter: (p) => short(Array.isArray(p.value) ? p.value[1] : p.value, f),
          };
        }
      } else {
        e.showSymbol = false;
        e.symbol = "circle";
        e.symbolSize = 6;
        e.connectNulls = false;
        e.smooth = false;
        e.lineStyle = { color: cor, width: s.fundo ? 1.2 : 2, opacity: s.fundo ? 0.55 : 1, cap: "round", join: "round" };
        e.itemStyle = { color: cor };
        // Área empilhada de várias séries precisa de corpo para se distinguir; uma
        // série só (uma fazenda) é apenas um traço com leve preenchimento.
        const empilhadas = series.filter((x) => x.tipo === "area" && x.pilha).length > 1;
        if (area) e.areaStyle = { color: cor, opacity: pilha && empilhadas ? 0.78 : 0.12 };
        if (area && pilha && empilhadas) e.lineStyle.width = 1;
      }
      return e;
    });

    // Linhas de referência e faixa: penduradas na primeira série visível.
    const alvo = echSeries.find((s, i) => !series[i].fundo) || echSeries[0];
    if (alvo && o.linhas_ref && o.linhas_ref.length) {
      alvo.markLine = {
        silent: true, symbol: "none",
        lineStyle: { color: INK2, width: 1.25, type: "solid" },
        label: { color: INK2, fontSize: 11, formatter: (p) => p.name, position: horiz ? "end" : "insideEndTop" },
        data: o.linhas_ref.map((r) => (horiz ? { xAxis: r.valor, name: r.rotulo } : { yAxis: r.valor, name: r.rotulo })),
      };
    }
    if (alvo && o.faixa) {
      alvo.markArea = {
        silent: true,
        itemStyle: { color: TEMA.destaque },
        label: { color: INK2, fontSize: 11, position: "insideTopLeft" },
        data: [[{ yAxis: o.faixa.de, name: o.faixa.rotulo }, { yAxis: o.faixa.ate }]],
      };
    }

    const comLegenda = multi && !ranking;
    // Legenda em linhas (nunca paginada): estima quantas linhas o texto ocupa.
    const nomes = series.filter((s) => !s.fundo).map((s) => s.nome);
    const largura = ctx.el.clientWidth || 600;
    const linhasLegenda = comLegenda
      ? Math.max(1, Math.ceil(nomes.reduce((a, n) => a + n.length * 6.8 + 34, 0) / Math.max(largura - 16, 200)))
      : 0;
    return {
      legend: {
        show: comLegenda, top: 0, left: 0, type: "plain", icon: "roundRect", itemWidth: 12, itemHeight: 6,
        itemGap: 14, textStyle: { color: INK2 }, data: nomes,
      },
      grid: {
        top: (comLegenda ? 14 + linhasLegenda * 22 : 14) + (!horiz && o.titulo_y ? 16 : 0),
        left: 8, right: rotulado && horiz ? (compact ? 56 : 84) : 16, bottom: numericoX ? 34 : !horiz && o.titulo_x ? (girar ? 60 : 34) : girar ? 10 : 4,
        containLabel: true,
      },
      xAxis: horiz ? valorAxis : categoriaAxis,
      yAxis: horiz ? categoriaAxis : valorAxis,
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: horiz ? "shadow" : "line",
          lineStyle: { color: AXIS, width: 1, type: "solid" },
          shadowStyle: { color: TEMA.sombra },
        },
        formatter: (params) => {
          const lista = Array.isArray(params) ? params : [params];
          const titulo = numericoX ? fmt(lista[0].value[0], "num0") + " dias" : lista[0].axisValueLabel;
          const linhas = lista
            .filter((p) => !series[p.seriesIndex].fundo || lista.length === 1)
            .map((p) => {
              const s = series[p.seriesIndex];
              const v = Array.isArray(p.value) ? p.value[1] : p.value;
              let extra = "";
              if (s.participacao && ok(s.participacao[p.dataIndex])) {
                extra = nf(1).format(s.participacao[p.dataIndex]) + "% do total · " + nf(1).format(s.acumulado[p.dataIndex]) + "% acumulado";
              }
              if (ok(s.por_limite) && ok(v) && v > s.por_limite) extra = "acima do limite de " + fmt(s.por_limite, f);
              return { cor: colorOf(s.cor, p.seriesIndex), nome: s.nome.trim(), valor: fmt(v, fmtDe(s.nome)), extra };
            });
          return tip(titulo, linhas);
        },
      },
      series: echSeries,
    };
  }

  // ------------------------------------------------------------------- rosca
  function rosca(o, ctx) {
    const f = o.formato;
    const total = o.itens.reduce((a, i) => a + (i.valor || 0), 0);
    const itens = o.itens.filter((i) => i.valor).map((it, i) => ({
      name: it.nome, value: it.valor, itemStyle: { color: colorOf(it.cor, i) },
    }));
    const pct = {};
    itens.forEach((i) => { pct[i.name] = total ? (i.value / total) * 100 : 0; });
    const tam = o.centro.valor.length > 12 ? 13 : o.centro.valor.length > 8 ? 16 : 20;
    return {
      legend: {
        bottom: 0, left: "center", type: "plain", icon: "roundRect", itemWidth: 12, itemHeight: 6, itemGap: 12,
        textStyle: { color: INK2 }, formatter: (n) => `${n}  ${nf(1).format(pct[n] || 0)}%`,
      },
      tooltip: {
        trigger: "item",
        formatter: (p) => tip(p.name, [
          { cor: p.color, nome: "Valor", valor: fmt(p.value, f) },
          { nome: "Participação", valor: nf(1).format(p.percent) + "%" },
        ]),
      },
      series: [{
        type: "pie", radius: ["54%", "78%"], center: ["50%", ctx.compact ? "40%" : "42%"],
        avoidLabelOverlap: true, label: { show: false }, labelLine: { show: false },
        itemStyle: { borderColor: SURFACE, borderWidth: 2 },
        emphasis: { scaleSize: 4 },
        data: itens,
      }],
      graphic: [
        { type: "text", left: "center", top: ctx.compact ? "32%" : "34%", style: { text: o.centro.valor, font: `600 ${tam}px ${FONT}`, fill: INK, textAlign: "center" } },
        { type: "text", left: "center", top: ctx.compact ? "42%" : "44%", style: { text: o.centro.rotulo, font: `400 12px ${FONT}`, fill: MUTED, textAlign: "center" } },
      ],
    };
  }

  // ----------------------------------------------------------------- treemap
  function treemap(o, ctx) {
    const f = o.formato;
    const conv = (n) => ({ name: n.nome, value: n.valor, children: n.filhos ? n.filhos.map(conv) : undefined });
    const max = Math.max(...o.nos.map((n) => n.valor || 0), 1);
    return {
      tooltip: {
        trigger: "item",
        formatter: (p) => tip(p.name, [{ nome: "Valor", valor: fmt(p.value, f) }]),
      },
      series: [{
        type: "treemap", roam: false, nodeClick: "zoomToNode", width: "100%", height: ctx.compact ? "100%" : "92%",
        breadcrumb: { show: true, bottom: 0, height: 22, itemStyle: { color: TEMA.crumb, textStyle: { color: INK2 }, borderColor: GRID } },
        label: {
          show: true, color: "#fff", fontSize: ctx.compact ? 11 : 12, fontFamily: FONT,
          formatter: (p) => `${p.name}\n${short(p.value, f)}`, overflow: "truncate",
        },
        upperLabel: { show: false },
        itemStyle: { borderColor: SURFACE, borderWidth: 2, gapWidth: 2 },
        levels: [
          { color: TREE, colorMappingBy: "value", itemStyle: { borderColor: SURFACE, borderWidth: 2, gapWidth: 2 } },
          { colorAlpha: [0.78, 1], itemStyle: { gapWidth: 1, borderWidth: 1, borderColor: SURFACE } },
        ],
        visualMin: 0, visualMax: max,
        data: o.nos.map(conv),
      }],
    };
  }

  // --------------------------------------------------------------- mapa de calor
  function calor(o, ctx) {
    const f = o.formato;
    const max = Math.max(...o.celulas.map((c) => c[2] || 0), 1);
    const rotulos = o.celulas.length <= 60 && !ctx.compact;
    const data = o.celulas.map((c) => ({
      value: c,
      label: { show: rotulos, color: c[2] / max > 0.5 ? TEMA.sobreClaro : INK, fontSize: 11, formatter: () => short(c[2], f) },
    }));
    return {
      tooltip: {
        trigger: "item",
        formatter: (p) => tip(`${o.y[p.value[1]]} · ${o.x[p.value[0]]}`, [{ nome: o.titulo_y || "Valor", valor: fmt(p.value[2], f) }]),
      },
      grid: { top: 8, left: 8, right: 16, bottom: 56, containLabel: true },
      xAxis: { type: "category", data: o.x, splitArea: { show: false }, axisLine: { lineStyle: { color: AXIS } }, axisTick: { show: false }, axisLabel: { color: MUTED, hideOverlap: false, interval: 0, rotate: o.x.length > 4 ? 32 : 0 } },
      yAxis: { type: "category", data: o.y, inverse: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: INK2, width: ctx.compact ? 84 : 120, overflow: "truncate" } },
      visualMap: {
        min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 12, itemHeight: ctx.compact ? 110 : 160,
        inRange: { color: SEQ }, text: ["mais", "menos"], textStyle: { color: INK2 }, formatter: (v) => short(v, f),
      },
      series: [{
        type: "heatmap", data,
        itemStyle: { borderColor: SURFACE, borderWidth: 2, borderRadius: 3 },
        emphasis: { itemStyle: { borderColor: INK, borderWidth: 1.5 } },
      }],
    };
  }

  // ----------------------------------------------------------------- cascata
  function cascata(o, ctx) {
    const f = o.formato;
    const nomes = o.passos.map((p) => p.nome);
    const basePos = [], visPos = [], baseNeg = [], visNeg = [], topo = [], cores = [], acumulados = [];
    let correndo = 0;
    o.passos.forEach((p) => {
      let de, ate;
      if (p.tipo === "total") { de = 0; ate = p.valor; correndo = p.valor; }
      else { de = correndo; ate = correndo + p.valor; correndo = ate; }
      const lo = Math.min(de, ate), hi = Math.max(de, ate);
      basePos.push(Math.max(lo, 0));
      visPos.push(Math.max(hi, 0) - Math.max(lo, 0));
      baseNeg.push(Math.min(hi, 0));
      visNeg.push(Math.min(lo, 0) - Math.min(hi, 0));
      topo.push(hi);
      acumulados.push(correndo);
      cores.push(p.tipo === "total" ? TOKEN.total : p.valor >= 0 ? TOKEN.positivo : TOKEN.negativo);
    });
    const rotulo = (posicao) => ({
      show: true, position: posicao, color: INK, fontSize: ctx.compact ? 10 : 11, fontFamily: FONT,
      formatter: (p) => (p.value ? short(o.passos[p.dataIndex].valor, f) : ""),
    });
    const barra = (nome, dados, visivel, posicao) => ({
      name: nome, type: "bar", stack: "w", barMaxWidth: 36, silent: !visivel,
      label: visivel ? rotulo(posicao) : { show: false },
      itemStyle: visivel
        ? { borderRadius: 3 }
        : { color: "transparent" },
      data: dados.map((v, i) => ({ value: v, itemStyle: visivel ? { color: cores[i], decal: o.passos[i].tipo === "total" ? undefined : (state.texturas ? DECAL(o.passos[i].valor >= 0 ? 0 : 1) : undefined) } : { color: "transparent" } })),
      tooltip: { show: false },
    });
    return {
      grid: { top: 28, left: 8, right: 12, bottom: 4, containLabel: true },
      xAxis: { type: "category", data: nomes, axisTick: { show: false }, axisLine: { lineStyle: { color: AXIS } }, axisLabel: { color: INK2, interval: 0, width: ctx.compact ? 58 : 84, overflow: "break", lineHeight: 14 } },
      yAxis: { type: "value", axisLabel: { color: MUTED, formatter: (v) => short(v, f) }, splitLine: { lineStyle: { color: GRID, width: 1 } }, axisLine: { show: false }, axisTick: { show: false } },
      tooltip: {
        trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: TEMA.sombra } },
        formatter: (ps) => {
          const i = ps[0].dataIndex, p = o.passos[i];
          return tip(p.nome, [
            { cor: cores[i], nome: p.tipo === "total" ? "Total" : "Variação", valor: fmt(p.valor, f) },
            { nome: "Acumulado até aqui", valor: fmt(acumulados[i], f) },
          ]);
        },
      },
      series: [
        barra("__base+", basePos, false), barra("Valor", visPos, true, "top"),
        barra("__base-", baseNeg, false), barra("Valor ", visNeg, true, "bottom"),
      ],
    };
  }

  // --------------------------------------------------------------- dispersão
  function dispersao(o, ctx) {
    const todos = o.series.flatMap((s) => s.pontos);
    const rs = todos.map((p) => p.r).filter(ok);
    const rmax = rs.length ? Math.max(...rs) : 1;
    const tam = (p) => (ok(p.r) ? 12 + 24 * Math.sqrt(p.r / rmax) : 14);
    const diagonal = (o.linhas_ref || []).some((r) => r.tipo === "diagonal");
    let eixoMin, eixoMax;
    if (diagonal && todos.length) {
      const v = todos.flatMap((p) => [p.x, p.y]);
      eixoMin = Math.floor(Math.min(...v) * 0.95); eixoMax = Math.ceil(Math.max(...v) * 1.05);
    }
    const eixo = (nome, formato, vertical) => ({
      type: "value", scale: true, name: nome || "", nameLocation: "middle", nameGap: vertical ? 56 : 30,
      nameTextStyle: { color: MUTED }, axisLabel: { color: MUTED, formatter: (v) => short(v, formato) },
      splitLine: { lineStyle: { color: GRID, width: 1 } }, axisLine: { show: false }, axisTick: { show: false },
      min: diagonal ? eixoMin : undefined, max: diagonal ? eixoMax : undefined,
    });
    const yAxis = eixo(o.titulo_y, o.formato_y, true);
    if (o.faixa) {
      yAxis.min = (v) => Math.floor(Math.min(v.min, o.faixa.de) - 1);
      yAxis.max = (v) => Math.ceil(Math.max(v.max, o.faixa.ate) + 1);
    }
    const series = [];
    const legenda = [];
    o.series.forEach((s, i) => {
      const cor = colorOf(s.cor, i);
      legenda.push(s.nome);
      const dados = s.pontos.map((p) => ({ value: [p.x, p.y], nome: p.nome, r: p.r, size: tam(p) }));
      series.push({
        name: s.nome, type: "scatter", data: dados, z: 3,
        symbolSize: (v, par) => par.data.size,
        itemStyle: { color: cor, opacity: 0.85, borderColor: SURFACE, borderWidth: 2 },
        tooltip: { show: false },
      });
      // Área de toque ≥ 24 px: ponto pequeno é alvo ruim. Camada transparente
      // maior carrega o tooltip e mostra um anel ao passar o mouse.
      series.push({
        name: s.nome + "·alvo", type: "scatter", data: dados, z: 4,
        symbolSize: (v, par) => Math.max(26, par.data.size + 6),
        itemStyle: { color: "transparent", borderColor: "transparent" },
        emphasis: { scale: false, itemStyle: { color: TEMA.hover, borderColor: INK, borderWidth: 1.25 } },
        tooltip: {
          trigger: "item",
          formatter: (p) => {
            const d = p.data;
            const linhas = [
              { cor, nome: o.titulo_x || "X", valor: fmt(d.value[0], o.formato_x) },
              { cor, nome: o.titulo_y || "Y", valor: fmt(d.value[1], o.formato_y) },
            ];
            if (ok(d.r)) linhas.push({ nome: "Cabeças", valor: nf(0).format(d.r) });
            return tip(d.nome || s.nome, linhas);
          },
        },
      });
    });
    const alvo = series[0];
    if (alvo && o.faixa) {
      alvo.markArea = {
        silent: true, itemStyle: { color: TEMA.destaque },
        label: { color: INK2, fontSize: 11, position: "insideTopLeft" },
        data: [[{ yAxis: o.faixa.de, name: o.faixa.rotulo }, { yAxis: o.faixa.ate }]],
      };
    }
    if (alvo && diagonal) {
      const r = o.linhas_ref.find((x) => x.tipo === "diagonal");
      alvo.markLine = {
        silent: true, symbol: "none", lineStyle: { color: INK2, width: 1.25, type: "solid" },
        label: { color: INK2, fontSize: 11, formatter: r.rotulo, position: "insideEndTop" },
        data: [[{ coord: [eixoMin, eixoMin] }, { coord: [eixoMax, eixoMax] }]],
      };
    }
    return {
      legend: { show: o.series.length > 1, top: 0, left: 0, icon: "circle", itemWidth: 9, itemHeight: 9, textStyle: { color: INK2 }, data: legenda },
      grid: { top: o.series.length > 1 ? 36 : 14, left: 8, right: 20, bottom: 36, containLabel: true },
      xAxis: eixo(o.titulo_x, o.formato_x, false),
      yAxis,
      series,
    };
  }

  // ------------------------------------------------------------------ sankey
  function sankey(o, ctx) {
    const f = o.formato;
    const cor = {};
    o.nos.forEach((n, i) => { cor[n.nome] = colorOf(n.cor, i); });
    return {
      tooltip: {
        trigger: "item",
        formatter: (p) => p.dataType === "edge"
          ? tip(`${p.data.source.trim()} → ${p.data.target.trim()}`, [{ nome: "Quantidade", valor: fmt(p.data.value, f) }])
          : tip(p.name.trim(), [{ nome: "Passa por aqui", valor: fmt(p.value, f) }]),
      },
      series: [{
        type: "sankey", left: 8, right: ctx.compact ? 70 : 110, top: 12, bottom: 12, nodeWidth: 14, nodeGap: 12,
        draggable: false, emphasis: { focus: "adjacency" },
        label: { color: INK2, fontSize: ctx.compact ? 10 : 12, formatter: (p) => p.name.trim() },
        lineStyle: { color: "source", opacity: 0.32, curveness: 0.5 },
        itemStyle: { borderWidth: 0 },
        data: o.nos.map((n) => ({ name: n.nome, itemStyle: { color: cor[n.nome] } })),
        links: o.ligacoes.map((l) => ({ source: l.de, target: l.para, value: l.valor })),
      }],
    };
  }

  // -------------------------------------------------------------- calendário
  function calendario(o, ctx) {
    const f = o.formato;
    const max = Math.max(...o.dias.map((d) => d[1] || 0), 1);
    return {
      tooltip: {
        trigger: "item",
        formatter: (p) => tip(new Date(p.value[0] + "T12:00:00").toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" }), [{ nome: "Valor", valor: fmt(p.value[1], f) }]),
      },
      visualMap: {
        min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 12, itemHeight: 140,
        inRange: { color: SEQ }, text: ["mais", "menos"], textStyle: { color: INK2 }, formatter: (v) => short(v, f),
      },
      calendar: {
        range: [o.inicio, o.fim], left: 30, right: 8, top: 24, bottom: 44, cellSize: ["auto", ctx.compact ? 12 : 16], orient: "horizontal",
        yearLabel: { show: false },
        dayLabel: { firstDay: 1, nameMap: ["D", "S", "T", "Q", "Q", "S", "S"], color: MUTED, fontSize: 10 },
        monthLabel: { nameMap: ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"], color: MUTED },
        splitLine: { show: false },
        itemStyle: { color: TEMA.vazio, borderColor: SURFACE, borderWidth: 2 },
      },
      series: [{ type: "heatmap", coordinateSystem: "calendar", data: o.dias, itemStyle: { borderColor: SURFACE, borderWidth: 2 } }],
    };
  }

  // ------------------------------------------------------------------- funil
  function funil(o, ctx) {
    const f = o.formato;
    const n = o.etapas.length;
    return {
      grid: { top: 8, left: 8, right: ctx.compact ? 96 : 150, bottom: 4, containLabel: true },
      xAxis: { type: "value", show: false },
      yAxis: { type: "category", inverse: true, data: o.etapas.map((e) => e.nome), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: INK2, width: ctx.compact ? 100 : 160, overflow: "truncate" } },
      tooltip: {
        trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: TEMA.sombra } },
        formatter: (ps) => { const e = o.etapas[ps[0].dataIndex]; return tip(e.nome, [{ cor: ordCor(ps[0].dataIndex, n), nome: "Quantidade", valor: fmt(e.valor, f), extra: e.rotulo }]); },
      },
      series: [{
        type: "bar", barMaxWidth: 24, barCategoryGap: "35%",
        data: o.etapas.map((e, i) => ({
          value: e.valor,
          itemStyle: { color: ordCor(i, n), borderRadius: [0, 4, 4, 0], decal: state.texturas ? DECAL(i) : undefined },
        })),
        label: { show: true, position: "right", color: INK, fontSize: ctx.compact ? 10 : 11, formatter: (p) => short(p.value, f) },
      }],
    };
  }

  const BUILDERS = { cartesiano, rosca, treemap, calor, cascata, dispersao, sankey, calendario, funil };

  // ------------------------------------------------------------ ciclo de vida
  const instancias = new Map(); // elemento → { chart, spec, compact, observer }

  const PONTOS_PARA_NAO_ANIMAR = 400;
  function pontosDe(opcao) {
    const series = Array.isArray(opcao.series) ? opcao.series : [];
    return series.reduce((a, s) => a + (Array.isArray(s.data) ? s.data.length : 0), 0);
  }

  function montar(el, spec) {
    // Elemento restaurado do histórico do HTMX traz o <canvas> antigo, sem instância.
    if (!instancias.has(el) && !window.echarts.getInstanceByDom(el)) el.replaceChildren();
    const compact = el.clientWidth < 520;
    let reg = instancias.get(el);
    let chart = reg ? reg.chart : window.echarts.getInstanceByDom(el);
    if (!chart) chart = window.echarts.init(el, null, { renderer: "canvas" });
    const construir = BUILDERS[spec.tipo];
    if (!construir) return;
    const opcao = Object.assign(base(compact), construir(spec.opcoes, { compact, el, spec }));
    // `base()` traz o tooltip comum; o do gráfico (formatter) o completa.
    opcao.tooltip = Object.assign({}, base(compact).tooltip, opcao.tooltip || {});
    // Animar centenas de pontos (curva de peso de cada lote: milhares) trava a
    // thread principal na abertura da aba, e ninguém acompanha a animação.
    if (opcao.animation && pontosDe(opcao) > PONTOS_PARA_NAO_ANIMAR) opcao.animation = false;
    chart.setOption(opcao, true);
    if (!reg) {
      // O ResizeObserver avisa uma vez ao começar a observar; se o gráfico já foi
      // desenhado com largura, esse aviso só o redesenharia à toa.
      let pular = el.clientWidth > 0;
      const obs = new ResizeObserver(() => {
        if (pular) { pular = false; return; }
        if (!el.clientWidth) return; // aba oculta (tabela aberta)
        const r = instancias.get(el);
        if (!r) return;
        const agora = el.clientWidth < 520;
        if (agora !== r.compact) { r.compact = agora; montar(el, r.spec); } else { r.chart.resize(); }
      });
      obs.observe(el);
      reg = { chart, spec, compact, observer: obs };
      instancias.set(el, reg);
    } else {
      reg.spec = spec; reg.compact = compact;
    }
  }

  // Gráficos fora da tela só são desenhados quando se aproximam dela: uma aba
  // com 15 gráficos não precisa pagar os 15 no clique, e a página abre antes.
  const pendentes = new Map(); // elemento → spec ainda não desenhada
  const vigia = "IntersectionObserver" in window
    ? new IntersectionObserver((entradas) => {
        entradas.forEach((en) => {
          if (!en.isIntersecting) return;
          const spec = pendentes.get(en.target);
          vigia.unobserve(en.target);
          pendentes.delete(en.target);
          if (spec && en.target.isConnected) montar(en.target, spec);
        });
      }, { rootMargin: "300px 0px" })
    : null;

  function agendar(el, spec) {
    if (!vigia || instancias.has(el)) { montar(el, spec); return; }
    pendentes.set(el, spec);
    vigia.observe(el);
  }

  function limpar() {
    instancias.forEach((reg, el) => {
      if (!el.isConnected) { reg.observer.disconnect(); reg.chart.dispose(); instancias.delete(el); }
    });
    pendentes.forEach((spec, el) => {
      if (!el.isConnected) { if (vigia) vigia.unobserve(el); pendentes.delete(el); }
    });
  }

  function iniciar() {
    limpar();
    if (!window.echarts) return;
    const tag = document.getElementById("dash-dados");
    let dados = {};
    try { dados = tag ? JSON.parse(tag.textContent) : {}; } catch (e) { dados = {}; }
    document.querySelectorAll("[data-chart]").forEach((el) => {
      const spec = dados[el.dataset.chart];
      if (spec) agendar(el, spec);
    });
  }

  document.addEventListener("click", (ev) => {
    const botao = ev.target.closest("[data-dash-png]");
    if (!botao) return;
    const el = document.querySelector(`[data-chart="${CSS.escape(botao.dataset.dashPng)}"]`);
    if (el && pendentes.has(el)) { // ainda não desenhado: desenha antes de exportar
      const spec = pendentes.get(el);
      vigia.unobserve(el);
      pendentes.delete(el);
      montar(el, spec);
    }
    const reg = el && instancias.get(el);
    if (!reg) return;
    const a = document.createElement("a");
    a.href = reg.chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: SURFACE });
    a.download = (botao.dataset.dashPng || "grafico") + ".png";
    a.click();
  });

  window.addEventListener("dash:texturas", (ev) => {
    state.texturas = !!ev.detail;
    instancias.forEach((reg, el) => montar(el, reg.spec));
  });

  // Histórico do HTMX (hx-push-url nas abas): o painel de ajuda ("i") é teleportado
  // para o <body> pelo Alpine, e o retrato do histórico o copiaria sem o escopo dele
  // ("aberto is not defined" ao voltar). Tira esses painéis do retrato e os devolve.
  let guardados = [];
  document.addEventListener("htmx:beforeHistorySave", () => {
    guardados = [...document.querySelectorAll("[data-info-dialog]")];
    guardados.forEach((n) => n.remove());
  });
  document.addEventListener("htmx:historyItemCreated", () => {
    guardados.forEach((n) => document.body.appendChild(n));
    guardados = [];
  });

  document.addEventListener("DOMContentLoaded", iniciar);
  document.addEventListener("htmx:afterSettle", iniciar);
  document.addEventListener("htmx:historyRestore", iniciar);
  // Script com `defer` roda em "interactive" e o DOMContentLoaded vem logo depois:
  // chamar `iniciar` aqui também montava todos os gráficos duas vezes.
  if (document.readyState === "complete") iniciar();
})();
