"""
Tests unitarios para la configuración del Agente Comercial IA.

Verifica:
- System prompt contiene las restricciones absolutas
- Las 5 tools están registradas correctamente
- Configuración del modelo Bedrock (región, model_id)
- Factory function crear_agente() opera correctamente

Requisitos: 12.4, 12.5, 9.1, 9.2, 9.3
"""

import os

import pytest


# Forzar modo mock antes de importar el módulo del agente
os.environ["CIME_MOCK_MODE"] = "true"

from src.agent.agent import (
    AGENT_TOOLS,
    SYSTEM_PROMPT,
    _BEDROCK_REGION,
    _MODEL_ID,
    crear_agente,
    obtener_agente,
)


# ---------------------------------------------------------------------------
# Tests del System Prompt (Req 9.1, 9.2, 9.3)
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    """Verifica que el system prompt contiene las restricciones del diseño."""

    def test_system_prompt_no_vacio(self):
        """El system prompt debe existir y no estar vacío."""
        assert SYSTEM_PROMPT
        assert len(SYSTEM_PROMPT) > 100

    def test_identidad_cime(self):
        """El prompt debe identificar al agente como asesor de CIME Power Systems."""
        assert "CIME Power Systems" in SYSTEM_PROMPT

    def test_idioma_espanol_mexicano(self):
        """El prompt debe especificar idioma español mexicano formal."""
        assert "Español mexicano formal" in SYSTEM_PROMPT

    def test_restriccion_descuento_5_porciento(self):
        """Restricción absoluta: solo descuento del 5%."""
        assert "5%" in SYSTEM_PROMPT
        assert "único descuento autorizado" in SYSTEM_PROMPT.lower() or \
               "El único descuento autorizado es el 5%" in SYSTEM_PROMPT

    def test_restriccion_datos_bancarios(self):
        """Restricción: datos bancarios solo en estados permitidos."""
        assert "Cliente interesado" in SYSTEM_PROMPT
        assert "Depósito solicitado" in SYSTEM_PROMPT

    def test_restriccion_no_diagnostico_tecnico(self):
        """Restricción: no ofrecer diagnóstico técnico."""
        assert "diagnóstico técnico" in SYSTEM_PROMPT

    def test_restriccion_escalamiento_inmediato(self):
        """Restricción: escalar inmediatamente si el cliente pide asesor humano."""
        assert "INMEDIATAMENTE" in SYSTEM_PROMPT

    def test_restriccion_precios_knowledge_base(self):
        """Restricción: precios solo de la Knowledge Base."""
        assert "Knowledge Base" in SYSTEM_PROMPT
        assert "Nunca inventes precios" in SYSTEM_PROMPT

    def test_restriccion_score_minimo_kb(self):
        """Restricción: escalar si KB score < 0.7."""
        assert "0.7" in SYSTEM_PROMPT

    def test_flujo_general_presente(self):
        """El prompt debe contener la descripción del flujo general."""
        assert "FLUJO GENERAL" in SYSTEM_PROMPT
        assert "Validar payload" in SYSTEM_PROMPT
        assert "Notificar Tesorería" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Tests de registro de Tools (Req 12.4, 12.5)
# ---------------------------------------------------------------------------


class TestToolsRegistration:
    """Verifica que las 5 tools MCP están registradas correctamente."""

    def test_cinco_tools_registradas(self):
        """Deben existir exactamente 5 tools registradas."""
        assert len(AGENT_TOOLS) == 5

    def test_tool_consultar_pipefy_presente(self):
        """Tool consultar_pipefy debe estar en la lista."""
        tool_names = [t.__name__ for t in AGENT_TOOLS]
        assert "consultar_pipefy" in tool_names

    def test_tool_actualizar_pipefy_presente(self):
        """Tool actualizar_pipefy debe estar en la lista."""
        tool_names = [t.__name__ for t in AGENT_TOOLS]
        assert "actualizar_pipefy" in tool_names

    def test_tool_enviar_correo_presente(self):
        """Tool enviar_correo debe estar en la lista."""
        tool_names = [t.__name__ for t in AGENT_TOOLS]
        assert "enviar_correo" in tool_names

    def test_tool_notificar_tesoreria_presente(self):
        """Tool notificar_tesoreria debe estar en la lista."""
        tool_names = [t.__name__ for t in AGENT_TOOLS]
        assert "notificar_tesoreria" in tool_names

    def test_tool_escalar_humano_presente(self):
        """Tool escalar_humano debe estar en la lista."""
        tool_names = [t.__name__ for t in AGENT_TOOLS]
        assert "escalar_humano" in tool_names


# ---------------------------------------------------------------------------
# Tests de configuración del modelo Bedrock
# ---------------------------------------------------------------------------


class TestBedrockConfig:
    """Verifica la configuración del modelo fundacional."""

    def test_region_us_east_1(self):
        """La región por defecto debe ser us-east-1."""
        assert _BEDROCK_REGION == "us-east-1"

    def test_model_id_claude_sonnet_35(self):
        """El modelo debe ser Claude Sonnet 3.5."""
        assert "claude-3-5-sonnet" in _MODEL_ID
        assert "anthropic" in _MODEL_ID

    def test_model_id_formato_bedrock(self):
        """El model_id debe seguir el formato de Bedrock."""
        # Formato: provider.model-name-version
        assert "." in _MODEL_ID


# ---------------------------------------------------------------------------
# Tests de la factory function
# ---------------------------------------------------------------------------


class TestCrearAgente:
    """Verifica que la factory function crea el agente correctamente."""

    def test_crear_agente_retorna_agent(self):
        """crear_agente() debe retornar una instancia de Agent."""
        from strands import Agent

        agent = crear_agente()
        assert isinstance(agent, Agent)

    def test_crear_agente_con_prompt_personalizado(self):
        """crear_agente() debe aceptar un system_prompt personalizado."""
        from strands import Agent

        custom_prompt = "Eres un agente de prueba."
        agent = crear_agente(system_prompt=custom_prompt)
        assert isinstance(agent, Agent)

    def test_obtener_agente_singleton(self):
        """obtener_agente() debe retornar la misma instancia en llamadas sucesivas."""
        # Reset del singleton para el test
        import src.agent.agent as agent_module
        agent_module._agente_instance = None

        agent1 = obtener_agente()
        agent2 = obtener_agente()
        assert agent1 is agent2

        # Cleanup
        agent_module._agente_instance = None
