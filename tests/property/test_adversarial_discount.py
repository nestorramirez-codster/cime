"""
Property-Based Test — Propiedad 6: Guardrail adversarial de descuento.

Feature: agente-comercial-polizas
Property 6: Guardrail adversarial de descuento (propiedad de seguridad)

**Validates: Requirements 3, 9.1**

Para cualquier mensaje del cliente que solicite un descuento distinto al 5%
(incluyendo variaciones adversariales en distintos idiomas, formatos y contextos),
la Policy SIEMPRE debe bloquear el tool call y el agente debe responder con la
oferta estándar del 5% o invocar escalar_humano.

Se generan mínimo 100 variaciones adversariales de mensajes que incluyen:
- Porcentajes explícitos en español e inglés (10%, 20%, 50%, etc.)
- Frases coloquiales ("mitad de precio", "give me 30% off")
- Formatos numéricos variados (con decimales, enteros)
- Patrones con "por ciento" y "porciento"
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.models.constants import DESCUENTO_PRE_VENCIMIENTO
from src.policy.guardrails import PolicyGuardrail


# ---------------------------------------------------------------------------
# Estrategias Hypothesis para generar descuentos adversariales
# ---------------------------------------------------------------------------

# Porcentajes que NO son 5% (el único autorizado)
_st_porcentaje_no_5 = st.one_of(
    # Enteros de 1 a 100 excluyendo 5
    st.integers(min_value=1, max_value=4),
    st.integers(min_value=6, max_value=100),
    # Flotantes que no son 5.0 (con un decimal)
    st.floats(min_value=0.1, max_value=4.9, allow_nan=False, allow_infinity=False).map(
        lambda x: round(x, 1)
    ),
    st.floats(min_value=5.1, max_value=99.9, allow_nan=False, allow_infinity=False).map(
        lambda x: round(x, 1)
    ),
)

# Plantillas de mensajes adversariales en español con porcentaje embebido
_PLANTILLAS_ESPANOL_PORCENTAJE = [
    "Necesito un descuento del {pct}%",
    "¿Me pueden dar {pct}% de descuento?",
    "Quiero {pct}% de rebaja en mi póliza",
    "Aplicar descuento de {pct} por ciento",
    "Ofrezcan {pct}porciento para renovar",
    "Necesito al menos un {pct}% para renovar",
    "Solo renuevo si me dan {pct}% de descuento",
    "Mi presupuesto necesita {pct}% menos",
    "El año pasado me dieron {pct}%",
    "La competencia me ofrece {pct}% de descuento",
    "Dame {pct} por ciento o no renuevo",
    "Solicito un {pct}% por ser cliente frecuente",
    "Requiero descuento del {pct}% para aprobar la renovación",
    "Con un {pct}% cerramos el trato hoy mismo",
    "Estoy buscando un {pct}% mínimo",
]

# Plantillas en inglés con porcentaje embebido (usando % que el regex detecta)
_PLANTILLAS_INGLES_PORCENTAJE = [
    "I need a {pct}% discount",
    "Give me {pct}% off the renewal price",
    "Can you offer {pct}% discount?",
    "I want {pct}% off please",
    "Looking for at least {pct}% reduction",
    "My budget requires {pct}% discount minimum",
]

# Todas las plantillas combinadas
_TODAS_PLANTILLAS = _PLANTILLAS_ESPANOL_PORCENTAJE + _PLANTILLAS_INGLES_PORCENTAJE

# Estrategia para seleccionar una plantilla
_st_plantilla = st.sampled_from(_TODAS_PLANTILLAS)


# Estrategia para generar el texto adversarial completo
@st.composite
def _st_mensaje_adversarial_porcentaje(draw: st.DrawFn) -> str:
    """Genera un mensaje con porcentaje != 5% embebido en una plantilla."""
    plantilla = draw(_st_plantilla)
    porcentaje = draw(_st_porcentaje_no_5)
    return plantilla.format(pct=porcentaje)


# Estrategia para generar descuento como parámetro explícito (valor decimal != 0.05)
_st_descuento_parametro_no_5 = st.one_of(
    # Valores decimales que no son 0.05
    st.floats(min_value=0.01, max_value=0.049, allow_nan=False, allow_infinity=False).map(
        lambda x: round(x, 3)
    ),
    st.floats(min_value=0.051, max_value=1.0, allow_nan=False, allow_infinity=False).map(
        lambda x: round(x, 3)
    ),
    # Valores enteros (como si pasaran el porcentaje directamente en vez del decimal)
    st.integers(min_value=1, max_value=4).map(float),
    st.integers(min_value=6, max_value=100).map(float),
)

# Nombres de tools que podrían ser afectados
_st_tool_name = st.sampled_from([
    "enviar_correo",
    "generar_cotizacion",
    "aplicar_descuento",
])

# Session states genéricos
_st_session_id = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=5,
    max_size=20,
)

_st_estado_pipefy = st.sampled_from([
    "Póliza detectada",
    "Contacto inicial enviado",
    "Seguimiento en curso",
    "Cliente interesado",
    "Depósito solicitado",
])


# ===========================================================================
# PROPERTY TEST — Propiedad 6: Guardrail adversarial de descuento
# ===========================================================================


class TestProperty6GuardrailAdversarialDescuento:
    """
    Feature: agente-comercial-polizas
    Property 6: Guardrail adversarial de descuento (propiedad de seguridad)

    **Validates: Requirements 3, 9.1**

    Para cualquier mensaje del cliente que solicite un descuento distinto al 5%,
    la Policy SIEMPRE debe bloquear el tool call. Se valida con mínimo 100
    variaciones adversariales.
    """

    @given(
        descuento=_st_descuento_parametro_no_5,
        tool_name=_st_tool_name,
        session_id=_st_session_id,
        estado_pipefy=_st_estado_pipefy,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_bloquea_descuento_parametro_distinto_5_porciento(
        self,
        descuento: float,
        tool_name: str,
        session_id: str,
        estado_pipefy: str,
    ) -> None:
        """
        Req 9.1 — Cualquier tool call con parámetro 'descuento' cuyo valor
        sea distinto a 0.05 (5%) DEBE ser bloqueado por el guardrail.

        Se generan 100 valores adversariales (enteros, flotantes, > y < 5%).
        """
        guardrail = PolicyGuardrail()

        params = {"descuento": descuento}
        session_state = {
            "session_id": session_id,
            "estado_pipefy": estado_pipefy,
        }

        result = guardrail.validar_tool_call(
            tool_name=tool_name,
            params=params,
            session_state=session_state,
        )

        assert result.bloqueado is True, (
            f"El guardrail NO bloqueó un descuento de {descuento} "
            f"({descuento * 100:.1f}%). Solo 5% (0.05) está autorizado.\n"
            f"Tool: {tool_name}, Estado: {estado_pipefy}"
        )

        # Verificar que el motivo de bloqueo menciona el descuento no autorizado
        assert "no autorizado" in result.motivo_bloqueo.lower() or "no numérico" in result.motivo_bloqueo.lower(), (
            f"El motivo de bloqueo debería indicar descuento no autorizado.\n"
            f"Motivo actual: {result.motivo_bloqueo}"
        )

        # Verificar que ofrece opciones disponibles (oferta estándar 5% o escalar)
        assert len(result.opciones_disponibles) > 0, (
            f"Tras bloqueo, deben ofrecerse opciones disponibles al cliente.\n"
            f"Opciones: {result.opciones_disponibles}"
        )

        # Verificar que una de las opciones menciona 5% o asesor
        opciones_texto = " ".join(result.opciones_disponibles).lower()
        assert "5%" in opciones_texto or "asesor" in opciones_texto, (
            f"Las opciones deben incluir oferta estándar del 5% o escalar a asesor.\n"
            f"Opciones: {result.opciones_disponibles}"
        )

    @given(
        mensaje=_st_mensaje_adversarial_porcentaje(),
        session_id=_st_session_id,
        estado_pipefy=_st_estado_pipefy,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_bloquea_descuento_en_cuerpo_correo_adversarial(
        self,
        mensaje: str,
        session_id: str,
        estado_pipefy: str,
    ) -> None:
        """
        Req 3, 9.1 — Cualquier correo cuyo cuerpo contenga un porcentaje
        distinto a 5% en formato adversarial DEBE ser bloqueado por el
        guardrail cuando se intenta enviar vía enviar_correo.

        Se generan 100+ variaciones adversariales en español e inglés con
        formatos numéricos variados (enteros, decimales, "por ciento", "porciento").
        """
        guardrail = PolicyGuardrail()

        params = {"cuerpo": mensaje}
        session_state = {
            "session_id": session_id,
            "estado_pipefy": estado_pipefy,
        }

        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params=params,
            session_state=session_state,
        )

        assert result.bloqueado is True, (
            f"El guardrail NO bloqueó un correo con descuento adversarial.\n"
            f"Mensaje: '{mensaje}'\n"
            f"Estado: {estado_pipefy}, Session: {session_id}"
        )

        # Verificar que el motivo indica el descuento no autorizado
        assert "no autorizado" in result.motivo_bloqueo.lower(), (
            f"El motivo de bloqueo debe indicar descuento no autorizado.\n"
            f"Motivo: {result.motivo_bloqueo}\n"
            f"Mensaje: '{mensaje}'"
        )

        # Verificar campos de trazabilidad
        assert result.tool_call_intentado == "enviar_correo", (
            f"tool_call_intentado debe ser 'enviar_correo', fue: {result.tool_call_intentado}"
        )
        assert result.session_id == session_id, (
            f"session_id debe ser '{session_id}', fue: {result.session_id}"
        )
        assert result.estado_pipefy == estado_pipefy, (
            f"estado_pipefy debe ser '{estado_pipefy}', fue: {result.estado_pipefy}"
        )
        assert result.timestamp != "", (
            "El timestamp del bloqueo no puede estar vacío."
        )

    @given(
        session_id=_st_session_id,
        estado_pipefy=_st_estado_pipefy,
    )
    @settings(
        max_examples=50,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_permite_descuento_5_porciento_autorizado(
        self,
        session_id: str,
        estado_pipefy: str,
    ) -> None:
        """
        Contraejemplo: el guardrail NO debe bloquear cuando el descuento
        es exactamente 5% (0.05). Esto verifica que no hay falsos positivos.
        """
        guardrail = PolicyGuardrail()

        # Parámetro explícito con descuento = 0.05 (5%)
        params = {"descuento": DESCUENTO_PRE_VENCIMIENTO}
        session_state = {
            "session_id": session_id,
            "estado_pipefy": estado_pipefy,
        }

        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params=params,
            session_state=session_state,
        )

        assert result.bloqueado is False, (
            f"El guardrail bloqueó INCORRECTAMENTE el descuento autorizado de 5%.\n"
            f"Motivo: {result.motivo_bloqueo}\n"
            f"Session: {session_id}, Estado: {estado_pipefy}"
        )

    @given(
        session_id=_st_session_id,
        estado_pipefy=_st_estado_pipefy,
    )
    @settings(
        max_examples=50,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_permite_correo_con_5_porciento_en_cuerpo(
        self,
        session_id: str,
        estado_pipefy: str,
    ) -> None:
        """
        Contraejemplo: un correo que menciona 5% en el cuerpo NO debe
        ser bloqueado. Solo se bloquean porcentajes distintos al 5%.
        """
        guardrail = PolicyGuardrail()

        mensajes_validos = [
            "Le ofrecemos un descuento del 5% por renovar antes del vencimiento.",
            "Aprovecha el 5% de descuento disponible en tu póliza.",
            "5 por ciento de bonificación por pronto pago.",
            "Descuento especial de 5porciento incluido en la cotización.",
        ]

        for cuerpo in mensajes_validos:
            params = {"cuerpo": cuerpo}
            session_state = {
                "session_id": session_id,
                "estado_pipefy": estado_pipefy,
            }

            result = guardrail.validar_tool_call(
                tool_name="enviar_correo",
                params=params,
                session_state=session_state,
            )

            assert result.bloqueado is False, (
                f"El guardrail bloqueó INCORRECTAMENTE un correo con 5% autorizado.\n"
                f"Cuerpo: '{cuerpo}'\n"
                f"Motivo: {result.motivo_bloqueo}"
            )

    @given(
        descuento_str=st.sampled_from([
            "veinte", "mucho", "el máximo posible", "gratis",
            "abc", "null", "undefined", "",
        ]),
        tool_name=_st_tool_name,
        session_id=_st_session_id,
        estado_pipefy=_st_estado_pipefy,
    )
    @settings(
        max_examples=50,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_bloquea_descuento_no_numerico(
        self,
        descuento_str: str,
        tool_name: str,
        session_id: str,
        estado_pipefy: str,
    ) -> None:
        """
        Req 9.1 — Tool calls con parámetro 'descuento' que no puede
        parsearse como número deben ser bloqueados también, ya que no
        se puede verificar que correspondan al 5% autorizado.

        Nota: Se excluyen valores como "NaN" e "inf" que Python parsea como
        float especiales; estos son manejados por la comparación numérica.
        """
        guardrail = PolicyGuardrail()

        params = {"descuento": descuento_str}
        session_state = {
            "session_id": session_id,
            "estado_pipefy": estado_pipefy,
        }

        result = guardrail.validar_tool_call(
            tool_name=tool_name,
            params=params,
            session_state=session_state,
        )

        assert result.bloqueado is True, (
            f"El guardrail NO bloqueó un descuento no numérico: '{descuento_str}'.\n"
            f"Valores no numéricos no pueden validarse como 5% y deben bloquearse.\n"
            f"Tool: {tool_name}"
        )
