"""Views genéricas compartilhadas. Finas: só HTTP, nunca regra de negócio."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.core.exceptions import BlockingDependencyError, BusinessError, DependencyError
from apps.core.impact import analisar_impacto, rotulo
from apps.core.permissions import pode_excluir_confirmado


class ExclusaoComImpactoView(LoginRequiredMixin, View):
    """GET mostra a análise de impacto; POST exclui, com motivo obrigatório
    e — só se o usuário marcar — em cascata sobre os dependentes.

    A subclasse declara `model`, `executar_exclusao()` e `url_do_registro()`.
    Registro fora do escopo devolve 404, não 403 (ADR 0003).
    """

    template_name = "core/impacto_exclusao.html"
    model = None
    titulo = "Excluir"

    def get_registro(self, pk):
        return get_object_or_404(self.model.objects.for_user(self.request.user), pk=pk)

    def url_do_registro(self, registro) -> str:
        raise NotImplementedError

    def executar_exclusao(self, registro, *, motivo, cascata):
        raise NotImplementedError

    def pode_excluir(self, registro) -> bool:
        """Quem pode excluir este registro. Por padrão, o papel que exclui
        registro confirmado; a subclasse afrouxa para o rascunho."""
        return pode_excluir_confirmado(self.request.user)

    def _sem_permissao(self, registro):
        messages.error(
            self.request, "Você não tem permissão para excluir este registro."
        )
        return redirect(self.url_do_registro(registro))

    def _contexto(self, registro, **extra):
        return {
            "registro": registro,
            "rotulo": rotulo(registro),
            "impacto": analisar_impacto(registro),
            "voltar_url": self.url_do_registro(registro),
            "titulo": self.titulo,
            **extra,
        }

    def get(self, request, pk):
        registro = self.get_registro(pk)
        if not self.pode_excluir(registro):
            return self._sem_permissao(registro)
        return render(request, self.template_name, self._contexto(registro))

    def post(self, request, pk):
        registro = self.get_registro(pk)
        if not self.pode_excluir(registro):
            return self._sem_permissao(registro)

        motivo = request.POST.get("motivo", "")
        cascata = request.POST.get("cascata") == "1"
        try:
            self.executar_exclusao(registro, motivo=motivo, cascata=cascata)
        except DependencyError as exc:
            messages.error(
                request,
                "Há registros que dependem deste. Confirme a exclusão em "
                "cascata para desfazer todos juntos.",
            )
            return render(
                request,
                self.template_name,
                self._contexto(registro, motivo=motivo, erro=str(exc)),
            )
        except (BlockingDependencyError, BusinessError) as exc:
            return render(
                request,
                self.template_name,
                self._contexto(registro, motivo=motivo, erro=str(exc)),
            )
        messages.success(request, f"✓ {rotulo(registro)} excluído.")
        return redirect(self.url_do_registro(registro))
