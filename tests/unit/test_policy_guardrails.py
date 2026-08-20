"""
Tests unitarios para PolicyGuardrail — Guardrails determinísticos.

Verifica los 5 guardrails de AgentCore Policy:
1. Descuento ≠ 5% (Req 9.1)
2. Datos bancarios en estados no autorizados (Req 9.2)
3. Servicios fuera del alcance de póliza (Req 9.3)
4. Estados inválidos de Pipefy (Req 9.4)
5. Condiciones comerciales no presentes en KB (Req 9.5)

También verifica registro en Observability (Req 9.6) y opciones al cliente (Req 9.7).
"""

from unittest.mock import patch

import pytest

from src.policy.guardrails import PolicyBlockResult, PolicyGuardrail


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def guardrail():
    """Guardrail en modo permisivo para KB (sin lista de condiciones)."""
    return PolicyGuardrail()


@pytest.fixture
def guardrail_con_kb():
    """Guardrail con condiciones de KB configuradas."""
    condiciones = [
        "$45,000.00",
        "$85,000.00",
        "$120,000.00",
        "12 meses de vigencia",
    ]
    return PolicyGuardrail(kb_condiciones=condiciones)


@pytest.fixture
def session_state_interesado():
    return {
        "session_id": "sess-test-001",
        "estado_pipefy": "Cliente interesado",
    }


@pytest.fixture
def session_state_detectada():
    return {
        "session_id": "sess-test-002",
        "estado_pipefy": "Póliza detectada",
    }


@pytest.fixture
def session_state_deposito():
    return {
        "session_id": "sess-test-003",
        "estado_pipefy": "Depósito solicitado",
    }


# ---------------------------------------------------------------------------
# Tests: Guardrail 1 — Descuento ≠ 5% (Req 9.1)
# ---------------------------------------------------------------------------


class TestGuardrailDescuento:
    """Req 9.1: Bloquear tool call con descuento ≠ 5%."""

    def test_descuento_5_permitido(self, guardrail, session_state_interesado):
        """Descuento exacto de 5% no debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.05, "cuerpo": "Descuento del 5% aplicado."},
            session_state=session_state_interesado,
        )
        assert not result.bloqueado

    def test_descuento_10_bloqueado(self, guardrail, session_state_interesado):
        """Descuento de 10% debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.10, "cuerpo": "Descuento del 10% aplicado."},
            session_state=session_state_interesado,
        )
        assert result.bloqueado
        assert "10.0%" in result.motivo_bloqueo
        assert result.tool_call_intentado == "enviar_correo"

    def test_descuento_0_bloqueado(self, guardrail, session_state_interesado):
        """Descuento de 0% debe ser bloqueado (es distinto a 5%)."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.0, "cuerpo": "Sin descuento."},
            session_state=session_state_interesado,
        )
        assert result.bloqueado

    def test_descuento_20_en_cuerpo_bloqueado(self, guardrail, session_state_interesado):
        """Descuento de 20% detectado en cuerpo de correo debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Le ofrecemos un descuento del 20% en su renovación."
            },
            session_state=session_state_interesado,
        )
        assert result.bloqueado
        assert "20.0%" in result.motivo_bloqueo

    def test_descuento_5_en_cuerpo_permitido(self, guardrail, session_state_interesado):
        """Descuento de 5% en cuerpo de correo no debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Aplica un descuento del 5% por renovación anticipada."
            },
            session_state=session_state_interesado,
        )
        assert not result.bloqueado

    def test_descuento_no_numerico_bloqueado(self, guardrail, session_state_interesado):
        """Descuento con valor no numérico debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": "mucho", "cuerpo": "Descuento especial."},
            session_state=session_state_interesado,
        )
        assert result.bloqueado
        assert "no numérico" in result.motivo_bloqueo

    def test_sin_descuento_permitido(self, guardrail, session_state_interesado):
        """Tool call sin parámetro de descuento debe pasar."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "Recordatorio de renovación de póliza."},
            session_state=session_state_interesado,
        )
        assert not result.bloqueado

    def test_descuento_15_por_ciento_bloqueado(self, guardrail, session_state_interesado):
        """Descuento de 15 por ciento en cuerpo debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Ofrecemos un 15 por ciento de descuento."
            },
            session_state=session_state_interesado,
        )
        assert result.bloqueado


