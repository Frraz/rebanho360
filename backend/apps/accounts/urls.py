from django.urls import path

from apps.accounts import user_views, views

app_name = "accounts"

urlpatterns = [
    path("entrar/", views.LoginView.as_view(), name="login"),
    path("sair/", views.LogoutView.as_view(), name="logout"),
    path(
        "2fa/",
        views.StatusSegundoFatorView.as_view(),
        name="2fa_status",
    ),
    path(
        "2fa/configurar/",
        views.ConfigurarSegundoFatorView.as_view(),
        name="2fa_configurar",
    ),
    path(
        "2fa/verificar/",
        views.VerificarSegundoFatorView.as_view(),
        name="2fa_verificar",
    ),
    path("conta/", views.ContaView.as_view(), name="conta"),
    path("senha/trocar/", views.PasswordChangeView.as_view(), name="password_change"),
    path("senha/redefinir/", views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "senha/redefinir/enviado/",
        views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "senha/redefinir/<uidb64>/<token>/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "senha/redefinir/concluido/",
        views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    # Tela pública: quem ainda não tem conta pede acesso.
    path(
        "solicitar-acesso/",
        user_views.SolicitarAcessoView.as_view(),
        name="solicitar_acesso",
    ),
    path(
        "solicitar-acesso/enviado/",
        user_views.SolicitacaoEnviadaView.as_view(),
        name="solicitar_acesso_enviado",
    ),
    # Gerenciamento de usuários e das solicitações (só ADMIN).
    path("usuarios/", user_views.UsuarioListView.as_view(), name="usuarios"),
    path("usuarios/novo/", user_views.UsuarioCreateView.as_view(), name="usuario_novo"),
    path(
        "usuarios/<int:pk>/",
        user_views.UsuarioDetailView.as_view(),
        name="usuario_detalhe",
    ),
    path(
        "usuarios/<int:pk>/editar/",
        user_views.UsuarioUpdateView.as_view(),
        name="usuario_editar",
    ),
    path(
        "usuarios/<int:pk>/desativar/",
        user_views.DesativarUsuarioView.as_view(),
        name="usuario_desativar",
    ),
    path(
        "usuarios/<int:pk>/reativar/",
        user_views.ReativarUsuarioView.as_view(),
        name="usuario_reativar",
    ),
    path(
        "usuarios/<int:pk>/excluir/",
        user_views.ExcluirUsuarioView.as_view(),
        name="usuario_excluir",
    ),
    path(
        "usuarios/<int:pk>/restaurar/",
        user_views.RestaurarUsuarioView.as_view(),
        name="usuario_restaurar",
    ),
    path(
        "usuarios/<int:pk>/senha/",
        user_views.RedefinirSenhaView.as_view(),
        name="usuario_senha",
    ),
    path(
        "usuarios/<int:pk>/sessoes/",
        user_views.EncerrarSessoesView.as_view(),
        name="usuario_sessoes",
    ),
    path(
        "usuarios/<int:pk>/segundo-fator/",
        user_views.RedefinirSegundoFatorView.as_view(),
        name="usuario_2fa",
    ),
    path(
        "solicitacoes/",
        user_views.SolicitacaoListView.as_view(),
        name="solicitacoes",
    ),
    path(
        "solicitacoes/<int:pk>/aprovar/",
        user_views.AprovarSolicitacaoView.as_view(),
        name="solicitacao_aprovar",
    ),
    path(
        "solicitacoes/<int:pk>/recusar/",
        user_views.RecusarSolicitacaoView.as_view(),
        name="solicitacao_recusar",
    ),
]
