"""
Property-Based Test — Propiedad 2: Idempotencia de activación en estados bloqueantes.

Feature: agente-comercial-polizas
Property 2: Idempotencia de activación en estados bloqueantes

**Validates: Requirements 1.6**

Para cualquier póliza con Estado_Pipefy ∈ {"Renovación confirmada", "Escalado a humano"},
invocar el agente N veces con el mismo payload debe producir el mismo estado final
(sin cambios) y cero correos enviados al cliente.

`f(activar_agente(póliza_bloqueante)) = Estado_Pipefy_sin_cambio` para todo N >= 1.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.session import iniciar_sesion
from src.models.constants import ESTADOS_BLOQUEANTES
from src.models.data_models import ActivationPayload, PipelineCard


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Estados bloqueantes: elegir uno de los dos
_st_estado_bloqueante = st.sampled_from(sorted(ESTADOS_BLOQUEANTES))

# Número de invocaciones consecutivas del agente (N >= 1)
_st_num_invocaciones = st.integers(min_value=1, max_value=10)

# Campos de texto no vacíos para el payload
_st_texto_no_vacio = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: bool(s.strip()))

# Email válido simple
_st_email = st.from_regex(
    r"[a-z]{3,10}\@[a-z]{3,8}\.[a-z]{2,4}", fullmatch=True
)

# Precio de renovación positivo
_st_precio_positivo = st.floats(
    min_value=1000.0,
    max_value=500_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Fecha de vencimiento
_st_fecha = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2030, 12, 31),
)

# Session ID generado
_st_session_id = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=5,
    max_size=20,
).map(lambda s: f"sess-{s}")


# ===========================================================================
# PROPERTY TEST — Propiedad 2: Idempotencia de activación en estados bloqueantes
# ===========================================================================


class TestProperty2IdempotenciaEstadosBloqueantes:
    """
    Feature: agente-comercial-polizas
    Property 2: Idempotencia de activación en estados bloqueantes

    **Validates: Requirements 1.6**

    Para pólizas con Estado_Pipefy ∈ {"Renovación confirmada", "Escalado a humano"},
    invocar el agente N veces debe producir cero cambios de estado y cero correos enviados.
    """

    @given(
        estado_bloqueante=_st_estado_bloqueante,
        num_invocaciones=_st_num_invocaciones,
        cliente_nombre=_st_texto_no_vacio,
        cliente_email=_st_email,
        equipo_nombre=_st_texto_no_vacio,
        precio=_st_precio_positivo,
        fecha=_st_fecha,
        session_id=_st_session_id,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_invocaciones_multiples_no_cambian_estado_ni_envian_correo(
        self,
        mock_consultar_pipefy: MagicMock,
        mock_actualizar_pipefy: MagicMock,
        mock_guardar_estado: MagicMock,
        estado_bloqueante: str,
        num_invocaciones: int,
        cliente_nombre: str,
        cliente_email: str,
        equipo_nombre: str,
        precio: float,
        fecha: date,
        session_id: str,
    ) -> None:
        """
        Req 1.6 — Para cada estado bloqueante, invocar iniciar_sesion N veces
        debe resultar en:
        - 0 llamadas a actualizar_pipefy (no se cambia estado)
        - 0 llamadas a enviar_correo (no se envían correos)
        - Todas las respuestas con success=False y reason="estado_bloqueante"
        """
        # Configurar mock de consultar_pipefy para retornar estado bloqueante
        card_bloqueante = PipelineCard(
            poliza_id="POL-PROP2-TEST",
            estado_actual=estado_bloqueante,
            cliente_nombre=cliente_nombre,
            cliente_email=cliente_email,
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[],
        )
        mock_consultar_pipefy.return_value = card_bloqueante

        # Construir payload válido
        payload = ActivationPayload(
            poliza_id="POL-PROP2-TEST",
            cliente_nombre=cliente_nombre,
            cliente_email=cliente_email,
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
        )

        # Invocar iniciar_sesion N veces
        resultados = []
        with patch("src.agent.session.escalar_humano") as mock_escalar:
            mock_escalar.return_value = True

            for i in range(num_invocaciones):
                # Reset mocks para cada invocación para contar de forma acumulada
                resultado = iniciar_sesion(payload, f"{session_id}-{i}")
                resultados.append(resultado)

        # --- VERIFICACIÓN DE LA PROPIEDAD ---

        # 1. Todas las invocaciones retornan failure por estado bloqueante
        for i, resultado in enumerate(resultados):
            assert resultado["success"] is False, (
                f"VIOLACIÓN Req 1.6: Invocación {i+1}/{num_invocaciones} "
                f"con estado bloqueante '{estado_bloqueante}' retornó success=True"
            )
            assert resultado["reason"] == "estado_bloqueante", (
                f"VIOLACIÓN Req 1.6: Invocación {i+1}/{num_invocaciones} "
                f"retornó reason='{resultado['reason']}' en vez de 'estado_bloqueante'"
            )

        # 2. actualizar_pipefy NUNCA fue invocado (0 cambios de estado)
        assert mock_actualizar_pipefy.call_count == 0, (
            f"VIOLACIÓN Req 1.6: actualizar_pipefy fue invocado "
            f"{mock_actualizar_pipefy.call_count} veces con estado bloqueante "
            f"'{estado_bloqueante}' en {num_invocaciones} invocaciones. "
            f"Debería ser 0 (no se cambia estado)."
        )

        # 3. guardar_estado_sesion NUNCA fue invocado (no se persiste sesión)
        assert mock_guardar_estado.call_count == 0, (
            f"VIOLACIÓN Req 1.6: guardar_estado_sesion fue invocado "
            f"{mock_guardar_estado.call_count} veces con estado bloqueante "
            f"'{estado_bloqueante}'. Debería ser 0."
        )
