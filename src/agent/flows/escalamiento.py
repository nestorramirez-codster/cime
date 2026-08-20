"""
Flujo de Escalamiento — Agente Comercial IA de CIME Power Systems.

Evalúa el mensaje del cliente para detectar triggers de escalamiento
y ejecuta el escalamiento apropiado con notificación al cliente y
actualización de Pipefy.

Triggers implementados:
- Solicitud explícita de asesor humano (Req 6.1)
- Negociación especial (Req 6.3)
- Facturación / datos fiscales (Req 6.4)
- Inconformidad / queja / atención personalizada (Req 6.5)
- Duda técnica no resuelta en KB (Req 6.6)

Acciones post-escalamiento:
- Confirmar al cliente por correo: asesor en máx 24h hábiles (Req 6.2)
- Actualizar Pipefy a "Escalado a humano" (Req 6.9)
- Incluir datos completos si Memory no disponible (Req 6.8)

Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 6.9
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from src.config.kb_client import KBClient
from src.models.constants import KB_SCORE_MINIMO
from src.models.data_models import (
    ActivationPayload,
    DatosPoliza,
    SessionState,
)
from src.tools.email_tools import enviar_correo
from src.tools.escalation_tools import escalar_humano
from src.tools.pipefy_tools import actualizar_pipefy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keywords para detección de triggers de escalamiento
# ---------------------------------------------------------------------------

_KEYWORDS_ASESOR_HUMANO = [
    "asesor",
    "humano",
    "persona",
    "hablar con alguien",
]

_KEYWORDS_NEGOCIACION_ESPECIAL = [
    "descuento",
    "diferido",
    "plazo",
    "extensión",
    "extension",
    "especial",
]

_KEYWORDS_FACTURACION = [
    "factura",
    "fiscal",
    "rfc",
    "datos fiscales",
    "cfdi",
]

_KEYWORDS_ATENCION_PERSONALIZADA = [
    "queja",
    "inconformidad",
    "molesto",
    "insatisfecho",
    "reclamo",
]


# ---------------------------------------------------------------------------
# Funciones de detección de triggers
# ---------------------------------------------------------------------------


def _requiere_asesor_humano(mensaje: str) -> bool:
    """Detecta si el cliente solicita explícitamente hablar con un asesor humano.

    Req 6.1: keywords como "asesor", "humano", "persona", "hablar con alguien".
    """
    msg_lower = mensaje.lower()
    return any(kw in msg_lower for kw in _KEYWORDS_ASESOR_HUMANO)


def _requiere_negociacion_especial(mensaje: str) -> bool:
    """Detecta si el cliente solicita negociación fuera de reglas estándar.

    Req 6.3: descuentos ≠ 5%, plazos diferidos, extensión de cobertura.
    La mención de "5%" por sí sola no escala (es el descuento estándar).
    """
    msg_lower = mensaje.lower()
    tiene_keyword = any(kw in msg_lower for kw in _KEYWORDS_NEGOCIACION_ESPECIAL)

    if not tiene_keyword:
        return False

    # Si menciona "5%" como único descuento referido, es el estándar → no escalar
    # Solo escalar si hay keywords Y no es solo una referencia al 5% estándar
    if "descuento" in msg_lower:
        # Si menciona "5%" exclusivamente (sin otros porcentajes), no escalar
        porcentajes = re.findall(r"(\d+(?:\.\d+)?)\s*%", mensaje)
        if porcentajes and all(p == "5" for p in porcentajes):
            return False

    return True


def _requiere_facturacion(mensaje: str) -> bool:
    """Detecta si el cliente solicita info de facturación o datos fiscales.

    Req 6.4: factura, fiscal, RFC, datos fiscales, CFDI.
    """
    msg_lower = mensaje.lower()
    return any(kw in msg_lower for kw in _KEYWORDS_FACTURACION)


def _requiere_atencion_personalizada(mensaje: str) -> bool:
    """Detecta si el cliente expresa inconformidad o queja.

    Req 6.5: queja, inconformidad, molesto, insatisfecho, reclamo.
    """
    msg_lower = mensaje.lower()
    return any(kw in msg_lower for kw in _KEYWORDS_ATENCION_PERSONALIZADA)


def _requiere_soporte_tecnico(mensaje: str, kb_client: Optional[KBClient]) -> bool:
    """Detecta si el cliente tiene duda técnica no respondida en la KB.

    Req 6.6: consulta la KB y si el score < 0.70, indica que la duda no
    está cubierta y requiere escalamiento.

    Si kb_client es None (KB no disponible), se considera que no se puede
    responder y se debe escalar.
    """
    if kb_client is None:
        return True

    try:
        response = kb_client.query(mensaje)
        return response.top_score < KB_SCORE_MINIMO
    except Exception as e:
        logger.warning(
            f"Error consultando KB para soporte técnico: {e}. "
            "Escalando por precaución."
        )
        return True


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _construir_datos_poliza(payload: ActivationPayload) -> DatosPoliza:
    """Construye DatosPoliza a partir del ActivationPayload."""
    return DatosPoliza(
        poliza_id=payload.poliza_id,
        cliente_nombre=payload.cliente_nombre,
        cliente_email=payload.cliente_email,
        fecha_vencimiento=payload.fecha_vencimiento,
        precio_renovacion=payload.precio_renovacion,
        equipo_nombre=payload.equipo_nombre,
    )


def _ejecutar_escalamiento(
    motivo: str,
    session_state: SessionState,
    payload: ActivationPayload,
    memory_disponible: bool = True,
) -> dict:
    """Ejecuta el escalamiento completo: escalar_humano + correo + Pipefy.

    Args:
        motivo: Razón específica del escalamiento.
        session_state: Estado actual de la sesión.
        payload: Datos de activación originales.
        memory_disponible: Si False, incluye todos los datos del payload
            en el escalamiento (Req 6.8).

    Returns:
        Dict con resultado del escalamiento.
    """
    datos_poliza = _construir_datos_poliza(payload)

    # Req 6.8: Si Memory no disponible, los datos del payload + sesión actual
    # ya van incluidos en historial y datos_poliza del EscalationPayload
    historial = session_state.historial_mensajes

    # 1. Invocar escalar_humano (Req 6.9)
    escalar_humano(
        motivo=motivo,
        historial=historial,
        estado_pipefy=session_state.estado_pipefy,
        datos_poliza=datos_poliza,
        session_id=session_state.session_id,
    )

    logger.info(
        f"Escalamiento ejecutado para poliza {payload.poliza_id}: {motivo}"
    )

    # 2. Confirmar al cliente por correo (Req 6.2)
    asunto = (
        f"Atención personalizada - Póliza {payload.equipo_nombre}"
    )
    cuerpo = (
        f"Estimado/a {payload.cliente_nombre},\n\n"
        f"Hemos recibido su solicitud y un asesor especializado "
        f"lo contactará en un plazo máximo de 24 horas hábiles.\n\n"
        f"Agradecemos su paciencia.\n\n"
        f"Atentamente,\nCIME Power Systems"
    )

    try:
        email_result = enviar_correo(
            destinatario=payload.cliente_email,
            asunto=asunto,
            cuerpo=cuerpo,
        )
        email_enviado = email_result.success
    except Exception as e:
        logger.warning(
            f"No se pudo enviar correo de confirmación de escalamiento "
            f"a {payload.cliente_email}: {e}"
        )
        email_enviado = False

    # 3. Actualizar Pipefy a "Escalado a humano" (Req 6.9)
    try:
        actualizar_pipefy(
            poliza_id=payload.poliza_id,
            estado="Escalado a humano",
            nota=f"Escalado: {motivo[:180]}",
            session_id=session_state.session_id,
        )
        pipefy_actualizado = True
    except Exception as e:
        logger.warning(
            f"No se pudo actualizar Pipefy a 'Escalado a humano' "
            f"para poliza {payload.poliza_id}: {e}"
        )
        pipefy_actualizado = False

    return {
        "escalado": True,
        "motivo": motivo,
        "email_confirmacion_enviado": email_enviado,
        "pipefy_actualizado": pipefy_actualizado,
    }


# ---------------------------------------------------------------------------
# Función principal: evaluar_escalamiento
# ---------------------------------------------------------------------------


def evaluar_escalamiento(
    mensaje_cliente: str,
    session_state: SessionState,
    payload: ActivationPayload,
    kb_client: Optional[KBClient] = None,
    memory_disponible: bool = True,
) -> dict:
    """Evalúa el mensaje del cliente para triggers de escalamiento.

    Analiza el mensaje en orden de prioridad y ejecuta el escalamiento
    correspondiente si se detecta un trigger. Si no se detecta ningún
    trigger, retorna indicando que no se requiere escalamiento.

    Orden de evaluación:
    1. Solicitud explícita de asesor humano (Req 6.1) — INMEDIATO
    2. Negociación especial (Req 6.3)
    3. Facturación / datos fiscales (Req 6.4)
    4. Inconformidad / atención personalizada (Req 6.5)
    5. Duda técnica no respondida en KB (Req 6.6)

    Args:
        mensaje_cliente: Texto del mensaje del cliente a evaluar.
        session_state: Estado actual de la sesión del agente.
        payload: Datos de activación originales (ActivationPayload).
        kb_client: Cliente de Knowledge Base (inyectable para testing).
            Si None y se evalúa soporte técnico, se asume KB no disponible.
        memory_disponible: Si False, incluye todos los datos del payload
            en el escalamiento (Req 6.8).

    Returns:
        Dict con:
            - escalado: bool indicando si se ejecutó escalamiento.
            - motivo: str con la razón (o "sin_escalamiento").
            - trigger: str identificador del trigger detectado.
            - email_confirmacion_enviado: bool (solo si escalado=True).
            - pipefy_actualizado: bool (solo si escalado=True).
    """
    if not mensaje_cliente or not mensaje_cliente.strip():
        return {
            "escalado": False,
            "motivo": "sin_escalamiento",
            "trigger": "ninguno",
        }

    # --- 1. Solicitud explícita de asesor humano (Req 6.1) ---
    if _requiere_asesor_humano(mensaje_cliente):
        motivo = (
            "Cliente solicita explícitamente hablar con un asesor humano"
        )
        resultado = _ejecutar_escalamiento(
            motivo=motivo,
            session_state=session_state,
            payload=payload,
            memory_disponible=memory_disponible,
        )
        resultado["trigger"] = "asesor_humano"
        return resultado

    # --- 2. Negociación especial (Req 6.3) ---
    if _requiere_negociacion_especial(mensaje_cliente):
        motivo = (
            "Cliente solicita negociación especial: "
            f"'{mensaje_cliente[:100]}'"
        )
        resultado = _ejecutar_escalamiento(
            motivo=motivo,
            session_state=session_state,
            payload=payload,
            memory_disponible=memory_disponible,
        )
        resultado["trigger"] = "negociacion_especial"
        return resultado

    # --- 3. Facturación / datos fiscales (Req 6.4) ---
    if _requiere_facturacion(mensaje_cliente):
        motivo = (
            "Cliente solicita información de facturación o datos fiscales: "
            f"'{mensaje_cliente[:100]}'"
        )
        resultado = _ejecutar_escalamiento(
            motivo=motivo,
            session_state=session_state,
            payload=payload,
            memory_disponible=memory_disponible,
        )
        resultado["trigger"] = "facturacion"
        return resultado

    # --- 4. Inconformidad / atención personalizada (Req 6.5) ---
    if _requiere_atencion_personalizada(mensaje_cliente):
        motivo = (
            "Cliente expresa inconformidad o solicita atención personalizada: "
            f"'{mensaje_cliente[:100]}'"
        )
        resultado = _ejecutar_escalamiento(
            motivo=motivo,
            session_state=session_state,
            payload=payload,
            memory_disponible=memory_disponible,
        )
        resultado["trigger"] = "atencion_personalizada"
        return resultado

    # --- 5. Duda técnica no respondida en KB (Req 6.6) ---
    if _requiere_soporte_tecnico(mensaje_cliente, kb_client):
        motivo = (
            "Duda técnica del cliente no respondida en Knowledge Base: "
            f"'{mensaje_cliente[:100]}'"
        )
        resultado = _ejecutar_escalamiento(
            motivo=motivo,
            session_state=session_state,
            payload=payload,
            memory_disponible=memory_disponible,
        )
        resultado["trigger"] = "soporte_tecnico"
        return resultado

    # --- Sin trigger de escalamiento ---
    return {
        "escalado": False,
        "motivo": "sin_escalamiento",
        "trigger": "ninguno",
    }
