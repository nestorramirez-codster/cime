"""
Capa de Observabilidad — Agente Comercial IA · CIME Power Systems.

Implementa las 5 trazas definidas en el diseño con enmascaramiento de datos
sensibles aplicado ANTES de registrar cualquier parámetro.

Requisitos: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6

Modos de operación:
- Mock mode: registra en Python logger (JSON estructurado)
- Real mode: envía a AWS CloudWatch Logs (via boto3)
- Fallback: si falla escritura primaria, registra en CloudWatch Logs directo
  sin interrumpir el flujo del agente (Req 10.6)
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from src.models.constants import OBSERVABILITY_MAX_ENTRY_BYTES

# ---------------------------------------------------------------------------
# Logger configurado con formato JSON estructurado
# ---------------------------------------------------------------------------

_logger = logging.getLogger("cime.observability")

if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)

# Logger de fallback (Req 10.6) — escribe directamente si el primario falla
_fallback_logger = logging.getLogger("cime.observability.fallback")

if not _fallback_logger.handlers:
    _fb_handler = logging.StreamHandler(sys.stderr)
    _fb_handler.setFormatter(logging.Formatter("[FALLBACK] %(message)s"))
    _fallback_logger.addHandler(_fb_handler)
    _fallback_logger.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Enmascaramiento de datos sensibles (Req 10.5)
# ---------------------------------------------------------------------------

# Regex para detectar emails: RFC 5321 simplificado
_EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})"
)

# Regex para detectar datos bancarios: secuencias de 16-18 dígitos
# (CLABE 18 dígitos, tarjetas 16 dígitos, cuentas 10-18 dígitos)
_BANKING_REGEX = re.compile(
    r"\b(\d[\d\s\-]{10,17}\d)\b"
)

# Claves que típicamente contienen nombres completos
_NOMBRE_KEYS = {"nombre", "cliente_nombre", "nombre_completo", "nombre_cliente"}


def _enmascarar_email(valor: str) -> str:
    """
    Enmascara emails: usuario@dominio.com → ***@dominio.com

    Solo el dominio queda visible.
    """
    return _EMAIL_REGEX.sub(r"***@\1", valor)


def _extraer_ultimos_4(texto_numerico: str) -> str:
    """Extrae los últimos 4 dígitos de una cadena numérica."""
    solo_digitos = re.sub(r"\D", "", texto_numerico)
    if len(solo_digitos) >= 4:
        return solo_digitos[-4:]
    return solo_digitos


def _enmascarar_datos_bancarios(valor: str) -> str:
    """
    Enmascara datos bancarios: secuencias numéricas largas (10-18 dígitos)
    → ****-****-****-XXXX (últimos 4 dígitos visibles).
    """
    def _reemplazo(match: re.Match) -> str:
        texto_original = match.group(1)
        solo_digitos = re.sub(r"\D", "", texto_original)
        if len(solo_digitos) >= 10:
            ultimos_4 = solo_digitos[-4:]
            return f"****-****-****-{ultimos_4}"
        return texto_original

    return _BANKING_REGEX.sub(_reemplazo, valor)


def _enmascarar_nombre(nombre: str) -> str:
    """
    Enmascara nombre completo: "Juan García" → "J.G."
    Solo muestra iniciales con punto.
    """
    if not nombre or not isinstance(nombre, str):
        return nombre

    partes = nombre.strip().split()
    if len(partes) == 0:
        return nombre

    iniciales = ".".join(p[0].upper() for p in partes if p) + "."
    return iniciales


def enmascarar_datos_sensibles(data: dict) -> dict:
    """
    Aplica enmascaramiento a datos sensibles en un diccionario.

    Reglas (Req 10.5):
    - Email → ***@dominio.com (solo dominio visible)
    - Datos bancarios → ****-****-****-1234 (últimos 4 dígitos)
    - Nombre completo (cuando key contiene "nombre") → J.G. (solo iniciales)

    El enmascaramiento se aplica ANTES de registrar cualquier parámetro
    de tool en Observability.

    Args:
        data: Diccionario con los datos a enmascarar.

    Returns:
        Nuevo diccionario con los valores sensibles enmascarados.
    """
    if not isinstance(data, dict):
        return data

    resultado: dict = {}

    for key, valor in data.items():
        key_lower = key.lower()

        if isinstance(valor, dict):
            # Recursión para diccionarios anidados
            resultado[key] = enmascarar_datos_sensibles(valor)
        elif isinstance(valor, list):
            # Procesar listas recursivamente
            resultado[key] = [
                enmascarar_datos_sensibles(item) if isinstance(item, dict)
                else _enmascarar_valor(key_lower, item)
                for item in valor
            ]
        elif isinstance(valor, str):
            resultado[key] = _enmascarar_valor(key_lower, valor)
        else:
            resultado[key] = valor

    return resultado


def _enmascarar_valor(key_lower: str, valor: Any) -> Any:
    """Aplica reglas de enmascaramiento a un valor según su clave."""
    if not isinstance(valor, str):
        return valor

    # Regla 1: Si la clave contiene "nombre", enmascarar como nombre completo
    if any(nk in key_lower for nk in _NOMBRE_KEYS):
        return _enmascarar_nombre(valor)

    # Regla 2: Enmascarar emails encontrados en el valor
    valor = _enmascarar_email(valor)

    # Regla 3: Enmascarar datos bancarios
    valor = _enmascarar_datos_bancarios(valor)

    return valor


# ---------------------------------------------------------------------------
# Truncado a 10 KB máx (Req 10.1)
# ---------------------------------------------------------------------------

def _truncar_entrada(data: dict) -> dict:
    """
    Trunca una entrada de observabilidad a máximo OBSERVABILITY_MAX_ENTRY_BYTES (10 KB).

    Si la serialización supera el límite, se trunca el campo más grande
    progresivamente hasta cumplir con el límite.
    """
    serializado = json.dumps(data, ensure_ascii=False, default=str)
    if len(serializado.encode("utf-8")) <= OBSERVABILITY_MAX_ENTRY_BYTES:
        return data

    # Copiar y truncar campos de tipo string progresivamente
    resultado = dict(data)
    resultado["_truncado"] = True

    # Encontrar campos string y ordenar por tamaño descendente
    campos_str = [
        (k, v) for k, v in resultado.items()
        if isinstance(v, str) and k != "_truncado"
    ]
    campos_str.sort(key=lambda x: len(x[1]), reverse=True)

    for campo, valor in campos_str:
        serializado = json.dumps(resultado, ensure_ascii=False, default=str)
        if len(serializado.encode("utf-8")) <= OBSERVABILITY_MAX_ENTRY_BYTES:
            break
        # Truncar al 50% del tamaño actual
        nuevo_tamanio = max(50, len(valor) // 2)
        resultado[campo] = valor[:nuevo_tamanio] + "...[truncado]"

    # Verificación final: si aún excede, serializar y cortar directamente
    serializado = json.dumps(resultado, ensure_ascii=False, default=str)
    if len(serializado.encode("utf-8")) > OBSERVABILITY_MAX_ENTRY_BYTES:
        # Último recurso: cortar el JSON serializado
        bytes_json = serializado.encode("utf-8")[:OBSERVABILITY_MAX_ENTRY_BYTES - 50]
        resultado = {"_truncado": True, "_raw": bytes_json.decode("utf-8", errors="ignore")}

    return resultado


# ---------------------------------------------------------------------------
# Registro seguro con fallback (Req 10.6)
# ---------------------------------------------------------------------------

def _registrar_traza(tipo_evento: str, datos: dict) -> None:
    """
    Registra una traza con fallback en caso de fallo.

    1. Intenta escribir en el logger primario (OTel/CloudWatch en modo real).
    2. Si falla, escribe en logger de fallback (CloudWatch Logs directo).
    3. NUNCA interrumpe el flujo del agente.
    """
    entrada = {
        "tipo_evento": tipo_evento,
        "timestamp_registro": datetime.now(timezone.utc).isoformat(),
        **datos,
    }

    # Truncar a 10 KB (Req 10.1)
    entrada = _truncar_entrada(entrada)

    try:
        mensaje_json = json.dumps(entrada, ensure_ascii=False, default=str)
        _logger.info(mensaje_json)
    except Exception as e:
        # Fallback: si falla escritura primaria, registrar en fallback (Req 10.6)
        try:
            fallback_msg = json.dumps(
                {
                    "tipo_evento": tipo_evento,
                    "error_escritura": str(e),
                    "timestamp_registro": datetime.now(timezone.utc).isoformat(),
                    "_fallback": True,
                },
                ensure_ascii=False,
                default=str,
            )
            _fallback_logger.warning(fallback_msg)
        except Exception:
            # Último recurso: no interrumpir el flujo bajo ninguna circunstancia
            pass


# ---------------------------------------------------------------------------
# 5 Tipos de traza (diseño § AgentCore Observability)
# ---------------------------------------------------------------------------

def registrar_inicio_sesion(
    poliza_id: str,
    session_id: str,
    timestamp_inicio: datetime,
    estado_pipefy_inicial: str,
) -> None:
    """
    Traza 1: Inicio de sesión.

    Registra el arranque de una sesión de seguimiento comercial.
    Los datos se enmascaran antes de registrar.

    Args:
        poliza_id: ID de la póliza activada.
        session_id: ID de sesión generado por AgentCore Runtime.
        timestamp_inicio: Momento UTC de inicio.
        estado_pipefy_inicial: Estado de la póliza al iniciar.
    """
    datos = enmascarar_datos_sensibles({
        "poliza_id": poliza_id,
        "session_id": session_id,
        "timestamp_inicio": timestamp_inicio.isoformat() if isinstance(timestamp_inicio, datetime) else str(timestamp_inicio),
        "estado_pipefy_inicial": estado_pipefy_inicial,
    })
    _registrar_traza("inicio_sesion", datos)


def registrar_tool_call(
    tool_name: str,
    params_enmascarados: dict,
    resultado: Any,
    duracion_ms: float,
) -> None:
    """
    Traza 2: Invocación de tool.

    Registra cada llamada a una tool MCP con parámetros enmascarados.
    El enmascaramiento se aplica ANTES de registrar.

    Args:
        tool_name: Nombre de la tool invocada.
        params_enmascarados: Parámetros de la tool (serán enmascarados).
        resultado: Resultado de la invocación (enmascarado también).
        duracion_ms: Duración de la invocación en milisegundos.
    """
    # Enmascarar parámetros
    params_safe = enmascarar_datos_sensibles(params_enmascarados) if isinstance(params_enmascarados, dict) else params_enmascarados

    # Enmascarar resultado si es dict
    resultado_safe = enmascarar_datos_sensibles(resultado) if isinstance(resultado, dict) else resultado

    datos = {
        "tool_name": tool_name,
        "params_enmascarados": params_safe,
        "resultado": str(resultado_safe) if not isinstance(resultado_safe, (dict, list, str)) else resultado_safe,
        "duracion_ms": duracion_ms,
    }
    _registrar_traza("tool_call", datos)


def registrar_error(
    tipo_error: str,
    componente: str,
    mensaje_error: str,
    num_reintento: int,
    accion_mitigacion: str,
) -> None:
    """
    Traza 3: Error técnico.

    Registra errores técnicos del sistema con contexto de reintento.

    Args:
        tipo_error: Clasificación del error (ej: "TimeoutError", "APIError").
        componente: Componente que generó el error (ej: "pipefy", "ses").
        mensaje_error: Descripción del error.
        num_reintento: Número de reintento actual (0 = primer intento).
        accion_mitigacion: Acción tomada para mitigar (ej: "retry", "escalar_humano").
    """
    datos = enmascarar_datos_sensibles({
        "tipo_error": tipo_error,
        "componente": componente,
        "mensaje_error": mensaje_error,
        "num_reintento": num_reintento,
        "accion_mitigacion": accion_mitigacion,
    })
    _registrar_traza("error_tecnico", datos)


def registrar_cierre_sesion(
    estado_final: str,
    duracion_total_ms: float,
    mensajes_enviados: int,
    motivo_cierre: str,
) -> None:
    """
    Traza 4: Cierre de sesión.

    Registra el fin de una sesión de seguimiento.

    Args:
        estado_final: Estado_Pipefy al momento del cierre.
        duracion_total_ms: Duración total de la sesión en ms.
        mensajes_enviados: Cantidad de mensajes enviados al cliente.
        motivo_cierre: Razón del cierre (ej: "flujo_completado", "error_fatal").
    """
    datos = enmascarar_datos_sensibles({
        "estado_final": estado_final,
        "duracion_total_ms": duracion_total_ms,
        "mensajes_enviados": mensajes_enviados,
        "motivo_cierre": motivo_cierre,
    })
    _registrar_traza("cierre_sesion", datos)


def registrar_bloqueo_policy(
    motivo_bloqueo: str,
    tool_intentada: str,
    session_id: str,
    estado_pipefy: str,
    timestamp: Optional[datetime] = None,
) -> None:
    """
    Traza 5: Bloqueo por Policy.

    Registra cuando un guardrail bloquea una acción del agente.

    Args:
        motivo_bloqueo: Razón del bloqueo (ej: "descuento_no_autorizado").
        tool_intentada: Tool que se intentó ejecutar.
        session_id: ID de la sesión activa.
        estado_pipefy: Estado actual de la póliza.
        timestamp: Momento del bloqueo (UTC). Si None, se usa ahora.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    datos = enmascarar_datos_sensibles({
        "motivo_bloqueo": motivo_bloqueo,
        "tool_intentada": tool_intentada,
        "session_id": session_id,
        "estado_pipefy": estado_pipefy,
        "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
    })
    _registrar_traza("bloqueo_policy", datos)
