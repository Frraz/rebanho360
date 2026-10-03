"""Constraint de banco para 'safras da mesma empresa não se sobrepõem'
(F1-01). Seria um `ExclusionConstraint` com `btree_gist` em Postgres puro,
mas a extensão não está disponível neste ambiente — trigger plpgsql
cumpre o mesmo papel, no mesmo espírito do ADR 0006 (trigger de
imutabilidade do AuditEvent). Só se aplica a Postgres."""

from django.db import migrations


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION organizations_season_no_overlap()
        RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM organizations_season s
                WHERE s.company_id = NEW.company_id
                  AND s.id IS DISTINCT FROM NEW.id
                  AND s.start_date <= NEW.end_date
                  AND s.end_date >= NEW.start_date
            ) THEN
                RAISE EXCEPTION
                    'Safra sobreposta: ja existe uma safra desta empresa no periodo informado.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER organizations_season_no_overlap
        BEFORE INSERT OR UPDATE ON organizations_season
        FOR EACH ROW EXECUTE FUNCTION organizations_season_no_overlap();
        """
    )


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS organizations_season_no_overlap ON organizations_season;"
    )
    schema_editor.execute(
        "DROP FUNCTION IF EXISTS organizations_season_no_overlap();"
    )


class Migration(migrations.Migration):
    dependencies = [("organizations", "0001_initial")]

    operations = [migrations.RunPython(create_trigger, drop_trigger)]
