"""
Property-Based Tests — Propiedad 3: Consistencia de contenido pre/post vencimiento (metamórfica).

Feature: agente-comercial-polizas
Property 3: Consistencia de contenido pre/post vencimiento

**Validates: Requirements 2.3, 2.4**

Estrategia metamórfica:
- Fecha futura (pre-vencimiento)  → cuerpo del correo DEBE contener mención de descuento 3%
- Fecha pasada (post-vencimiento) → cuerpo del correo NO DEBE contener mención de descuento 3%

Se ejercita `enviar_contacto_inicial` con mocks de enviar_correo y actualizar_pipefy,
inyectando un mock_kb_client con score >= 0.70 para que el flujo llegue a generar el correo.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.flows.contacto_inicial import enviar_contacto_inicial
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.data_models import ActivationPayload, SessionState


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Fechas futuras: pre-vencimiento (fecha_vencimiento > hoy)
_st_fecha_futura = st.dates(
    min_value=date.today() + timedelta(days=1),
    max_value=date(2030, 12, 31),
)

# Fechas pasadas: post-vencimiento (fecha_vencimiento <= hoy)
_st_fecha_pasada = st.dates(
    min_value=date(2000, 1, 1),
    max_value=date.today(),
)

# Campos de texto no vacíos para el payload
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
    min_value=1.0,
    max_value=500_000.0,
    allow_nan=False,
    allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crear_session_state() -> SessionState:
    """Crea un SessionState de prueba para las propiedades."""
    return SessionState(
        session_id="test-session-prop3",
        poliza_id="POL-PROP-TEST",
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
                content="Plantilla de contacto inicial...",
                score=0.85,
                source_uri="s3://cime-kb/plantillas_mensajes.md",
            )
        ],
        query_text="plantilla",
    )
    return kb


# ===========================================================================
# PROPERTY TESTS — Propiedad 3
# ===========================================================================


class TestProperty3ConsistenciaPrePostVencimiento:
    """
    Feature: agente-comercial-polizas
    Property 3: Consistencia de contenido pre/post vencimiento (metamórfica)

    **Validates: Requirements 2.3, 2.4**
    """

    # -----------------------------------------------------------------------
    # Pre-vencimiento: fecha futura → correo DEBE contener mención de 3%
    # -----------------------------------------------------------------------

    @given(
        fecha=_st_fecha_futura,
        nombre=_st_texto_no_vacio,
        equipo=_st_texto_no_vacio,
        precio=_st_precio_positivo,
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_pre_vencimiento_incluye_descuento_3_porciento(
        self,
        mock_enviar_correo: MagicMock,
        mock_actualizar_pipefy: MagicMock,
        fecha: date,
        nombre: str,
        equipo: str,
        precio: float,
    ) -> None:
        """
        Req 2.3 — Para cualquier fecha futura (pre-vencimiento), el cuerpo
        del correo de contacto inicial DEBE contener mención del 3% de descuento.
        """
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-prop3-pre", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        payload = ActivationPayload(
            poliza_id="POL-PROP3-PRE",
            cliente_nombre=nombre,
            cliente_email="test@example.com",
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo,
        )

        session_state = _crear_session_state()
        kb_client = _crear_mock_kb_client()

        result = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload,
            kb_client=kb_client,
        )

        assert result["success"] is True
        assert result["pre_vencimiento"] is True

        # Extraer el cuerpo del correo enviado
        call_args = mock_enviar_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo", "")

        assert "3%" in cuerpo, (
            f"Pre-vencimiento (fecha={fecha}): el cuerpo del correo debe "
            f"contener '3%' pero no lo contiene.\nCuerpo: {cuerpo[:200]}"
        )
        assert "descuento" in cuerpo.lower(), (
            f"Pre-vencimiento (fecha={fecha}): el cuerpo del correo debe "
            f"contener 'descuento' pero no lo contiene.\nCuerpo: {cuerpo[:200]}"
        )

    # -----------------------------------------------------------------------
    # Post-vencimiento: fecha pasada → correo NO DEBE contener mención de 3%
    # -----------------------------------------------------------------------

    @given(
        fecha=_st_fecha_pasada,
        nombre=_st_texto_no_vacio,
        equipo=_st_texto_no_vacio,
        precio=_st_precio_positivo,
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_post_vencimiento_excluye_descuento_3_porciento(
        self,
        mock_enviar_correo: MagicMock,
        mock_actualizar_pipefy: MagicMock,
        fecha: date,
        nombre: str,
        equipo: str,
        precio: float,
    ) -> None:
        """
        Req 2.4 — Para cualquier fecha pasada o de hoy (post-vencimiento), el cuerpo
        del correo de contacto inicial NO DEBE contener mención del 3% de descuento.
        """
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-prop3-post", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        payload = ActivationPayload(
            poliza_id="POL-PROP3-POST",
            cliente_nombre=nombre,
            cliente_email="test@example.com",
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo,
        )

        session_state = _crear_session_state()
        kb_client = _crear_mock_kb_client()

        result = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload,
            kb_client=kb_client,
        )

        assert result["success"] is True
        assert result["pre_vencimiento"] is False

        # Extraer el cuerpo del correo enviado
        call_args = mock_enviar_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo", "")

        assert "3%" not in cuerpo, (
            f"Post-vencimiento (fecha={fecha}): el cuerpo del correo NO debe "
            f"contener '3%' pero lo contiene.\nCuerpo: {cuerpo[:200]}"
        )
        assert "descuento" not in cuerpo.lower(), (
            f"Post-vencimiento (fecha={fecha}): el cuerpo del correo NO debe "
            f"contener 'descuento' pero lo contiene.\nCuerpo: {cuerpo[:200]}"
        )


# ===========================================================================
# PROPERTY TESTS — Propiedad 7
# ===========================================================================

from src.agent.flows.cotizacion import _calcular_precio_final
from src.models.constants import DESCUENTO_PRE_VENCIMIENTO

# Estrategia: precios base en rango $1,000–$500,000 MXN
_st_precio_base = st.floats(
    min_value=1000.0,
    max_value=500_000.0,
    allow_nan=False,
    allow_infinity=False,
)


class TestProperty7CalculoAritmeticoDescuento:
    """
    Feature: agente-comercial-polizas
    Property 7: Cálculo aritmético exacto del precio con descuento

    **Validates: Requirements 4.3**

    Verifica que _calcular_precio_final aplica correctamente el descuento
    del 5% pre-vencimiento sobre cualquier precio base en [$1,000, $500,000].
    """

    @given(precio_base=_st_precio_base)
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_con_descuento_precio_final_es_95_porciento(
        self,
        precio_base: float,
    ) -> None:
        """
        Req 4.3 — Para cualquier precio_base, cuando aplica_descuento=True:
        precio_final == round(precio_base * 0.95, 2)
        """
        resultado = _calcular_precio_final(precio_base, aplica_descuento=True)
        esperado = round(precio_base * (1 - DESCUENTO_PRE_VENCIMIENTO), 2)

        assert resultado == esperado, (
            f"Con descuento: _calcular_precio_final({precio_base}, True) = {resultado}, "
            f"esperado = {esperado}"
        )

    @given(precio_base=_st_precio_base)
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_sin_descuento_precio_final_es_precio_base(
        self,
        precio_base: float,
    ) -> None:
        """
        Req 4.3 — Para cualquier precio_base, cuando aplica_descuento=False:
        precio_final == precio_base (sin modificación)
        """
        resultado = _calcular_precio_final(precio_base, aplica_descuento=False)

        assert resultado == precio_base, (
            f"Sin descuento: _calcular_precio_final({precio_base}, False) = {resultado}, "
            f"esperado = {precio_base}"
        )
