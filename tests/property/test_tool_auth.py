"""
Property-Based Test — Propiedad 23: Autenticación exclusiva de credenciales por tool.

Feature: agente-comercial-polizas
Property 23: Autenticación exclusiva de credenciales por tool

**Validates: Requirements 12.8**

Para cualquier par de tools distintas (tool_X, tool_Y), invocar tool_X con
credenciales de tool_Y debe retornar un error de autorización y la tool
NO debe ejecutarse.

`tool_X.credenciales != tool_Y.credenciales` para todo par (X, Y) donde X != Y.

El mapeo de credenciales del sistema (AgentCore Identity):
  - consultar_pipefy / actualizar_pipefy → cime/pipefy/api-token
  - enviar_correo → cime/ses/smtp-credentials
  - notificar_tesoreria → cime/tesoreria/endpoint-key
  - escalar_humano → cime/comercial/slack-webhook
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Set

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Modelo de autenticación de credenciales por tool (AgentCore Identity)
# ---------------------------------------------------------------------------

# Mapeo oficial: tool → secreto asignado (de agentcore_identity_config.yaml)
TOOL_CREDENTIAL_MAP: Dict[str, str] = {
    "consultar_pipefy": "cime/pipefy/api-token",
    "actualizar_pipefy": "cime/pipefy/api-token",
    "enviar_correo": "cime/ses/smtp-credentials",
    "notificar_tesoreria": "cime/tesoreria/endpoint-key",
    "escalar_humano": "cime/comercial/slack-webhook",
}

# Conjunto de todas las tools del sistema
ALL_TOOLS: list[str] = sorted(TOOL_CREDENTIAL_MAP.keys())

# Conjunto de todos los secretos disponibles
ALL_SECRETS: list[str] = sorted(set(TOOL_CREDENTIAL_MAP.values()))


class AuthorizationError(Exception):
    """Error de autorización cuando una tool es invocada con credenciales incorrectas."""

    def __init__(self, tool_name: str, secret_provided: str, secret_expected: str):
        self.tool_name = tool_name
        self.secret_provided = secret_provided
        self.secret_expected = secret_expected
        super().__init__(
            f"AuthorizationError: tool '{tool_name}' requiere secreto "
            f"'{secret_expected}' pero recibió '{secret_provided}'"
        )


class ToolCredentialRegistry:
    """
    Registro de credenciales por tool que modela el comportamiento de
    AgentCore Identity (Req 12.8).

    Cada tool tiene asignado un secreto exclusivo. Una invocación con
    credenciales de otra tool debe ser rechazada con AuthorizationError.
    """

    def __init__(self, credential_map: Dict[str, str]) -> None:
        self._credential_map = credential_map

    @property
    def tools(self) -> list[str]:
        """Lista de tools registradas."""
        return sorted(self._credential_map.keys())

    @property
    def secrets(self) -> list[str]:
        """Lista de secretos únicos disponibles."""
        return sorted(set(self._credential_map.values()))

    def get_assigned_secret(self, tool_name: str) -> str:
        """Retorna el secreto asignado a una tool."""
        if tool_name not in self._credential_map:
            raise ValueError(f"Tool '{tool_name}' no está registrada")
        return self._credential_map[tool_name]

    def authorize_tool_call(self, tool_name: str, secret_provided: str) -> bool:
        """
        Autoriza la invocación de una tool con un secreto dado.

        Args:
            tool_name: Nombre de la tool a invocar.
            secret_provided: Secreto proporcionado para la autenticación.

        Returns:
            True si la autorización es exitosa.

        Raises:
            AuthorizationError: Si el secreto proporcionado no coincide
                con el secreto asignado a la tool.
            ValueError: Si la tool no está registrada.
        """
        if tool_name not in self._credential_map:
            raise ValueError(f"Tool '{tool_name}' no está registrada")

        expected_secret = self._credential_map[tool_name]

        if secret_provided != expected_secret:
            raise AuthorizationError(
                tool_name=tool_name,
                secret_provided=secret_provided,
                secret_expected=expected_secret,
            )

        return True


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Estrategia: seleccionar una tool del sistema
_st_tool = st.sampled_from(ALL_TOOLS)

# Estrategia: seleccionar un secreto del sistema
_st_secret = st.sampled_from(ALL_SECRETS)

# Estrategia: par (tool, secreto incorrecto) — donde el secreto NO es el asignado
_st_tool_with_wrong_credential = st.tuples(_st_tool, _st_secret).filter(
    lambda pair: pair[1] != TOOL_CREDENTIAL_MAP[pair[0]]
)

# Estrategia: par (tool, secreto correcto) — donde el secreto SÍ es el asignado
_st_tool_with_correct_credential = _st_tool.map(
    lambda tool: (tool, TOOL_CREDENTIAL_MAP[tool])
)


# ===========================================================================
# PROPERTY TEST — Propiedad 23: Autenticación exclusiva de credenciales por tool
# ===========================================================================


class TestProperty23AutenticacionExclusivaCredenciales:
    """
    Feature: agente-comercial-polizas
    Property 23: Autenticación exclusiva de credenciales por tool

    **Validates: Requirements 12.8**

    Para cada par de tools distintas (X, Y), verificar que invocar tool_X
    con credenciales de tool_Y retorna error de autorización y la tool
    NO se ejecuta.
    """

    @given(tool_and_wrong_secret=_st_tool_with_wrong_credential)
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_tool_con_credencial_ajena_retorna_authorization_error(
        self,
        tool_and_wrong_secret: tuple[str, str],
    ) -> None:
        """
        Req 12.8 — Para cualquier par (tool_X, credencial_Y) donde Y no es
        la credencial asignada a X, el sistema debe rechazar la invocación
        con AuthorizationError.

        Verifica que:
        1. Se lanza AuthorizationError (no se ejecuta la tool)
        2. El error contiene el nombre de la tool rechazada
        3. El error identifica la credencial incorrecta proporcionada
        4. El error indica la credencial esperada
        """
        tool_name, wrong_secret = tool_and_wrong_secret
        registry = ToolCredentialRegistry(TOOL_CREDENTIAL_MAP)

        # La credencial proporcionada NO debe ser la asignada a la tool
        assert wrong_secret != TOOL_CREDENTIAL_MAP[tool_name], (
            f"Error en la estrategia: el secreto '{wrong_secret}' SÍ es el "
            f"asignado a '{tool_name}'"
        )

        # Invocar la tool con credencial ajena DEBE lanzar AuthorizationError
        with pytest.raises(AuthorizationError) as exc_info:
            registry.authorize_tool_call(tool_name, wrong_secret)

        # Verificar que el error contiene información útil para diagnóstico
        error = exc_info.value
        assert error.tool_name == tool_name, (
            f"AuthorizationError no identifica la tool correcta: "
            f"esperado '{tool_name}', obtenido '{error.tool_name}'"
        )
        assert error.secret_provided == wrong_secret, (
            f"AuthorizationError no identifica la credencial proporcionada: "
            f"esperado '{wrong_secret}', obtenido '{error.secret_provided}'"
        )
        assert error.secret_expected == TOOL_CREDENTIAL_MAP[tool_name], (
            f"AuthorizationError no indica la credencial esperada correcta"
        )

    @given(tool_and_correct_secret=_st_tool_with_correct_credential)
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_tool_con_credencial_propia_autoriza_exitosamente(
        self,
        tool_and_correct_secret: tuple[str, str],
    ) -> None:
        """
        Complemento de Req 12.8 — Verificar que una tool invocada con su
        credencial asignada SÍ se autoriza correctamente (no genera
        falsos positivos de rechazo).

        Esto garantiza que el mecanismo de autorización no es demasiado
        restrictivo (solo rechaza credenciales ajenas, no las propias).
        """
        tool_name, correct_secret = tool_and_correct_secret
        registry = ToolCredentialRegistry(TOOL_CREDENTIAL_MAP)

        # Verificar que es realmente la credencial correcta
        assert correct_secret == TOOL_CREDENTIAL_MAP[tool_name]

        # La invocación con credencial propia DEBE ser exitosa
        result = registry.authorize_tool_call(tool_name, correct_secret)
        assert result is True, (
            f"Tool '{tool_name}' fue rechazada con su propia credencial "
            f"'{correct_secret}' — falso positivo de autorización"
        )

    @given(
        tool_x=_st_tool,
        tool_y=_st_tool,
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_pares_de_tools_con_credenciales_cruzadas(
        self,
        tool_x: str,
        tool_y: str,
    ) -> None:
        """
        Req 12.8 — Para cualquier par de tools (X, Y), si X != Y y sus
        credenciales asignadas son diferentes, invocar tool_X con la
        credencial de tool_Y debe fallar.

        Si X == Y o comparten credencial (consultar_pipefy y actualizar_pipefy
        ambas usan cime/pipefy/api-token), la invocación debe ser exitosa.
        """
        registry = ToolCredentialRegistry(TOOL_CREDENTIAL_MAP)

        credential_of_y = TOOL_CREDENTIAL_MAP[tool_y]
        expected_credential_of_x = TOOL_CREDENTIAL_MAP[tool_x]

        if credential_of_y == expected_credential_of_x:
            # Misma credencial → autorización exitosa (ej: consultar_pipefy
            # invocada con credencial de actualizar_pipefy, ambas usan
            # cime/pipefy/api-token)
            result = registry.authorize_tool_call(tool_x, credential_of_y)
            assert result is True, (
                f"Tool '{tool_x}' debería aceptar credencial '{credential_of_y}' "
                f"(es su credencial asignada), pero fue rechazada"
            )
        else:
            # Credencial diferente → debe rechazar con AuthorizationError
            with pytest.raises(AuthorizationError) as exc_info:
                registry.authorize_tool_call(tool_x, credential_of_y)

            error = exc_info.value
            assert error.tool_name == tool_x
            assert error.secret_provided == credential_of_y
            assert error.secret_expected == expected_credential_of_x

    def test_exhaustivo_todas_las_combinaciones_invalidas(self) -> None:
        """
        Test exhaustivo determinístico: verifica TODAS las combinaciones
        (tool, credencial_incorrecta) del sistema para garantizar cobertura
        completa del mapeo definido en AgentCore Identity.

        Este test complementa el property test con una verificación
        determinística de las 5 tools × 4 secretos = 20 combinaciones
        posibles (menos las correctas).
        """
        registry = ToolCredentialRegistry(TOOL_CREDENTIAL_MAP)
        combinaciones_rechazadas = 0

        for tool_name in ALL_TOOLS:
            assigned_secret = TOOL_CREDENTIAL_MAP[tool_name]

            for secret in ALL_SECRETS:
                if secret == assigned_secret:
                    # Credencial propia → debe autorizar
                    result = registry.authorize_tool_call(tool_name, secret)
                    assert result is True, (
                        f"Tool '{tool_name}' rechazada con su propia credencial"
                    )
                else:
                    # Credencial ajena → debe rechazar
                    with pytest.raises(AuthorizationError):
                        registry.authorize_tool_call(tool_name, secret)
                    combinaciones_rechazadas += 1

        # Verificar que se probaron combinaciones inválidas
        # 5 tools × 4 secretos = 20 combinaciones totales
        # Menos las válidas: 2 tools comparten pipefy-token + 3 tools con
        # secreto único = 5 combinaciones válidas
        # → 20 - 5 = 15 combinaciones que deben ser rechazadas
        assert combinaciones_rechazadas == 15, (
            f"Se esperaban 15 combinaciones inválidas rechazadas, "
            f"pero se encontraron {combinaciones_rechazadas}"
        )

    def test_tools_con_credencial_compartida_se_autorizan_mutuamente(
        self,
    ) -> None:
        """
        Caso especial: consultar_pipefy y actualizar_pipefy comparten
        el secreto 'cime/pipefy/api-token'. Verificar que ambas aceptan
        el mismo secreto (no son mutuamente excluyentes).
        """
        registry = ToolCredentialRegistry(TOOL_CREDENTIAL_MAP)
        shared_secret = "cime/pipefy/api-token"

        # Ambas tools deben aceptar el mismo secreto
        assert registry.authorize_tool_call("consultar_pipefy", shared_secret) is True
        assert registry.authorize_tool_call("actualizar_pipefy", shared_secret) is True

        # Pero ninguna otra tool debe aceptarlo
        for tool_name in ALL_TOOLS:
            if tool_name in ("consultar_pipefy", "actualizar_pipefy"):
                continue
            with pytest.raises(AuthorizationError):
                registry.authorize_tool_call(tool_name, shared_secret)

    def test_cada_tool_tiene_exactamente_un_secreto_asignado(self) -> None:
        """
        Invariante del diseño: cada tool tiene exactamente un secreto asignado
        en el mapeo de AgentCore Identity. No puede haber tools sin secreto
        ni tools con múltiples secretos.
        """
        registry = ToolCredentialRegistry(TOOL_CREDENTIAL_MAP)

        for tool_name in ALL_TOOLS:
            secret = registry.get_assigned_secret(tool_name)
            assert secret is not None and len(secret) > 0, (
                f"Tool '{tool_name}' no tiene secreto asignado"
            )
            assert secret in ALL_SECRETS, (
                f"Tool '{tool_name}' tiene un secreto '{secret}' "
                f"que no está en el conjunto de secretos del sistema"
            )
