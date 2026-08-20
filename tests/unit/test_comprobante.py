"""
Unit tests para el flujo de recepción y procesamiento de comprobante de pago.

Cubre:
- Validación de formato y tamaño de adjuntos (Req 5.1, 5.6)
- Flujo completo con adjunto válido (Req 5.1, 5.2, 5.3, 5.4)
- Flujo con adjunto inválido → correo de reenvío (Req 5.6)
- Orden temporal: confirmación al cliente ANTES de notificar tesorería (Req 5.3)
- Escalamiento cuando notificar_tesoreria falla (Req 5.5)
- NO validación bancaria (Req 5.7)
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

# Activar mock mode para tests
os.environ["CIME_MOCK_MODE"] = "true"

from src.agent.flows.comprobante import (
    Adjunto,
    _enviar_confirmacion_recepcion,
    _notificar_tesoreria_y_actualizar,
    _validar_formato_adjunto,
    procesar_comprobante,
)
from src.models.constants import (
    FORMATOS_COMPROBANTE_ACEPTADOS,
    TAMANIO_MAXIMO_COMPROBANTE_BYTES,
)
from src.models.data_models import (
    ActivationPayload,
    DatosPago,
    SessionState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_state():
    """SessionState de prueba."""
    return SessionState(
        session_id="sess-test-comprobante-001",
        poliza_id="POL-2024-TEST",
        estado_pipefy="Depósito solicitado",
        historial_mensajes=[],
        timestamp_inicio=datetime(2025, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def payload():
    """ActivationPayload de prueba."""
    return ActivationPayload(
        poliza_id="POL-2024-TEST",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


@pytest.fixture
def adjunto_valido():
    """Adjunto con formato y tamaño válidos."""
    return Adjunto(
        nombre_archivo="comprobante.pdf",
        tamanio_bytes=500_000,  # ~500 KB
        s3_key="adjuntos/sess-test/comprobante.pdf",
    )


@pytest.fixture
def adjunto_invalido_formato():
    """Adjunto con formato no soportado."""
    return Adjunto(
        nombre_archivo="comprobante.docx",
        tamanio_bytes=500_000,
        s3_key="adjuntos/sess-test/comprobante.docx",
    )


@pytest.fixture
def adjunto_invalido_tamanio():
    """Adjunto que excede el tamaño máximo (>10 MB)."""
    return Adjunto(
        nombre_archivo="comprobante.pdf",
        tamanio_bytes=11 * 1024 * 1024,  # 11 MB
        s3_key="adjuntos/sess-test/comprobante-grande.pdf",
    )


# ---------------------------------------------------------------------------
# Tests: _validar_formato_adjunto
# ---------------------------------------------------------------------------


class TestValidarFormatoAdjunto:
    """Tests para la función de validación de formato y tamaño."""

    @pytest.mark.parametrize(
        "nombre,esperado",
        [
            ("comprobante.pdf", True),
            ("comprobante.PDF", True),
            ("imagen.jpg", True),
            ("foto.JPG", True),
            ("captura.png", True),
            ("comprobante.PNG", True),
            ("foto.jpeg", True),
            ("foto.JPEG", True),
            ("archivo.Pdf", True),  # Mixed case
        ],
    )
    def test_formatos_validos(self, nombre: str, esperado: bool):
        """Formatos PDF, JPG, PNG, JPEG deben ser aceptados (case-insensitive)."""
        es_valido, motivo = _validar_formato_adjunto(nombre, 1000)
        assert es_valido is esperado
        assert motivo == ""

    @pytest.mark.parametrize(
        "nombre",
        [
            "comprobante.docx",
            "comprobante.xlsx",
            "comprobante.txt",
            "comprobante.gif",
            "comprobante.bmp",
            "comprobante.webp",
            "comprobante.tiff",
        ],
    )
    def test_formatos_invalidos(self, nombre: str):
        """Formatos no soportados deben ser rechazados."""
        es_valido, motivo = _validar_formato_adjunto(nombre, 1000)
        assert es_valido is False
        assert "no es soportado" in motivo

    def test_archivo_sin_extension(self):
        """Archivos sin extensión deben ser rechazados."""
        es_valido, motivo = _validar_formato_adjunto("comprobante", 1000)
        assert es_valido is False
        assert "no tiene extensión" in motivo

    def test_tamanio_exacto_10mb(self):
        """Archivo de exactamente 10 MB debe ser aceptado."""
        es_valido, motivo = _validar_formato_adjunto(
            "comprobante.pdf", TAMANIO_MAXIMO_COMPROBANTE_BYTES
        )
        assert es_valido is True

    def test_tamanio_excede_10mb(self):
        """Archivo mayor a 10 MB debe ser rechazado."""
        es_valido, motivo = _validar_formato_adjunto(
            "comprobante.pdf", TAMANIO_MAXIMO_COMPROBANTE_BYTES + 1
        )
        assert es_valido is False
        assert "excede el tamaño máximo" in motivo

    def test_tamanio_cero(self):
        """Archivo de 0 bytes con formato válido debe pasar validación."""
        es_valido, motivo = _validar_formato_adjunto("comprobante.pdf", 0)
        assert es_valido is True


# ---------------------------------------------------------------------------
# Tests: procesar_comprobante — adjunto inválido (Req 5.6)
# ---------------------------------------------------------------------------


class TestProcesarComprobanteInvalido:
    """Tests para flujo con adjunto inválido → correo de reenvío."""

    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_formato_invalido_envia_correo_reenvio(
        self, mock_enviar, session_state, payload, adjunto_invalido_formato
    ):
        """Si el formato es inválido, envía correo solicitando reenvío."""
        mock_enviar.return_value = MagicMock(success=True)

        resultado = procesar_comprobante(
            adjunto_invalido_formato, session_state, payload
        )

        assert resultado["success"] is False
        assert resultado["formato_valido"] is False
        mock_enviar.assert_called_once()

        # Verificar que el correo menciona formatos aceptados
        kwargs = mock_enviar.call_args
        cuerpo = kwargs[1]["cuerpo"] if "cuerpo" in kwargs[1] else kwargs[0][2]
        assert "PDF" in cuerpo or "formatos" in cuerpo.lower()

    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_tamanio_invalido_envia_correo_reenvio(
        self, mock_enviar, session_state, payload, adjunto_invalido_tamanio
    ):
        """Si el tamaño excede 10 MB, envía correo solicitando reenvío."""
        mock_enviar.return_value = MagicMock(success=True)

        resultado = procesar_comprobante(
            adjunto_invalido_tamanio, session_state, payload
        )

        assert resultado["success"] is False
        assert resultado["formato_valido"] is False
        mock_enviar.assert_called_once()

    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_formato_invalido_no_actualiza_pipefy(
        self,
        mock_enviar,
        mock_actualizar,
        session_state,
        payload,
        adjunto_invalido_formato,
    ):
        """Si el adjunto es inválido, NO se actualiza Pipefy."""
        mock_enviar.return_value = MagicMock(success=True)

        procesar_comprobante(adjunto_invalido_formato, session_state, payload)

        mock_actualizar.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: procesar_comprobante — adjunto válido (Req 5.1, 5.2, 5.3, 5.4)
# ---------------------------------------------------------------------------


class TestProcesarComprobanteValido:
    """Tests para flujo exitoso con adjunto válido."""

    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_flujo_completo_exitoso(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        session_state,
        payload,
        adjunto_valido,
    ):
        """Flujo completo: validar → Pipefy → confirmar → Tesorería → Pipefy."""
        mock_enviar.return_value = MagicMock(success=True)
        mock_actualizar.return_value = True
        mock_notificar.return_value = True

        resultado = procesar_comprobante(adjunto_valido, session_state, payload)

        assert resultado["success"] is True
        assert resultado["formato_valido"] is True
        assert resultado["notificacion_tesoreria"] is True
        assert resultado["escalado"] is False
        assert "timestamp_confirmacion" in resultado

    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_pipefy_actualizado_a_comprobante_recibido(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        session_state,
        payload,
        adjunto_valido,
    ):
        """Pipefy se actualiza primero a "Comprobante recibido"."""
        mock_enviar.return_value = MagicMock(success=True)
        mock_actualizar.return_value = True
        mock_notificar.return_value = True

        procesar_comprobante(adjunto_valido, session_state, payload)

        # Primera llamada a actualizar_pipefy con "Comprobante recibido"
        primera_llamada = mock_actualizar.call_args_list[0]
        assert primera_llamada[1]["estado"] == "Comprobante recibido"

    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_pipefy_actualizado_a_en_validacion(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        session_state,
        payload,
        adjunto_valido,
    ):
        """Después de notificar Tesorería, Pipefy se actualiza a 'En validación con tesorería'."""
        mock_enviar.return_value = MagicMock(success=True)
        mock_actualizar.return_value = True
        mock_notificar.return_value = True

        procesar_comprobante(adjunto_valido, session_state, payload)

        # Segunda llamada a actualizar_pipefy con "En validación con tesorería"
        segunda_llamada = mock_actualizar.call_args_list[1]
        assert segunda_llamada[1]["estado"] == "En validación con tesorería"

    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_orden_temporal_confirmacion_antes_de_tesoreria(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        session_state,
        payload,
        adjunto_valido,
    ):
        """Req 5.3: La confirmación al cliente SIEMPRE precede a notificar_tesoreria.

        Se verifica que enviar_correo se llama ANTES de notificar_tesoreria
        usando el orden de llamadas de los mocks.
        """
        call_order = []

        def track_enviar(*args, **kwargs):
            call_order.append("enviar_correo")
            return MagicMock(success=True)

        def track_actualizar(*args, **kwargs):
            call_order.append("actualizar_pipefy")
            return True

        def track_notificar(*args, **kwargs):
            call_order.append("notificar_tesoreria")
            return True

        mock_enviar.side_effect = track_enviar
        mock_actualizar.side_effect = track_actualizar
        mock_notificar.side_effect = track_notificar

        procesar_comprobante(adjunto_valido, session_state, payload)

        # enviar_correo debe aparecer ANTES de notificar_tesoreria
        idx_enviar = call_order.index("enviar_correo")
        idx_notificar = call_order.index("notificar_tesoreria")
        assert idx_enviar < idx_notificar, (
            f"Confirmación al cliente (idx={idx_enviar}) debe preceder "
            f"a notificación a Tesorería (idx={idx_notificar})"
        )

    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_datos_pago_enviados_a_tesoreria(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        session_state,
        payload,
        adjunto_valido,
    ):
        """notificar_tesoreria recibe DatosPago con todos los campos correctos."""
        mock_enviar.return_value = MagicMock(success=True)
        mock_actualizar.return_value = True
        mock_notificar.return_value = True

        procesar_comprobante(adjunto_valido, session_state, payload)

        mock_notificar.assert_called_once()
        datos_pago = mock_notificar.call_args[0][0]

        assert isinstance(datos_pago, DatosPago)
        assert datos_pago.cliente_nombre == payload.cliente_nombre
        assert datos_pago.poliza_id == payload.poliza_id
        assert datos_pago.monto == payload.precio_renovacion
        assert datos_pago.referencia_adjunto == adjunto_valido.s3_key


# ---------------------------------------------------------------------------
# Tests: Fallo en notificar_tesoreria → escalamiento (Req 5.5)
# ---------------------------------------------------------------------------


class TestFalloTesoreria:
    """Tests para escalamiento cuando notificar_tesoreria falla."""

    @patch("src.agent.flows.comprobante.escalar_humano")
    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_fallo_tesoreria_escala_humano(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        mock_escalar,
        session_state,
        payload,
        adjunto_valido,
    ):
        """Si notificar_tesoreria falla, se invoca escalar_humano."""
        from src.tools.treasury_tools import NotificationError

        mock_enviar.return_value = MagicMock(success=True)
        mock_actualizar.return_value = True
        mock_notificar.side_effect = NotificationError(
            "Tesorería no respondió tras reintentos"
        )
        mock_escalar.return_value = True

        resultado = procesar_comprobante(adjunto_valido, session_state, payload)

        assert resultado["success"] is False
        assert resultado["escalado"] is True
        assert resultado["formato_valido"] is True
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.comprobante.escalar_humano")
    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_fallo_tesoreria_timeout_escala_humano(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        mock_escalar,
        session_state,
        payload,
        adjunto_valido,
    ):
        """Si notificar_tesoreria timeout, se invoca escalar_humano."""
        mock_enviar.return_value = MagicMock(success=True)
        mock_actualizar.return_value = True
        mock_notificar.side_effect = TimeoutError("Timeout 60s")
        mock_escalar.return_value = True

        resultado = procesar_comprobante(adjunto_valido, session_state, payload)

        assert resultado["success"] is False
        assert resultado["escalado"] is True
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.comprobante.escalar_humano")
    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_fallo_tesoreria_no_actualiza_pipefy_a_validacion(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        mock_escalar,
        session_state,
        payload,
        adjunto_valido,
    ):
        """Si Tesorería falla, Pipefy NO se actualiza a 'En validación con tesorería'."""
        from src.tools.treasury_tools import NotificationError

        mock_enviar.return_value = MagicMock(success=True)
        mock_actualizar.return_value = True
        mock_notificar.side_effect = NotificationError("Error")
        mock_escalar.return_value = True

        procesar_comprobante(adjunto_valido, session_state, payload)

        # Solo una llamada a actualizar_pipefy ("Comprobante recibido")
        # NO debe haber segunda llamada con "En validación con tesorería"
        assert mock_actualizar.call_count == 1
        assert (
            mock_actualizar.call_args_list[0][1]["estado"]
            == "Comprobante recibido"
        )


# ---------------------------------------------------------------------------
# Tests: No validación bancaria (Req 5.7)
# ---------------------------------------------------------------------------


class TestNoValidacionBancaria:
    """Req 5.7: El agente NO realiza validación bancaria del comprobante."""

    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_no_valida_monto_del_comprobante(
        self,
        mock_enviar,
        mock_actualizar,
        mock_notificar,
        session_state,
        payload,
    ):
        """El flujo acepta cualquier comprobante sin validar contenido bancario."""
        mock_enviar.return_value = MagicMock(success=True)
        mock_actualizar.return_value = True
        mock_notificar.return_value = True

        # Crear adjunto con cualquier nombre — no se inspecciona contenido
        adjunto = Adjunto(
            nombre_archivo="deposito_5pesos.pdf",
            tamanio_bytes=100_000,
            s3_key="adjuntos/deposito_5pesos.pdf",
        )

        resultado = procesar_comprobante(adjunto, session_state, payload)

        # El flujo completa exitosamente sin inspeccionar el contenido del archivo
        assert resultado["success"] is True
        assert resultado["formato_valido"] is True
