"""
Validadores de modelos de datos para el Agente Comercial IA.
Requisitos: 1.2, 1.3
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from src.models.data_models import ActivationPayload

# ---------------------------------------------------------------------------
# Expresión regular para validación de email (RFC 5321 — subconjunto práctico)
# Verifica: local-part @ domain con al menos un punto en el dominio.
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _es_email_valido(email: Any) -> bool:
    """
    Verifica que el email tenga formato RFC 5321 básico:
    - No es None ni string vacío
    - Tiene exactamente un símbolo '@'
    - El dominio contiene al menos un punto
    - Coincide con el patrón de caracteres permitidos
    """
    if not isinstance(email, str) or not email.strip():
        return False
    return bool(_EMAIL_RE.match(email.strip()))


def _es_fecha_valida(valor: Any) -> bool:
    """
    Verifica que el valor sea un objeto `date` válido (ISO 8601 YYYY-MM-DD).
    Al usar dataclasses tipadas la fecha ya llega como `date`; esta función
    también acepta strings para facilitar la construcción desde JSON/webhook.
    """
    if isinstance(valor, date):
        return True
    if isinstance(valor, str) and valor.strip():
        try:
            date.fromisoformat(valor.strip())
            return True
        except ValueError:
            return False
    return False


def _es_precio_valido(precio: Any) -> bool:
    """
    Verifica que el precio sea numérico y mayor a 0 (Req 1.2).
    Rechaza NaN, Inf y valores <= 0.
    """
    try:
        valor = float(precio)
    except (TypeError, ValueError):
        return False
    import math
    if math.isnan(valor) or math.isinf(valor):
        return False
    return valor > 0


def _es_campo_texto_valido(valor: Any) -> bool:
    """Verifica que el campo sea un string no nulo y no vacío."""
    return isinstance(valor, str) and bool(valor.strip())


def es_payload_valido(payload: ActivationPayload) -> bool:
    """
    Valida que el ActivationPayload cumpla con todos los criterios del Req 1.2:

    - poliza_id       : string no vacío
    - cliente_nombre  : string no vacío
    - cliente_email   : email válido formato RFC 5321
    - fecha_vencimiento: fecha calendario válida (date ISO 8601)
    - precio_renovacion: número > 0 (MXN)
    - equipo_nombre   : string no vacío

    Returns:
        True si todos los campos son válidos, False en caso contrario.
    """
    if payload is None:
        return False

    if not _es_campo_texto_valido(getattr(payload, "poliza_id", None)):
        return False

    if not _es_campo_texto_valido(getattr(payload, "cliente_nombre", None)):
        return False

    if not _es_email_valido(getattr(payload, "cliente_email", None)):
        return False

    if not _es_fecha_valida(getattr(payload, "fecha_vencimiento", None)):
        return False

    if not _es_precio_valido(getattr(payload, "precio_renovacion", None)):
        return False

    if not _es_campo_texto_valido(getattr(payload, "equipo_nombre", None)):
        return False

    return True


def obtener_campos_invalidos(payload: ActivationPayload) -> list[str]:
    """
    Retorna la lista de nombres de campos inválidos en el payload.
    Útil para el registro detallado de errores en Observability (Req 1.3).
    """
    if payload is None:
        return ["payload_nulo"]

    invalidos: list[str] = []

    if not _es_campo_texto_valido(getattr(payload, "poliza_id", None)):
        invalidos.append("poliza_id")

    if not _es_campo_texto_valido(getattr(payload, "cliente_nombre", None)):
        invalidos.append("cliente_nombre")

    if not _es_email_valido(getattr(payload, "cliente_email", None)):
        invalidos.append("cliente_email")

    if not _es_fecha_valida(getattr(payload, "fecha_vencimiento", None)):
        invalidos.append("fecha_vencimiento")

    if not _es_precio_valido(getattr(payload, "precio_renovacion", None)):
        invalidos.append("precio_renovacion")

    if not _es_campo_texto_valido(getattr(payload, "equipo_nombre", None)):
        invalidos.append("equipo_nombre")

    return invalidos
