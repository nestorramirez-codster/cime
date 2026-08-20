"""
Property-Based Test — Propiedad 9: Completitud de campos en la cotización.

Feature: agente-comercial-polizas
Property 9: Completitud de campos en la cotización

**Validates: Requirements 4.1**

Para 100 instancias de SessionState con Estado_Pipefy "Cliente interesado" y datos válidos,
verifica que la cotización generada contiene todos los campos obligatorios:
- nombre del Cliente
- nombre del equipo cubierto
- período de vigencia (12 meses)
- precio base (formateado con 2 decimales y MXN)
- precio final (formateado con 2 decimales y MXN)
- datos bancarios (ya que estado es "Cliente interesado")
- descuento (solo si pre-vencimiento)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.flows.cotizacion import generar_cotizacion
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.constants import DESCUENTO_PRE_VENCIMIENTO
from src.models.data_models import ActivationPayload, SessionState


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Campos de texto no vacíos
_st_texto_no_vacio = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: bool(s.strip()))

# Precio de renovación positivo
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


def _crear_session_state(poliza_id: str = "POL-PROP9") -> SessionState:
    """Crea un SessionState con estado 'Cliente interesado'."""
    return SessionState(
        session_id="test-session-prop9",
        poliza_id=poliza_id,
        estado_pipefy="Cliente interesado",
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )


def _crear_mock_kb_client() -> MagicMock:
    """Crea un KBClient mock que retorna score >= 0.70."""
    kb = MagicMock(spec=KBClient)
    kb.query.return_value = KBQueryResponse(
        results=[
            KBResult(
                content="Precio catálogo para equipo...",
                score=0.85,
                source_uri="s3://cime-kb/catalogo_precios.json",
            )
        ],
        query_text="precio catálogo",
    )
    return kb


# ===========================================================================
# PROPERTY TEST — Propiedad 9: Completitud de campos en la cotización
# ===========================================================================


class TestProperty9CompletitudCamposCotizacion:
    """
    Feature: agente-comercial-polizas
    Property 9: Completitud de campos en la cotización

    **Validates: Requirements 4.1**

    Para 100 instancias de SessionState con Estado_Pipefy "Cliente interesado"
    y datos válidos, verifica que la cotización generada contiene TODOS los
    campos obligatorios definidos en Req 4.1.
    """

    @given(
        cliente_nombre=_st_texto_no_vacio,
        equipo_nombre=_st_texto_no_vacio,
        precio=_st_precio_positivo,
        fecha=_st_fecha,
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.agent.flows.cotizacion.actualizar_pipefy")
    @patch("src.agent.flows.cotizacion.enviar_correo")
    @patch("src.agent.flows.cotizacion.escalar_humano")
    def test_cotizacion_contiene_todos_campos_obligatorios(
        self,
        mock_escalar: MagicMock,
        mock_enviar_correo: MagicMock,
        mock_actualizar_pipefy: MagicMock,
        cliente_nombre: str,
        equipo_nombre: str,
        precio: float,
        fecha: date,
    ) -> None:
        """
        Req 4.1 — La cotización DEBE contener: nombre del cliente, nombre del
        equipo, período de 12 meses, precio base (MXN), precio final (MXN),
        datos bancarios, y descuento si aplica (pre-vencimiento).
        """
        # Configurar mock de enviar_correo para capturar el cuerpo
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-prop9", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        payload = ActivationPayload(
            poliza_id="POL-PROP9-TEST",
            cliente_nombre=cliente_nombre,
            cliente_email="test@example.com",
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
        )

        session_state = _crear_session_state()
        kb_client = _crear_mock_kb_client()

        result = generar_cotizacion(
            session_state=session_state,
            payload=payload,
            kb_client=kb_client,
        )

        # La cotización debe haberse enviado exitosamente
        assert result["success"] is True, (
            f"generar_cotizacion debería tener success=True pero fue {result}"
        )

        # Extraer cuerpo del correo enviado
        call_args = mock_enviar_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo", "")

        # --- Campo obligatorio 1: nombre del cliente ---
        assert cliente_nombre in cuerpo, (
            f"El cuerpo debe contener el nombre del cliente '{cliente_nombre}' "
            f"pero no se encontró.\nCuerpo (primeros 300): {cuerpo[:300]}"
        )

        # --- Campo obligatorio 2: nombre del equipo ---
        assert equipo_nombre in cuerpo, (
            f"El cuerpo debe contener el nombre del equipo '{equipo_nombre}' "
            f"pero no se encontró.\nCuerpo (primeros 300): {cuerpo[:300]}"
        )

        # --- Campo obligatorio 3: período de 12 meses ---
        assert "12 meses" in cuerpo, (
            f"El cuerpo debe contener '12 meses' (período de vigencia) "
            f"pero no se encontró.\nCuerpo (primeros 300): {cuerpo[:300]}"
        )

        # --- Campo obligatorio 4: precio base (formateado MXN) ---
        precio_base_formateado = f"{precio:,.2f} MXN"
        assert precio_base_formateado in cuerpo, (
            f"El cuerpo debe contener el precio base '{precio_base_formateado}' "
            f"pero no se encontró.\nCuerpo (primeros 300): {cuerpo[:300]}"
        )

        # --- Campo obligatorio 5: precio final (formateado MXN) ---
        es_pre_vencimiento = fecha > date.today()
        if es_pre_vencimiento:
            precio_final = round(precio * (1 - DESCUENTO_PRE_VENCIMIENTO), 2)
        else:
            precio_final = precio
        precio_final_formateado = f"{precio_final:,.2f} MXN"
        assert precio_final_formateado in cuerpo, (
            f"El cuerpo debe contener el precio final '{precio_final_formateado}' "
            f"pero no se encontró.\nCuerpo (primeros 300): {cuerpo[:300]}"
        )

        # --- Campo obligatorio 6: datos bancarios ---
        # Estado "Cliente interesado" → siempre incluye datos bancarios
        assert "BBVA" in cuerpo, (
            f"El cuerpo debe contener datos bancarios (BBVA) ya que el estado "
            f"es 'Cliente interesado', pero no se encontró.\nCuerpo: {cuerpo[:300]}"
        )
        assert "CLABE" in cuerpo, (
            f"El cuerpo debe contener datos bancarios (CLABE) ya que el estado "
            f"es 'Cliente interesado', pero no se encontró.\nCuerpo: {cuerpo[:300]}"
        )

        # --- Campo obligatorio 7: descuento si aplica (pre-vencimiento) ---
        if es_pre_vencimiento:
            porcentaje_descuento = str(int(DESCUENTO_PRE_VENCIMIENTO * 100)) + "%"
            assert porcentaje_descuento in cuerpo, (
                f"Pre-vencimiento (fecha={fecha}): el cuerpo debe contener "
                f"'{porcentaje_descuento}' de descuento pero no se encontró.\n"
                f"Cuerpo (primeros 300): {cuerpo[:300]}"
            )
