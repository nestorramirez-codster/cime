"""
Guardrails determinísticos de AgentCore Policy — Agente Comercial IA.

Intercepta cada tool call antes de su ejecución y bloquea acciones que violen
las políticas comerciales y de seguridad de CIME Power Systems.

Guardrails implementados:
1. Bloquear descuento ≠ 5% (Req 9.1)
2. Bloquear datos bancarios en estados no autorizados (Req 9.2)
3. Bloquear servicios fuera del alcance de póliza (Req 9.3)
4. Bloquear estados inválidos en Pipefy (Req 9.4)
5. Bloquear condiciones comerciales no presentes en KB (Req 9.5)

Cada bloqueo registra en Observability: motivo_bloqueo, tool_call_intentado,
session_id, estado_pipefy, timestamp (Req 9.6).

Requisitos: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.models.constants import (
    DESCUENTO_PRE_VENCIMIENTO,
    ESTADOS_CON_DATOS_BANCARIOS,
    ESTADOS_VALIDOS_PIPEFY,
)
from src.observability.tracer import registrar_bloqueo_policy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Datos bancarios autorizados de CIME (misma cadena que cotizacion.py)
# ---------------------------------------------------------------------------

DATOS_BANCARIOS_CIME: str = (
    "Banco: BBVA | Cuenta: 0123456789 | CLABE: 012345678901234567 "
    "| Beneficiario: CIME Power Systems S.A. de C.V."
)

# Fragmentos clave para detectar presencia de datos bancarios en un cuerpo
_FRAGMENTOS_BANCARIOS: List[str] = [
    "CLABE",
    "012345678901234567",
    "0123456789",
    "CIME Power Systems S.A. de C.V.",
]

# ---------------------------------------------------------------------------
# Servicios fuera del alcance de la póliza de mantenimiento (Req 9.3)
# ---------------------------------------------------------------------------

SERVICIOS_FUERA_DE_ALCANCE: List[str] = [
    "diagnóstico técnico",
    "diagnostico tecnico",
    "venta de refacciones",
    "refacciones",
    "soporte técnico",
    "soporte tecnico",
    "modificaciones de equipos",
    "modificacion de equipos",
    "reparación de equipos",
    "reparacion de equipos",
    "instalación de equipos",
    "instalacion de equipos",
]

# Patrón regex compilado para detectar servicios fuera de alcance
_PATTERN_FUERA_ALCANCE = re.compile(
    "|".join(re.escape(s) for s in SERVICIOS_FUERA_DE_ALCANCE),
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Patrón para detectar descuentos en el contenido de correo
# Busca patrones como: "10%", "descuento del 20%", "15 por ciento", etc.
# ---------------------------------------------------------------------------

_PATTERN_DESCUENTO = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:%|por\s*ciento|porciento)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Dataclass de resultado de bloqueo
# ---------------------------------------------------------------------------


@dataclass
class PolicyBlockResult:
    """Resultado estructurado de un bloqueo por Policy.

    Contiene todos los campos requeridos para el registro en Observability
    (Req 9.6) y la información necesaria para que el agente notifique al
    cliente (Req 9.7).
    """

    bloqueado: bool
    motivo_bloqueo: str = ""
    tool_call_intentado: str = ""
    session_id: str = ""
    estado_pipefy: str = ""
    timestamp: str = ""
    opciones_disponibles: List[str] = field(default_factory=list)

    def to_observability_entry(self) -> Dict[str, Any]:
        """Genera el dict para registro en AgentCore Observability (Req 9.6)."""
        return {
            "motivo_bloqueo": self.motivo_bloqueo,
            "tool_call_intentado": self.tool_call_intentado,
            "session_id": self.session_id,
            "estado_pipefy": self.estado_pipefy,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Clase principal: PolicyGuardrail
# ---------------------------------------------------------------------------


class PolicyGuardrail:
    """Guardrails determinísticos de AgentCore Policy.

    Intercepta cada tool call y valida contra las 5 reglas de bloqueo.
    Cada método de validación retorna un PolicyBlockResult indicando si
    la acción fue bloqueada y el motivo.

    Uso:
        guardrail = PolicyGuardrail()
        result = guardrail.validar_tool_call(
            tool_name="enviar_correo",
            params={"cuerpo": "...datos bancarios..."},
            session_state={"session_id": "abc", "estado_pipefy": "Póliza detectada"}
        )
        if result.bloqueado:
            # Registrar en observability y notificar al cliente
            ...
    """

    def __init__(self, kb_condiciones: Optional[List[str]] = None):
        """Inicializa el guardrail.

        Args:
            kb_condiciones: Lista de condiciones comerciales autorizadas
                presentes en la Knowledge Base. Si es None, el guardrail
                de condiciones KB opera en modo permisivo (placeholder).
        """
        self._kb_condiciones = kb_condiciones

    def validar_tool_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> PolicyBlockResult:
        """Valida un tool call contra todos los guardrails determinísticos.

        Ejecuta los 5 guardrails en orden. Si alguno bloquea, retorna
        inmediatamente el resultado del bloqueo.

        Args:
            tool_name: Nombre de la tool que se intenta invocar.
            params: Parámetros del tool call.
            session_state: Estado de la sesión con al menos:
                - session_id: str
                - estado_pipefy: str

        Returns:
            PolicyBlockResult con bloqueado=False si pasa todas las reglas,
            o con bloqueado=True y motivo si alguna regla bloquea.
        """
        session_id = session_state.get("session_id", "")
        estado_pipefy = session_state.get("estado_pipefy", "")

        # Ejecutar cada guardrail en secuencia
        validaciones = [
            self._validar_descuento,
            self._validar_datos_bancarios,
            self._validar_alcance_servicio,
            self._validar_estado_pipefy,
            self._validar_condiciones_kb,
        ]

        for validacion in validaciones:
            result = validacion(tool_name, params, session_id, estado_pipefy)
            if result.bloqueado:
                # Registrar en AgentCore Observability (Req 9.6)
                self._registrar_bloqueo_en_observability(result)
                # Registrar en log local como fallback adicional
                logger.warning(
                    f"POLICY BLOCK: {result.motivo_bloqueo} | "
                    f"tool={result.tool_call_intentado} | "
                    f"session={result.session_id} | "
                    f"estado_pipefy={result.estado_pipefy}"
                )
                return result

        # Todas las validaciones pasaron
        return PolicyBlockResult(bloqueado=False)

    def generar_notificacion_cliente(self, block_result: PolicyBlockResult) -> str:
        """Genera el mensaje de notificación al cliente tras un bloqueo (Req 9.7).

        Notifica al cliente que la solicitud no puede procesarse y le ofrece
        las opciones disponibles dentro del alcance aprobado o escalamiento.

        Args:
            block_result: Resultado del bloqueo con opciones disponibles.

        Returns:
            Texto del mensaje para notificar al cliente.
        """
        if not block_result.bloqueado:
            return ""

        opciones_texto = "\n".join(
            f"  - {opcion}" for opcion in block_result.opciones_disponibles
        )

        mensaje = (
            "Estimado cliente, lamentamos informarle que no es posible "
            "proceder con esa solicitud en este momento. "
            "Las opciones disponibles para usted son:\n"
            f"{opciones_texto}\n\n"
            "Si desea atención personalizada, con gusto lo conectamos "
            "con un asesor comercial de CIME Power Systems."
        )
        return mensaje

    @staticmethod
    def _registrar_bloqueo_en_observability(result: PolicyBlockResult) -> None:
        """Registra el bloqueo en AgentCore Observability con los campos requeridos (Req 9.6).

        Campos registrados:
        - motivo_bloqueo
        - tool_call_intentado
        - session_id
        - estado_pipefy
        - timestamp
        """
        from datetime import datetime, timezone

        # Parsear timestamp del resultado o usar ahora
        try:
            ts = datetime.fromisoformat(result.timestamp) if result.timestamp else datetime.now(timezone.utc)
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc)

        registrar_bloqueo_policy(
            motivo_bloqueo=result.motivo_bloqueo,
            tool_intentada=result.tool_call_intentado,
            session_id=result.session_id,
            estado_pipefy=result.estado_pipefy,
            timestamp=ts,
        )

    # -------------------------------------------------------------------
    # Guardrail 1: Descuento ≠ 5% (Req 9.1)
    # -------------------------------------------------------------------

    def _validar_descuento(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_id: str,
        estado_pipefy: str,
    ) -> PolicyBlockResult:
        """Bloquea tool calls que apliquen un descuento distinto al 5%.

        Inspecciona:
        - Parámetro 'descuento' explícito en params
        - Contenido del cuerpo de correo buscando porcentajes de descuento
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Verificar parámetro explícito de descuento
        descuento = params.get("descuento")
        if descuento is not None:
            try:
                descuento_valor = float(descuento)
            except (ValueError, TypeError):
                # Descuento no numérico → bloquear
                return PolicyBlockResult(
                    bloqueado=True,
                    motivo_bloqueo=(
                        "Descuento con valor no numérico. "
                        "Solo se permite exactamente 5%."
                    ),
                    tool_call_intentado=tool_name,
                    session_id=session_id,
                    estado_pipefy=estado_pipefy,
                    timestamp=timestamp,
                    opciones_disponibles=[
                        "Aplicar el descuento autorizado del 5% por renovación anticipada",
                        "Solicitar hablar con un asesor para condiciones especiales",
                    ],
                )

            # Comparar con tolerancia de punto flotante
            if abs(descuento_valor - DESCUENTO_PRE_VENCIMIENTO) > 1e-9:
                return PolicyBlockResult(
                    bloqueado=True,
                    motivo_bloqueo=(
                        f"Descuento de {descuento_valor*100:.1f}% no autorizado. "
                        f"Solo se permite exactamente 5%."
                    ),
                    tool_call_intentado=tool_name,
                    session_id=session_id,
                    estado_pipefy=estado_pipefy,
                    timestamp=timestamp,
                    opciones_disponibles=[
                        "Aplicar el descuento autorizado del 5% por renovación anticipada",
                        "Solicitar hablar con un asesor para condiciones especiales",
                    ],
                )

        # Verificar descuentos en el cuerpo del correo (si es enviar_correo)
        if tool_name == "enviar_correo":
            cuerpo = params.get("cuerpo", "")
            matches = _PATTERN_DESCUENTO.findall(cuerpo)
            for match_str in matches:
                try:
                    porcentaje = float(match_str)
                except ValueError:
                    continue

                # 5% es el único descuento permitido
                if abs(porcentaje - 5.0) > 1e-9:
                    return PolicyBlockResult(
                        bloqueado=True,
                        motivo_bloqueo=(
                            f"Correo contiene descuento de {porcentaje}% "
                            f"no autorizado. Solo se permite 5%."
                        ),
                        tool_call_intentado=tool_name,
                        session_id=session_id,
                        estado_pipefy=estado_pipefy,
                        timestamp=timestamp,
                        opciones_disponibles=[
                            "Aplicar el descuento autorizado del 5% por renovación anticipada",
                            "Solicitar hablar con un asesor para condiciones especiales",
                        ],
                    )

        return PolicyBlockResult(bloqueado=False)

    # -------------------------------------------------------------------
    # Guardrail 2: Datos bancarios en estados no autorizados (Req 9.2)
    # -------------------------------------------------------------------

    def _validar_datos_bancarios(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_id: str,
        estado_pipefy: str,
    ) -> PolicyBlockResult:
        """Bloquea enviar_correo con datos bancarios cuando Estado_Pipefy
        no es 'Cliente interesado' ni 'Depósito solicitado'.
        """
        if tool_name != "enviar_correo":
            return PolicyBlockResult(bloqueado=False)

        # Si el estado es uno de los autorizados, no bloquear
        if estado_pipefy in ESTADOS_CON_DATOS_BANCARIOS:
            return PolicyBlockResult(bloqueado=False)

        # Verificar si el cuerpo contiene datos bancarios
        cuerpo = params.get("cuerpo", "")
        if self._contiene_datos_bancarios(cuerpo):
            timestamp = datetime.now(timezone.utc).isoformat()
            return PolicyBlockResult(
                bloqueado=True,
                motivo_bloqueo=(
                    f"Datos bancarios detectados en correo con "
                    f"Estado_Pipefy='{estado_pipefy}'. Solo se permiten "
                    f"datos bancarios cuando el estado es 'Cliente interesado' "
                    f"o 'Depósito solicitado'."
                ),
                tool_call_intentado=tool_name,
                session_id=session_id,
                estado_pipefy=estado_pipefy,
                timestamp=timestamp,
                opciones_disponibles=[
                    "Enviar el correo sin incluir datos bancarios",
                    "Solicitar hablar con un asesor comercial",
                ],
            )

        return PolicyBlockResult(bloqueado=False)

    # -------------------------------------------------------------------
    # Guardrail 3: Servicios fuera del alcance de póliza (Req 9.3)
    # -------------------------------------------------------------------

    def _validar_alcance_servicio(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_id: str,
        estado_pipefy: str,
    ) -> PolicyBlockResult:
        """Bloquea tool calls que ofrezcan servicios fuera de la póliza.

        Servicios no permitidos: diagnóstico técnico, venta de refacciones,
        soporte técnico, modificaciones de equipos.
        """
        # Inspeccionar el cuerpo de correo
        texto_a_verificar = ""
        if tool_name == "enviar_correo":
            texto_a_verificar = params.get("cuerpo", "")
        elif tool_name == "escalar_humano":
            # No bloquear escalamientos — es una acción válida
            return PolicyBlockResult(bloqueado=False)

        # También verificar parámetro 'servicio' si existe
        servicio = params.get("servicio", "")
        texto_a_verificar = f"{texto_a_verificar} {servicio}"

        if not texto_a_verificar.strip():
            return PolicyBlockResult(bloqueado=False)

        match = _PATTERN_FUERA_ALCANCE.search(texto_a_verificar)
        if match:
            servicio_detectado = match.group(0)
            timestamp = datetime.now(timezone.utc).isoformat()
            return PolicyBlockResult(
                bloqueado=True,
                motivo_bloqueo=(
                    f"Servicio fuera del alcance de póliza detectado: "
                    f"'{servicio_detectado}'. El agente solo gestiona "
                    f"renovaciones de pólizas de mantenimiento."
                ),
                tool_call_intentado=tool_name,
                session_id=session_id,
                estado_pipefy=estado_pipefy,
                timestamp=timestamp,
                opciones_disponibles=[
                    "Consultar sobre la renovación de su póliza de mantenimiento",
                    "Solicitar hablar con un asesor para otros servicios",
                ],
            )

        return PolicyBlockResult(bloqueado=False)

    # -------------------------------------------------------------------
    # Guardrail 4: Estado inválido en actualizar_pipefy (Req 9.4)
    # -------------------------------------------------------------------

    def _validar_estado_pipefy(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_id: str,
        estado_pipefy: str,
    ) -> PolicyBlockResult:
        """Bloquea actualizar_pipefy con estado fuera de ESTADOS_VALIDOS_PIPEFY."""
        if tool_name != "actualizar_pipefy":
            return PolicyBlockResult(bloqueado=False)

        estado_destino = params.get("estado", "")
        if estado_destino not in ESTADOS_VALIDOS_PIPEFY:
            timestamp = datetime.now(timezone.utc).isoformat()
            return PolicyBlockResult(
                bloqueado=True,
                motivo_bloqueo=(
                    f"Estado '{estado_destino}' no es un estado válido de Pipefy. "
                    f"Estados permitidos: {sorted(ESTADOS_VALIDOS_PIPEFY)}"
                ),
                tool_call_intentado=tool_name,
                session_id=session_id,
                estado_pipefy=estado_pipefy,
                timestamp=timestamp,
                opciones_disponibles=[
                    "Verificar el estado correcto del flujo de renovación",
                    "Escalar a humano para resolver inconsistencia",
                ],
            )

        return PolicyBlockResult(bloqueado=False)

    # -------------------------------------------------------------------
    # Guardrail 5: Condiciones comerciales no presentes en KB (Req 9.5)
    # -------------------------------------------------------------------

    def _validar_condiciones_kb(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_id: str,
        estado_pipefy: str,
    ) -> PolicyBlockResult:
        """Bloquea enviar_correo con condiciones comerciales no presentes en KB.

        Si kb_condiciones es None, opera en modo permisivo (no bloquea).
        Si está configurado, verifica que cualquier precio o condición
        mencionada en el correo esté en la lista de condiciones autorizadas.
        """
        if tool_name != "enviar_correo":
            return PolicyBlockResult(bloqueado=False)

        # Modo permisivo si no se configuraron condiciones de KB
        if self._kb_condiciones is None:
            return PolicyBlockResult(bloqueado=False)

        cuerpo = params.get("cuerpo", "")
        if not cuerpo:
            return PolicyBlockResult(bloqueado=False)

        # Buscar precios/condiciones en el cuerpo del correo
        condicion_no_autorizada = self._detectar_condicion_no_autorizada(cuerpo)
        if condicion_no_autorizada:
            timestamp = datetime.now(timezone.utc).isoformat()
            return PolicyBlockResult(
                bloqueado=True,
                motivo_bloqueo=(
                    f"Condición comercial no autorizada detectada: "
                    f"'{condicion_no_autorizada}'. Solo se permiten condiciones "
                    f"documentadas en la Knowledge Base."
                ),
                tool_call_intentado=tool_name,
                session_id=session_id,
                estado_pipefy=estado_pipefy,
                timestamp=timestamp,
                opciones_disponibles=[
                    "Consultar las condiciones actualizadas en la Knowledge Base",
                    "Solicitar hablar con un asesor para condiciones especiales",
                ],
            )

        return PolicyBlockResult(bloqueado=False)

    # -------------------------------------------------------------------
    # Métodos auxiliares
    # -------------------------------------------------------------------

    @staticmethod
    def _contiene_datos_bancarios(texto: str) -> bool:
        """Detecta si un texto contiene datos bancarios de CIME."""
        texto_lower = texto.lower()
        for fragmento in _FRAGMENTOS_BANCARIOS:
            if fragmento.lower() in texto_lower:
                return True
        return False

    def _detectar_condicion_no_autorizada(self, cuerpo: str) -> Optional[str]:
        """Detecta condiciones comerciales en el correo no presentes en KB.

        Busca patrones de precios (formato "$X,XXX.XX") y condiciones
        textuales. Si alguno no está en la lista de condiciones autorizadas,
        retorna la condición detectada.

        Returns:
            La condición no autorizada encontrada, o None si todo es válido.
        """
        if self._kb_condiciones is None:
            return None

        # Buscar precios en el texto
        patron_precio = re.compile(r"\$[\d,]+(?:\.\d{2})?")
        precios_en_cuerpo = patron_precio.findall(cuerpo)

        for precio in precios_en_cuerpo:
            if precio not in self._kb_condiciones:
                return precio

        # Buscar condiciones textuales conocidas
        for condicion in self._kb_condiciones:
            # Las condiciones KB son las autorizadas — no bloquear si están
            pass

        # Buscar patrones sospechosos: plazos no estándar, condiciones ad-hoc
        patron_plazo = re.compile(
            r"(\d+)\s*(?:meses|días|semanas)\s*(?:de plazo|para pagar|sin intereses)",
            re.IGNORECASE,
        )
        plazos = patron_plazo.findall(cuerpo)
        for plazo in plazos:
            condicion_plazo = f"{plazo} meses/días de plazo"
            if condicion_plazo not in self._kb_condiciones:
                return f"plazo de {plazo} períodos"

        return None
