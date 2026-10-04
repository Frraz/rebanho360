"""Busca por nome de parceiro: índice trigram sobre `UPPER(name)`, que é o que o
`icontains` do Django consulta no PostgreSQL (`UPPER(col) LIKE UPPER('%x%')`).
Sem ele, cada busca varre a tabela inteira."""

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("partners", "0001_initial"),
    ]

    # `CREATE INDEX CONCURRENTLY` não trava a escrita enquanto o índice é
    # construído e exige estar fora de transação.
    atomic = False

    operations = [
        TrigramExtension(),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS partner_name_trgm "
                "ON partners_partner USING gin (UPPER(name) gin_trgm_ops)"
            ),
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS partner_name_trgm",
        ),
    ]
