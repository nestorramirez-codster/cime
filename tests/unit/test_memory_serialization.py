"""
Property-Based Tests — Propiedad 17: Round-trip de serialización del historial de memoria.

Feature: agente-comercial-polizas
Property 17: Round-trip de serialización del historial de memoria

**Validates: Requirements 8.1**

Estrategia:
- Generar listas aleatorias de Mensaje con timestamps, remitentes y tipos variados
- Serializar el historial a JSON (vía _serializar_mensaje)
- Deserializar de vuelta (vía _deserializar_mensaje)
- Verificar igualdad: deserializar(serializar(historial)) == historial
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.memory.short_term import _deserializar_mensaje, _serializar_mensaje
from src.models.constants import Remitente, TipoMensaje
from src.models.data_models import Mensaje

# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Timestamps timezone-aware en UTC (necesario para round-trip con isoformat)
_st_timestamp_utc = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

# Remitentes válidos
_st_remitente = st.sampled_from(sorted(Remitente.TODOS))

# Tipos de mensaje válidos
_st_tipo_mensaje = st.sampled_from(sorted(TipoMensaje.TODOS))

# Contenido del mensaje: texto no vacío
_st_contenido = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=200,
)

# Estrategia para un Mensaje individual
_st_mensaje = st.builds(
    Mensaje,
    timestamp=_st_timestamp_utc,
    remitente=_st_remitente,
    contenido=_st_contenido,
    tipo=_st_tipo_mensaje,
)

# Estrategia para un historial (lista de mensajes)
_st_historial = st.lists(_st_mensaje, min_size=0, max_size=20)


# ===========================================================================
# PROPERTY TESTS
# ===========================================================================


class TestProperty17RoundTripSerializacionHistorial:
    """
    Feature: agente-comercial-polizas
    Property 17: Round-trip de serialización del historial de memoria

    **Validates: Requirements 8.1**
    """

    @given(historial=_st_historial)
    @settings(max_examples=100, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_roundtrip_serializar_deserializar_historial(
        self, historial: list[Mensaje]
    ) -> None:
        """
        Para cualquier lista de N mensajes, verificar que:
        deserializar(serializar(historial)) == historial

        El round-trip usa JSON como formato intermedio (tal como en DynamoDB).
        """
        # 1. Serializar cada mensaje a dict
        serializado = [_serializar_mensaje(m) for m in historial]

        # 2. Convertir a JSON string (simula almacenamiento en DynamoDB)
        json_str = json.dumps(serializado)

        # 3. Parsear JSON de vuelta a lista de dicts
        deserializado_raw = json.loads(json_str)

        # 4. Deserializar cada dict de vuelta a Mensaje
        historial_recuperado = [_deserializar_mensaje(d) for d in deserializado_raw]

        # 5. Verificar igualdad completa
        assert len(historial_recuperado) == len(historial), (
            f"Longitud difiere: original={len(historial)}, "
            f"recuperado={len(historial_recuperado)}"
        )

        for i, (original, recuperado) in enumerate(
            zip(historial, historial_recuperado)
        ):
            assert original == recuperado, (
                f"Mensaje[{i}] difiere tras round-trip.\n"
                f"  Original:   {original}\n"
                f"  Recuperado: {recuperado}"
            )


# ===========================================================================
# SMOKE TESTS — TTL de comprobante y aislamiento de sesión (Task 8.4)
# ===========================================================================
# **Validates: Requirements 8.5, 12.7**


import time as _time_module
from unittest.mock import patch

from src.memory.short_term import (
    _mock_store,
    _reset_mock_store,
    eliminar_dato_comprobante,
    guardar_estado_sesion,
    obtener_estado_sesion,
)
from src.models.data_models import DatosComprobanteTemp, SessionState


def _crear_session_state(
    session_id: str,
    poliza_id: str = "POL-001",
    estado: str = "Comprobante recibido",
    con_comprobante: bool = False,
) -> SessionState:
    """Helper para crear un SessionState con datos mínimos para los smoke tests."""
    datos_comprobante = None
    if con_comprobante:
        datos_comprobante = DatosComprobanteTemp(
            referencia_adjunto=f"s3://bucket/{session_id}/comprobante.pdf",
            monto=15000.0,
            timestamp_recepcion=datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            formato="PDF",
            tamanio_bytes=2048,
        )
    return SessionState(
        session_id=session_id,
        poliza_id=poliza_id,
        estado_pipefy=estado,
        historial_mensajes=[],
        timestamp_inicio=datetime(2024, 6, 15, 9, 0, 0, tzinfo=timezone.utc),
        datos_comprobante=datos_comprobante,
    )


class TestSmokeComprobanteTTL:
    """
    Smoke test: TTL de comprobante (Req 8.5).

    Verifica que los datos de comprobante son eliminados (retornados como None)
    tras expirar el TTL de 10 minutos simulado.

    **Validates: Requirements 8.5**
    """

    def setup_method(self) -> None:
        _reset_mock_store()

    def teardown_method(self) -> None:
        _reset_mock_store()

    def test_comprobante_disponible_antes_de_ttl(self) -> None:
        """Datos de comprobante accesibles antes de que expire el TTL."""
        session = _crear_session_state("ses-ttl-01", con_comprobante=True)
        guardar_estado_sesion(session)

        resultado = obtener_estado_sesion("ses-ttl-01")

        assert resultado is not None
        assert resultado.datos_comprobante is not None
        assert resultado.datos_comprobante.referencia_adjunto == (
            "s3://bucket/ses-ttl-01/comprobante.pdf"
        )
        assert resultado.datos_comprobante.monto == 15000.0

    def test_comprobante_none_tras_ttl_expirado(self) -> None:
        """
        Datos de comprobante retornados como None después de que el TTL expira.

        Simula la expiración manipulando comprobante_expiry_time en el mock store
        a un valor en el pasado.
        """
        session = _crear_session_state("ses-ttl-02", con_comprobante=True)
        guardar_estado_sesion(session)

        # Manipular el TTL del comprobante para simular expiración (tiempo pasado)
        _mock_store["ses-ttl-02"]["comprobante_expiry_time"] = int(
            _time_module.time()
        ) - 1

        resultado = obtener_estado_sesion("ses-ttl-02")

        assert resultado is not None
        # Los datos de comprobante deben ser None tras expiración del TTL
        assert resultado.datos_comprobante is None

    def test_sesion_permanece_tras_ttl_comprobante(self) -> None:
        """
        La sesión y sus otros datos persisten aún después de que el comprobante expire.
        Solo datos_comprobante se purga, no toda la sesión.
        """
        session = _crear_session_state(
            "ses-ttl-03", poliza_id="POL-777", con_comprobante=True
        )
        guardar_estado_sesion(session)

        # Expirar el comprobante
        _mock_store["ses-ttl-03"]["comprobante_expiry_time"] = int(
            _time_module.time()
        ) - 600

        resultado = obtener_estado_sesion("ses-ttl-03")

        assert resultado is not None
        assert resultado.session_id == "ses-ttl-03"
        assert resultado.poliza_id == "POL-777"
        assert resultado.estado_pipefy == "Comprobante recibido"
        assert resultado.datos_comprobante is None


class TestSmokeAislamientoSesion:
    """
    Smoke test: Aislamiento de sesión (Req 12.7).

    Verifica que leer Memory con session_id_A no retorna datos de session_id_B
    y que operaciones sobre una sesión no afectan a otra.

    **Validates: Requirements 12.7**
    """

    def setup_method(self) -> None:
        _reset_mock_store()

    def teardown_method(self) -> None:
        _reset_mock_store()

    def test_sesiones_independientes_datos_distintos(self) -> None:
        """
        Dos sesiones con session_id diferente almacenan y retornan datos
        independientes sin contaminación cruzada.
        """
        session_a = _crear_session_state(
            "ses-A", poliza_id="POL-100", estado="Contacto inicial enviado"
        )
        session_b = _crear_session_state(
            "ses-B", poliza_id="POL-200", estado="Cliente interesado"
        )

        guardar_estado_sesion(session_a)
        guardar_estado_sesion(session_b)

        resultado_a = obtener_estado_sesion("ses-A")
        resultado_b = obtener_estado_sesion("ses-B")

        # Session A retorna solo sus datos
        assert resultado_a is not None
        assert resultado_a.session_id == "ses-A"
        assert resultado_a.poliza_id == "POL-100"
        assert resultado_a.estado_pipefy == "Contacto inicial enviado"

        # Session B retorna solo sus datos
        assert resultado_b is not None
        assert resultado_b.session_id == "ses-B"
        assert resultado_b.poliza_id == "POL-200"
        assert resultado_b.estado_pipefy == "Cliente interesado"

        # No hay contaminación cruzada
        assert resultado_a.poliza_id != resultado_b.poliza_id
        assert resultado_a.estado_pipefy != resultado_b.estado_pipefy

    def test_obtener_sesion_inexistente_retorna_none(self) -> None:
        """
        Buscar un session_id que no existe no retorna datos de otra sesión.
        """
        session_a = _crear_session_state("ses-existente", poliza_id="POL-300")
        guardar_estado_sesion(session_a)

        resultado = obtener_estado_sesion("ses-no-existe")

        assert resultado is None

    def test_eliminar_comprobante_no_afecta_otra_sesion(self) -> None:
        """
        eliminar_dato_comprobante(session_id_A) no afecta datos_comprobante
        de session_id_B.
        """
        session_a = _crear_session_state(
            "ses-iso-A", poliza_id="POL-400", con_comprobante=True
        )
        session_b = _crear_session_state(
            "ses-iso-B", poliza_id="POL-500", con_comprobante=True
        )

        guardar_estado_sesion(session_a)
        guardar_estado_sesion(session_b)

        # Eliminar comprobante SOLO de sesión A
        resultado_eliminar = eliminar_dato_comprobante("ses-iso-A")
        assert resultado_eliminar is True

        # Verificar que sesión A ya no tiene comprobante
        estado_a = obtener_estado_sesion("ses-iso-A")
        assert estado_a is not None
        assert estado_a.datos_comprobante is None

        # Verificar que sesión B MANTIENE su comprobante intacto
        estado_b = obtener_estado_sesion("ses-iso-B")
        assert estado_b is not None
        assert estado_b.datos_comprobante is not None
        assert estado_b.datos_comprobante.referencia_adjunto == (
            "s3://bucket/ses-iso-B/comprobante.pdf"
        )
        assert estado_b.datos_comprobante.monto == 15000.0

    def test_guardar_sesion_no_sobreescribe_otra(self) -> None:
        """
        Guardar una nueva sesión no modifica sesiones existentes con otro ID.
        """
        session_a = _crear_session_state(
            "ses-guard-A", poliza_id="POL-600", estado="Seguimiento en curso"
        )
        guardar_estado_sesion(session_a)

        # Guardar sesión B después
        session_b = _crear_session_state(
            "ses-guard-B", poliza_id="POL-700", estado="Depósito solicitado"
        )
        guardar_estado_sesion(session_b)

        # Sesión A sigue intacta
        estado_a = obtener_estado_sesion("ses-guard-A")
        assert estado_a is not None
        assert estado_a.poliza_id == "POL-600"
        assert estado_a.estado_pipefy == "Seguimiento en curso"


# ===========================================================================
# PROPERTY TEST — Propiedad 18: No duplicación de información en mensajes
# consecutivos
# ===========================================================================
# **Validates: Requirements 8.4**

import re
from typing import List


def detectar_duplicacion(
    nuevo_mensaje: str, historial_reciente: list[str]
) -> bool:
    """Detecta si un nuevo mensaje duplica contenido sustancial del historial reciente.

    Una duplicación se detecta cuando:
    1. El nuevo mensaje contiene al menos una frase de más de 10 palabras que
       ya aparece textualmente en alguno de los mensajes del historial reciente, O
    2. Alguna frase sustancial del historial aparece textualmente en el nuevo mensaje.

    Args:
        nuevo_mensaje: Texto del mensaje candidato a enviar.
        historial_reciente: Lista de los últimos N mensajes (máximo 20) ya enviados.

    Returns:
        True si se detecta duplicación sustancial, False en caso contrario.
    """
    if not nuevo_mensaje or not historial_reciente:
        return False

    nuevo_lower = nuevo_mensaje.lower()

    # Dirección 1: Extraer frases del nuevo mensaje y buscarlas en historial
    frases_nuevo = _extraer_frases_sustanciales(nuevo_mensaje)
    if frases_nuevo:
        historial_texto = " ".join(historial_reciente).lower()
        for frase in frases_nuevo:
            if frase.lower() in historial_texto:
                return True

    # Dirección 2: Extraer frases del historial y buscarlas en el nuevo mensaje
    for msg in historial_reciente:
        frases_historial = _extraer_frases_sustanciales(msg)
        for frase in frases_historial:
            if frase.lower() in nuevo_lower:
                return True

    return False


def _extraer_frases_sustanciales(texto: str) -> list[str]:
    """Extrae frases con más de 10 palabras de un texto.

    Divide el texto por delimitadores de oración (., ;, !, ?, \\n) y retorna
    las frases que tienen más de 10 palabras.

    Args:
        texto: Texto fuente del cual extraer frases.

    Returns:
        Lista de frases con más de 10 palabras.
    """
    # Separar por delimitadores de oración
    segmentos = re.split(r"[.;!?\n]+", texto)

    frases = []
    for segmento in segmentos:
        segmento = segmento.strip()
        palabras = segmento.split()
        if len(palabras) > 10:
            frases.append(segmento)

    return frases


# ---------------------------------------------------------------------------
# Estrategias Hypothesis para Propiedad 18
# ---------------------------------------------------------------------------

# Palabras de vocabulario comercial para generar mensajes realistas
_VOCABULARIO_COMERCIAL = [
    "renovación", "póliza", "mantenimiento", "equipo", "precio",
    "vencimiento", "cotización", "descuento", "plazo", "cobertura",
    "vigencia", "factura", "cliente", "pago", "comprobante",
    "tesorería", "asesor", "contacto", "depósito", "confirmación",
    "estimado", "informamos", "servicio", "período", "condiciones",
]

# Estrategia para generar una frase sustancial (más de 10 palabras)
_st_frase_sustancial = st.lists(
    st.sampled_from(_VOCABULARIO_COMERCIAL),
    min_size=11,
    max_size=20,
).map(lambda palabras: " ".join(palabras))

# Estrategia para generar un mensaje con al menos una frase sustancial
_st_mensaje_con_frase = st.builds(
    lambda frase, extra: f"{frase}. {extra}",
    frase=_st_frase_sustancial,
    extra=st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"),
            whitelist_characters=" .,",
        ),
        min_size=0,
        max_size=50,
    ),
)

# Estrategia para un historial reciente (lista de mensajes)
_st_historial_reciente = st.lists(
    _st_mensaje_con_frase,
    min_size=1,
    max_size=20,
)

# Estrategia para un mensaje corto (sin frases sustanciales, < 10 palabras por segmento)
_st_mensaje_corto = st.lists(
    st.sampled_from(_VOCABULARIO_COMERCIAL),
    min_size=1,
    max_size=8,
).map(lambda palabras: " ".join(palabras))


class TestProperty18NoDuplicacionMensajes:
    """
    Feature: agente-comercial-polizas
    Property 18: No duplicación de información en mensajes consecutivos

    **Validates: Requirements 8.4**

    Verifica que la función `detectar_duplicacion` identifica correctamente
    cuando un mensaje nuevo repite información sustancial (frases > 10 palabras)
    del historial reciente (últimos 20 mensajes).
    """

    @given(historial=_st_historial_reciente)
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_mensaje_duplicado_es_detectado(
        self, historial: list[str]
    ) -> None:
        """
        Para cualquier historial de N mensajes, si el mensaje N+1 contiene
        una frase de más de 10 palabras que ya aparece textualmente en el
        historial, entonces detectar_duplicacion debe retornar True.
        """
        # Tomar una frase sustancial de algún mensaje del historial
        frases_en_historial: list[str] = []
        for msg in historial:
            frases_en_historial.extend(_extraer_frases_sustanciales(msg))

        if not frases_en_historial:
            # Si no hay frases sustanciales, el test no aplica
            return

        # Construir un nuevo mensaje que incluye una frase ya dicha
        frase_repetida = frases_en_historial[0]
        nuevo_mensaje = f"Como le comenté antes, {frase_repetida}. Quedo atento."

        # La duplicación DEBE ser detectada
        assert detectar_duplicacion(nuevo_mensaje, historial) is True, (
            f"detectar_duplicacion debió retornar True.\n"
            f"  Frase repetida: '{frase_repetida}'\n"
            f"  Nuevo mensaje: '{nuevo_mensaje}'\n"
            f"  Historial (primeros 3): {historial[:3]}"
        )

    @given(historial=_st_historial_reciente, mensaje_corto=_st_mensaje_corto)
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_mensaje_corto_no_detecta_duplicacion(
        self, historial: list[str], mensaje_corto: str
    ) -> None:
        """
        Para cualquier historial de N mensajes, si el mensaje N+1 no contiene
        ninguna frase de más de 10 palabras, entonces detectar_duplicacion
        debe retornar False (no hay contenido sustancial que pueda duplicar).
        """
        # Un mensaje corto (< 10 palabras por segmento) no puede ser duplicado
        assert detectar_duplicacion(mensaje_corto, historial) is False, (
            f"detectar_duplicacion debió retornar False para mensaje corto.\n"
            f"  Mensaje: '{mensaje_corto}'\n"
            f"  Historial (primeros 3): {historial[:3]}"
        )

    @given(
        historial=_st_historial_reciente,
        palabras_unicas=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L",)),
                min_size=3,
                max_size=8,
            ),
            min_size=12,
            max_size=18,
        ),
    )
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_mensaje_original_no_detecta_duplicacion(
        self, historial: list[str], palabras_unicas: list[str]
    ) -> None:
        """
        Para cualquier historial de N mensajes, si el mensaje N+1 contiene
        una frase de más de 10 palabras que NO aparece en el historial,
        entonces detectar_duplicacion debe retornar False.

        Se generan palabras aleatorias que con altísima probabilidad no
        coinciden con las frases del vocabulario comercial del historial.
        """
        # Construir frase única que no está en historial
        frase_unica = " ".join(palabras_unicas)
        nuevo_mensaje = f"Nueva información: {frase_unica}. Fin del comunicado."

        # Verificar que la frase no existe en el historial (precondición)
        historial_texto = " ".join(historial).lower()
        if frase_unica.lower() in historial_texto:
            # Caso extremadamente raro: la frase generada coincidió, skip
            return

        assert detectar_duplicacion(nuevo_mensaje, historial) is False, (
            f"detectar_duplicacion debió retornar False para contenido original.\n"
            f"  Frase única: '{frase_unica}'\n"
            f"  Nuevo mensaje: '{nuevo_mensaje}'"
        )

    @given(data=st.data())
    @settings(
        max_examples=100,
        deadline=5000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_historial_vacio_no_detecta_duplicacion(self, data: st.DataObject) -> None:
        """
        Con historial vacío, ningún mensaje debe ser detectado como duplicado.
        """
        nuevo_mensaje = data.draw(_st_mensaje_con_frase)
        assert detectar_duplicacion(nuevo_mensaje, []) is False
