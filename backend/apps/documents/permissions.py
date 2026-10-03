"""Quem baixa o quê. O documento tem os números do escopo de quem o gerou:
ele mesmo baixa; ADMIN e GESTOR, que enxergam tudo, também."""


def pode_ver_documento(user, documento) -> bool:
    if not user.is_authenticated:
        return False
    return user.has_broad_access or documento.generated_by_id == user.pk