# ---------------------------------------------------------------------------
# Tests: Guardrail 2 — Datos bancarios en estados no autorizados (Req 9.2)
# ---------------------------------------------------------------------------


class TestGuardrailDatosBancarios:
    """Req 9.2: Bloquear enviar_correo con datos bancarios en estados incorrectos."""

    def test_datos_bancarios_estado_interesado_permitido(
        self, guardrail, session_state_interesado
    ):
        """Datos bancarios permitidos cuando Estado = 'Cliente interesado'."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": (
                    "CLABE: 012345678901234567 | Cuenta: 0123456789 | "
                    "Beneficiario: CIME Power Systems S.A. de C.V."
                )
            },
            session_state=session_state_interesado,
        )
        assert not result.bloqueado

    def test_datos_bancarios_estado_deposito_permitido(
        self, guardrail, session_state_deposito
    ):
        """Datos bancarios permitidos cuando Estado = 'Depósito solicitado'."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "CLABE: 012345678901234567 para realizar su depósito."
            },
            session_state=session_state_deposito,
        )
        assert not result.bloqueado

    def test_datos_bancarios_estado_detectada_bloqueado(
        self, guardrail, session_state_detectada
    ):
        """Datos bancarios bloqueados cuando Estado = 'Póliza detectada'."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "CLABE: 012345678901234567 para realizar su depósito."
            },
            session_state=session_state_detectada,
        )
        assert result.bloqueado
        assert "Datos bancarios" in result.motivo_bloqueo
        assert result.estado_pipefy == "Póliza detectada"

    def test_datos_bancarios_estado_seguimiento_bloqueado(self, guardrail):
        """Datos bancarios bloqueados cuando Estado = 'Seguimiento en curso'."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Banco: BBVA | Cuenta: 0123456789"
            },
            session_state={
                "session_id": "sess-004",
                "estado_pipefy": "Seguimiento en curso",
            },
        )
        assert result.bloqueado

    def test_sin_datos_bancarios_cualquier_estado_permitido(
        self, guardrail, session_state_detectada
    ):
        """Correo sin datos bancarios permitido en cualquier estado."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Estimado cliente, le recordamos renovar su póliza."
            },
            session_state=session_state_detectada,
        )
        assert not result.bloqueado

    def test_datos_bancarios_otra_tool_no_aplica(
        self, guardrail, session_state_detectada
    ):
        """Guardrail de datos bancarios solo aplica a enviar_correo."""
        result = guardrail.validar_tool_call(
            tool_name="actualizar_pipefy",
            params={
                "nota": "CLABE: 012345678901234567",
                "estado": "Contacto inicial enviado",
            },
            session_state=session_state_detectada,
        )
        assert not result.bloqueado


# ---------------------------------------------------------------------------
# Tests: Guardrail 3 — Servicios fuera de alcance (Req 9.3)
# ---------------------------------------------------------------------------


class TestGuardrailAlcanceServicio:
    """Req 9.3: Bloquear tool calls que ofrezcan servicios fuera de póliza."""

    def test_diagnostico_tecnico_bloqueado(self, guardrail, session_state_interesado):
        """Oferta de diagnóstico técnico debe ser bloqueada."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Le ofrecemos un diagnóstico técnico de su equipo."
            },
            session_state=session_state_interesado,
        )
        assert result.bloqueado
        assert "diagnóstico técnico" in result.motivo_bloqueo.lower()

    def test_venta_refacciones_bloqueado(self, guardrail, session_state_interesado):
        """Oferta de venta de refacciones debe ser bloqueada."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Tenemos refacciones disponibles para su equipo UPS."
            },
            session_state=session_state_interesado,
        )
        assert result.bloqueado

    def test_soporte_tecnico_bloqueado(self, guardrail, session_state_interesado):
        """Oferta de soporte técnico debe ser bloqueada."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Nuestro equipo de soporte técnico puede ayudarle."
            },
            session_state=session_state_interesado,
        )
        assert result.bloqueado

    def test_modificaciones_equipos_bloqueado(self, guardrail, session_state_interesado):
        """Oferta de modificaciones de equipos debe ser bloqueada."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Podemos realizar modificaciones de equipos según su necesidad."
            },
            session_state=session_state_interesado,
        )
        assert result.bloqueado

    def test_renovacion_poliza_permitido(self, guardrail, session_state_interesado):
        """Contenido sobre renovación de póliza no debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": (
                    "Le invitamos a renovar su póliza de mantenimiento "
                    "con un 5% de descuento por renovación anticipada."
                )
            },
            session_state=session_state_interesado,
        )
        assert not result.bloqueado

    def test_escalar_humano_no_bloqueado(self, guardrail, session_state_interesado):
        """escalar_humano nunca debe ser bloqueado por este guardrail."""
        result = guardrail.validar_tool_call(
            tool_name="escalar_humano",
            params={
                "motivo": "Cliente solicita diagnóstico técnico de su equipo."
            },
            session_state=session_state_interesado,
        )
        assert not result.bloqueado


