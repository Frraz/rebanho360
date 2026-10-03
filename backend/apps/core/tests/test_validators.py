import pytest
from django.core.exceptions import ValidationError

from apps.core.validators import (
    cpf_valido,
    formatar_cpf,
    mascarar_cpf,
    somente_digitos,
    validar_cpf,
)

# 529.982.247-25 e 111.444.777-35 são CPFs de teste com dígitos corretos.
VALIDO = "52998224725"


@pytest.mark.parametrize("cpf", [VALIDO, "529.982.247-25", "11144477735"])
def test_cpf_valido_aceita_com_ou_sem_pontuacao(cpf):
    assert cpf_valido(cpf)


@pytest.mark.parametrize(
    "cpf",
    [
        "52998224724",  # dígito verificador errado
        "11111111111",  # sequência repetida passa na conta, mas não é CPF
        "00000000000",
        "1234567890",  # 10 dígitos
        "529982247255",  # 12 dígitos
        "abc",
    ],
)
def test_cpf_invalido(cpf):
    assert not cpf_valido(cpf)


def test_validar_cpf_normaliza_para_digitos():
    assert validar_cpf(" 529.982.247-25 ") == VALIDO


def test_validar_cpf_vazio_e_opcional():
    assert validar_cpf("") == ""
    assert validar_cpf(None) == ""


def test_validar_cpf_recusa_invalido_com_mensagem_clara():
    with pytest.raises(ValidationError, match="CPF inválido"):
        validar_cpf("123.456.789-00")


def test_formatar_e_mascarar():
    assert formatar_cpf(VALIDO) == "529.982.247-25"
    assert mascarar_cpf(VALIDO) == "***.***.***-25"
    assert mascarar_cpf("") == ""
    assert formatar_cpf("") == ""


def test_mascara_nao_vaza_os_primeiros_digitos():
    assert "529" not in mascarar_cpf(VALIDO)
    assert somente_digitos("529.982.247-25") == VALIDO
