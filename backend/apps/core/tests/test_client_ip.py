"""O IP gravado na auditoria não pode ser escolhido pelo cliente."""

from django.test import RequestFactory

from apps.core.request_context import client_ip


def test_vale_o_ip_real_que_o_nginx_define():
    pedido = RequestFactory().get(
        "/", HTTP_X_REAL_IP="203.0.113.7", REMOTE_ADDR="127.0.0.1"
    )
    assert client_ip(pedido) == "203.0.113.7"


def test_x_forwarded_for_enviado_pelo_cliente_e_ignorado():
    pedido = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7", REMOTE_ADDR="198.51.100.9"
    )
    assert client_ip(pedido) == "198.51.100.9"


def test_sem_proxy_vale_o_endereco_da_conexao():
    assert client_ip(RequestFactory().get("/", REMOTE_ADDR="198.51.100.9")) == (
        "198.51.100.9"
    )
