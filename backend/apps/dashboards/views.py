"""Fino. Recebe request, chama os seletores do painel, devolve template."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.accounts import two_factor
from apps.core import context as ctx
from apps.dashboards import selectors


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
