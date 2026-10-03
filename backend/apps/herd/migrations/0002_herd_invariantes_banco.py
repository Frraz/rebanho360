"""Invariantes do núcleo do sistema, garantidas pelo banco — não só por
Python (docs/regras-negocio/01-rebanho-movimentacoes.md#invariantes):

3. Tipo de 2 linhas exige origem E destino, diferindo em pelo menos um campo.
4. Tipo de 1 linha exige origem OU destino, nunca ambos.
6. Soma das linhas de um movimento de deslocamento = 0 — a invariante que
   torna o "-140" da planilha impossível de representar.

(3) e (4) são uma CHECK constraint de verdade (uma linha só). (6) precisa
somar linhas-irmãs do mesmo movimento, o que uma CHECK de linha não
alcança — usa um *constraint trigger* `DEFERRABLE INITIALLY DEFERRED`,
que só avalia no COMMIT, depois que as duas linhas da transação já
existem. `HerdLedgerEntry` também ganha o trigger de imutabilidade do
ADR 0006 (mesmo padrão do `AuditEvent`), em complemento ao `save()`/
`delete()` que já recusam em Python.
"""

from django.db import migrations

TWO_LINE_TYPES = "'TRANSFERENCIA', 'EVOLUCAO', 'RECLASSIFICACAO'"


def create_constraints(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        f"""
        ALTER TABLE herd_herdmovement ADD CONSTRAINT
        herdmovement_origem_destino_por_tipo CHECK (
            (
                type IN ({TWO_LINE_TYPES})
                AND origin_farm_id IS NOT NULL
                AND origin_lot_id IS NOT NULL
                AND origin_category_id IS NOT NULL
                AND destination_farm_id IS NOT NULL
                AND destination_lot_id IS NOT NULL
                AND destination_category_id IS NOT NULL
                AND (origin_farm_id, origin_lot_id, origin_category_id)
                    IS DISTINCT FROM
                    (destination_farm_id, destination_lot_id, destination_category_id)
            )
            OR
            (
                type NOT IN ({TWO_LINE_TYPES})
                AND (
                    (
                        origin_farm_id IS NOT NULL AND origin_lot_id IS NOT NULL
                        AND origin_category_id IS NOT NULL
                        AND destination_farm_id IS NULL AND destination_lot_id IS NULL
                        AND destination_category_id IS NULL
                    )
                    OR
                    (
                        destination_farm_id IS NOT NULL AND destination_lot_id IS NOT NULL
                        AND destination_category_id IS NOT NULL
                        AND origin_farm_id IS NULL AND origin_lot_id IS NULL
                        AND origin_category_id IS NULL
                    )
                )
            )
        );
        """
    )

    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION herdledgerentry_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'HerdLedgerEntry e append-only: %% nao e permitido em linha ja gravada',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER herdledgerentry_immutable_trigger
        BEFORE UPDATE OR DELETE ON herd_herdledgerentry
        FOR EACH ROW EXECUTE FUNCTION herdledgerentry_immutable();
        """
    )

    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION herdledgerentry_soma_zero() RETURNS trigger AS $$
        DECLARE
            tipo_movimento varchar;
            soma integer;
        BEGIN
            SELECT type INTO tipo_movimento FROM herd_herdmovement
                WHERE id = NEW.movement_id;

            IF tipo_movimento IN ('TRANSFERENCIA', 'EVOLUCAO', 'RECLASSIFICACAO') THEN
                SELECT COALESCE(SUM(quantity), 0) INTO soma FROM herd_herdledgerentry
                    WHERE movement_id = NEW.movement_id;

                IF soma != 0 THEN
                    RAISE EXCEPTION
                        'Movimento de deslocamento com soma diferente de zero (soma atual: %%)',
                        soma;
                END IF;
            END IF;

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    schema_editor.execute(
        """
        CREATE CONSTRAINT TRIGGER herdledgerentry_soma_zero_trigger
        AFTER INSERT ON herd_herdledgerentry
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION herdledgerentry_soma_zero();
        """
    )


def drop_constraints(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "ALTER TABLE herd_herdmovement DROP CONSTRAINT IF EXISTS "
        "herdmovement_origem_destino_por_tipo;"
    )
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS herdledgerentry_immutable_trigger "
        "ON herd_herdledgerentry;"
    )
    schema_editor.execute("DROP FUNCTION IF EXISTS herdledgerentry_immutable();")
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS herdledgerentry_soma_zero_trigger "
        "ON herd_herdledgerentry;"
    )
    schema_editor.execute("DROP FUNCTION IF EXISTS herdledgerentry_soma_zero();")


class Migration(migrations.Migration):
    dependencies = [("herd", "0001_initial")]

    operations = [migrations.RunPython(create_constraints, drop_constraints)]
