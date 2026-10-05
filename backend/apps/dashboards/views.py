"""Fino. Recebe request, chama os seletores do painel, devolve template."""

import datetime
import time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.safestring import mark_safe
from django.views.generic import TemplateView

from apps.accounts import two_factor
from apps.core import context as ctx
from apps.core import result_cache
from apps.dashboards import selectors
from apps.dashboards.bi import abas as registro
from apps.dashboards.bi.escopo import Escopo


class InicioView(LoginRequiredMixin, TemplateView):
    """Tela inicial: responde "o que preciso fazer hoje?". Pendências em
    primeiro lugar; indicador sem dado aparece como "—".
    Ver docs/ux/01-navegacao-e-ui.md#tela-inicial."""

    template_name = "dashboards/inicio.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        season = ctx.current_season(self.request, ctx.current_company())
        farm = ctx.current_farm(self.request, user)

        rebanho = selectors.cartao_do_rebanho(user, farm=farm)
        context.update(
            {
                "pendencias": selectors.pendencias_do_painel(
                    user, farm=farm, season=season
                ),
                "rebanho": rebanho,
                "safra": self._cartao_da_safra(user, season, farm, rebanho.cabecas),
                "season": season,
                "farm": farm,
                "sugerir_segundo_fator": two_factor.recomenda_segundo_fator(user),
                "lancamentos": selectors.ultimos_lancamentos(user, farm=farm),
            }
        )
        return context

    def _cartao_da_safra(self, user, season, farm, cabecas):
        """O Custo/@ refaz o rateio de todos os lotes encerrados: é 2/3 do tempo
        desta tela. Vale enquanto nenhum dado mudar (`result_cache`)."""
        if season is None:
            return None
        partes = (
            user.pk,
            season.pk,
            farm.pk if farm else None,
            datetime.date.today().isoformat(),
            cabecas,
        )
        return result_cache.obter(
            "cartao-da-safra",
            partes,
            lambda: selectors.cartao_da_safra(
                user, season=season, farm=farm, cabecas_atuais=cabecas
            ),
        )


class DashboardView(LoginRequiredMixin, TemplateView):
    """Dashboard analítico: uma aba por assunto, carregada sob demanda.

    A página inteira vem com a aba pedida; ao trocar de aba o HTMX pede só o
    fragmento (`HX-Request`). O recorte — safra e fazenda — é o do topo da tela:
    não há segundo filtro para dessincronizar. Docs:
    docs/regras-negocio/11-dashboard-analitico.md.

    O fragmento da aba (a parte cara) fica no cache de resultados enquanto nenhum
    dado mudar (`apps/core/result_cache.py`); a casca da página é sempre montada,
    porque traz a barra do topo, que é de quem pede.
    """

    template_name = "dashboards/dashboard.html"
    template_fragmento = "dashboards/_aba.html"

    def _e_fragmento(self) -> bool:
        return bool(self.request.headers.get("HX-Request")) and not (
            self.request.headers.get("HX-History-Restore-Request")
        )

    def get_context_data(self, aba=registro.PADRAO, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        atual = registro.aba_por_slug(aba)
        if atual is None:
            raise Http404("Aba inexistente.")
        if not atual.visivel(user):
            # Permissão, não escopo: 403 (a aba existe para todos).
            raise PermissionDenied

        season = ctx.current_season(self.request, ctx.current_company())
        farm = ctx.current_farm(self.request, user)
        hoje = datetime.date.today()
        context.update(
            season=season,
            farm=farm,
            dados_ate=Escopo.fim_do_recorte(season, hoje) if season else None,
            aba_html=mark_safe(  # noqa: S308 — HTML do nosso próprio template
                self._html_da_aba(atual, user, season, farm, hoje)
            ),
        )
        return context

    def _html_da_aba(self, atual, user, season, farm, hoje) -> str:
        """O fragmento da aba, pronto. Tudo o que o muda está na chave: quem pede
        (a aba e o dinheiro dependem do papel), a safra, a fazenda e o dia."""
        partes = (
            user.pk,
            atual.slug,
            season.pk if season else None,
            farm.pk if farm else None,
            hoje.isoformat(),
        )
        return result_cache.obter(
            "dashboard-aba",
            partes,
            lambda: self._montar_a_aba(atual, user, season, farm, hoje),
            recalcular=bool(self.request.GET.get("recalcular")),
        )

    def _montar_a_aba(self, atual, user, season, farm, hoje) -> str:
        escopo = Escopo.criar(user, season=season, farm=farm, hoje=hoje)
        context = dict(
            abas=registro.abas_visiveis(user),
            aba=atual,
            season=season,
            farm=farm,
            escopo=escopo,
            # `quadro`, não `painel`: o contexto do topo (partials/context_bar.html)
            # usa `painel` para escolher a versão empilhada do celular.
            quadro=None,
            graficos_json={},
            calculado_em=timezone.localtime(),
            safra_url=reverse("organizations:safra_lista"),
        )
        if escopo is not None:
            inicio = time.perf_counter()
            quadro = atual.montar(escopo).finalizar()
            context.update(
                quadro=quadro,
                graficos_json=quadro.json_dos_graficos(),
                segundos=round(time.perf_counter() - inicio, 2),
            )
        return render_to_string(self.template_fragmento, context)

    def render_to_response(self, context, **kwargs):
        if self._e_fragmento():
            resposta = HttpResponse(context["aba_html"])
        else:
            resposta = super().render_to_response(context, **kwargs)
        # A mesma URL devolve página inteira ou fragmento: sem isto, um cache
        # serviria o fragmento a quem abriu o endereço direto.
        patch_vary_headers(resposta, ["HX-Request"])
        return resposta
