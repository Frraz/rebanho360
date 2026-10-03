import logging

from config.logging_filters import SensitiveDataFilter, redact


def _make_record(msg, args=()):
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=args,
        exc_info=None,
    )


class TestRedact:
    def test_redige_senha(self):
        assert "***" in redact('password="segredo123"')
        assert "segredo123" not in redact('password="segredo123"')

    def test_redige_cpf(self):
        assert "123.456.789-00" not in redact("CPF: 123.456.789-00")


class TestSensitiveDataFilter:
    def test_preserva_args_em_dict_para_formatacao_por_mapeamento(self):
        """Regressão: o filtro não pode quebrar o %-formatting por dict que
        o Celery usa no log de sucesso de task (`msg % {"name": ..., ...}`).
        """
        record = _make_record(
            "Task %(name)s succeeded: %(return_value)s",
            {"name": "core.ping", "return_value": "pong"},
        )
        assert SensitiveDataFilter().filter(record) is True
        assert record.getMessage() == "Task core.ping succeeded: pong"

    def test_redige_senha_em_args_posicionais(self):
        record = _make_record("login com %s", ('password="abc123"',))
        SensitiveDataFilter().filter(record)
        assert "abc123" not in record.getMessage()
