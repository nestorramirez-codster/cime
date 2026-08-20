"""
Property-Based Test — Propiedad 15: Contexto mínimo requerido en todo escalamiento.

Feature: agente-comercial-polizas
Property 15: Contexto mínimo requerido en todo escalamiento

**Validates: Requisito 6.9**

Para cualquier invocación de `escalar_humano`, verificar:
- `motivo != ""` (no vacío, no solo espacios)
- `estado_pipefy ∈ ESTADOS_VALIDOS_PIPEFY`

La función `escalar_humano` DEBE validar estos dos campos y lanzar ValueError
si no se cumplen. Esto garantiza que todo escalamiento llega al Equipo Comercial
con el contexto mínimo necesario para actuar.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.models.constants import ESTADOS_VALIDOS_PIPEFY
from src.models.data_models import DatosPoliza, Mensaje
from src.tools.escalation_tools import escalar_humano


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Motivos válidos: texto no vacío
_st_motivo_valido = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z", "P"), blacklist_characters="\x00"),
    min_size=3,
    max_size=200,
).filter(lambda s: bool(s.strip()))

# Motivos inválidos: vacío o solo whitespace
_st_motivo_invalido = st.one_of(
    st.just(""),
    st.text(
        alphabet=st.sampled_from([" ", "\t", "\n", "\r"]),
        min_size=1,
        max_size=20,
    ),
)

# Estados válidos de Pipefy
_st_estado_valido = st.sampled_from(sorted(ESTADOS_VALIDOS_PIPEFY))

# Estados inválidos de Pipefy: texto que NO pertenece al conjunto válido
_st_estado_invalido = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"), blacklist_characters="\x00"),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() not in ESTADOS_VALIDOS_PIPEFY and bool(s.strip()))

# DatosPoliza: siempre válido (no es lo que se testea aquí)
_st_datos_poliza = st.builds(
    DatosPoliza,
    poliza_id=st.from_regex(r"POL-20[0-9]{2}-[0-9]{3}", fullmatch=True),
    cliente_nombre=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z"), whitelist_characters=".-"),
        min_size=5,
        max_size=40,
    ).filter(lambda s: bool(s.strip())),
    cliente_email=st.from_regex(r"[a-z]{3,8}@[a-z]{3,6}\.(com|mx)", fullmatch=True),
    fecha_vencimiento=st.dates(min_value=date(2025, 1, 1), max_value=date(2030, 12, 31)),
    precio_renovacion=st.floats(min_value=1000.0, max_value=500_000.0, allow_nan=False, allow_infinity=False),
    equipo_nombre=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z"), whitelist_characters="-"),
        min_size=5,
        max_size=30,
    ).filter(lambda s: bool(s.strip())),
)

# Session IDs
_st_session_id = st.from_regex(r"sess-[a-z0-9]{6,10}", fullmatch=True)


# ===========================================================================
# PROPERTY TEST — Propiedad 15: Contexto mínimo en escalamiento
# ===========================================================================


class TestProperty15ContextoMinimoEscalamiento:
    """
    Feature: agente-comercial-polizas
    Property 15: Contexto mínimo requerido en todo escalamiento

    **Validates: Requisito 6.9**

    Para cualquier invocación de `escalar_humano`, verificar:
    - `motivo != ""` → aceptado
    - `estado_pipefy ∈ ESTADOS_VALIDOS_PIPEFY` → aceptado
    - `motivo vacío` → ValueError
    - `estado_pipefy inválido` → ValueError
    """

    # --- Caso positivo: inputs válidos → retorna True ---

    @given(
        motivo=_st_motivo_valido,
        estado_pipefy=_st_estado_valido,
        datos_poliza=_st_datos_poliza,
        session_id=_st_session_id,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_motivo_no_vacio_y_estado_valido_retorna_true(
        self,
        motivo: str,
        estado_pipefy: str,
        datos_poliza: DatosPoliza,
        session_id: str,
    ) -> None:
        """
        Req 6.9 — Con motivo no vacío y estado_pipefy válido, escalar_humano
        debe aceptar la invocación y retornar True (modo mock).
        """
        result = escalar_humano(
            motivo=motivo,
            historial=[],
            estado_pipefy=estado_pipefy,
            datos_poliza=datos_poliza,
            session_id=session_id,
        )

        assert result is True, (
            f"escalar_humano debería retornar True con inputs válidos.\n"
            f"motivo='{motivo}', estado_pipefy='{estado_pipefy}'"
        )

    # --- Caso negativo: motivo vacío → ValueError ---

    @given(
        motivo=_st_motivo_invalido,
        estado_pipefy=_st_estado_valido,
        datos_poliza=_st_datos_poliza,
        session_id=_st_session_id,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_motivo_vacio_lanza_valueerror(
        self,
        motivo: str,
        estado_pipefy: str,
        datos_poliza: DatosPoliza,
        session_id: str,
    ) -> None:
        """
        Req 6.9 — Con motivo vacío (cadena vacía o solo whitespace),
        escalar_humano DEBE lanzar ValueError.
        """
        with pytest.raises(ValueError, match="motivo"):
            escalar_humano(
                motivo=motivo,
                historial=[],
                estado_pipefy=estado_pipefy,
                datos_poliza=datos_poliza,
                session_id=session_id,
            )

    # --- Caso negativo: estado Pipefy inválido → ValueError ---

    @given(
        motivo=_st_motivo_valido,
        estado_pipefy=_st_estado_invalido,
        datos_poliza=_st_datos_poliza,
        session_id=_st_session_id,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_estado_pipefy_invalido_lanza_valueerror(
        self,
        motivo: str,
        estado_pipefy: str,
        datos_poliza: DatosPoliza,
        session_id: str,
    ) -> None:
        """
        Req 6.9 — Con estado_pipefy que NO pertenece a ESTADOS_VALIDOS_PIPEFY,
        escalar_humano DEBE lanzar ValueError.
        """
        with pytest.raises(ValueError, match="no es válido"):
            escalar_humano(
                motivo=motivo,
                historial=[],
                estado_pipefy=estado_pipefy,
                datos_poliza=datos_poliza,
                session_id=session_id,
            )

    # --- Caso negativo combinado: ambos inválidos → ValueError ---

    @given(
        motivo=_st_motivo_invalido,
        estado_pipefy=_st_estado_invalido,
        datos_poliza=_st_datos_poliza,
        session_id=_st_session_id,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_ambos_invalidos_lanza_valueerror(
        self,
        motivo: str,
        estado_pipefy: str,
        datos_poliza: DatosPoliza,
        session_id: str,
    ) -> None:
        """
        Req 6.9 — Con motivo vacío Y estado_pipefy inválido, escalar_humano
        DEBE lanzar ValueError (validación del motivo ocurre primero).
        """
        with pytest.raises(ValueError):
            escalar_humano(
                motivo=motivo,
                historial=[],
                estado_pipefy=estado_pipefy,
                datos_poliza=datos_poliza,
                session_id=session_id,
            )
