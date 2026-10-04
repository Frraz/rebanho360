/*
 * Seletor com busca para todo <select> do sistema.
 *
 * Melhoria progressiva: o <select> real continua no DOM (escondido, mas
 * focável) e é a fonte da verdade. Este script desenha, logo depois dele, um
 * botão que abre a lista completa com campo de busca. Ao escolher, grava em
 * select.value e dispara `input` e `change`, então formulário, HTMX
 * (hx-trigger="change"), Alpine (x-model), onchange inline, rascunho e
 * `required` continuam funcionando sem nenhuma mudança nos templates.
 * Sem JavaScript, fica o <select> nativo.
 *
 * Ciclo de vida: um MutationObserver melhora os selects que surgem depois
 * (swap do HTMX, linha de formset clonada) e remove o botão de quem saiu.
 * Opte por sair com <select data-native>.
 */
(function () {
  "use strict";
  if (window.__combobox) return;
  window.__combobox = true;

  var script = document.currentScript;
  var SPRITE = (script && script.getAttribute("data-icons")) || "";
  var SVG_NS = "http://www.w3.org/2000/svg";
  var LIMITE_BUSCA_NO_TOQUE = 8; // no celular, lista curta abre sem teclado
  var uid = 0;
  var aberto = null; // só um painel aberto por vez

  /* ---------- utilidades ---------- */

  function el(tag, cls, attrs) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  function icone(nome, cls) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "icon " + (cls || ""));
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    var use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", SPRITE + "#" + nome);
    svg.appendChild(use);
    return svg;
  }

  // Texto sem acento e em minúsculas, guardando de onde cada letra veio no
  // original (para destacar o trecho achado sem errar a posição).
  function indexar(txt) {
    var n = "";
    var mapa = [];
    for (var i = 0; i < txt.length; i++) {
      var c = txt[i].normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
      for (var k = 0; k < c.length; k++) {
        n += c[k];
        mapa.push(i);
      }
    }
    return { n: n, mapa: mapa };
  }

  function termos(consulta) {
    return indexar(consulta).n.split(/\s+/).filter(Boolean);
  }

  function celular() {
    return window.matchMedia("(max-width: 639px)").matches;
  }

  function ponteiroPreciso() {
    return window.matchMedia("(pointer: fine)").matches;
  }

  function textoDe(ids) {
    return ids
      .split(/\s+/)
      .map(function (id) {
        var e = document.getElementById(id);
        return e ? e.textContent.trim() : "";
      })
      .filter(Boolean)
      .join(" ");
  }

  /* ---------- componente ---------- */

  function Combo(select) {
    this.select = select;
    this.id = "cb" + ++uid;
    this.ctx = select.classList.contains("ctx-select");
    this.painel = null;
    this.itens = [];
    this.visiveis = [];
    this.ativo = -1;
    this.escutas = [];

    // Classes do select viram as do botão, menos as que o HTMX põe durante o
    // swap (htmx-*): ele insere o select novo com os atributos do antigo.
    var cls = Array.prototype.filter
      .call(select.classList, function (c) {
        return c.indexOf("htmx-") !== 0 && c !== "ctx-select";
      })
      .join(" ");
    if (cls.split(" ").indexOf("field-input") === -1) cls = "field-input " + cls;
    var t = el("button", this.ctx ? "cb-trigger cb-ctx" : "cb-trigger " + cls, {
      type: "button",
      role: "combobox",
      "aria-haspopup": "listbox",
      "aria-expanded": "false",
      "aria-controls": this.id + "-lista",
    });
    this.valor = el("span", "cb-value", { id: this.id + "-valor" });
    t.appendChild(this.valor);
    t.appendChild(icone("chevron-down", "cb-chevron"));
    this.trigger = t;

    // Nome acessível: o rótulo do campo + o valor escolhido.
    var rotulos = [];
    var ref = select.getAttribute("aria-labelledby");
    if (ref) {
      rotulos = ref.split(/\s+/);
    } else if (select.labels) {
      var base = this.id;
      Array.prototype.forEach.call(select.labels, function (l, i) {
        if (!l.id) l.id = base + "-rotulo" + i;
        rotulos.push(l.id);
      });
    }
    this.rotuloIds = rotulos.join(" ");
    if (rotulos.length) t.setAttribute("aria-labelledby", this.rotuloIds + " " + this.valor.id);
    var desc = select.getAttribute("aria-describedby");
    if (desc) t.setAttribute("aria-describedby", desc);
    if (select.autofocus) t.autofocus = true;

    select.setAttribute("data-cb-native", "");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    select.insertAdjacentElement("afterend", t);
    select._cb = this;

    var self = this;
    this.aoFocarSelect = function () {
      self.trigger.focus({ preventScroll: true });
    };
    this.aoMudar = function () {
      self.sync();
    };
    select.addEventListener("focus", this.aoFocarSelect);
    select.addEventListener("change", this.aoMudar);
    t.addEventListener("click", function () {
      self.isOpen() ? self.close(true) : self.open("");
    });
    t.addEventListener("keydown", function (e) {
      self.teclaNoGatilho(e);
    });
    // O valor pode ter sido mudado por código (Alpine, rascunho): confere ao
    // encostar no campo, antes de o usuário ver um rótulo velho.
    t.addEventListener("mouseenter", this.aoMudar);
    t.addEventListener("focus", this.aoMudar);

    this.obs = new MutationObserver(this.aoMudar);
    this.obs.observe(select, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["disabled", "aria-invalid", "class"],
    });
    if (select.form) {
      this.form = select.form;
      this.aoRedefinir = function () {
        setTimeout(self.aoMudar, 0);
      };
      this.form.addEventListener("reset", this.aoRedefinir);
    }
    this.sync();
  }

  Combo.prototype.isOpen = function () {
    return !!this.painel;
  };

  Combo.prototype.sync = function () {
    var s = this.select;
    var op = s.options[s.selectedIndex];
    var texto = op ? op.text.trim() : "";
    var vazio = !op || op.value === "";
    // "---------" do Django vira um convite; "Todas as fazendas" é uma escolha de verdade.
    var convite = vazio && (!texto || /^[-–—\s]+$/.test(texto));
    this.valor.textContent = convite ? "Selecione" : texto;
    this.valor.classList.toggle("cb-placeholder", vazio && !this.ctx);
    this.trigger.disabled = s.disabled;
    if (s.getAttribute("aria-invalid") === "true" || s.classList.contains("is-invalid")) {
      this.trigger.setAttribute("aria-invalid", "true");
    } else {
      this.trigger.removeAttribute("aria-invalid");
    }
  };

  Combo.prototype.destroy = function () {
    if (this.isOpen()) this.close(false);
    this.obs.disconnect();
    var s = this.select;
    s.removeEventListener("focus", this.aoFocarSelect);
    s.removeEventListener("change", this.aoMudar);
    if (this.form) this.form.removeEventListener("reset", this.aoRedefinir);
    s.removeAttribute("data-cb-native");
    s.removeAttribute("aria-hidden");
    s._cb = null;
    if (this.trigger.parentNode) this.trigger.parentNode.removeChild(this.trigger);
  };

  /* ---------- teclado no botão ---------- */

  Combo.prototype.teclaNoGatilho = function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var k = e.key;
    if (k === "ArrowDown" || k === "ArrowUp") {
      e.preventDefault();
      this.open("");
    } else if (k.length === 1 && k !== " " && !this.isOpen()) {
      // Digitar com o campo focado já abre a busca com a letra digitada.
      e.preventDefault();
      this.open(k);
    }
  };

  /* ---------- painel ---------- */

  Combo.prototype.title = function () {
    var t = this.rotuloIds ? textoDe(this.rotuloIds) : "";
    return t || "Selecione";
  };

  Combo.prototype.lerOpcoes = function () {
    var itens = [];
    Array.prototype.forEach.call(this.select.options, function (op) {
      var txt = op.text.trim();
      if (op.value === "" && /^[-–—\s]*$/.test(txt)) txt = "Sem seleção";
      var ix = indexar(txt);
      itens.push({ op: op, texto: txt, n: ix.n, mapa: ix.mapa, li: null });
    });
    this.itens = itens;
  };

  Combo.prototype.open = function (consulta) {
    var self = this;
    if (this.isOpen() || this.select.disabled) return;
    if (aberto && aberto !== this) aberto.close(false);
    this.sync();
    this.lerOpcoes();
    this.folha = celular();

    var p = el("div", "cb-panel" + (this.folha ? " cb-sheet" : ""), { tabindex: "-1" });
    if (this.folha) {
      var cab = el("div", "cb-sheet-head");
      var tit = el("span", "cb-sheet-title");
      tit.textContent = this.title();
      var fechar = el("button", "cb-sheet-close", { type: "button", "aria-label": "Fechar" });
      fechar.appendChild(icone("x", "icon-lg"));
      fechar.addEventListener("click", function () {
        self.close(true);
      });
      cab.appendChild(tit);
      cab.appendChild(fechar);
      p.appendChild(cab);
    }

    var busca = el("div", "cb-search-wrap");
    busca.appendChild(icone("search", "cb-search-icon"));
    var inp = el("input", "cb-search", {
      type: "text",
      role: "combobox",
      autocomplete: "off",
      autocapitalize: "off",
      spellcheck: "false",
      enterkeyhint: "done",
      placeholder: "Buscar…",
      "aria-label": "Buscar em " + this.title(),
      "aria-autocomplete": "list",
      "aria-expanded": "true",
      "aria-controls": this.id + "-lista",
    });
    this.contagem = el("span", "cb-count");
    busca.appendChild(inp);
    busca.appendChild(this.contagem);
    p.appendChild(busca);

    var ul = el("ul", "cb-list", { role: "listbox", id: this.id + "-lista", "aria-label": this.title() });
    this.itens.forEach(function (it, i) {
      var li = el("li", "cb-option", { role: "option", id: self.id + "-o" + i, "data-i": String(i) });
      if (it.op.disabled) li.setAttribute("aria-disabled", "true");
      li.setAttribute("aria-selected", it.op.selected ? "true" : "false");
      li.appendChild(el("span", "cb-option-text"));
      li.appendChild(icone("check", "cb-check"));
      it.li = li;
      ul.appendChild(li);
    });
    p.appendChild(ul);

    this.vazio = el("div", "cb-empty", { hidden: "" });
    this.vazio.setAttribute("role", "status");
    p.appendChild(this.vazio);

    this.input = inp;
    this.lista = ul;
    this.painel = p;

    if (this.folha) {
      this.fundo = el("div", "cb-backdrop");
      this.fundo.addEventListener("click", function () {
        self.close(true);
      });
      document.body.appendChild(this.fundo);
    }
    document.body.appendChild(p);

    inp.value = consulta || "";
    this.filtrar(true);
    this.trigger.setAttribute("aria-expanded", "true");
    aberto = this;
    this.posicionar();

    // Escutas do painel aberto.
    var ouvir = function (alvo, tipo, fn, opc) {
      alvo.addEventListener(tipo, fn, opc);
      self.escutas.push([alvo, tipo, fn, opc]);
    };
    ouvir(inp, "input", function () {
      self.filtrar(false);
    });
    ouvir(p, "keydown", function (e) {
      self.teclaNoPainel(e);
    });
    ouvir(ul, "click", function (e) {
      var li = e.target.closest(".cb-option");
      if (li) self.escolher(parseInt(li.getAttribute("data-i"), 10));
    });
    ouvir(ul, "mousemove", function (e) {
      var li = e.target.closest(".cb-option");
      if (!li || li.hasAttribute("hidden")) return;
      var pos = self.visiveis.indexOf(parseInt(li.getAttribute("data-i"), 10));
      if (pos >= 0 && pos !== self.ativo) self.mover(pos, false);
    });
    ouvir(
      document,
      "pointerdown",
      function (e) {
        if (!p.contains(e.target) && !self.trigger.contains(e.target)) self.close(false);
      },
      true
    );
    ouvir(
      window,
      "scroll",
      function (e) {
        if (!p.contains(e.target)) self.posicionar();
      },
      true
    );
    ouvir(window, "resize", function () {
      self.posicionar();
    });
    if (this.folha && window.visualViewport) {
      ouvir(window.visualViewport, "resize", function () {
        self.posicionar();
      });
      ouvir(window.visualViewport, "scroll", function () {
        self.posicionar();
      });
    }

    // No celular, lista curta abre sem teclado; a busca continua a um toque.
    var comTeclado = ponteiroPreciso() || this.itens.length > LIMITE_BUSCA_NO_TOQUE || !!consulta;
    if (comTeclado) {
      inp.focus({ preventScroll: true });
      if (consulta) inp.setSelectionRange(inp.value.length, inp.value.length);
    } else {
      p.focus({ preventScroll: true });
    }
    var sel = this.visiveis.indexOf(this.select.selectedIndex);
    if (this.ativo >= 0 && sel >= 0 && !consulta) this.mover(sel, true, true);
  };

  Combo.prototype.posicionar = function () {
    var p = this.painel;
    if (!p) return;
    if (this.folha) {
      var vv = window.visualViewport;
      var alto = vv ? vv.height : window.innerHeight;
      var base = vv ? window.innerHeight - (vv.height + vv.offsetTop) : 0;
      p.style.bottom = Math.max(0, base) + "px";
      p.style.maxHeight = Math.round(alto * 0.85) + "px";
      return;
    }
    var r = this.trigger.getBoundingClientRect();
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var largura = Math.min(Math.max(r.width, 240), vw - 16);
    var esq = Math.min(Math.max(8, r.left), vw - largura - 8);
    var abaixo = vh - r.bottom - 8;
    var acima = r.top - 8;
    var embaixo = abaixo >= 260 || abaixo >= acima;
    var max = Math.min(360, Math.max(160, embaixo ? abaixo : acima));
    p.style.left = esq + "px";
    p.style.width = largura + "px";
    p.style.maxHeight = max + "px";
    if (embaixo) {
      p.style.top = r.bottom + 4 + "px";
      p.style.bottom = "auto";
    } else {
      p.style.bottom = vh - r.top + 4 + "px";
      p.style.top = "auto";
    }
    p.classList.toggle("cb-up", !embaixo);
  };

  Combo.prototype.close = function (voltarFoco) {
    if (!this.isOpen()) return;
    this.escutas.forEach(function (e) {
      e[0].removeEventListener(e[1], e[2], e[3]);
    });
    this.escutas = [];
    this.painel.parentNode && this.painel.parentNode.removeChild(this.painel);
    if (this.fundo && this.fundo.parentNode) this.fundo.parentNode.removeChild(this.fundo);
    this.painel = this.fundo = this.input = this.lista = this.vazio = this.contagem = null;
    this.itens = [];
    this.visiveis = [];
    this.ativo = -1;
    this.trigger.setAttribute("aria-expanded", "false");
    this.trigger.removeAttribute("aria-activedescendant");
    if (aberto === this) aberto = null;
    if (voltarFoco) this.trigger.focus({ preventScroll: true });
  };

  /* ---------- filtro e destaque ---------- */

  Combo.prototype.filtrar = function (inicial) {
    var consulta = this.input.value;
    var ts = termos(consulta);
    var visiveis = [];
    this.itens.forEach(function (it, i) {
      var ok = ts.every(function (t) {
        return it.n.indexOf(t) !== -1;
      });
      if (ok) {
        visiveis.push(i);
        it.li.removeAttribute("hidden");
      } else {
        it.li.setAttribute("hidden", "");
      }
      pintar(it, ok ? ts : []);
    });
    this.visiveis = visiveis;
    var total = this.itens.length;
    this.contagem.textContent = ts.length ? visiveis.length + " de " + total : total > 12 ? total + " opções" : "";
    if (!visiveis.length) {
      this.vazio.textContent = "Nenhum resultado para “" + consulta.trim() + "”.";
      this.vazio.removeAttribute("hidden");
    } else {
      this.vazio.setAttribute("hidden", "");
    }
    // Com busca, o primeiro resultado já fica pronto para o Enter; sem busca, o escolhido.
    var alvo = 0;
    if (!ts.length) {
      var s = visiveis.indexOf(this.select.selectedIndex);
      alvo = s >= 0 ? s : 0;
    }
    this.itens.forEach(function (it) {
      it.li.classList.remove("is-active");
    });
    this.ativo = -1;
    if (visiveis.length) this.mover(alvo, !inicial, inicial);
    else this.input.removeAttribute("aria-activedescendant");
  };

  // Escreve o texto do item, com <mark> nos trechos achados.
  function pintar(it, ts) {
    var alvo = it.li.firstChild;
    var faixas = [];
    ts.forEach(function (t) {
      var ini = it.n.indexOf(t);
      if (ini === -1) return;
      faixas.push([it.mapa[ini], it.mapa[ini + t.length - 1] + 1]);
    });
    if (!faixas.length) {
      if (alvo.textContent !== it.texto || alvo.childNodes.length !== 1) alvo.textContent = it.texto;
      return;
    }
    faixas.sort(function (a, b) {
      return a[0] - b[0];
    });
    var juntas = [faixas[0]];
    for (var i = 1; i < faixas.length; i++) {
      var ult = juntas[juntas.length - 1];
      if (faixas[i][0] <= ult[1]) ult[1] = Math.max(ult[1], faixas[i][1]);
      else juntas.push(faixas[i]);
    }
    alvo.textContent = "";
    var pos = 0;
    juntas.forEach(function (f) {
      if (f[0] > pos) alvo.appendChild(document.createTextNode(it.texto.slice(pos, f[0])));
      var m = el("mark", "cb-mark");
      m.textContent = it.texto.slice(f[0], f[1]);
      alvo.appendChild(m);
      pos = f[1];
    });
    if (pos < it.texto.length) alvo.appendChild(document.createTextNode(it.texto.slice(pos)));
  }

  /* ---------- navegação e escolha ---------- */

  Combo.prototype.mover = function (pos, rolar, centralizar) {
    if (!this.visiveis.length) return;
    pos = Math.max(0, Math.min(this.visiveis.length - 1, pos));
    var antes = this.itens[this.visiveis[this.ativo]];
    if (antes) antes.li.classList.remove("is-active");
    this.ativo = pos;
    var it = this.itens[this.visiveis[pos]];
    it.li.classList.add("is-active");
    this.input.setAttribute("aria-activedescendant", it.li.id);
    this.trigger.setAttribute("aria-activedescendant", it.li.id);
    if (rolar !== false) {
      if (centralizar) {
        var l = this.lista;
        l.scrollTop = it.li.offsetTop - l.clientHeight / 2 + it.li.offsetHeight / 2;
      } else {
        it.li.scrollIntoView({ block: "nearest" });
      }
    }
  };

  Combo.prototype.teclaNoPainel = function (e) {
    var k = e.key;
    var passo = Math.max(1, Math.floor(this.lista.clientHeight / (this.itens[0] && this.itens[0].li.offsetHeight || 36)) - 1);
    if (k === "ArrowDown") {
      e.preventDefault();
      this.mover(this.ativo + 1);
    } else if (k === "ArrowUp") {
      e.preventDefault();
      this.mover(this.ativo - 1);
    } else if (k === "PageDown") {
      e.preventDefault();
      this.mover(this.ativo + passo);
    } else if (k === "PageUp") {
      e.preventDefault();
      this.mover(this.ativo - passo);
    } else if (k === "Home" && e.target !== this.input) {
      e.preventDefault();
      this.mover(0);
    } else if (k === "End" && e.target !== this.input) {
      e.preventDefault();
      this.mover(this.visiveis.length - 1);
    } else if (k === "Enter") {
      e.preventDefault(); // não envia o formulário por trás do painel
      if (this.ativo >= 0) this.escolher(this.visiveis[this.ativo]);
    } else if (k === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // não fecha o painel de contexto/menu que está por baixo
      this.close(true);
    } else if (k === "Tab") {
      // Foco volta ao botão antes de o navegador decidir para onde o Tab vai.
      this.trigger.focus({ preventScroll: true });
      this.close(false);
    }
  };

  Combo.prototype.escolher = function (i) {
    var it = this.itens[i];
    if (!it || it.op.disabled) return;
    var s = this.select;
    var mudou = s.selectedIndex !== it.op.index;
    s.selectedIndex = it.op.index;
    this.sync();
    this.close(true);
    if (mudou) {
      s.dispatchEvent(new Event("input", { bubbles: true }));
      s.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };

  /* ---------- varredura e ciclo de vida ---------- */

  function melhorar(select) {
    if (select._cb || select.hasAttribute("data-native") || select.multiple || select.size > 1) return;
    if (select.closest("template")) return;
    new Combo(select);
  }

  function varrer(raiz) {
    if (raiz.nodeType !== 1) return;
    if (raiz.tagName === "SELECT") melhorar(raiz);
    if (raiz.querySelectorAll) Array.prototype.forEach.call(raiz.querySelectorAll("select"), melhorar);
  }

  function limpar(raiz) {
    if (raiz.nodeType !== 1) return;
    var lista = raiz.tagName === "SELECT" ? [raiz] : [];
    if (raiz.querySelectorAll) lista = lista.concat(Array.prototype.slice.call(raiz.querySelectorAll("select")));
    lista.forEach(function (s) {
      // Quem saiu do documento perde o botão; quem só mudou de lugar é refeito pela varredura.
      if (s._cb && !document.contains(s)) s._cb.destroy();
    });
  }

  function sincronizarTodos() {
    Array.prototype.forEach.call(document.querySelectorAll("select[data-cb-native]"), function (s) {
      if (s._cb) s._cb.sync();
    });
  }

  function iniciar() {
    varrer(document.documentElement);
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        Array.prototype.forEach.call(m.removedNodes, limpar);
        Array.prototype.forEach.call(m.addedNodes, varrer);
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();

  // Alpine (x-model) e restauração de página (botão voltar) mexem em .value sem evento.
  document.addEventListener("alpine:initialized", sincronizarTodos);
  window.addEventListener("pageshow", sincronizarTodos);
  document.addEventListener("htmx:afterSettle", sincronizarTodos);
})();
