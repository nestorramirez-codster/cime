"""
Property-Based Test — Propiedad 14: Escalamiento inmediato por discrepancia de datos.

Feature: agente-comercial-polizas
Property 14: Escalamiento inmediato por discrepancia de datos

**Validates: Requisito 6.7**

Para 100 pares (payload_activacion, datos_pipefy) con discrepancias en
precio >1%, nombre o fecha, verificar que el agente SIEMPRE invoca
`escalar_humano` y NUNCA invoca `enviar_correo`.

La detección de discrepancias entre el payload de Zapier y el estado actual
en Pipefy es un mecanismo de seguridad: si los datos no coinciden, el agente
debe escalar inmediatamente sin enviar comunicaciones al cliente.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.session import iniciar_sesion
from src.models.constants import ESTADOS_BLOQUEANTES, ESTADOS_VALIDOS_PIPEFY
from src.models.data_models import ActivationPayload, PipelineCard


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Estados no bloqueantes (para que el flujo llegue a la detección de discrepancias)
_ESTADOS_NO_BLOQUEANTES = sorted(ESTADOS_VALIDOS_PIPEFY - ESTADOS_BLOQUEANTES)
_st_estado_no_bloqueante = st.sampled_from(_ESTADOS_NO_BLOQUEANTES)

# Precios válidos (> 0)
_st_precio = st.floats(min_value=1000.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)

# Nombres de clientes no vacíos
_st_nombre = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"), whitelist_characters=".-"),
    min_size=3,
    max_size=50,
).filter(lambda s: bool(s.strip()))

# Emails válidos con formato simple
_st_email = st.from_regex(r"[a-z]{3,10}@[a-z]{3,8}\.(com|mx|net)", fullmatch=True)

# Fechas de vencimiento futuras
_st_fecha = st.dates(min_value=date(2025, 1, 1), max_value=date(2030, 12, 31))

# Nombres de equipo
_st_equipo = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"), whitelist_characters="-"),
    min_size=5,
    max_size=40,
).filter(lambda s: bool(s.strip()))

# Póliza IDs
_st_poliza_id = st.from_regex(r"POL-20[0-9]{2}-[0-9]{3,5}", fullmatch=True)

# Session IDs
_st_session_id = st.from_regex(r"sess-[a-z0-9]{6,12}", fullmatch=True)

# Tipo de discrepancia a inyectar
_st_tipo_discrepancia = st.sampled_from(["precio", "nombre", "fecha"])


# ---------------------------------------------------------------------------
# Estrategia: generar par (payload, card) con discrepancia garantizada
# ---------------------------------------------------------------------------

@st.composite
def _st_par_con_discrepancia(draw):
    """
    Genera un par (ActivationPayload, PipelineCard) con al menos una discrepancia
    garantizada en precio (>1%), nombre o fecha.
    """
    tipo = draw(_st_tipo_discrepancia)

    poliza_id = draw(_st_poliza_id)
    nombre_payload = draw(_st_nombre)
    email = draw(_st_email)
    fecha_payload = draw(_st_fecha)
    precio_payload = draw(_st_precio)
    equipo = draw(_st_equipo)
    estado_card = draw(_st_estado_no_bloqueante)

    # Iniciar con datos iguales
    nombre_card = nombre_payload
    fecha_card = fecha_payload
    precio_card = precio_payload

    # Inyectar discrepancia según tipo
    if tipo == "precio":
        # Diferencia > 1%: multiplicar por factor entre 1.02 y 2.0
        factor = draw(st.floats(min_value=1.02, max_value=2.0, allow_nan=False, allow_infinity=False))
        precio_card = precio_payload * factor
    elif tipo == "nombre":
        # Nombre completamente diferente
        nombre_card = draw(_st_nombre.filter(lambda n: n.strip().lower() != nombre_payload.strip().lower()))
    elif tipo == "fecha":
        # Fecha diferente (al menos 1 día de diferencia)
        offset_days = draw(st.integers(min_value=1, max_value=365))
        fecha_card = fecha_payload + timedelta(days=offset_days)

    payload = ActivationPayload(
        poliza_id=poliza_id,
        cliente_nombre=nombre_payload,
        cliente_email=email,
        fecha_vencimiento=fecha_payload,
        precio_renovacion=precio_payload,
        equipo_nombre=equipo,
    )

    card = PipelineCard(
        poliza_id=poliza_id,
        estado_actual=estado_card,
        cliente_nombre=nombre_card,
        cliente_email=email,
        fecha_vencimiento=fecha_card,
        precio_renovacion=precio_card,
        equipo_nombre=equipo,
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=[],
    )

    return payload, card


# ===========================================================================
# PROPERTY TEST — Propiedad 14: Escalamiento por discrepancia de datos
# ===========================================================================


class TestProperty14EscalamientoDiscrepanciaDatos:
    """
    Feature: agente-comercial-polizas
    Property 14: Escalamiento inmediato por discrepancia de datos

    **Validates: Requisito 6.7**

    Para 100 pares (payload_activacion, datos_pipefy) con discrepancias en
    precio >1%, nombre o fecha, verificar que el agente SIEMPRE invoca
    `escalar_humano` y NUNCA invoca `enviar_correo`.
    """

    @given(
        par=_st_par_con_discrepancia(),
        session_id=_st_session_id,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.escalar_humano")
    @patch("src.agent.session.consultar_pipefy")
    def test_discrepancia_siempre_escala_y_nunca_envia_correo(
        self,
        mock_consultar: MagicMock,
        mock_escalar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        par: tuple,
        session_id: str,
    ) -> None:
        """
        Req 6.7 — Para cualquier par (payload, card) con discrepancia garantizada:
        1. escalar_humano SIEMPRE es invocado
        2. enviar_correo NUNCA es invocado (no se mockea, verificamos que
           actualizar_pipefy NO se llama, lo que indica que el flujo se detuvo)
        3. El resultado es success=False con reason='discrepancia_datos'
        """
        payload, card = par

        mock_consultar.return_value = card
        mock_escalar.return_value = True

        resultado = iniciar_sesion(payload, session_id)

        # --- Propiedad 1: El agente SIEMPRE escala ---
        assert mock_escalar.called, (
            f"escalar_humano NO fue invocado a pesar de discrepancia.\n"
            f"Payload precio={payload.precio_renovacion}, "
            f"Card precio={card.precio_renovacion}\n"
            f"Payload nombre='{payload.cliente_nombre}', "
            f"Card nombre='{card.cliente_nombre}'\n"
            f"Payload fecha={payload.fecha_vencimiento}, "
            f"Card fecha={card.fecha_vencimiento}"
        )

        # --- Propiedad 2: NUNCA se envía correo (el flujo se detiene antes) ---
        # actualizar_pipefy a "Póliza detectada" NO debe llamarse (eso indica
        # que el flujo NO continuó hacia el envío de correo)
        mock_actualizar.assert_not_called()

        # --- Propiedad 3: El resultado indica discrepancia ---
        assert resultado["success"] is False, (
            f"Se esperaba success=False por discrepancia, pero fue True.\n"
            f"Resultado: {resultado}"
        )
        assert resultado["reason"] == "discrepancia_datos", (
            f"Se esperaba reason='discrepancia_datos', "
            f"pero fue '{resultado.get('reason')}'.\n"
            f"Resultado: {resultado}"
        )

    @given(
        par=_st_par_con_discrepancia(),
        session_id=_st_session_id,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.escalar_humano")
    @patch("src.agent.session.consultar_pipefy")
    def test_escalamiento_incluye_motivo_no_vacio(
        self,
        mock_consultar: MagicMock,
        mock_escalar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        par: tuple,
        session_id: str,
    ) -> None:
        """
        Req 6.7 — Cuando se escala por discrepancia, el motivo describe
        la discrepancia y no está vacío.
        """
        payload, card = par

        mock_consultar.return_value = card
        mock_escalar.return_value = True

        iniciar_sesion(payload, session_id)

        # Verificar que se llamó con un motivo descriptivo
        if mock_escalar.called:
            call_kwargs = mock_escalar.call_args[1]
            motivo = call_kwargs["motivo"]
            assert motivo and len(motivo.strip()) > 0, (
                "El motivo de escalamiento por discrepancia está vacío."
            )
            assert "Discrepancia" in motivo or "discrepancia" in motivo.lower(), (
                f"El motivo '{motivo}' no menciona la discrepancia."
            )