# ---------------------------------------------------------------------------
# Tests: Guardrail 4 — Estado inválido de Pipefy (Req 9.4)
# ---------------------------------------------------------------------------


class TestGuardrailEstadoPipefy:
    """Req 9.4: Bloquear actualizar_pipefy con estado fuera del conjunto válido."""

    def test_estado_valido_permitido(self, guardrail, session_state_detectada):
        """Estado válido 'Contacto inicial enviado' no debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="actualizar_pipefy",
            params={"estado": "Contacto inicial enviado", "nota": "Test"},
            session_state=session_state_detectada,
        )
        assert not result.bloqueado

    def test_todos_estados_validos_permitidos(self, guardrail, session_state_detectada):
        """Todos los 10 estados válidos deben pasar."""
        from src.models.constants import ESTADOS_VALIDOS_PIPEFY

        for estado in ESTADOS_VALIDOS_PIPEFY:
            result = guardrail.validar_tool_call(
                tool_name="actualizar_pipefy",
                params={"estado": estado, "nota": "Test"},
                session_state=session_state_detectada,
            )
            assert not result.bloqueado, f"Estado válido '{estado}' fue bloqueado"

    def test_estado_inventado_bloqueado(self, guardrail, session_state_detectada):
        """Estado inventado 'Cancelada' debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="actualizar_pipefy",
            params={"estado": "Cancelada", "nota": "Test"},
            session_state=session_state_detectada,
        )
        assert result.bloqueado
        assert "Cancelada" in result.motivo_bloqueo

    def test_estado_vacio_bloqueado(self, guardrail, session_state_detectada):
        """Estado vacío debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="actualizar_pipefy",
            params={"estado": "", "nota": "Test"},
            session_state=session_state_detectada,
        )
        assert result.bloqueado

    def test_estado_con_typo_bloqueado(self, guardrail, session_state_detectada):
        """Estado con error ortográfico debe ser bloqueado."""
        result = guardrail.validar_tool_call(
            tool_name="actualizar_pipefy",
            params={"estado": "Poliza detectada", "nota": "Test"},  # sin tilde
            session_state=session_state_detectada,
        )
        assert result.bloqueado

    def test_otra_tool_no_aplica(self, guardrail, session_state_detectada):
        """Guardrail de estados solo aplica a actualizar_pipefy."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "Estado: Cancelada"},
            session_state=session_state_detectada,
        )
        assert not result.bloqueado


# ---------------------------------------------------------------------------
# Tests: Guardrail 5 — Condiciones no presentes en KB (Req 9.5)
# ---------------------------------------------------------------------------


