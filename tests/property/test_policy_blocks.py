"""
Property-Based Test — Propiedad 24: Completitud de registro de bloqueos por Policy.

Feature: agente-comercial-polizas
Property 24: Completitud de registro de bloqueos por Policy

**Validates: Requirements 9.6**

Para N eventos de bloqueo por Policy, verificar que existen exactamente N
entradas en Observability con todos los campos requeridos:
- motivo_bloqueo
- tool_call_intentado
- session_id
- estado_pipefy
- timestamp

Cada vez que PolicyGuardrail bloquea una acción, debe registrar una traza
completa en AgentCore Observability con los 5 campos obligatorios (Req 9.6).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.models.constants import ESTADOS_VALIDOS_PIPEFY
from src.policy.guardrails import PolicyGuardrail


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Campos requeridos en cada registro de Observability (Req 9.6)
CAMPOS_REQUERIDOS_OBSERVABILITY = {
    "motivo_bloqueo",
    "tool_intentada",
    "session_id",
    "estado_pipefy",
    "timestamp",
}

# Session IDs aleatorios
_st_session_id = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=5,
    max_size=30,
).filter(lambda s: bool(s.strip()))

# Estados Pipefy válidos para el contexto de sesión
_st_estado_pipefy = st.sampled_from(sorted(ESTADOS_VALIDOS_PIPEFY))

# ---------------------------------------------------------------------------
# Generadores de tool calls que DEBEN ser bloqueados por Policy
# ---------------------------------------------------------------------------

# Tipo 1: Descuento inválido (≠ 5%)
_st_descuento_invalido = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
).filter(lambda x: abs(x - 0.05) > 1e-9).map(
    lambda descuento: {
        "tipo": "descuento_invalido",
        "tool_name": "enviar_correo",
        "params": {"descuento": descuento, "cuerpo": "Cotización de renovación"},
    }
)

# Tipo 2: Datos bancarios en estado no autorizado
_st_estados_sin_bancarios = st.sampled_from(
    sorted(ESTADOS_VALIDOS_PIPEFY - {"Cliente interesado", "Depósito solicitado"})
)

_st_datos_bancarios_invalido = _st_estados_sin_bancarios.map(
    lambda estado: {
        "tipo": "datos_bancarios_estado_invalido",
        "tool_name": "enviar_correo",
        "params": {
            "cuerpo": "Favor de depositar a CLABE: 012345678901234567 a nombre de CIME Power Systems S.A. de C.V."
        },
        "override_estado": estado,
    }
)

# Tipo 3: Estado Pipefy inválido en actualizar_pipefy
_st_estado_invalido_texto = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"), blacklist_characters="\x00"),
    min_size=3,
    max_size=40,
).filter(lambda s: s.strip() not in ESTADOS_VALIDOS_PIPEFY and bool(s.strip()))

_st_estado_pipefy_invalido = _st_estado_invalido_texto.map(
    lambda estado: {
        "tipo": "estado_pipefy_invalido",
        "tool_name": "actualizar_pipefy",
        "params": {"estado": estado},
    }
)

# Tipo 4: Servicio fuera de alcance
_st_servicios_fuera = st.sampled_from([
    "diagnóstico técnico",
    "venta de refacciones",
    "soporte técnico",
    "modificaciones de equipos",
    "reparación de equipos",
    "instalación de equipos",
])

_st_servicio_fuera_alcance = _st_servicios_fuera.map(
    lambda servicio: {
        "tipo": "servicio_fuera_alcance",
        "tool_name": "enviar_correo",
        "params": {
            "cuerpo": f"Le informo que podemos ofrecerle {servicio} para su equipo."
        },
    }
)

# Estrategia combinada: selecciona aleatoriamente un tipo de violación
_st_violacion_policy = st.one_of(
    _st_descuento_invalido,
    _st_datos_bancarios_invalido,
    _st_estado_pipefy_invalido,
    _st_servicio_fuera_alcance,
)

# Lista de N violaciones (entre 1 y 10)
_st_lista_violaciones = st.lists(
    _st_violacion_policy,
    min_size=1,
    max_size=10,
)


# ===========================================================================
# PROPERTY TEST — Propiedad 24: Completitud de registro de bloqueos por Policy
# ===========================================================================


class TestProperty24CompletitudRegistroBloqueos:
    """
    Feature: agente-comercial-polizas
    Property 24: Completitud de registro de bloqueos por Policy

    **Validates: Requirements 9.6**

    Para N eventos de bloqueo por Policy, verificar que existen exactamente N
    entradas en Observability con todos los campos requeridos.
    """

    @given(
        violaciones=_st_lista_violaciones,
        session_id=_st_session_id,
        estado_pipefy_sesion=_st_estado_pipefy,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.policy.guardrails.registrar_bloqueo_policy")
    def test_n_bloqueos_producen_n_registros_completos(
        self,
        mock_registrar_bloqueo: Any,
        violaciones: List[Dict[str, Any]],
        session_id: str,
        estado_pipefy_sesion: str,
    ) -> None:
        """
        Req 9.6 — Para N eventos de bloqueo por Policy, verificar que:
        1. Se invoca registrar_bloqueo_policy exactamente N veces
        2. Cada invocación incluye los 5 campos obligatorios no vacíos:
           motivo_bloqueo, tool_intentada, session_id, estado_pipefy, timestamp

        Se generan N violaciones aleatorias de distintos tipos (descuento
        inválido, datos bancarios en estado no autorizado, estado Pipefy
        inválido, servicio fuera de alcance) y se verifica la completitud
        del registro en Observability.
        """
        guardrail = PolicyGuardrail()
        bloqueos_esperados = 0

        for violacion in violaciones:
            tool_name = violacion["tool_name"]
            params = violacion["params"]

            # Determinar el estado_pipefy para la sesión de este tool call
            # Para datos bancarios en estado no autorizado, usar el estado overrideado
            estado_para_sesion = violacion.get("override_estado", estado_pipefy_sesion)

            # Para el tipo "datos_bancarios_estado_invalido", forzar un estado no autorizado
            if violacion["tipo"] == "datos_bancarios_estado_invalido":
                estado_para_sesion = violacion["override_estado"]

            session_state = {
                "session_id": session_id,
                "estado_pipefy": estado_para_sesion,
            }

            result = guardrail.validar_tool_call(
                tool_name=tool_name,
                params=params,
                session_state=session_state,
            )

            if result.bloqueado:
                bloqueos_esperados += 1

        # --- Verificación de la propiedad (Req 9.6) ---

        # 1. El número de llamadas a registrar_bloqueo_policy debe ser exactamente
        #    igual al número de bloqueos que ocurrieron
        assert mock_registrar_bloqueo.call_count == bloqueos_esperados, (
            f"Se esperaban {bloqueos_esperados} registros de bloqueo en "
            f"Observability pero se registraron {mock_registrar_bloqueo.call_count}.\n"
            f"Violaciones generadas: {len(violaciones)}\n"
            f"Tipos: {[v['tipo'] for v in violaciones]}"
        )

        # 2. Cada registro de bloqueo debe contener los 5 campos requeridos (Req 9.6)
        for i, call in enumerate(mock_registrar_bloqueo.call_args_list):
            kwargs = call.kwargs

            # Verificar presencia de cada campo requerido
            for campo in CAMPOS_REQUERIDOS_OBSERVABILITY:
                assert campo in kwargs, (
                    f"Registro de bloqueo #{i+1} NO contiene el campo "
                    f"obligatorio '{campo}' (Req 9.6).\n"
                    f"Campos presentes: {list(kwargs.keys())}"
                )

            # Verificar que los campos no estén vacíos
            assert kwargs["motivo_bloqueo"] and len(str(kwargs["motivo_bloqueo"]).strip()) > 0, (
                f"Registro de bloqueo #{i+1}: 'motivo_bloqueo' está vacío (Req 9.6)."
            )
            assert kwargs["tool_intentada"] and len(str(kwargs["tool_intentada"]).strip()) > 0, (
                f"Registro de bloqueo #{i+1}: 'tool_intentada' está vacío (Req 9.6)."
            )
            assert kwargs["session_id"] and len(str(kwargs["session_id"]).strip()) > 0, (
                f"Registro de bloqueo #{i+1}: 'session_id' está vacío (Req 9.6)."
            )
            assert kwargs["estado_pipefy"] is not None, (
                f"Registro de bloqueo #{i+1}: 'estado_pipefy' es None (Req 9.6)."
            )
            assert kwargs["timestamp"] is not None, (
                f"Registro de bloqueo #{i+1}: 'timestamp' es None (Req 9.6)."
            )

            # Verificar que timestamp es un datetime válido
            ts = kwargs["timestamp"]
            assert isinstance(ts, datetime), (
                f"Registro de bloqueo #{i+1}: 'timestamp' no es un datetime, "
                f"es {type(ts).__name__}: {ts} (Req 9.6)."
            )

    @given(
        violaciones=_st_lista_violaciones,
        session_id=_st_session_id,
        estado_pipefy_sesion=_st_estado_pipefy,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.policy.guardrails.registrar_bloqueo_policy")
    def test_bloqueos_registran_session_id_correcto(
        self,
        mock_registrar_bloqueo: Any,
        violaciones: List[Dict[str, Any]],
        session_id: str,
        estado_pipefy_sesion: str,
    ) -> None:
        """
        Req 9.6 — Verificar que cada registro de bloqueo contiene el session_id
        correcto de la sesión que generó la violación.
        """
        guardrail = PolicyGuardrail()

        for violacion in violaciones:
            tool_name = violacion["tool_name"]
            params = violacion["params"]
            estado_para_sesion = violacion.get("override_estado", estado_pipefy_sesion)

            if violacion["tipo"] == "datos_bancarios_estado_invalido":
                estado_para_sesion = violacion["override_estado"]

            session_state = {
                "session_id": session_id,
                "estado_pipefy": estado_para_sesion,
            }

            guardrail.validar_tool_call(
                tool_name=tool_name,
                params=params,
                session_state=session_state,
            )

        # Cada registro de bloqueo debe tener el session_id que fue proporcionado
        for i, call in enumerate(mock_registrar_bloqueo.call_args_list):
            kwargs = call.kwargs
            assert kwargs["session_id"] == session_id, (
                f"Registro de bloqueo #{i+1}: session_id registrado "
                f"'{kwargs['session_id']}' no coincide con el session_id "
                f"de la sesión '{session_id}' (Req 9.6)."
            )
