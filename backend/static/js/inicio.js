/* Preferência visual por usuário, neste navegador. O details continua
   funcionando por teclado e mesmo sem JavaScript ou armazenamento local. */
(function () {
  const painel = document.querySelector("[data-pendencias-usuario]");
  if (!painel) return;
  const chave = "rebanho360:inicio:pendencias:" + painel.dataset.pendenciasUsuario;
  try {
    painel.open = localStorage.getItem(chave) === "aberto";
  } catch (_) { /* Armazenamento indisponível: mantém o padrão recolhido. */ }
  painel.addEventListener("toggle", function () {
    try {
      localStorage.setItem(chave, painel.open ? "aberto" : "fechado");
    } catch (_) { /* A interação nativa independe de armazenamento. */ }
  });
})();
