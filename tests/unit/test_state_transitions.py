"""
Property-Based Test — Propiedad 16: Invariante de estados válidos en Pipefy.

Feature: agente-comercial-polizas
Property 16: Invariante de estados válidos en Pipefy

**Validates: Requirements 7.1, 9.4**

Para N secuencias de eventos generados, verificar que TODOS los estados registrados
pertenecen a `ESTADOS_VALIDOS_PIPEFY`. Ningún tool call puede registrar un estado
fuera de este conjunto.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.session import iniciar_sesion
from src.models.constants import ESTADOS_BLOQUEANTES, ESTADOS_VALIDOS_PIPEFY
from src.models.data_models import ActivationPayload, PipelineCard


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Estados no bloqueantes (para que la sesión avance y genere transiciones)
_ESTADOS_NO_BLOQUEANTES = sorted(ESTADOS_VALIDOS_PIPEFY - ESTADOS_BLOQUEANTES)

_st_estado_no_bloqueante = st.sampled_from(_ESTADOS_NO_BLOQUEANTES)

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

# Número de eventos/sesiones a simular
_st_num_eventos = st.integers(min_value=1, max_value=5)


# ===========================================================================
# PROPERTY TEST — Propiedad 16: Invariante de estados válidos en Pipefy
# ===========================================================================


class TestProperty16InvarianteEstadosValidos:
    """
    Feature: agente-comercial-polizas
    Property 16: Invariante de estados válidos en Pipefy

    **Validates: Requirements 7.1, 9.4**

    Para N secuencias de eventos generados, verificar que TODOS los estados
    registrados mediante actualizar_pipefy pertenecen a ESTADOS_VALIDOS_PIPEFY.
    """

    @given(
        estado_inicial=_st_estado_no_bloqueante,
        num_eventos=_st_num_eventos,
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
    def test_todos_los_estados_registrados_son_validos(
        self,
        mock_consultar_pipefy: MagicMock,
        mock_actualizar_pipefy: MagicMock,
        mock_guardar_estado: MagicMock,
        estado_inicial: str,
        num_eventos: int,
        cliente_nombre: str,
        cliente_email: str,
        equipo_nombre: str,
        precio: float,
        fecha: date,
        session_id: str,
    ) -> None:
        """
        Reqs 7.1, 9.4 — Captura todos los estados pasados a actualizar_pipefy
        durante N ejecuciones de iniciar_sesion y verifica que cada uno
        pertenece a ESTADOS_VALIDOS_PIPEFY.
        """
        # Almacén para capturar todos los estados registrados
        estados_registrados: List[str] = []

        def _capturar_estado(*args, **kwargs) -> bool:
            """Side effect que captura el estado pasado a actualizar_pipefy."""
            estado = kwargs.get("estado") or (args[1] if len(args) > 1 else None)
            if estado is not None:
                estados_registrados.append(estado)
            return True

        mock_actualizar_pipefy.side_effect = _capturar_estado

        # Configurar mock de consultar_pipefy con estado no-bloqueante
        # y datos consistentes con el payload (sin discrepancias)
        card = PipelineCard(
            poliza_id="POL-PROP16-TEST",
            estado_actual=estado_inicial,
            cliente_nombre=cliente_nombre,
            cliente_email=cliente_email,
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[],
        )
        mock_consultar_pipefy.return_value = card

        # Construir payload válido consistente con la card
        payload = ActivationPayload(
            poliza_id="POL-PROP16-TEST",
            cliente_nombre=cliente_nombre,
            cliente_email=cliente_email,
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
        )

        # Ejecutar iniciar_sesion N veces para generar transiciones de estado
        for i in range(num_eventos):
            iniciar_sesion(payload, f"{session_id}-{i}")

        # --- VERIFICACIÓN DE LA PROPIEDAD ---

        # Todos los estados registrados deben pertenecer a ESTADOS_VALIDOS_PIPEFY
        for estado in estados_registrados:
            assert estado in ESTADOS_VALIDOS_PIPEFY, (
                f"VIOLACIÓN Reqs 7.1, 9.4: Se registró estado '{estado}' "
                f"que NO pertenece a ESTADOS_VALIDOS_PIPEFY.\n"
                f"Estados válidos: {sorted(ESTADOS_VALIDOS_PIPEFY)}\n"
                f"Todos los estados capturados: {estados_registrados}"
            )

    @given(
        estado_bloqueante=st.sampled_from(sorted(ESTADOS_BLOQUEANTES)),
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
    def test_estado_bloqueante_no_genera_transiciones_invalidas(
        self,
        mock_consultar_pipefy: MagicMock,
        mock_actualizar_pipefy: MagicMock,
        mock_guardar_estado: MagicMock,
        estado_bloqueante: str,
        cliente_nombre: str,
        cliente_email: str,
        equipo_nombre: str,
        precio: float,
        fecha: date,
        session_id: str,
    ) -> None:
        """
        Reqs 7.1, 9.4 — Con estado bloqueante, no se deben registrar
        transiciones de estado. Verifica que actualizar_pipefy no es
        invocado con ningún estado (válido o inválido).
        """
        # Configurar mock de consultar_pipefy con estado bloqueante
        card = PipelineCard(
            poliza_id="POL-PROP16-BLQ",
            estado_actual=estado_bloqueante,
            cliente_nombre=cliente_nombre,
            cliente_email=cliente_email,
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[],
        )
        mock_consultar_pipefy.return_value = card

        # Construir payload válido
        payload = ActivationPayload(
            poliza_id="POL-PROP16-BLQ",
            cliente_nombre=cliente_nombre,
            cliente_email=cliente_email,
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
        )

        # Ejecutar sesión
        resultado = iniciar_sesion(payload, session_id)

        # --- VERIFICACIÓN ---
        # Con estado bloqueante, no se invoca actualizar_pipefy en absoluto
        assert mock_actualizar_pipefy.call_count == 0, (
            f"VIOLACIÓN Reqs 7.1, 9.4: actualizar_pipefy fue invocado "
            f"{mock_actualizar_pipefy.call_count} veces con estado bloqueante "
            f"'{estado_bloqueante}'. No debería haber transiciones."
        )

        assert resultado["success"] is False
        assert resultado["reason"] == "estado_bloqueante"