class TestGuardrailCondicionesKB:
    """Req 9.5: Bloquear correo con condiciones no presentes en KB."""

    def test_modo_permisivo_sin_kb(self, guardrail, session_state_interesado):
        """Sin KB configurada, no bloquea ningún correo."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "Precio especial: $999,999.99"},
            session_state=session_state_interesado,
        )
        assert not result.bloqueado

    def test_precio_autorizado_permitido(
        self, guardrail_con_kb, session_state_interesado
    ):
        """Precio presente en KB no debe ser bloqueado."""
        result = guardrail_con_kb.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "El precio de renovación es $45,000.00 MXN."},
            session_state=session_state_interesado,
        )
        assert not result.bloqueado

    def test_precio_no_autorizado_bloqueado(
        self, guardrail_con_kb, session_state_interesado
    ):
        """Precio no presente en KB debe ser bloqueado."""
        result = guardrail_con_kb.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "Le ofrecemos un precio especial de $999,999.99"},
            session_state=session_state_interesado,
        )
        assert result.bloqueado
        assert "$999,999.99" in result.motivo_bloqueo

    def test_plazo_no_autorizado_bloqueado(
        self, guardrail_con_kb, session_state_interesado
    ):
        """Plazo de pago no autorizado debe ser bloqueado."""
        result = guardrail_con_kb.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": "Puede pagar en 6 meses de plazo sin intereses."
            },
            session_state=session_state_interesado,
        )
        assert result.bloqueado
        assert "plazo" in result.motivo_bloqueo.lower()

    def test_otra_tool_no_aplica(self, guardrail_con_kb, session_state_interesado):
        """Guardrail KB solo aplica a enviar_correo."""
        result = guardrail_con_kb.validar_tool_call(
            tool_name="actualizar_pipefy",
            params={"estado": "Cliente interesado", "nota": "Precio $999,999.99"},
            session_state=session_state_interesado,
        )
        assert not result.bloqueado


# ---------------------------------------------------------------------------
# Tests: Observability — Registro de bloqueos (Req 9.6)
# ---------------------------------------------------------------------------


class TestObservabilityBloqueos:
    """Req 9.6: Verificar campos de registro en Observability."""

    def test_bloqueo_contiene_todos_los_campos(self, guardrail, session_state_detectada):
        """Cada bloqueo debe producir los 5 campos requeridos."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "CLABE: 012345678901234567"},
            session_state=session_state_detectada,
        )
        assert result.bloqueado

        entry = result.to_observability_entry()
        assert "motivo_bloqueo" in entry
        assert "tool_call_intentado" in entry
        assert "session_id" in entry
        assert "estado_pipefy" in entry
        assert "timestamp" in entry

        # Verificar valores no vacíos
        assert entry["motivo_bloqueo"] != ""
        assert entry["tool_call_intentado"] == "enviar_correo"
        assert entry["session_id"] == "sess-test-002"
        assert entry["estado_pipefy"] == "Póliza detectada"
        assert entry["timestamp"] != ""

    def test_bloqueo_descuento_registra_campos(
        self, guardrail, session_state_interesado
    ):
        """Bloqueo por descuento incorrecto registra todos los campos."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.20, "cuerpo": "Descuento del 20%"},
            session_state=session_state_interesado,
        )
        entry = result.to_observability_entry()
        assert "20.0%" in entry["motivo_bloqueo"]
        assert entry["tool_call_intentado"] == "enviar_correo"
        assert entry["session_id"] == "sess-test-001"

    def test_timestamp_formato_iso(self, guardrail, session_state_detectada):
        """Timestamp debe estar en formato ISO 8601."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "CLABE: 012345678901234567"},
            session_state=session_state_detectada,
        )
        # ISO 8601 contiene "T" y termina con "+00:00" o "Z"
        assert "T" in result.timestamp


# ---------------------------------------------------------------------------
# Tests: Notificación al cliente y opciones (Req 9.7)
# ---------------------------------------------------------------------------


class TestNotificacionCliente:
    """Req 9.7: Tras bloqueo, ofrecer opciones disponibles al cliente."""

    def test_bloqueo_ofrece_opciones(self, guardrail, session_state_interesado):
        """Todo bloqueo debe ofrecer opciones al cliente."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.30, "cuerpo": "Descuento 30%"},
            session_state=session_state_interesado,
        )
        assert result.bloqueado
        assert len(result.opciones_disponibles) > 0

    def test_opciones_descuento_incluyen_5_y_escalar(
        self, guardrail, session_state_interesado
    ):
        """Opciones tras bloqueo de descuento deben incluir 5% y escalar."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.15, "cuerpo": ""},
            session_state=session_state_interesado,
        )
        opciones_texto = " ".join(result.opciones_disponibles).lower()
        assert "5%" in opciones_texto
        assert "asesor" in opciones_texto

    def test_opciones_datos_bancarios_incluyen_alternativa(
        self, guardrail, session_state_detectada
    ):
        """Opciones tras bloqueo de datos bancarios deben ofrecer alternativas."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "CLABE: 012345678901234567"},
            session_state=session_state_detectada,
        )
        assert len(result.opciones_disponibles) >= 2

    def test_no_bloqueado_sin_opciones(self, guardrail, session_state_interesado):
        """Si no hay bloqueo, no se necesitan opciones."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "Mensaje de seguimiento normal."},
            session_state=session_state_interesado,
        )
        assert not result.bloqueado
        assert result.opciones_disponibles == []


