"""Trigger de banco que recusa UPDATE/DELETE em `audit_auditevent` — a
terceira camada de imutabilidade do ADR 0006, abaixo de Python e acima do
papel de banco da aplicação. Só se aplica a Postgres: é o motor de
produção e dev (nunca SQLite, por decisão do projeto)."""

from django.db import migrations


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION audit_event_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'AuditEvent e append-only: %% nao e permitido em evento ja gravado',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER audit_auditevent_immutable
        BEFORE UPDATE OR DELETE ON audit_auditevent
        FOR EACH ROW EXECUTE FUNCTION audit_event_immutable();
        """
    )


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS audit_auditevent_immutable ON audit_auditevent;"
    )
    schema_editor.execute("DROP FUNCTION IF EXISTS audit_event_immutable();")


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunPython(create_trigger, drop_trigger)]
