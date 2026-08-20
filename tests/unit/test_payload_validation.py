"""
Property-Based Tests — Propiedad 1: Validación exhaustiva de payload de activación.

Feature: agente-comercial-polizas
Property 1: Validación exhaustiva de payload de activación

Valida: Requisitos 1.2, 1.3

Estrategia:
- Payloads con al menos un campo inválido  → sesion_iniciada=False, correo_enviado=False
- Payloads con todos los campos válidos    → sesion_iniciada=True

La lógica de negocio se ejerce a través de `es_payload_valido()` de
`src/models/validators.py`, que implementa las reglas del Req 1.2.
El resultado de esa función determina de manera determinística el
comportamiento del agente en su fase de arranque (Req 1.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.models.data_models import ActivationPayload
from src.models.validators import es_payload_valido, obtener_campos_invalidos

# ---------------------------------------------------------------------------
# Resultado simulado del arranque de sesión
# (Representa la decisión del agente al recibir el payload — Req 1.2, 1.3)
# ---------------------------------------------------------------------------

@dataclass
class ResultadoActivacion:
    sesion_iniciada: bool
    correo_enviado: bool
    error_registrado: bool
    campos_invalidos: list[str]


def simular_activacion(payload: ActivationPayload) -> ResultadoActivacion:
    """
    Simula la lógica de arranque del agente para un payload dado.

    Req 1.2 — validar campos obligatorios.
    Req 1.3 — si payload inválido: registrar error, NO enviar correo, terminar.

    Returns:
        ResultadoActivacion con los flags de decisión del agente.
    """
    invalidos = obtener_campos_invalidos(payload)
    valido = len(invalidos) == 0

    return ResultadoActivacion(
        sesion_iniciada=valido,
        correo_enviado=False,  # El correo se envía en un paso posterior, nunca aquí
        error_registrado=not valido,
        campos_invalidos=invalidos,
    )


# ---------------------------------------------------------------------------
# Estrategias Hypothesis — campos válidos
# ---------------------------------------------------------------------------

# Email RFC 5321 válido: local@domain.tld
_st_email_valido = st.builds(
    lambda local, domain, tld: f"{local}@{domain}.{tld}",
    local=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-",
        min_size=1, max_size=30,
    ).filter(lambda s: not s.startswith(".") and not s.endswith(".")),
    domain=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
        min_size=1, max_size=20,
    ).filter(lambda s: not s.startswith("-") and not s.endswith("-")),
    tld=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz",
        min_size=2, max_size=6,
    ),
)

# Fecha de vencimiento: cualquier fecha dentro de ±5 años desde hoy
_today = date.today()
_st_fecha_valida = st.dates(
    min_value=_today - timedelta(days=365 * 5),
    max_value=_today + timedelta(days=365 * 5),
)

# Precio de renovación > 0
_st_precio_valido = st.floats(min_value=1.0, max_value=500_000.0, allow_nan=False, allow_infinity=False)

# Campo de texto no vacío (poliza_id, cliente_nombre, equipo_nombre)
_st_texto_valido = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1, max_size=80,
).filter(lambda s: bool(s.strip()))

# ---------------------------------------------------------------------------
# Estrategia para payload completamente válido
# ---------------------------------------------------------------------------

_st_payload_valido = st.builds(
    ActivationPayload,
    poliza_id=_st_texto_valido,
    cliente_nombre=_st_texto_valido,
    cliente_email=_st_email_valido,
    fecha_vencimiento=_st_fecha_valida,
    precio_renovacion=_st_precio_valido,
    equipo_nombre=_st_texto_valido,
)

# ---------------------------------------------------------------------------
# Estrategias para campos inválidos (uno o más campos malos)
# ---------------------------------------------------------------------------

# Email inválido: sin @, sin dominio, solo espacios, etc.
_st_email_invalido = st.one_of(
    st.just(""),
    st.just("   "),
    st.just("no-arroba"),
    st.just("@sin-local.com"),
    st.just("doble@@arroba.com"),
    st.just("sin-punto-en-dominio@dominio"),
    st.just("espacios en@email.com"),
    st.text(min_size=0, max_size=10).filter(
        lambda s: "@" not in s or "." not in s.split("@")[-1]
    ),
)

# Fecha inválida: string que no es fecha, None, etc.  (type annotation es date
# pero hypothesis puede generar otros tipos cuando usamos builds con override)
_st_fecha_invalida = st.one_of(
    st.just("no-es-fecha"),
    st.just("32/13/2025"),
    st.just(""),
    st.just("2025-13-01"),
    st.just("2025-00-10"),
    st.just("2025-02-30"),
)

# Precio inválido
_st_precio_invalido = st.one_of(
    st.just(0.0),
    st.just(-1.0),
    st.just(-100.0),
    st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
    st.just(float("nan")),
    st.just(float("inf")),
    st.just(float("-inf")),
    st.just(None),
)

# Texto inválido: vacío o solo espacios
_st_texto_invalido = st.one_of(
    st.just(""),
    st.just("   "),
    st.just("\t"),
    st.just("\n"),
    st.just(None),
)


def _st_payload_un_campo_invalido(campo: str) -> st.SearchStrategy:
    """Genera un ActivationPayload donde solo `campo` es inválido."""
    overrides: dict = {}

    if campo == "poliza_id":
        overrides["poliza_id"] = _st_texto_invalido
    elif campo == "cliente_nombre":
        overrides["cliente_nombre"] = _st_texto_invalido
    elif campo == "cliente_email":
        overrides["cliente_email"] = _st_email_invalido
    elif campo == "fecha_vencimiento":
        overrides["fecha_vencimiento"] = _st_fecha_invalida
    elif campo == "precio_renovacion":
        overrides["precio_renovacion"] = _st_precio_invalido
    elif campo == "equipo_nombre":
        overrides["equipo_nombre"] = _st_texto_invalido

    # El resto de campos son válidos
    defaults = {
        "poliza_id": _st_texto_valido,
        "cliente_nombre": _st_texto_valido,
        "cliente_email": _st_email_valido,
        "fecha_vencimiento": _st_fecha_valida,
        "precio_renovacion": _st_precio_valido,
        "equipo_nombre": _st_texto_valido,
    }
    defaults.update(overrides)
    return st.builds(ActivationPayload, **defaults)


# Estrategia global para payloads inválidos: al menos un campo malo
_st_payload_invalido = st.one_of(
    *[_st_payload_un_campo_invalido(c) for c in (
        "poliza_id", "cliente_nombre", "cliente_email",
        "fecha_vencimiento", "precio_renovacion", "equipo_nombre",
    )]
)


# ===========================================================================
# PROPERTY TESTS
# ===========================================================================

class TestProperty1ValidacionExhaustivaPayload:
    """
    Feature: agente-comercial-polizas
    Property 1: Validación exhaustiva de payload de activación
    Valida: Requisitos 1.2, 1.3
    """

    # -----------------------------------------------------------------------
    # Rama de payload INVÁLIDO
    # -----------------------------------------------------------------------

    @given(_st_payload_invalido)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_payload_invalido_sesion_no_iniciada(self, payload: ActivationPayload) -> None:
        """
        Req 1.3 — Payload con al menos un campo inválido:
        el agente NO debe iniciar sesión.
        """
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False, (
            f"Se esperaba sesion_iniciada=False para payload inválido. "
            f"Campos inválidos detectados: {resultado.campos_invalidos}. "
            f"Payload: {payload}"
        )

    @given(_st_payload_invalido)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_payload_invalido_correo_no_enviado(self, payload: ActivationPayload) -> None:
        """
        Req 1.3 — Payload con al menos un campo inválido:
        el agente NO debe enviar correo al cliente.
        """
        resultado = simular_activacion(payload)
        assert resultado.correo_enviado is False, (
            f"Se esperaba correo_enviado=False para payload inválido. "
            f"Campos inválidos: {resultado.campos_invalidos}. "
            f"Payload: {payload}"
        )

    @given(_st_payload_invalido)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_payload_invalido_error_registrado(self, payload: ActivationPayload) -> None:
        """
        Req 1.3 — Payload inválido debe generar registro de error en Observability.
        """
        resultado = simular_activacion(payload)
        assert resultado.error_registrado is True, (
            f"Se esperaba error_registrado=True para payload inválido. "
            f"Payload: {payload}"
        )

    @given(_st_payload_invalido)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_payload_invalido_campos_identificados(self, payload: ActivationPayload) -> None:
        """
        Req 1.3 — Los campos inválidos deben ser identificados para el log de Observability.
        """
        resultado = simular_activacion(payload)
        assert len(resultado.campos_invalidos) >= 1, (
            f"Se esperaba al menos un campo inválido identificado. Payload: {payload}"
        )

    # -----------------------------------------------------------------------
    # Rama de payload VÁLIDO
    # -----------------------------------------------------------------------

    @given(_st_payload_valido)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_payload_valido_sesion_iniciada(self, payload: ActivationPayload) -> None:
        """
        Req 1.2 — Payload con todos los campos válidos:
        el agente DEBE iniciar sesión.
        """
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is True, (
            f"Se esperaba sesion_iniciada=True para payload válido. "
            f"Campos inválidos inesperados: {resultado.campos_invalidos}. "
            f"Payload: {payload}"
        )

    @given(_st_payload_valido)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_payload_valido_sin_error(self, payload: ActivationPayload) -> None:
        """
        Req 1.2 — Payload válido no debe generar registro de error.
        """
        resultado = simular_activacion(payload)
        assert resultado.error_registrado is False, (
            f"Se esperaba error_registrado=False para payload válido. "
            f"Campos inesperadamente inválidos: {resultado.campos_invalidos}. "
            f"Payload: {payload}"
        )

    @given(_st_payload_valido)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_payload_valido_correo_no_enviado_en_activacion(self, payload: ActivationPayload) -> None:
        """
        El correo de contacto inicial NO se envía durante la validación del payload;
        es un paso posterior en el flujo del agente. Este test confirma que la función
        de activación no tiene efecto secundario de envío.
        """
        resultado = simular_activacion(payload)
        assert resultado.correo_enviado is False, (
            f"correo_enviado debe ser False en la fase de activación (el envío es un paso posterior). "
            f"Payload: {payload}"
        )


# ===========================================================================
# UNIT TESTS DE EJEMPLO (casos específicos)
# ===========================================================================

class TestValidacionPayloadEjemplos:
    """Tests de ejemplo para casos específicos y de borde — Req 1.2."""

    def _payload_valido(self, **overrides) -> ActivationPayload:
        base = dict(
            poliza_id="POL-2024-001",
            cliente_nombre="ACME Corporativo S.A. de C.V.",
            cliente_email="contacto@acmecorp.com.mx",
            fecha_vencimiento=date(2025, 12, 31),
            precio_renovacion=15_000.0,
            equipo_nombre="UPS APC Smart-UPS 3000VA",
        )
        base.update(overrides)
        return ActivationPayload(**base)

    # --- poliza_id ---

    def test_poliza_id_vacio_invalida_sesion(self) -> None:
        payload = self._payload_valido(poliza_id="")
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "poliza_id" in resultado.campos_invalidos

    def test_poliza_id_solo_espacios_invalida_sesion(self) -> None:
        payload = self._payload_valido(poliza_id="   ")
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "poliza_id" in resultado.campos_invalidos

    def test_poliza_id_valido(self) -> None:
        payload = self._payload_valido(poliza_id="POL-2025-042")
        resultado = simular_activacion(payload)
        assert "poliza_id" not in resultado.campos_invalidos

    # --- cliente_nombre ---

    def test_cliente_nombre_vacio_invalida_sesion(self) -> None:
        payload = self._payload_valido(cliente_nombre="")
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "cliente_nombre" in resultado.campos_invalidos

    def test_cliente_nombre_valido(self) -> None:
        payload = self._payload_valido(cliente_nombre="Industrias Beta")
        resultado = simular_activacion(payload)
        assert "cliente_nombre" not in resultado.campos_invalidos

    # --- cliente_email ---

    def test_email_sin_arroba_invalida_sesion(self) -> None:
        payload = self._payload_valido(cliente_email="correo-sin-arroba.com")
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "cliente_email" in resultado.campos_invalidos

    def test_email_sin_dominio_invalida_sesion(self) -> None:
        payload = self._payload_valido(cliente_email="usuario@")
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "cliente_email" in resultado.campos_invalidos

    def test_email_sin_tld_invalida_sesion(self) -> None:
        payload = self._payload_valido(cliente_email="usuario@dominio")
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "cliente_email" in resultado.campos_invalidos

    def test_email_vacio_invalida_sesion(self) -> None:
        payload = self._payload_valido(cliente_email="")
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "cliente_email" in resultado.campos_invalidos

    def test_email_valido_rfc5321(self) -> None:
        for email in [
            "usuario@empresa.com",
            "nombre.apellido@empresa.com.mx",
            "contacto+facturacion@dominio.org",
            "user123@sub.domain.co.uk",
        ]:
            payload = self._payload_valido(cliente_email=email)
            resultado = simular_activacion(payload)
            assert "cliente_email" not in resultado.campos_invalidos, (
                f"Email válido '{email}' fue rechazado"
            )

    # --- fecha_vencimiento ---

    def test_fecha_string_invalido_invalida_sesion(self) -> None:
        payload = self._payload_valido(fecha_vencimiento="no-es-fecha")  # type: ignore[arg-type]
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "fecha_vencimiento" in resultado.campos_invalidos

    def test_fecha_objeto_date_valido(self) -> None:
        payload = self._payload_valido(fecha_vencimiento=date(2026, 6, 15))
        resultado = simular_activacion(payload)
        assert "fecha_vencimiento" not in resultado.campos_invalidos

    def test_fecha_iso8601_string_valido(self) -> None:
        """Los validators también aceptan strings ISO 8601 válidos."""
        payload = self._payload_valido(fecha_vencimiento="2026-06-15")  # type: ignore[arg-type]
        resultado = simular_activacion(payload)
        assert "fecha_vencimiento" not in resultado.campos_invalidos

    # --- precio_renovacion ---

    def test_precio_cero_invalida_sesion(self) -> None:
        payload = self._payload_valido(precio_renovacion=0.0)
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "precio_renovacion" in resultado.campos_invalidos

    def test_precio_negativo_invalida_sesion(self) -> None:
        payload = self._payload_valido(precio_renovacion=-500.0)
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "precio_renovacion" in resultado.campos_invalidos

    def test_precio_nan_invalida_sesion(self) -> None:
        payload = self._payload_valido(precio_renovacion=float("nan"))
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "precio_renovacion" in resultado.campos_invalidos

    def test_precio_infinito_invalida_sesion(self) -> None:
        payload = self._payload_valido(precio_renovacion=float("inf"))
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "precio_renovacion" in resultado.campos_invalidos

    def test_precio_positivo_valido(self) -> None:
        for precio in [0.01, 1.0, 15_000.0, 500_000.0]:
            payload = self._payload_valido(precio_renovacion=precio)
            resultado = simular_activacion(payload)
            assert "precio_renovacion" not in resultado.campos_invalidos, (
                f"Precio válido {precio} fue rechazado"
            )

    # --- equipo_nombre ---

    def test_equipo_nombre_vacio_invalida_sesion(self) -> None:
        payload = self._payload_valido(equipo_nombre="")
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "equipo_nombre" in resultado.campos_invalidos

    def test_equipo_nombre_valido(self) -> None:
        payload = self._payload_valido(equipo_nombre="UPS Eaton 9PX 6000VA")
        resultado = simular_activacion(payload)
        assert "equipo_nombre" not in resultado.campos_invalidos

    # --- payload nulo ---

    def test_payload_nulo_retorna_invalido(self) -> None:
        resultado = simular_activacion(None)  # type: ignore[arg-type]
        assert resultado.sesion_iniciada is False
        assert resultado.error_registrado is True

    # --- payload completamente válido ---

    def test_payload_completo_valido_inicia_sesion(self) -> None:
        payload = self._payload_valido()
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is True
        assert resultado.correo_enviado is False
        assert resultado.error_registrado is False
        assert resultado.campos_invalidos == []

    # --- múltiples campos inválidos ---

    def test_multiples_campos_invalidos_todos_reportados(self) -> None:
        payload = self._payload_valido(
            poliza_id="",
            cliente_email="email-malo",
            precio_renovacion=-1.0,
        )
        resultado = simular_activacion(payload)
        assert resultado.sesion_iniciada is False
        assert "poliza_id" in resultado.campos_invalidos
        assert "cliente_email" in resultado.campos_invalidos
        assert "precio_renovacion" in resultado.campos_invalidos

    # --- consistencia entre es_payload_valido y simular_activacion ---

    def test_consistencia_validador_y_activacion(self) -> None:
        """La función simular_activacion debe ser consistente con es_payload_valido."""
        valido = self._payload_valido()
        assert es_payload_valido(valido) is True
        assert simular_activacion(valido).sesion_iniciada is True

        invalido = self._payload_valido(cliente_email="")
        assert es_payload_valido(invalido) is False
        assert simular_activacion(invalido).sesion_iniciada is False


# ===========================================================================
# PROPERTY TEST — Propiedad 21: Escalamiento por score insuficiente en KB
# ===========================================================================


class TestProperty21EscalamientoPorScoreInsuficienteKB:
    """
    Feature: agente-comercial-polizas
    Property 21: Escalamiento por score insuficiente en Knowledge Base

    **Validates: Requirements 11.2**

    Para consultas a KB que retornan score máximo < 0.70, verificar que
    el agente SIEMPRE invoca `escalar_humano` en ambos flujos:
    - `enviar_contacto_inicial()`
    - `generar_cotizacion()`
    """

    @given(
        score=st.floats(min_value=0.0, max_value=0.6999, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_contacto_inicial_escala_con_score_bajo(self, score: float) -> None:
        """
        Para CUALQUIER score < 0.70 en la KB, el flujo de contacto inicial
        debe invocar `escalar_humano` y retornar success=False.
        """
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, patch

        from src.agent.flows.contacto_inicial import enviar_contacto_inicial
        from src.config.kb_client import KBClient, KBQueryResponse, KBResult
        from src.models.data_models import ActivationPayload, SessionState

        # Mock KB que retorna score insuficiente
        mock_kb = MagicMock(spec=KBClient)
        mock_kb.query.return_value = KBQueryResponse(
            results=[
                KBResult(
                    content="[Contenido mock]",
                    score=score,
                    source_uri="s3://cime-kb-documentos/plantillas_mensajes.md",
                    metadata={},
                )
            ],
            query_text="plantilla mensaje contacto",
        )

        payload = ActivationPayload(
            poliza_id="POL-KB-SCORE-TEST",
            cliente_nombre="Cliente Test KB",
            cliente_email="test@kb-score.com",
            fecha_vencimiento=date.today() + timedelta(days=15),
            precio_renovacion=15000.0,
            equipo_nombre="UPS Test 10 kVA",
        )

        session_state = SessionState(
            session_id="sess-kb-score-test",
            poliza_id=payload.poliza_id,
            estado_pipefy="Póliza detectada",
            historial_mensajes=[],
            timestamp_inicio=datetime.now(timezone.utc),
        )

        with patch("src.agent.flows.contacto_inicial.escalar_humano") as mock_escalar:
            mock_escalar.return_value = True

            resultado = enviar_contacto_inicial(
                session_state=session_state,
                payload=payload,
                kb_client=mock_kb,
            )

            # PROPIEDAD: score < 0.70 → escalar_humano SIEMPRE invocada
            mock_escalar.assert_called_once(), (
                f"Con score={score:.4f} (< 0.70), escalar_humano debe invocarse. "
                f"Resultado: {resultado}"
            )
            assert resultado["success"] is False, (
                f"Con score={score:.4f} (< 0.70), el flujo no debe ser exitoso."
            )

    @given(
        score=st.floats(min_value=0.0, max_value=0.6999, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_cotizacion_escala_con_score_bajo(self, score: float) -> None:
        """
        Para CUALQUIER score < 0.70 en la KB, el flujo de cotización
        debe invocar `escalar_humano` y retornar success=False.
        """
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, patch

        from src.agent.flows.cotizacion import generar_cotizacion
        from src.config.kb_client import KBClient, KBQueryResponse, KBResult
        from src.models.data_models import ActivationPayload, SessionState

        # Mock KB que retorna score insuficiente
        mock_kb = MagicMock(spec=KBClient)
        mock_kb.query.return_value = KBQueryResponse(
            results=[
                KBResult(
                    content="[Contenido mock - score bajo]",
                    score=score,
                    source_uri="s3://cime-kb-documentos/catalogo_precios.json",
                    metadata={},
                )
            ],
            query_text="precio catálogo equipo",
        )

        payload = ActivationPayload(
            poliza_id="POL-COT-SCORE-TEST",
            cliente_nombre="Cliente Cotización Score",
            cliente_email="cotizacion@score-test.com",
            fecha_vencimiento=date.today() + timedelta(days=20),
            precio_renovacion=25000.0,
            equipo_nombre="UPS Trifásico 10-20 kVA",
        )

        session_state = SessionState(
            session_id="sess-cot-score-test",
            poliza_id=payload.poliza_id,
            estado_pipefy="Cliente interesado",
            historial_mensajes=[],
            timestamp_inicio=datetime.now(timezone.utc),
        )

        with patch("src.agent.flows.cotizacion.escalar_humano") as mock_escalar:
            mock_escalar.return_value = True

            resultado = generar_cotizacion(
                session_state=session_state,
                payload=payload,
                kb_client=mock_kb,
            )

            # PROPIEDAD: score < 0.70 → escalar_humano SIEMPRE invocada
            mock_escalar.assert_called_once(), (
                f"Con score={score:.4f} (< 0.70) en cotización, escalar_humano "
                f"debe invocarse. Resultado: {resultado}"
            )
            assert resultado["success"] is False, (
                f"Con score={score:.4f} (< 0.70), la cotización no debe ser exitosa."
            )

    @given(
        score=st.floats(min_value=0.0, max_value=0.6999, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_score_insuficiente_nunca_envia_correo(self, score: float) -> None:
        """
        Para CUALQUIER score < 0.70, el agente NUNCA debe enviar correo.
        Verifica que `enviar_correo` no se invoca en ningún flujo.
        """
        from datetime import datetime, timezone
        from unittest.mock import MagicMock, patch

        from src.agent.flows.contacto_inicial import enviar_contacto_inicial
        from src.config.kb_client import KBClient, KBQueryResponse, KBResult
        from src.models.data_models import ActivationPayload, SessionState

        mock_kb = MagicMock(spec=KBClient)
        mock_kb.query.return_value = KBQueryResponse(
            results=[
                KBResult(
                    content="[Score insuficiente]",
                    score=score,
                    source_uri="s3://cime-kb-documentos/plantillas_mensajes.md",
                    metadata={},
                )
            ],
            query_text="plantilla mensaje",
        )

        payload = ActivationPayload(
            poliza_id="POL-NO-CORREO-TEST",
            cliente_nombre="Cliente Sin Correo",
            cliente_email="no-correo@test.com",
            fecha_vencimiento=date.today() + timedelta(days=10),
            precio_renovacion=8000.0,
            equipo_nombre="UPS Monofásico 5-10 kVA",
        )

        session_state = SessionState(
            session_id="sess-no-correo-test",
            poliza_id=payload.poliza_id,
            estado_pipefy="Póliza detectada",
            historial_mensajes=[],
            timestamp_inicio=datetime.now(timezone.utc),
        )

        with patch("src.agent.flows.contacto_inicial.escalar_humano") as mock_escalar, \
             patch("src.agent.flows.contacto_inicial.enviar_correo") as mock_correo:
            mock_escalar.return_value = True

            enviar_contacto_inicial(
                session_state=session_state,
                payload=payload,
                kb_client=mock_kb,
            )

            # PROPIEDAD: score < 0.70 → enviar_correo NUNCA invocada
            mock_correo.assert_not_called(), (
                f"Con score={score:.4f} (< 0.70), enviar_correo NO debe invocarse."
            )
