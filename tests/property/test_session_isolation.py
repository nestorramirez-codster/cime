"""
Property-Based Test — Propiedad 22: Aislamiento de sesiones concurrentes.

Feature: agente-comercial-polizas
Property 22: Aislamiento de sesiones concurrentes

**Validates: Requirements 12.7**

Simular N pares de sesiones concurrentes con datos de pólizas distintos.
Verificar que `memory.get(session_id_A) ∩ memory.get(session_id_B) == ∅`
para todo par A ≠ B.

La capa de memoria de corto plazo (short_term) debe garantizar que los datos
de una sesión NUNCA se filtran a otra sesión. Cada llamada a
obtener_estado_sesion(session_id) solo retorna datos del session_id indicado.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from itertools import combinations
from typing import List

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.memory.short_term import (
    _reset_mock_store,
    guardar_estado_sesion,
    obtener_estado_sesion,
)
from src.models.constants import ESTADOS_VALIDOS_PIPEFY
from src.models.data_models import SessionState

# ---------------------------------------------------------------------------
# Configurar modo mock para tests
# ---------------------------------------------------------------------------

os.environ["CIME_MOCK_MODE"] = "true"

# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Generar session_id únicos usando UUIDs
_st_session_id = st.uuids().map(str)

# Generar poliza_id únicos usando prefijo + UUID
_st_poliza_id = st.uuids().map(lambda u: f"POL-{u}")

# Estado Pipefy válido
_st_estado_pipefy = st.sampled_from(sorted(ESTADOS_VALIDOS_PIPEFY))

# Timestamp de inicio
_st_timestamp = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2025, 12, 31),
    timezones=st.just(timezone.utc),
)


def _st_session_state(session_id_st, poliza_id_st):
    """Estrategia que genera un SessionState con session_id y poliza_id dados."""
    return st.builds(
        SessionState,
        session_id=session_id_st,
        poliza_id=poliza_id_st,
        estado_pipefy=_st_estado_pipefy,
        historial_mensajes=st.just([]),
        timestamp_inicio=_st_timestamp,
        datos_comprobante=st.none(),
    )


# Generar N sesiones con session_id y poliza_id únicos (N entre 2 y 10)
@st.composite
def _st_sesiones_concurrentes(draw):
    """Genera una lista de N sesiones con session_id y poliza_id todos distintos."""
    n = draw(st.integers(min_value=2, max_value=10))

    # Generar N session_ids únicos
    session_ids = [str(uuid.uuid4()) for _ in range(n)]

    # Generar N poliza_ids únicos
    poliza_ids = [f"POL-{uuid.uuid4()}" for _ in range(n)]

    sessions: List[SessionState] = []
    for i in range(n):
        estado = draw(_st_estado_pipefy)
        ts = draw(_st_timestamp)
        session = SessionState(
            session_id=session_ids[i],
            poliza_id=poliza_ids[i],
            estado_pipefy=estado,
            historial_mensajes=[],
            timestamp_inicio=ts,
            datos_comprobante=None,
        )
        sessions.append(session)

    return sessions


# ===========================================================================
# PROPERTY TEST — Propiedad 22: Aislamiento de sesiones concurrentes
# ===========================================================================


class TestProperty22AislamientoSesionesConcurrentes:
    """
    Feature: agente-comercial-polizas
    Property 22: Aislamiento de sesiones concurrentes

    **Validates: Requirements 12.7**

    Simular N pares de sesiones concurrentes con datos de pólizas distintos.
    Verificar que memory.get(session_id_A) ∩ memory.get(session_id_B) == ∅
    para todo par A ≠ B.
    """

    @given(sessions=_st_sesiones_concurrentes())
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_sesiones_concurrentes_datos_aislados(
        self,
        sessions: List[SessionState],
    ) -> None:
        """
        Req 12.7 — Para N sesiones almacenadas simultáneamente:
        1. Cada sesión se recupera correctamente con su propio session_id
        2. poliza_id de sesión A != poliza_id de sesión B para todo par A ≠ B
        3. Datos de sesión A nunca aparecen al consultar con session_id de B
        """
        # Limpiar el store antes de cada ejecución
        _reset_mock_store()

        # --- Almacenar todas las sesiones ---
        for session in sessions:
            result = guardar_estado_sesion(session)
            assert result is True, (
                f"Error al guardar sesión {session.session_id} (Req 12.7)"
            )

        # --- Recuperar cada sesión y verificar aislamiento ---
        retrieved_sessions: List[SessionState] = []
        for session in sessions:
            retrieved = obtener_estado_sesion(session.session_id)
            assert retrieved is not None, (
                f"Sesión {session.session_id} no encontrada tras guardarla "
                f"(Req 12.7). Se almacenaron {len(sessions)} sesiones."
            )
            retrieved_sessions.append(retrieved)

            # Verificar que los datos recuperados corresponden a la sesión original
            assert retrieved.session_id == session.session_id, (
                f"session_id recuperado '{retrieved.session_id}' no coincide "
                f"con el original '{session.session_id}' (Req 12.7)."
            )
            assert retrieved.poliza_id == session.poliza_id, (
                f"poliza_id recuperado '{retrieved.poliza_id}' no coincide "
                f"con el original '{session.poliza_id}' para session "
                f"'{session.session_id}' (Req 12.7)."
            )

        # --- Verificar aislamiento: intersección vacía entre pares ---
        for (i, sess_a), (j, sess_b) in combinations(enumerate(retrieved_sessions), 2):
            # poliza_id debe ser diferente entre sesiones distintas
            assert sess_a.poliza_id != sess_b.poliza_id, (
                f"Violación de aislamiento (Req 12.7): "
                f"session[{i}] (id={sess_a.session_id}) y "
                f"session[{j}] (id={sess_b.session_id}) "
                f"comparten poliza_id='{sess_a.poliza_id}'."
            )

            # session_id debe ser diferente
            assert sess_a.session_id != sess_b.session_id, (
                f"Violación de aislamiento (Req 12.7): "
                f"dos sesiones tienen el mismo session_id='{sess_a.session_id}'."
            )

    @given(sessions=_st_sesiones_concurrentes())
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_consulta_con_id_ajeno_no_retorna_datos_de_otra_sesion(
        self,
        sessions: List[SessionState],
    ) -> None:
        """
        Req 12.7 — Verificar que consultar con session_id de sesión B
        NUNCA retorna datos de sesión A. Específicamente:
        - obtener_estado_sesion(id_B).poliza_id != poliza_id de A
        - obtener_estado_sesion(id_B).session_id == id_B (no id_A)
        """
        # Limpiar el store antes de cada ejecución
        _reset_mock_store()

        # Almacenar todas las sesiones
        for session in sessions:
            guardar_estado_sesion(session)

        # Para cada par de sesiones, verificar que consultar con id de una
        # no retorna datos de la otra
        for i, sess_a in enumerate(sessions):
            for j, sess_b in enumerate(sessions):
                if i == j:
                    continue

                # Consultar con session_id de B
                retrieved_b = obtener_estado_sesion(sess_b.session_id)
                assert retrieved_b is not None

                # Los datos recuperados NO deben contener datos de A
                assert retrieved_b.poliza_id != sess_a.poliza_id, (
                    f"Violación de aislamiento (Req 12.7): "
                    f"Consultar con session_id de B ('{sess_b.session_id}') "
                    f"retornó poliza_id de A ('{sess_a.poliza_id}'). "
                    f"Esperado: '{sess_b.poliza_id}'."
                )
                assert retrieved_b.session_id == sess_b.session_id, (
                    f"Violación de aislamiento (Req 12.7): "
                    f"Consultar con session_id '{sess_b.session_id}' "
                    f"retornó session_id '{retrieved_b.session_id}'."
                )

    @given(sessions=_st_sesiones_concurrentes())
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_sesion_inexistente_retorna_none(
        self,
        sessions: List[SessionState],
    ) -> None:
        """
        Req 12.7 — Verificar que consultar con un session_id que NO fue
        almacenado retorna None, sin filtrar datos de sesiones existentes.
        """
        # Limpiar el store antes de cada ejecución
        _reset_mock_store()

        # Almacenar todas las sesiones
        for session in sessions:
            guardar_estado_sesion(session)

        # Generar un session_id que NO está en el store
        id_inexistente = f"inexistente-{uuid.uuid4()}"

        # Debe retornar None
        resultado = obtener_estado_sesion(id_inexistente)
        assert resultado is None, (
            f"Violación de aislamiento (Req 12.7): "
            f"Consultar con session_id inexistente '{id_inexistente}' "
            f"retornó datos: {resultado}. Esperado: None."
        )
