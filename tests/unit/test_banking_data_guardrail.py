"""
Property-Based Test — Propiedad 8: Invariante de datos bancarios por estado.

Para los 8 estados en los que NO aplica (todos excepto "Cliente interesado"
y "Depósito solicitado"), verifica que ningún correo generado contiene la
cadena de datos bancarios.

**Validates: Requirements 4.4, 9.2**

Framework: hypothesis + pytest
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

import pytest

from src.models.constants import ESTADOS_CON_DATOS_BANCARIOS, ESTADOS_VALIDOS_PIPEFY
from src.policy.guardrails import PolicyGuardrail, DATOS_BANCARIOS_CIME, _FRAGMENTOS_BANCARIOS


# ---------------------------------------------------------------------------
# Estrategias de generación
# ---------------------------------------------------------------------------

# Los 8 estados donde NO se permiten datos bancarios
ESTADOS_SIN_DATOS_BANCARIOS = sorted(ESTADOS_VALIDOS_PIPEFY - ESTADOS_CON_DATOS_BANCARIOS)

estados_no_bancarios = st.sampled_from(ESTADOS_SIN_DATOS_BANCARIOS)
estados_con_bancarios = st.sampled_from(sorted(ESTADOS_CON_DATOS_BANCARIOS))

# Cuerpos de correo que contienen datos bancarios
cuerpos_con_datos_bancarios = st.sampled_from([
    f"Por favor deposite a: {DATOS_BANCARIOS_CIME}",
    "CLABE: 012345678901234567 — Beneficiario: CIME Power Systems S.A. de C.V.",
    "Datos para depósito:\nBanco: BBVA | Cuenta: 0123456789 | CLABE: 012345678901234567",
    "La CLABE interbancaria es 012345678901234567. Favor de depositar a nombre de CIME Power Systems S.A. de C.V.",
    "Cuenta: 0123456789 en BBVA a nombre de CIME Power Systems S.A. de C.V.",
])

# Session IDs generados aleatoriamente
session_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=5,
    max_size=30,
).map(lambda s: f"sess-{s}")


# ---------------------------------------------------------------------------
# Property Test: Datos bancarios BLOQUEADOS en estados no autorizados
# ---------------------------------------------------------------------------


class TestInvarianteDatosBancariosPorEstado:
    """
    **Validates: Requirements 4.4, 9.2**

    Propiedad 8: Para los 8 estados en los que NO aplica (todos excepto
    "Cliente interesado" y "Depósito solicitado"), verifica que el guardrail
    bloquea cualquier correo que contenga datos bancarios.
    """

    @given(
        estado=estados_no_bancarios,
        cuerpo=cuerpos_con_datos_bancarios,
        session_id=session_ids,
    )
    @settings(max_examples=100, deadline=5000)
    def test_datos_bancarios_bloqueados_en_estados_no_autorizados(
        self, estado: str, cuerpo: str, session_id: str
    ) -> None:
        """
        Para cualquier Estado_Pipefy distinto a 'Cliente interesado' o
        'Depósito solicitado', enviar_correo con datos bancarios debe ser
        bloqueado por el guardrail.

        **Validates: Requirements 4.4, 9.2**
        """
        guardrail = PolicyGuardrail()
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": cuerpo},
            session_state={
                "session_id": session_id,
                "estado_pipefy": estado,
            },
        )

        # El guardrail DEBE bloquear
        assert result.bloqueado, (
            f"Datos bancarios NO fueron bloqueados en estado '{estado}'. "
            f"Cuerpo contenía: {cuerpo[:80]}..."
        )
        assert "Datos bancarios" in result.motivo_bloqueo
        assert result.tool_call_intentado == "enviar_correo"
        assert result.estado_pipefy == estado

    @given(
        estado=estados_con_bancarios,
        cuerpo=cuerpos_con_datos_bancarios,
        session_id=session_ids,
    )
    @settings(max_examples=50, deadline=5000)
    def test_datos_bancarios_permitidos_en_estados_autorizados(
        self, estado: str, cuerpo: str, session_id: str
    ) -> None:
        """
        Para 'Cliente interesado' y 'Depósito solicitado', enviar_correo con
        datos bancarios NO debe ser bloqueado.

        **Validates: Requirements 4.4, 9.2**
        """
        guardrail = PolicyGuardrail()
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": cuerpo},
            session_state={
                "session_id": session_id,
                "estado_pipefy": estado,
            },
        )

        # El guardrail NO debe bloquear
        assert not result.bloqueado, (
            f"Datos bancarios fueron bloqueados INCORRECTAMENTE en estado "
            f"'{estado}' (debe estar permitido). Motivo: {result.motivo_bloqueo}"
        )


# ---------------------------------------------------------------------------
# Tests unitarios complementarios para el invariante de datos bancarios
# ---------------------------------------------------------------------------


class TestDatosBancariosDeteccion:
    """Verifica que la detección de datos bancarios funciona correctamente."""

    def test_clabe_completa_detectada(self) -> None:
        """CLABE de 18 dígitos debe ser detectada como dato bancario."""
        guardrail = PolicyGuardrail()
        assert guardrail._contiene_datos_bancarios("CLABE: 012345678901234567")

    def test_cuenta_10_digitos_detectada(self) -> None:
        """Cuenta de 10 dígitos con mención explícita debe ser detectada."""
        guardrail = PolicyGuardrail()
        assert guardrail._contiene_datos_bancarios("Cuenta: 0123456789")

    def test_beneficiario_cime_detectado(self) -> None:
        """Mención de beneficiario CIME debe ser detectada."""
        guardrail = PolicyGuardrail()
        assert guardrail._contiene_datos_bancarios(
            "Beneficiario: CIME Power Systems S.A. de C.V."
        )

    def test_texto_sin_datos_bancarios(self) -> None:
        """Texto normal sin datos bancarios no debe activar la detección."""
        guardrail = PolicyGuardrail()
        assert not guardrail._contiene_datos_bancarios(
            "Estimado cliente, le recordamos renovar su póliza de mantenimiento."
        )

    def test_fragmentos_bancarios_individuales(self) -> None:
        """Cada fragmento bancario debe ser detectado individualmente."""
        guardrail = PolicyGuardrail()
        for fragmento in _FRAGMENTOS_BANCARIOS:
            assert guardrail._contiene_datos_bancarios(fragmento), (
                f"Fragmento bancario no detectado: {fragmento}"
            )

    @pytest.mark.parametrize("estado", sorted(ESTADOS_VALIDOS_PIPEFY - ESTADOS_CON_DATOS_BANCARIOS))
    def test_cada_estado_no_autorizado_bloquea(self, estado: str) -> None:
        """Verifica explícitamente cada uno de los 8 estados no autorizados."""
        guardrail = PolicyGuardrail()
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": DATOS_BANCARIOS_CIME},
            session_state={
                "session_id": "sess-test-parametrize",
                "estado_pipefy": estado,
            },
        )
        assert result.bloqueado, f"Estado '{estado}' no bloqueó datos bancarios"
