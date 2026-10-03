from decimal import Decimal

from apps.core.money import (
    kg_to_arroba,
    quantize_money,
    quantize_percent,
    safe_div,
)


class TestSafeDiv:
    def test_divisor_zero_devolve_none(self):
        assert safe_div(Decimal("10"), Decimal("0")) is None

    def test_divisor_none_devolve_none(self):
        assert safe_div(Decimal("10"), None) is None

    def test_numerador_none_devolve_none(self):
        assert safe_div(None, Decimal("10")) is None

    def test_divisao_normal(self):
        assert safe_div(Decimal("10"), Decimal("2")) == Decimal("5")

    def test_inteiro_por_inteiro_devolve_decimal_nunca_float(self):
        """int ÷ int em Python é float — e float é proibido (regra 2)."""
        resultado = safe_div(2, 3)
        assert isinstance(resultado, Decimal)
        assert resultado == Decimal(2) / Decimal(3)
        assert isinstance(safe_div(84, 100), Decimal)
        assert safe_div(5, 0) is None


class TestArredondamento:
    def test_arredondamento_comercial_meio_para_cima(self):
        assert quantize_money(Decimal("0.005")) == Decimal("0.01")

    def test_arredondamento_duas_casas(self):
        assert quantize_money(Decimal("10.456")) == Decimal("10.46")

    def test_percent_quatro_casas(self):
        assert quantize_percent(Decimal("0.51333333")) == Decimal("0.5133")


class TestConversaoArroba:
    def test_kg_para_arroba(self):
        assert kg_to_arroba(Decimal("450")) == Decimal("30")