# ---------------------------------------------------------------------------
# Tests: Flujo completo (múltiples guardrails)
# ---------------------------------------------------------------------------


class TestFlujoCompleto:
    """Tests de integración para validar la ejecución secuencial de guardrails."""

    def test_tool_call_valido_pasa_todos_guardrails(
        self, guardrail, session_state_interesado
    ):
        """Un tool call completamente válido pasa todos los guardrails."""
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "cuerpo": (
                    "Estimado cliente, su cotización de renovación es "
                    "$45,000.00 MXN con un descuento del 5% por renovación "
                    "anticipada. Precio final: $42,750.00 MXN."
                ),
                "descuento": 0.05,
            },
            session_state=session_state_interesado,
        )
        assert not result.bloqueado

    def test_primer_guardrail_que_falla_bloquea(
        self, guardrail, session_state_detectada
    ):
        """El primer guardrail que falla detiene la validación."""
        # Este correo tiene descuento incorrecto Y datos bancarios en estado incorrecto
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={
                "descuento": 0.20,
                "cuerpo": "Descuento 20% más CLABE: 012345678901234567",
            },
            session_state=session_state_detectada,
        )
        assert result.bloqueado
        # El primer guardrail es descuento, así que debería ser ese el motivo
        assert "20.0%" in result.motivo_bloqueo

    def test_consultar_pipefy_sin_bloqueo(self, guardrail, session_state_interesado):
        """consultar_pipefy normalmente no activa ningún guardrail."""
        result = guardrail.validar_tool_call(
            tool_name="consultar_pipefy",
            params={"poliza_id": "POL-2024-001"},
            session_state=session_state_interesado,
        )
        assert not result.bloqueado


# ---------------------------------------------------------------------------
# Tests: Integración con registrar_bloqueo_policy (Req 9.6)
# ---------------------------------------------------------------------------


