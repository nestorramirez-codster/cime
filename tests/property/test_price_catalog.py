"""
Property-Based Test — Propiedad 10: Consistencia precio-catálogo (model-based testing).

Feature: agente-comercial-polizas
Property 10: Consistencia precio-catálogo

**Validates: Requirements 4.2**

Estrategia:
- Cargar el catálogo de precios `docs/kb/catalogo_precios.json`
- Para cada combinación (tipo_equipo, plan_mantenimiento) del catálogo,
  generar un ActivationPayload con el precio correspondiente y verificar
  que `generar_cotizacion()` utiliza el precio correcto como `precio_base`.
- Se mock KBClient para retornar score suficiente (>= 0.70) para
  equipos conocidos del catálogo.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.flows.cotizacion import generar_cotizacion
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.constants import KB_SCORE_MINIMO
from src.models.data_models import ActivationPayload, SessionState

# ---------------------------------------------------------------------------
# Cargar catálogo de precios
# ---------------------------------------------------------------------------

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "docs" / "kb" / "catalogo_precios.json"

with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
    _CATALOGO = json.load(f)

# Construir lista de todas las combinaciones (tipo_equipo, plan, precio)
_COMBINACIONES: List[Tuple[str, str, float]] = []
for equipo in _CATALOGO["equipos"]:
    for plan, precio in equipo["precios"].items():
        _COMBINACIONES.append((equipo["tipo"], plan, precio))


# ---------------------------------------------------------------------------
# Helpers para mocking
# ---------------------------------------------------------------------------


def _crear_kb_client_mock(score: float = 0.85) -> KBClient:
    """Crea un KBClient mock que retorna score suficiente."""
    mock_client = MagicMock(spec=KBClient)
    mock_response = KBQueryResponse(
        results=[
            KBResult(
                content="[Precio del catálogo para el equipo solicitado]",
                score=score,
                source_uri="s3://cime-kb-documentos/catalogo_precios.json",
                metadata={"document": "catalogo_precios.json"},
            )
        ],
        query_text="precio catálogo equipo",
    )
    mock_client.query.return_value = mock_response
    return mock_client


def _crear_session_state(poliza_id: str = "POL-TEST-001") -> SessionState:
    """Crea un SessionState con estado 'Cliente interesado' para cotización."""
    return SessionState(
        session_id="sess-test-price-catalog",
        poliza_id=poliza_id,
        estado_pipefy="Cliente interesado",
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Estrategia Hypothesis: generar índice aleatorio en la lista de combinaciones
# ---------------------------------------------------------------------------

_st_combinacion_index = st.integers(min_value=0, max_value=len(_COMBINACIONES) - 1)


# ===========================================================================
# PROPERTY TESTS
# ===========================================================================


class TestProperty10ConsistenciaPrecioCatalogo:
    """
    Feature: agente-comercial-polizas
    Property 10: Consistencia precio-catálogo (model-based testing)

    **Validates: Requirements 4.2**

    Para cada combinación (tipo_equipo, plan_mantenimiento) del catálogo,
    verificar que `cotizacion.precio_base == knowledge_base.precio(tipo_equipo, plan)`.
    """

    @given(idx=_st_combinacion_index)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    @patch("src.agent.flows.cotizacion.enviar_correo")
    @patch("src.agent.flows.cotizacion.actualizar_pipefy")
    def test_precio_base_coincide_con_catalogo(
        self,
        mock_actualizar: MagicMock,
        mock_enviar: MagicMock,
        idx: int,
    ) -> None:
        """
        Para cualquier combinación (tipo_equipo, plan) del catálogo,
        el precio_base de la cotización generada debe ser exactamente
        el precio del catálogo (que llega como precio_renovacion en el payload).

        El flujo `generar_cotizacion()` usa `payload.precio_renovacion` como
        precio_base, verificando primero que la KB tiene score >= 0.70.
        """
        tipo_equipo, plan, precio_catalogo = _COMBINACIONES[idx]

        # Mock enviar_correo para simular envío exitoso
        mock_enviar.return_value = MagicMock(
            success=True,
            message_id="msg-test-123",
            timestamp=datetime.now(timezone.utc),
            error_code=None,
        )
        mock_actualizar.return_value = True

        # Crear payload con el precio del catálogo como precio_renovacion
        # (esto simula que Zapier envía el precio correcto del catálogo)
        payload = ActivationPayload(
            poliza_id=f"POL-CAT-{idx:03d}",
            cliente_nombre="Cliente Test Catálogo",
            cliente_email="test@catalogo.com",
            fecha_vencimiento=date.today() + timedelta(days=30),
            precio_renovacion=precio_catalogo,
            equipo_nombre=tipo_equipo,
        )

        session_state = _crear_session_state(payload.poliza_id)
        kb_client = _crear_kb_client_mock(score=0.85)

        # Ejecutar flujo de cotización
        resultado = generar_cotizacion(
            session_state=session_state,
            payload=payload,
            kb_client=kb_client,
        )

        # Verificar que la cotización fue generada exitosamente
        assert resultado["success"] is True, (
            f"La cotización falló para equipo='{tipo_equipo}', plan='{plan}'. "
            f"Motivo: {resultado.get('motivo')}"
        )

        # PROPIEDAD CORE: precio_base == precio del catálogo
        assert resultado["precio_base"] == precio_catalogo, (
            f"Inconsistencia precio-catálogo: "
            f"cotización.precio_base={resultado['precio_base']} != "
            f"catálogo.precio({tipo_equipo}, {plan})={precio_catalogo}"
        )

    @given(idx=_st_combinacion_index)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    @patch("src.agent.flows.cotizacion.enviar_correo")
    @patch("src.agent.flows.cotizacion.actualizar_pipefy")
    def test_kb_consultada_para_verificar_precio(
        self,
        mock_actualizar: MagicMock,
        mock_enviar: MagicMock,
        idx: int,
    ) -> None:
        """
        Para cada combinación del catálogo, la KB debe ser consultada
        antes de generar la cotización (verificación del precio en catálogo).
        """
        tipo_equipo, plan, precio_catalogo = _COMBINACIONES[idx]

        mock_enviar.return_value = MagicMock(
            success=True,
            message_id="msg-test-456",
            timestamp=datetime.now(timezone.utc),
            error_code=None,
        )
        mock_actualizar.return_value = True

        payload = ActivationPayload(
            poliza_id=f"POL-KB-{idx:03d}",
            cliente_nombre="Cliente Verificación KB",
            cliente_email="kb@test.com",
            fecha_vencimiento=date.today() + timedelta(days=15),
            precio_renovacion=precio_catalogo,
            equipo_nombre=tipo_equipo,
        )

        session_state = _crear_session_state(payload.poliza_id)
        kb_client = _crear_kb_client_mock(score=0.85)

        generar_cotizacion(
            session_state=session_state,
            payload=payload,
            kb_client=kb_client,
        )

        # Verificar que la KB fue consultada
        kb_client.query.assert_called_once()
        # La query debe contener referencia al equipo
        query_text = kb_client.query.call_args[0][0]
        assert payload.equipo_nombre in query_text, (
            f"La query a KB debe contener el nombre del equipo. "
            f"Query: '{query_text}', equipo: '{payload.equipo_nombre}'"
        )


# ===========================================================================
# TESTS DE EJEMPLO ESPECÍFICOS
# ===========================================================================


class TestPrecioCatalogoEjemplos:
    """Tests de ejemplo para verificar combinaciones específicas del catálogo."""

    @patch("src.agent.flows.cotizacion.enviar_correo")
    @patch("src.agent.flows.cotizacion.actualizar_pipefy")
    def test_ups_monofasico_basico(
        self, mock_actualizar: MagicMock, mock_enviar: MagicMock
    ) -> None:
        """UPS Monofásico 1-3 kVA, plan básico: precio debe ser 1200.00"""
        mock_enviar.return_value = MagicMock(
            success=True, message_id="msg-1", timestamp=datetime.now(timezone.utc), error_code=None
        )
        mock_actualizar.return_value = True

        payload = ActivationPayload(
            poliza_id="POL-EJ-001",
            cliente_nombre="Ejemplo Corp",
            cliente_email="ejemplo@corp.com",
            fecha_vencimiento=date.today() + timedelta(days=20),
            precio_renovacion=1200.00,
            equipo_nombre="UPS Monofásico 1-3 kVA",
        )

        resultado = generar_cotizacion(
            session_state=_crear_session_state(),
            payload=payload,
            kb_client=_crear_kb_client_mock(),
        )

        assert resultado["success"] is True
        assert resultado["precio_base"] == 1200.00

    @patch("src.agent.flows.cotizacion.enviar_correo")
    @patch("src.agent.flows.cotizacion.actualizar_pipefy")
    def test_ups_trifasico_premium(
        self, mock_actualizar: MagicMock, mock_enviar: MagicMock
    ) -> None:
        """UPS Trifásico 300-500 kVA, plan premium: precio debe ser 500000.00"""
        mock_enviar.return_value = MagicMock(
            success=True, message_id="msg-2", timestamp=datetime.now(timezone.utc), error_code=None
        )
        mock_actualizar.return_value = True

        payload = ActivationPayload(
            poliza_id="POL-EJ-002",
            cliente_nombre="Gran Empresa SA",
            cliente_email="admin@granempresa.com",
            fecha_vencimiento=date.today() + timedelta(days=10),
            precio_renovacion=500_000.00,
            equipo_nombre="UPS Trifásico 300-500 kVA",
        )

        resultado = generar_cotizacion(
            session_state=_crear_session_state(),
            payload=payload,
            kb_client=_crear_kb_client_mock(),
        )

        assert resultado["success"] is True
        assert resultado["precio_base"] == 500_000.00

    @patch("src.agent.flows.cotizacion.escalar_humano")
    def test_kb_score_insuficiente_escala(self, mock_escalar: MagicMock) -> None:
        """Si KB retorna score < 0.70 → escalar_humano y no generar cotización."""
        mock_escalar.return_value = True

        payload = ActivationPayload(
            poliza_id="POL-EJ-003",
            cliente_nombre="Cliente Sin Precio",
            cliente_email="sin@precio.com",
            fecha_vencimiento=date.today() + timedelta(days=30),
            precio_renovacion=9999.99,
            equipo_nombre="Equipo Desconocido XYZ",
        )

        # KB retorna score bajo (< 0.70)
        kb_client = _crear_kb_client_mock(score=0.45)

        resultado = generar_cotizacion(
            session_state=_crear_session_state(),
            payload=payload,
            kb_client=kb_client,
        )

        assert resultado["success"] is False
        assert "insuficiente" in resultado["motivo"].lower() or "escalado" in resultado["motivo"].lower()
        mock_escalar.assert_called_once()
