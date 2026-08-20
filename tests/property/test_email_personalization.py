"""
Property-Based Test — Propiedad 5: Personalización del correo con datos del payload.

Feature: agente-comercial-polizas
Property 5: Personalización del correo con datos del payload

**Validates: Requirements 2.1**

Para 100 payloads válidos generados aleatoriamente, verificar que el cuerpo del
correo de contacto inicial contiene los valores exactos de:
- `cliente_nombre`
- `equipo_nombre`
- `fecha_vencimiento` (formato ISO 8601)
- `precio_renovacion` (formateado con 2 decimales y "MXN")
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.flows.contacto_inicial import enviar_contacto_inicial
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.data_models import ActivationPayload, SessionState


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Campos de texto no vacíos (simulan nombres de clientes y equipos reales)
_st_texto_no_vacio = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: bool(s.strip()))

# Precio de renovación positivo en rango realista
_st_precio_positivo = st.floats(
    min_value=1000.0,
    max_value=500_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Fechas: rango amplio para cubrir pre y post vencimiento
_st_fecha = st.dates(
    min_value=date(2000, 1, 1),
    max_value=date(2030, 12, 31),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crear_session_state(poliza_id: str = "POL-PROP5") -> SessionState:
    """Crea un SessionState válido para el flujo de contacto inicial."""
    return SessionState(
        session_id="test-session-prop5",
        poliza_id=poliza_id,
        estado_pipefy="Póliza detectada",
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )


def _crear_mock_kb_client() -> MagicMock:
    """Crea un KBClient mock que retorna score >= 0.70."""
    kb = MagicMock(spec=KBClient)
    kb.query.return_value = KBQueryResponse(
        results=[
            KBResult(
                content="Plantilla de contacto inicial aprobada por CIME...",
                score=0.85,
                source_uri="s3://cime-kb/plantillas_mensajes.md",
            )
        ],
        query_text="plantilla contacto inicial",
    )
    return kb


# ===========================================================================
# PROPERTY TEST — Propiedad 5: Personalización del correo con datos del payload
# ===========================================================================


class TestProperty5PersonalizacionCorreo:
    """
    Feature: agente-comercial-polizas
    Property 5: Personalización del correo con datos del payload

    **Validates: Requirements 2.1**

    Para 100 payloads válidos generados aleatoriamente, verificar que el cuerpo
    del correo de contacto inicial contiene los valores exactos de
    `cliente_nombre`, `equipo_nombre`, `fecha_vencimiento` (ISO 8601) y
    `precio_renovacion` (con 2 decimales y "MXN").
    """

    @given(
        cliente_nombre=_st_texto_no_vacio,
        equipo_nombre=_st_texto_no_vacio,
        precio=_st_precio_positivo,
        fecha=_st_fecha,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_correo_contiene_datos_personalizados_del_payload(
        self,
        mock_enviar_correo: MagicMock,
        mock_actualizar_pipefy: MagicMock,
        cliente_nombre: str,
        equipo_nombre: str,
        precio: float,
        fecha: date,
    ) -> None:
        """
        Req 2.1 — El correo de contacto inicial DEBE contener los datos
        personalizados del payload: nombre del cliente, nombre del equipo,
        fecha de vencimiento (ISO 8601) y precio de renovación formateado
        con 2 decimales y moneda MXN.
        """
        # Configurar mock de enviar_correo para capturar el cuerpo
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-prop5", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        payload = ActivationPayload(
            poliza_id="POL-PROP5-TEST",
            cliente_nombre=cliente_nombre,
            cliente_email="test@example.com",
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
        )

        session_state = _crear_session_state()
        kb_client = _crear_mock_kb_client()

        # Ejecutar flujo de contacto inicial
        result = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload,
            kb_client=kb_client,
        )

        # El correo debe haberse enviado exitosamente
        assert result["success"] is True, (
            f"enviar_contacto_inicial debería tener success=True pero fue {result}"
        )

        # Extraer cuerpo del correo enviado
        call_args = mock_enviar_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo", "")

        # --- Dato personalizado 1: cliente_nombre ---
        assert cliente_nombre in cuerpo, (
            f"El cuerpo del correo debe contener el nombre del cliente "
            f"'{cliente_nombre}' pero no se encontró.\n"
            f"Cuerpo (primeros 500): {cuerpo[:500]}"
        )

        # --- Dato personalizado 2: equipo_nombre ---
        assert equipo_nombre in cuerpo, (
            f"El cuerpo del correo debe contener el nombre del equipo "
            f"'{equipo_nombre}' pero no se encontró.\n"
            f"Cuerpo (primeros 500): {cuerpo[:500]}"
        )

        # --- Dato personalizado 3: fecha_vencimiento (ISO 8601) ---
        fecha_iso = fecha.isoformat()
        assert fecha_iso in cuerpo, (
            f"El cuerpo del correo debe contener la fecha de vencimiento "
            f"'{fecha_iso}' en formato ISO 8601 pero no se encontró.\n"
            f"Cuerpo (primeros 500): {cuerpo[:500]}"
        )

        # --- Dato personalizado 4: precio_renovacion (2 decimales + MXN) ---
        precio_formateado = f"{precio:,.2f} MXN"
        assert precio_formateado in cuerpo, (
            f"El cuerpo del correo debe contener el precio de renovación "
            f"'{precio_formateado}' (2 decimales + MXN) pero no se encontró.\n"
            f"Cuerpo (primeros 500): {cuerpo[:500]}"
        )