class TestRegistroObservabilityIntegrado:
    """Req 9.6: Verifica que cada bloqueo invoca registrar_bloqueo_policy."""

    @patch("src.policy.guardrails.registrar_bloqueo_policy")
    def test_bloqueo_descuento_registra_en_observability(
        self, mock_registrar, session_state_interesado
    ):
        """Bloqueo por descuento invoca registrar_bloqueo_policy con campos correctos."""
        guardrail = PolicyGuardrail()
        guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.20, "cuerpo": "Descuento del 20%"},
            session_state=session_state_interesado,
        )
        mock_registrar.assert_called_once()
        kwargs = mock_registrar.call_args.kwargs
        assert "20.0%" in kwargs["motivo_bloqueo"]
        assert kwargs["tool_intentada"] == "enviar_correo"
        assert kwargs["session_id"] == "sess-test-001"
        assert kwargs["estado_pipefy"] == "Cliente interesado"
        assert kwargs["timestamp"] is not None

    @patch("src.policy.guardrails.registrar_bloqueo_policy")
    def test_bloqueo_datos_bancarios_registra_en_observability(
        self, mock_registrar, session_state_detectada
    ):
        """Bloqueo por datos bancarios invoca registrar_bloqueo_policy."""
        guardrail = PolicyGuardrail()
        guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "CLABE: 012345678901234567"},
            session_state=session_state_detectada,
        )
        mock_registrar.assert_called_once()
        kwargs = mock_registrar.call_args.kwargs
        assert "Datos bancarios" in kwargs["motivo_bloqueo"]
        assert kwargs["tool_intentada"] == "enviar_correo"
        assert kwargs["session_id"] == "sess-test-002"
        assert kwargs["estado_pipefy"] == "Póliza detectada"

    @patch("src.policy.guardrails.registrar_bloqueo_policy")
    def test_bloqueo_alcance_registra_en_observability(
        self, mock_registrar, session_state_interesado
    ):
        """Bloqueo por servicio fuera de alcance invoca registrar_bloqueo_policy."""
        guardrail = PolicyGuardrail()
        guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "Le ofrecemos diagnóstico técnico de su equipo."},
            session_state=session_state_interesado,
        )
        mock_registrar.assert_called_once()
        kwargs = mock_registrar.call_args.kwargs
        assert "diagnóstico técnico" in kwargs["motivo_bloqueo"].lower()

    @patch("src.policy.guardrails.registrar_bloqueo_policy")
    def test_bloqueo_estado_invalido_registra_en_observability(
        self, mock_registrar, session_state_detectada
    ):
        """Bloqueo por estado inválido invoca registrar_bloqueo_policy."""
        guardrail = PolicyGuardrail()
        guardrail.validar_tool_call(
            tool_name="actualizar_pipefy",
            params={"estado": "Estado Inventado", "nota": "Test"},
            session_state=session_state_detectada,
        )
        mock_registrar.assert_called_once()
        kwargs = mock_registrar.call_args.kwargs
        assert "Estado Inventado" in kwargs["motivo_bloqueo"]

    @patch("src.policy.guardrails.registrar_bloqueo_policy")
    def test_bloqueo_condiciones_kb_registra_en_observability(
        self, mock_registrar, session_state_interesado
    ):
        """Bloqueo por condición no autorizada invoca registrar_bloqueo_policy."""
        guardrail = PolicyGuardrail(kb_condiciones=["$45,000.00"])
        guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "El precio es $999,999.99 MXN."},
            session_state=session_state_interesado,
        )
        mock_registrar.assert_called_once()
        kwargs = mock_registrar.call_args.kwargs
        assert "$999,999.99" in kwargs["motivo_bloqueo"]

    @patch("src.policy.guardrails.registrar_bloqueo_policy")
    def test_sin_bloqueo_no_registra(self, mock_registrar, session_state_interesado):
        """Si no hay bloqueo, no se invoca registrar_bloqueo_policy."""
        guardrail = PolicyGuardrail()
        guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "Renovación de póliza sin problemas."},
            session_state=session_state_interesado,
        )
        mock_registrar.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: generar_notificacion_cliente (Req 9.7)
# ---------------------------------------------------------------------------


class TestGenerarNotificacionCliente:
    """Req 9.7: Verifica la generación de mensaje de notificación al cliente."""

    def test_notificacion_tras_bloqueo_descuento(self, session_state_interesado):
        """Genera mensaje con opciones tras bloqueo de descuento."""
        guardrail = PolicyGuardrail()
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.30, "cuerpo": "Descuento del 30%"},
            session_state=session_state_interesado,
        )
        mensaje = guardrail.generar_notificacion_cliente(result)
        assert "no es posible" in mensaje.lower()
        assert "5%" in mensaje
        assert "asesor" in mensaje.lower()

    def test_notificacion_tras_bloqueo_datos_bancarios(self, session_state_detectada):
        """Genera mensaje con opciones tras bloqueo de datos bancarios."""
        guardrail = PolicyGuardrail()
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "CLABE: 012345678901234567"},
            session_state=session_state_detectada,
        )
        mensaje = guardrail.generar_notificacion_cliente(result)
        assert "no es posible" in mensaje.lower()
        assert "opciones" in mensaje.lower() or "asesor" in mensaje.lower()

    def test_sin_bloqueo_retorna_vacio(self, session_state_interesado):
        """Si no hay bloqueo, no genera mensaje de notificación."""
        guardrail = PolicyGuardrail()
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "Mensaje normal de seguimiento."},
            session_state=session_state_interesado,
        )
        mensaje = guardrail.generar_notificacion_cliente(result)
        assert mensaje == ""

    def test_notificacion_contiene_todas_las_opciones(self, session_state_interesado):
        """El mensaje de notificación incluye todas las opciones del bloqueo."""
        guardrail = PolicyGuardrail()
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"descuento": 0.15, "cuerpo": ""},
            session_state=session_state_interesado,
        )
        mensaje = guardrail.generar_notificacion_cliente(result)
        for opcion in result.opciones_disponibles:
            assert opcion in mensaje
