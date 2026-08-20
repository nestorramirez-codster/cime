"""
Property-Based Tests — Propiedad 11: Validación de formato de comprobante.

Feature: agente-comercial-polizas
Property 11: Validación de formato de comprobante

**Validates: Requirements 5.1, 5.6**

Verifica que _validar_formato_adjunto acepta un archivo si y solo si
su extensión pertenece a FORMATOS_COMPROBANTE_ACEPTADOS (case-insensitive)
Y su tamaño no excede TAMANIO_MAXIMO_COMPROBANTE_BYTES.

Propiedad lógica:
    acepta(adjunto) == (extension_valida(adjunto) AND tamaño_valido(adjunto))
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.flows.comprobante import _validar_formato_adjunto
from src.models.constants import (
    FORMATOS_COMPROBANTE_ACEPTADOS,
    TAMANIO_MAXIMO_COMPROBANTE_BYTES,
)


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Extensiones válidas (de FORMATOS_COMPROBANTE_ACEPTADOS, en distintas combinaciones de case)
_extensiones_validas = sorted(FORMATOS_COMPROBANTE_ACEPTADOS)

_st_extension_valida = st.sampled_from(_extensiones_validas).flatmap(
    lambda ext: st.sampled_from([ext.lower(), ext.upper(), ext.capitalize()])
)

# Extensiones inválidas (que NO están en FORMATOS_COMPROBANTE_ACEPTADOS)
_extensiones_invalidas = ["doc", "txt", "exe", "gif", "bmp", "webp", "tiff", "svg", "xlsx", "zip"]

_st_extension_invalida = st.sampled_from(_extensiones_invalidas).flatmap(
    lambda ext: st.sampled_from([ext.lower(), ext.upper(), ext.capitalize()])
)

# Nombre base del archivo (sin punto ni extensión)
_st_nombre_base = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        blacklist_characters=".\x00/\\",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: "." not in s and len(s.strip()) > 0)

# Tamaño válido: 1 byte a TAMANIO_MAXIMO_COMPROBANTE_BYTES (inclusive)
_st_tamanio_valido = st.integers(min_value=1, max_value=TAMANIO_MAXIMO_COMPROBANTE_BYTES)

# Tamaño inválido (excede el máximo): TAMANIO_MAXIMO + 1 hasta 50 MB
_st_tamanio_invalido = st.integers(
    min_value=TAMANIO_MAXIMO_COMPROBANTE_BYTES + 1,
    max_value=50 * 1024 * 1024,
)

# Nombre de archivo con extensión válida
_st_nombre_con_extension_valida = st.tuples(_st_nombre_base, _st_extension_valida).map(
    lambda t: f"{t[0]}.{t[1]}"
)

# Nombre de archivo con extensión inválida
_st_nombre_con_extension_invalida = st.tuples(_st_nombre_base, _st_extension_invalida).map(
    lambda t: f"{t[0]}.{t[1]}"
)

# Nombre de archivo sin extensión (sin punto)
_st_nombre_sin_extension = _st_nombre_base


# ===========================================================================
# PROPERTY TESTS — Propiedad 11
# ===========================================================================


class TestProperty11ValidacionFormatoComprobante:
    """
    Feature: agente-comercial-polizas
    Property 11: Validación de formato de comprobante

    **Validates: Requirements 5.1, 5.6**
    """

    # -----------------------------------------------------------------------
    # Caso 1: Extensión válida + tamaño válido → aceptado
    # -----------------------------------------------------------------------

    @given(
        nombre_archivo=_st_nombre_con_extension_valida,
        tamanio=_st_tamanio_valido,
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_extension_valida_y_tamanio_valido_es_aceptado(
        self,
        nombre_archivo: str,
        tamanio: int,
    ) -> None:
        """
        Req 5.1, 5.6 — Archivo con extensión válida y tamaño dentro del límite
        DEBE ser aceptado: retorna (True, "").
        """
        es_valido, motivo = _validar_formato_adjunto(nombre_archivo, tamanio)

        assert es_valido is True, (
            f"Archivo '{nombre_archivo}' ({tamanio} bytes) debería ser aceptado "
            f"pero fue rechazado con motivo: {motivo}"
        )
        assert motivo == "", (
            f"Archivo aceptado debería tener motivo vacío, pero tiene: '{motivo}'"
        )

    # -----------------------------------------------------------------------
    # Caso 2: Extensión inválida + tamaño válido → rechazado
    # -----------------------------------------------------------------------

    @given(
        nombre_archivo=_st_nombre_con_extension_invalida,
        tamanio=_st_tamanio_valido,
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_extension_invalida_y_tamanio_valido_es_rechazado(
        self,
        nombre_archivo: str,
        tamanio: int,
    ) -> None:
        """
        Req 5.6 — Archivo con extensión no soportada (incluso si el tamaño es válido)
        DEBE ser rechazado: retorna (False, motivo) donde motivo no está vacío.
        """
        es_valido, motivo = _validar_formato_adjunto(nombre_archivo, tamanio)

        assert es_valido is False, (
            f"Archivo '{nombre_archivo}' con extensión inválida debería ser rechazado "
            f"pero fue aceptado."
        )
        assert motivo != "", (
            f"Archivo rechazado debería tener un motivo, pero está vacío."
        )

    # -----------------------------------------------------------------------
    # Caso 3: Extensión válida + tamaño excesivo → rechazado
    # -----------------------------------------------------------------------

    @given(
        nombre_archivo=_st_nombre_con_extension_valida,
        tamanio=_st_tamanio_invalido,
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_extension_valida_y_tamanio_excesivo_es_rechazado(
        self,
        nombre_archivo: str,
        tamanio: int,
    ) -> None:
        """
        Req 5.1 — Archivo con extensión válida pero tamaño > 10 MB
        DEBE ser rechazado: retorna (False, motivo) donde motivo no está vacío.
        """
        es_valido, motivo = _validar_formato_adjunto(nombre_archivo, tamanio)

        assert es_valido is False, (
            f"Archivo '{nombre_archivo}' ({tamanio} bytes, > 10 MB) debería ser "
            f"rechazado pero fue aceptado."
        )
        assert motivo != "", (
            f"Archivo rechazado por tamaño debería tener un motivo, pero está vacío."
        )

    # -----------------------------------------------------------------------
    # Caso 4: Extensión inválida + tamaño excesivo → rechazado
    # -----------------------------------------------------------------------

    @given(
        nombre_archivo=_st_nombre_con_extension_invalida,
        tamanio=_st_tamanio_invalido,
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_extension_invalida_y_tamanio_excesivo_es_rechazado(
        self,
        nombre_archivo: str,
        tamanio: int,
    ) -> None:
        """
        Req 5.1, 5.6 — Archivo con extensión inválida Y tamaño excesivo
        DEBE ser rechazado: retorna (False, motivo).
        """
        es_valido, motivo = _validar_formato_adjunto(nombre_archivo, tamanio)

        assert es_valido is False, (
            f"Archivo '{nombre_archivo}' (ext inválida, {tamanio} bytes > 10 MB) "
            f"debería ser rechazado pero fue aceptado."
        )
        assert motivo != "", (
            f"Archivo rechazado debería tener un motivo, pero está vacío."
        )

    # -----------------------------------------------------------------------
    # Caso 5: Sin extensión + cualquier tamaño → rechazado
    # -----------------------------------------------------------------------

    @given(
        nombre_archivo=_st_nombre_sin_extension,
        tamanio=st.integers(min_value=1, max_value=50 * 1024 * 1024),
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_sin_extension_es_rechazado(
        self,
        nombre_archivo: str,
        tamanio: int,
    ) -> None:
        """
        Req 5.6 — Archivo sin extensión (sin punto en el nombre)
        DEBE ser rechazado independientemente del tamaño.
        """
        es_valido, motivo = _validar_formato_adjunto(nombre_archivo, tamanio)

        assert es_valido is False, (
            f"Archivo '{nombre_archivo}' sin extensión debería ser rechazado "
            f"pero fue aceptado."
        )
        assert motivo != "", (
            f"Archivo sin extensión rechazado debería tener motivo, pero está vacío."
        )

    # -----------------------------------------------------------------------
    # Caso 6: Propiedad compuesta — acepta == (ext_valida AND tam_valido)
    # -----------------------------------------------------------------------

    @given(
        nombre_base=_st_nombre_base,
        extension=st.one_of(_st_extension_valida, _st_extension_invalida),
        tiene_extension=st.booleans(),
        tamanio=st.integers(min_value=1, max_value=50 * 1024 * 1024),
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_propiedad_compuesta_acepta_iff_extension_valida_y_tamanio_valido(
        self,
        nombre_base: str,
        extension: str,
        tiene_extension: bool,
        tamanio: int,
    ) -> None:
        """
        Propiedad unificada (Req 5.1, 5.6):
            acepta(adjunto) == (extension_valida(adjunto) AND tamaño_valido(adjunto))

        Genera combinaciones arbitrarias y verifica la equivalencia lógica.
        """
        # Construir nombre de archivo
        if tiene_extension:
            nombre_archivo = f"{nombre_base}.{extension}"
        else:
            nombre_archivo = nombre_base

        # Calcular expectativa
        if not tiene_extension or "." not in nombre_archivo:
            extension_es_valida = False
        else:
            ext_upper = nombre_archivo.rsplit(".", 1)[-1].upper()
            extension_es_valida = ext_upper in FORMATOS_COMPROBANTE_ACEPTADOS

        tamanio_es_valido = tamanio <= TAMANIO_MAXIMO_COMPROBANTE_BYTES

        deberia_aceptar = extension_es_valida and tamanio_es_valido

        # Ejecutar función bajo test
        es_valido, motivo = _validar_formato_adjunto(nombre_archivo, tamanio)

        assert es_valido == deberia_aceptar, (
            f"Archivo '{nombre_archivo}' ({tamanio} bytes): "
            f"esperado acepta={deberia_aceptar} pero obtuvo acepta={es_valido}. "
            f"extension_valida={extension_es_valida}, tamanio_valido={tamanio_es_valido}. "
            f"Motivo: '{motivo}'"
        )

        # Verificar consistencia del motivo
        if es_valido:
            assert motivo == "", f"Si acepta, motivo debe ser vacío: '{motivo}'"
        else:
            assert motivo != "", "Si rechaza, motivo no debe ser vacío."
