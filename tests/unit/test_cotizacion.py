"""
Tests unitarios para el flujo de generación y envío de cotización.

Cubre:
- Cotización con descuento (pre-vencimiento)
- Cotización sin descuento (post-vencimiento)
- Estado != "Cliente interesado" → rechazo
- KB sin precio → escalamiento
- Aritmética correcta: precio_final == round(precio_base * 0.95, 2)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.agent.flows.cotizacion import (
    DATOS_BANCARIOS,
    PERIODO_MESES,
    _calcular_precio_final,
    _construir_cuerpo_cotizacion,
    _formatear_precio,
    generar_cotizacion,
)
from src.config.kb_client import KBQueryResponse, KBResult
from src.models.constants import DESCUENTO_PRE_VENCIMIENTO
from src.models.data_models import ActivationPayload, SessionState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_payload(
    fecha_vencimiento: date | None = None,
    precio_renovacion: float = 45000.00,
) -> ActivationPayload:
    """Crea un payload de prueba."""
    if fecha_vencimiento is None:
        # Default: 30 días en el futuro (pre-vencimiento)
        from datetime import timedelta

        fecha_vencimiento = date.today() + timedelta(days=30)

    return ActivationPayload(
        poliza_id="POL-TEST-001",
        cliente_nombre="Empresa Test S.A. de C.V.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=fecha_vencimiento,
        precio_renovacion=precio_renovacion,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


def _make_session_state(
    estado_pipefy: str = "Cliente interesado",
) -> SessionState:
    """Crea un session state de prueba."""
    return SessionState(
        session_id="sess-test-001",
        poliza_id="POL-TEST-001",
        estado_pipefy=estado_pipefy,
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )


def _make_kb_client(top_score: float = 0.85) -> MagicMock:
    """Crea un KBClient mock con score configurable."""
    kb_client = MagicMock()
    kb_response = KBQueryResponse(
        results=[
            KBResult(
                content="[Mock content: catálogo de precios]",
                score=top_score,
                source_uri="s3://mock-bucket/catalogo_precios.json",
            )
        ],
        query_text="precio catálogo equipo UPS",
    )
    kb_client.query.return_value = kb_response
    return kb_client


# ---------------------------------------------------------------------------
# Tests: _calcular_precio_final
# ---------------------------------------------------------------------------


class TestCalcularPrecioFinal:
    """Tests para la función _calcular_precio_final."""

    def test_con_descuento_precio_estandar(self):
        """Precio 45000 con descuento → 42750.00"""
        resultado = _calcular_precio_final(45000.00, aplica_descuento=True)
        assert resultado == 42750.00

    def test_sin_descuento_precio_sin_cambio(self):
        """Sin descuento, el precio no cambia."""
        resultado = _calcular_precio_final(45000.00, aplica_descuento=False)
        assert resultado == 45000.00

    def test_con_descuento_precision_dos_decimales(self):
        """Verifica que el redondeo a 2 decimales funciona correctamente."""
        # 33333.33 * 0.95 = 31666.6635 → round → 31666.66
        resultado = _calcular_precio_final(33333.33, aplica_descuento=True)
        assert resultado == round(33333.33 * 0.95, 2)

    def test_con_descuento_formula_exacta(self):
        """precio_final == round(precio_base * 0.95, 2)"""
        precios = [1000.0, 15000.50, 45000.00, 99999.99, 250000.75]
        for precio_base in precios:
            esperado = round(precio_base * (1 - DESCUENTO_PRE_VENCIMIENTO), 2)
            resultado = _calcular_precio_final(precio_base, aplica_descuento=True)
            assert resultado == esperado, (
                f"Para precio_base={precio_base}: "
                f"esperado={esperado}, obtenido={resultado}"
            )

    def test_sin_descuento_no_modifica(self):
        """Sin descuento, retorna el mismo valor exacto."""
        precios = [1000.0, 15000.50, 45000.00, 99999.99, 250000.75]
        for precio_base in precios:
            resultado = _calcular_precio_final(precio_base, aplica_descuento=False)
            assert resultado == precio_base


# ---------------------------------------------------------------------------
# Tests: _formatear_precio
# ---------------------------------------------------------------------------


class TestFormatearPrecio:
    """Tests para la función _formatear_precio."""

    def test_formato_con_miles(self):
        assert _formatear_precio(45000.00) == "45,000.00 MXN"

    def test_formato_centavos(self):
        assert _formatear_precio(1234.56) == "1,234.56 MXN"

    def test_formato_millones(self):
        assert _formatear_precio(1500000.00) == "1,500,000.00 MXN"


# ---------------------------------------------------------------------------
# Tests: generar_cotizacion — flujo exitoso con descuento
# ---------------------------------------------------------------------------


class TestGenerarCotizacionConDescuento:
    """Cotización con descuento pre-vencimiento."""

    @patch("src.agent.flows.cotizacion.actualizar_pipefy")
    @patch("src.agent.flows.cotizacion.enviar_correo")
    def test_cotizacion_pre_vencimiento_aplica_descuento(
        self, mock_enviar, mock_actualizar
    ):
        """Cuando la póliza no ha vencido, se aplica el 5% de descuento."""
        from datetime import timedelta

        mock_enviar.return_value = MagicMock(
            success=True,
            message_id="msg-123",
            timestamp=datetime.now(timezone.utc),
        )
        mock_actualizar.return_value = True

        fecha_futura = date.today() + timedelta(days=30)
        payload = _make_payload(fecha_vencimiento=fecha_futura, precio_renovacion=50000.00)
        session = _make_session_state(estado_pipefy="Cliente interesado")
        kb_client = _make_kb_client(top_score=0.85)

        resultado = generar_cotizacion(session, payload, kb_client)

        assert resultado["success"] is True
        assert resultado["aplica_descuento"] is True
        assert resultado["precio_base"] == 50000.00
        assert resultado["precio_final"] == round(50000.00 * 0.95, 2)

        # Verificar que enviar_correo fue llamado
        mock_enviar.assert_called_once()
        cuerpo = mock_enviar.call_args.kwargs["cuerpo"]
        assert "Descuento por renovación anticipada: 5%" in cuerpo
        assert DATOS_BANCARIOS in cuerpo

        # Verificar que se actualizó a "Depósito solicitado"
        mock_actualizar.assert_called_once()
        assert mock_actualizar.call_args.kwargs["estado"] == "Depósito solicitado"


# ---------------------------------------------------------------------------
# Tests: generar_cotizacion — flujo exitoso sin descuento
# ---------------------------------------------------------------------------


class TestGenerarCotizacionSinDescuento:
    """Cotización sin descuento (post-vencimiento)."""

    @patch("src.agent.flows.cotizacion.actualizar_pipefy")
    @patch("src.agent.flows.cotizacion.enviar_correo")
    def test_cotizacion_post_vencimiento_sin_descuento(
        self, mock_enviar, mock_actualizar
    ):
        """Cuando la póliza ya venció, no se aplica descuento."""
        from datetime import timedelta

        mock_enviar.return_value = MagicMock(
            success=True,
            message_id="msg-456",
            timestamp=datetime.now(timezone.utc),
        )
        mock_actualizar.return_value = True

        fecha_pasada = date.today() - timedelta(days=10)
        payload = _make_payload(fecha_vencimiento=fecha_pasada, precio_renovacion=45000.00)
        session = _make_session_state(estado_pipefy="Cliente interesado")
        kb_client = _make_kb_client(top_score=0.90)

        resultado = generar_cotizacion(session, payload, kb_client)

        assert resultado["success"] is True
        assert resultado["aplica_descuento"] is False
        assert resultado["precio_base"] == 45000.00
        assert resultado["precio_final"] == 45000.00

        # Verificar que el cuerpo NO menciona descuento
        cuerpo = mock_enviar.call_args.kwargs["cuerpo"]
        assert "Descuento por renovación anticipada" not in cuerpo


# ---------------------------------------------------------------------------
# Tests: generar_cotizacion — estado no permitido
# ---------------------------------------------------------------------------


class TestGenerarCotizacionEstadoInvalido:
    """Estado != 'Cliente interesado' → rechazo sin envío."""

    def test_estado_contacto_inicial_rechaza(self):
        """Estado 'Contacto inicial enviado' no permite cotización."""
        payload = _make_payload()
        session = _make_session_state(estado_pipefy="Contacto inicial enviado")
        kb_client = _make_kb_client()

        resultado = generar_cotizacion(session, payload, kb_client)

        assert resultado["success"] is False
        assert "Cliente interesado" in resultado["motivo"]
        # KB no debería haberse consultado
        kb_client.query.assert_not_called()

    def test_estado_deposito_solicitado_rechaza(self):
        """Estado 'Depósito solicitado' no permite nueva cotización."""
        payload = _make_payload()
        session = _make_session_state(estado_pipefy="Depósito solicitado")
        kb_client = _make_kb_client()

        resultado = generar_cotizacion(session, payload, kb_client)

        assert resultado["success"] is False
        assert "Cliente interesado" in resultado["motivo"]

    def test_estado_seguimiento_rechaza(self):
        """Estado 'Seguimiento en curso' no permite cotización."""
        payload = _make_payload()
        session = _make_session_state(estado_pipefy="Seguimiento en curso")
        kb_client = _make_kb_client()

        resultado = generar_cotizacion(session, payload, kb_client)

        assert resultado["success"] is False


# ---------------------------------------------------------------------------
# Tests: generar_cotizacion — KB sin precio → escalamiento
# ---------------------------------------------------------------------------


class TestGenerarCotizacionKBSinPrecio:
    """KB no tiene precio en catálogo → escalar a humano."""

    @patch("src.agent.flows.cotizacion.escalar_humano")
    def test_kb_score_bajo_escala_a_humano(self, mock_escalar):
        """Score < 0.70 → invoca escalar_humano."""
        mock_escalar.return_value = True

        payload = _make_payload()
        session = _make_session_state(estado_pipefy="Cliente interesado")
        kb_client = _make_kb_client(top_score=0.45)  # Score bajo

        resultado = generar_cotizacion(session, payload, kb_client)

        assert resultado["success"] is False
        assert "KB score insuficiente" in resultado["motivo"]
        mock_escalar.assert_called_once()

        # Verificar que el motivo del escalamiento es descriptivo
        call_kwargs = mock_escalar.call_args.kwargs
        assert "Catálogo de precios sin resultado relevante" in call_kwargs["motivo"]
        assert payload.equipo_nombre in call_kwargs["motivo"]

    @patch("src.agent.flows.cotizacion.escalar_humano")
    def test_kb_score_exacto_070_no_escala(self, mock_escalar):
        """Score == 0.70 → NO escala (umbral inclusivo)."""
        payload = _make_payload()
        session = _make_session_state(estado_pipefy="Cliente interesado")
        kb_client = _make_kb_client(top_score=0.70)

        with patch("src.agent.flows.cotizacion.enviar_correo") as mock_enviar, \
             patch("src.agent.flows.cotizacion.actualizar_pipefy") as mock_actualizar:
            mock_enviar.return_value = MagicMock(
                success=True,
                message_id="msg-789",
                timestamp=datetime.now(timezone.utc),
            )
            mock_actualizar.return_value = True

            resultado = generar_cotizacion(session, payload, kb_client)

        assert resultado["success"] is True
        mock_escalar.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: aritmética de descuento
# ---------------------------------------------------------------------------


class TestAritmeticaDescuento:
    """Verifica la aritmética exacta: precio_final == round(precio_base * 0.95, 2)."""

    @pytest.mark.parametrize(
        "precio_base",
        [1000.00, 12345.67, 33333.33, 45000.00, 99999.99, 150000.50, 500000.00],
    )
    def test_descuento_exacto(self, precio_base: float):
        """Para cada precio base, el descuento aplica correctamente."""
        esperado = round(precio_base * 0.95, 2)
        resultado = _calcular_precio_final(precio_base, aplica_descuento=True)
        assert resultado == esperado

    @pytest.mark.parametrize(
        "precio_base",
        [1000.00, 12345.67, 33333.33, 45000.00, 99999.99, 150000.50, 500000.00],
    )
    def test_sin_descuento_identidad(self, precio_base: float):
        """Sin descuento, el precio se mantiene idéntico."""
        resultado = _calcular_precio_final(precio_base, aplica_descuento=False)
        assert resultado == precio_base


# ---------------------------------------------------------------------------
# Tests: _construir_cuerpo_cotizacion
# ---------------------------------------------------------------------------


class TestConstruirCuerpoCotizacion:
    """Tests para la generación del cuerpo del correo de cotización."""

    def test_contiene_campos_obligatorios(self):
        """El cuerpo incluye nombre, equipo, período, precio_base, precio_final, datos bancarios."""
        from datetime import timedelta

        payload = _make_payload(
            fecha_vencimiento=date.today() + timedelta(days=30),
            precio_renovacion=45000.00,
        )
        cuerpo = _construir_cuerpo_cotizacion(
            payload=payload,
            precio_base=45000.00,
            precio_final=42750.00,
            aplica_descuento=True,
            datos_bancarios=DATOS_BANCARIOS,
        )

        assert payload.cliente_nombre in cuerpo
        assert payload.equipo_nombre in cuerpo
        assert f"{PERIODO_MESES} meses" in cuerpo
        assert "45,000.00 MXN" in cuerpo
        assert "42,750.00 MXN" in cuerpo
        assert DATOS_BANCARIOS in cuerpo

    def test_sin_datos_bancarios_no_incluye(self):
        """Si datos_bancarios=None, no se incluyen en el cuerpo."""
        from datetime import timedelta

        payload = _make_payload(
            fecha_vencimiento=date.today() - timedelta(days=5),
            precio_renovacion=30000.00,
        )
        cuerpo = _construir_cuerpo_cotizacion(
            payload=payload,
            precio_base=30000.00,
            precio_final=30000.00,
            aplica_descuento=False,
            datos_bancarios=None,
        )

        assert "BBVA" not in cuerpo
        assert "CLABE" not in cuerpo

    def test_descuento_aparece_solo_cuando_aplica(self):
        """La mención de descuento solo aparece si aplica_descuento=True."""
        from datetime import timedelta

        payload = _make_payload(fecha_vencimiento=date.today() + timedelta(days=30))

        cuerpo_con = _construir_cuerpo_cotizacion(
            payload=payload,
            precio_base=45000.00,
            precio_final=42750.00,
            aplica_descuento=True,
            datos_bancarios=DATOS_BANCARIOS,
        )
        assert "Descuento por renovación anticipada" in cuerpo_con

        cuerpo_sin = _construir_cuerpo_cotizacion(
            payload=payload,
            precio_base=45000.00,
            precio_final=45000.00,
            aplica_descuento=False,
            datos_bancarios=DATOS_BANCARIOS,
        )
        assert "Descuento por renovación anticipada" not in cuerpo_sin
