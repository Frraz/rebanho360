"""Fino. Recebe request, chama os seletores do painel, devolve template."""

import time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.generic import TemplateView

from apps.accounts import two_factor
from apps.core import context as ctx
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
                "safra": selectors.cartao_da_safra(
                    user, season=season, farm=farm, cabecas_atuais=rebanho.cabecas
                ),
                "season": season,
                "farm": farm,
                "sugerir_segundo_fator": two_factor.recomenda_segundo_fator(user),
                "lancamentos": selectors.ultimos_lancamentos(user, farm=farm),
            }
        )
        return context


class DashboardView(LoginRequiredMixin, TemplateView):
    """Dashboard analítico: uma aba por assunto, carregada sob demanda.

    A página inteira vem com a aba pedida; ao trocar de aba o HTMX pede só o
    fragmento (`HX-Request`). O recorte — safra e fazenda — é o do topo da tela:
    não há segundo filtro para dessincronizar. Docs:
    docs/regras-negocio/11-dashboard-analitico.md.
    """

    template_name = "dashboards/dashboard.html"
    template_fragmento = "dashboards/_aba.html"

    def get_template_names(self):
        if self.request.headers.get("HX-Request") and not self.request.headers.get(
            "HX-History-Restore-Request"
        ):
            return [self.template_fragmento]
        return [self.template_name]

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
        escopo = Escopo.criar(user, season=season, farm=farm)

        context.update(
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
        return context

    def render_to_response(self, context, **kwargs):
        resposta = super().render_to_response(context, **kwargs)
        # A mesma URL devolve página inteira ou fragmento: sem isto, um cache
        # serviria o fragmento a quem abriu o endereço direto.
        patch_vary_headers(resposta, ["HX-Request"])
        return resposta
