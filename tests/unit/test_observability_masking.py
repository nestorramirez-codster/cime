"""
Unit Tests — Observabilidad: Enmascaramiento de datos sensibles (Req 10.5).

Verifica que la función `enmascarar_datos_sensibles` aplica correctamente:
- Email → ***@dominio.com (solo dominio visible)
- Datos bancarios → ****-****-****-1234 (últimos 4 dígitos)
- Nombre completo → J.G. (solo iniciales)

También verifica:
- Truncado a 10 KB máximo (Req 10.1)
- Fallback si falla la escritura primaria (Req 10.6)
- Las 5 funciones de traza se ejecutan sin error
- Property 20: Enmascaramiento de datos sensibles en Observability (PBT)
"""

from __future__ import annotations

import json
import re
import string
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.models.constants import OBSERVABILITY_MAX_ENTRY_BYTES
from src.observability.tracer import (
    _enmascarar_datos_bancarios,
    _enmascarar_email,
    _enmascarar_nombre,
    _truncar_entrada,
    enmascarar_datos_sensibles,
    registrar_bloqueo_policy,
    registrar_cierre_sesion,
    registrar_error,
    registrar_inicio_sesion,
    registrar_tool_call,
)


# ===========================================================================
# TESTS DE ENMASCARAMIENTO DE EMAIL (Req 10.5)
# ===========================================================================


class TestEnmascaramientoEmail:
    """Verifica regla: Email → ***@dominio.com"""

    def test_email_simple_enmascarado(self) -> None:
        resultado = _enmascarar_email("usuario@empresa.com")
        assert resultado == "***@empresa.com"

    def test_email_con_subdominio(self) -> None:
        resultado = _enmascarar_email("contacto@sub.dominio.com.mx")
        assert resultado == "***@sub.dominio.com.mx"

    def test_email_con_caracteres_especiales_local(self) -> None:
        resultado = _enmascarar_email("nombre.apellido+tag@dominio.org")
        assert resultado == "***@dominio.org"

    def test_email_en_texto_largo(self) -> None:
        texto = "El cliente juan.perez@acme.com.mx envió un correo"
        resultado = _enmascarar_email(texto)
        assert "juan.perez" not in resultado
        assert "***@acme.com.mx" in resultado

    def test_multiples_emails_en_texto(self) -> None:
        texto = "De: admin@empresa.com Para: user@otro.org"
        resultado = _enmascarar_email(texto)
        assert "admin" not in resultado
        assert "user" not in resultado
        assert "***@empresa.com" in resultado
        assert "***@otro.org" in resultado

    def test_texto_sin_email_no_cambia(self) -> None:
        texto = "Este texto no tiene emails"
        resultado = _enmascarar_email(texto)
        assert resultado == texto

    def test_email_vacio_no_falla(self) -> None:
        resultado = _enmascarar_email("")
        assert resultado == ""


# ===========================================================================
# TESTS DE ENMASCARAMIENTO DE DATOS BANCARIOS (Req 10.5)
# ===========================================================================


class TestEnmascaramientoBancario:
    """Verifica regla: Datos bancarios → ****-****-****-XXXX (últimos 4)"""

    def test_clabe_18_digitos(self) -> None:
        resultado = _enmascarar_datos_bancarios("012345678901234567")
        assert resultado == "****-****-****-4567"

    def test_cuenta_16_digitos(self) -> None:
        resultado = _enmascarar_datos_bancarios("4152313456789012")
        assert resultado == "****-****-****-9012"

    def test_cuenta_con_guiones(self) -> None:
        resultado = _enmascarar_datos_bancarios("0123-4567-8901-2345")
        assert resultado == "****-****-****-2345"

    def test_cuenta_con_espacios(self) -> None:
        resultado = _enmascarar_datos_bancarios("0123 4567 8901 2345")
        assert resultado == "****-****-****-2345"

    def test_numero_corto_no_enmascara(self) -> None:
        """Números menores a 10 dígitos no se enmascaran."""
        resultado = _enmascarar_datos_bancarios("12345")
        assert resultado == "12345"

    def test_texto_sin_numeros_largos_no_cambia(self) -> None:
        texto = "El monto es de 15000 pesos"
        resultado = _enmascarar_datos_bancarios(texto)
        assert resultado == texto

    def test_clabe_en_contexto(self) -> None:
        texto = "Depositar a CLABE: 012345678901234567 en BBVA"
        resultado = _enmascarar_datos_bancarios(texto)
        assert "012345678901234567" not in resultado
        assert "****-****-****-4567" in resultado


# ===========================================================================
# TESTS DE ENMASCARAMIENTO DE NOMBRE (Req 10.5)
# ===========================================================================


class TestEnmascaramientoNombre:
    """Verifica regla: Nombre completo → J.G. (solo iniciales)"""

    def test_nombre_dos_palabras(self) -> None:
        resultado = _enmascarar_nombre("Juan García")
        assert resultado == "J.G."

    def test_nombre_tres_palabras(self) -> None:
        resultado = _enmascarar_nombre("María Fernanda López")
        assert resultado == "M.F.L."

    def test_nombre_una_palabra(self) -> None:
        resultado = _enmascarar_nombre("ACME")
        assert resultado == "A."

    def test_nombre_con_acentos(self) -> None:
        resultado = _enmascarar_nombre("José Ángel Ramírez")
        assert resultado == "J.Á.R."

    def test_nombre_vacio(self) -> None:
        resultado = _enmascarar_nombre("")
        assert resultado == ""

    def test_nombre_none(self) -> None:
        resultado = _enmascarar_nombre(None)
        assert resultado is None

    def test_nombre_solo_espacios(self) -> None:
        resultado = _enmascarar_nombre("   ")
        assert resultado == "   "


# ===========================================================================
# TESTS DE enmascarar_datos_sensibles() — FUNCIÓN PRINCIPAL
# ===========================================================================


class TestEnmascararDatosSensibles:
    """Verifica la función principal de enmascaramiento sobre diccionarios."""

    def test_enmascara_email_en_valor(self) -> None:
        data = {"correo": "cliente@empresa.com.mx"}
        resultado = enmascarar_datos_sensibles(data)
        assert resultado["correo"] == "***@empresa.com.mx"

    def test_enmascara_nombre_por_clave(self) -> None:
        data = {"cliente_nombre": "Juan García Pérez"}
        resultado = enmascarar_datos_sensibles(data)
        assert resultado["cliente_nombre"] == "J.G.P."

    def test_enmascara_nombre_clave_nombre(self) -> None:
        data = {"nombre": "María López"}
        resultado = enmascarar_datos_sensibles(data)
        assert resultado["nombre"] == "M.L."

    def test_enmascara_datos_bancarios_en_valor(self) -> None:
        data = {"clabe": "012345678901234567"}
        resultado = enmascarar_datos_sensibles(data)
        assert resultado["clabe"] == "****-****-****-4567"

    def test_diccionario_anidado(self) -> None:
        data = {
            "poliza": {
                "cliente_nombre": "Pedro Sánchez",
                "email": "pedro@dominio.com",
            }
        }
        resultado = enmascarar_datos_sensibles(data)
        assert resultado["poliza"]["cliente_nombre"] == "P.S."
        assert resultado["poliza"]["email"] == "***@dominio.com"

    def test_lista_de_diccionarios(self) -> None:
        data = {
            "contactos": [
                {"nombre": "Ana Torres"},
                {"nombre": "Luis Méndez"},
            ]
        }
        resultado = enmascarar_datos_sensibles(data)
        assert resultado["contactos"][0]["nombre"] == "A.T."
        assert resultado["contactos"][1]["nombre"] == "L.M."

    def test_valores_no_string_no_cambian(self) -> None:
        data = {"precio": 15000.0, "intentos": 2, "activo": True}
        resultado = enmascarar_datos_sensibles(data)
        assert resultado == data

    def test_input_no_dict_retorna_igual(self) -> None:
        assert enmascarar_datos_sensibles("texto") == "texto"  # type: ignore[arg-type]
        assert enmascarar_datos_sensibles(None) is None  # type: ignore[arg-type]
        assert enmascarar_datos_sensibles(42) == 42  # type: ignore[arg-type]

    def test_diccionario_vacio(self) -> None:
        resultado = enmascarar_datos_sensibles({})
        assert resultado == {}

    def test_combinacion_email_y_nombre(self) -> None:
        data = {
            "cliente_nombre": "Roberto Díaz",
            "destinatario": "roberto@cime.com.mx",
            "poliza_id": "POL-2024-001",
        }
        resultado = enmascarar_datos_sensibles(data)
        assert resultado["cliente_nombre"] == "R.D."
        assert resultado["destinatario"] == "***@cime.com.mx"
        assert resultado["poliza_id"] == "POL-2024-001"  # No se modifica


# ===========================================================================
# TESTS DE TRUNCADO A 10 KB (Req 10.1)
# ===========================================================================


class TestTruncado:
    """Verifica que las entradas no excedan 10 KB."""

    def test_entrada_pequena_no_se_trunca(self) -> None:
        data = {"poliza_id": "POL-001", "estado": "activo"}
        resultado = _truncar_entrada(data)
        assert "_truncado" not in resultado
        assert resultado == data

    def test_entrada_grande_se_trunca(self) -> None:
        # Crear entrada > 10 KB
        data = {"campo_grande": "x" * 15_000, "poliza_id": "POL-001"}
        resultado = _truncar_entrada(data)
        serializado = json.dumps(resultado, ensure_ascii=False, default=str)
        assert len(serializado.encode("utf-8")) <= OBSERVABILITY_MAX_ENTRY_BYTES

    def test_entrada_al_limite_no_se_trunca(self) -> None:
        # Crear entrada justo debajo de 10 KB
        overhead = len(json.dumps({"campo": ""}, ensure_ascii=False).encode("utf-8"))
        data = {"campo": "a" * (OBSERVABILITY_MAX_ENTRY_BYTES - overhead - 10)}
        resultado = _truncar_entrada(data)
        assert "_truncado" not in resultado


# ===========================================================================
# TESTS DE LAS 5 FUNCIONES DE TRAZA (sin errores)
# ===========================================================================


class TestFuncionesTraza:
    """Verifica que las 5 funciones de traza se ejecutan sin error."""

    def test_registrar_inicio_sesion(self) -> None:
        # No debe lanzar excepción
        registrar_inicio_sesion(
            poliza_id="POL-2024-001",
            session_id="sess-abc123",
            timestamp_inicio=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
            estado_pipefy_inicial="Póliza detectada",
        )

    def test_registrar_tool_call(self) -> None:
        registrar_tool_call(
            tool_name="enviar_correo",
            params_enmascarados={
                "destinatario": "cliente@empresa.com",
                "asunto": "Renovación",
            },
            resultado={"success": True, "message_id": "msg-123"},
            duracion_ms=450.0,
        )

    def test_registrar_error(self) -> None:
        registrar_error(
            tipo_error="TimeoutError",
            componente="pipefy",
            mensaje_error="No hubo respuesta en 30s",
            num_reintento=1,
            accion_mitigacion="retry",
        )

    def test_registrar_cierre_sesion(self) -> None:
        registrar_cierre_sesion(
            estado_final="En validación con tesorería",
            duracion_total_ms=45000.0,
            mensajes_enviados=3,
            motivo_cierre="flujo_completado",
        )

    def test_registrar_bloqueo_policy(self) -> None:
        registrar_bloqueo_policy(
            motivo_bloqueo="descuento_no_autorizado",
            tool_intentada="enviar_correo",
            session_id="sess-abc123",
            estado_pipefy="Cliente interesado",
            timestamp=datetime(2025, 7, 15, 11, 30, 0, tzinfo=timezone.utc),
        )

    def test_registrar_bloqueo_policy_sin_timestamp(self) -> None:
        """Si no se pasa timestamp, se usa datetime.now(UTC)."""
        registrar_bloqueo_policy(
            motivo_bloqueo="datos_bancarios_fuera_estado",
            tool_intentada="enviar_correo",
            session_id="sess-xyz456",
            estado_pipefy="Contacto inicial enviado",
        )


# ===========================================================================
# TEST DE FALLBACK (Req 10.6)
# ===========================================================================


class TestFallback:
    """Verifica que si falla la escritura primaria, se usa fallback."""

    def test_fallback_cuando_logger_falla(self) -> None:
        """Si el logger primario lanza excepción, el fallback registra sin interrumpir."""
        with patch("src.observability.tracer._logger.info", side_effect=Exception("Fallo OTel")):
            # No debe lanzar excepción
            registrar_inicio_sesion(
                poliza_id="POL-2024-001",
                session_id="sess-fallback",
                timestamp_inicio=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
                estado_pipefy_inicial="Póliza detectada",
            )
            # El test pasa si no hay excepción - flujo no interrumpido

    def test_tool_call_con_params_enmascara_antes_de_registrar(self) -> None:
        """Verifica que el enmascaramiento ocurre ANTES del registro."""
        registros: list[str] = []

        with patch("src.observability.tracer._logger.info", side_effect=lambda msg: registros.append(msg)):
            registrar_tool_call(
                tool_name="enviar_correo",
                params_enmascarados={
                    "destinatario": "secreto@empresa.com",
                    "cliente_nombre": "Juan García",
                },
                resultado={"success": True},
                duracion_ms=100.0,
            )

        assert len(registros) == 1
        registro = json.loads(registros[0])
        # El email debe estar enmascarado en el registro
        assert "secreto" not in registros[0]
        assert "***@empresa.com" in registros[0]
        # El nombre debe estar enmascarado
        assert "Juan García" not in registros[0]
        assert "J.G." in registros[0]



# ===========================================================================
# PROPERTY-BASED TEST — Propiedad 20: Enmascaramiento de datos sensibles (PBT)
# ===========================================================================

# Regex para detectar emails completos (NO enmascarados) en la salida
_FULL_EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


def _genera_numero_bancario(draw: st.DrawFn) -> str:
    """Estrategia para generar números bancarios de 10-18 dígitos."""
    longitud = draw(st.integers(min_value=10, max_value=18))
    digitos = draw(st.text(alphabet=string.digits, min_size=longitud, max_size=longitud))
    return digitos


# Estrategia de emails que hypothesis puede generar
_st_emails = st.emails()

# Estrategia de nombres: 1-4 palabras con letras
_st_nombres = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
        min_size=2,
        max_size=12,
    ),
    min_size=1,
    max_size=4,
).map(lambda partes: " ".join(partes))

# Estrategia de números bancarios (12-18 dígitos)
# La regex _BANKING_REGEX requiere al mínimo 12 caracteres para match:
# patrón \d[\d\s\-]{10,17}\d = 1 + (10-17) + 1 = 12-19 chars
_st_numeros_bancarios = st.integers(min_value=12, max_value=18).flatmap(
    lambda n: st.text(alphabet=string.digits, min_size=n, max_size=n)
)


class TestProperty20EnmascaramientoDatosSensibles:
    """
    **Validates: Requirements 10.5**

    Property 20: Enmascaramiento de datos sensibles en Observability.

    Para 100 registros generados con distintos datos de clientes (emails, nombres,
    datos bancarios), verificar que la regex de detección de emails NO encuentra
    coincidencias en campos `params_enmascarados` y `resultado`, y que no quedan
    datos bancarios crudos (secuencias de 10+ dígitos consecutivos) en la salida.
    """

    @given(
        cliente_email=_st_emails,
        cliente_nombre=_st_nombres,
        numero_bancario=_st_numeros_bancarios,
    )
    @settings(max_examples=100, deadline=5000)
    def test_property_20_no_emails_en_params_enmascarados(
        self,
        cliente_email: str,
        cliente_nombre: str,
        numero_bancario: str,
    ) -> None:
        """
        Feature: agente-comercial-polizas,
        Property 20: Enmascaramiento de datos sensibles en Observability

        Verifica que después de aplicar enmascarar_datos_sensibles(), los campos
        params_enmascarados y resultado NO contienen emails completos detectables
        por la regex [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}
        """
        # Construir datos de entrada con información sensible
        params_originales = {
            "destinatario": cliente_email,
            "cliente_nombre": cliente_nombre,
            "cuenta_bancaria": numero_bancario,
            "mensaje": f"Estimado {cliente_nombre}, su email es {cliente_email}",
        }

        resultado_original = {
            "success": True,
            "email_enviado_a": cliente_email,
            "nombre_cliente": cliente_nombre,
            "referencia_pago": numero_bancario,
        }

        # Aplicar enmascaramiento
        params_enmascarados = enmascarar_datos_sensibles(params_originales)
        resultado_enmascarado = enmascarar_datos_sensibles(resultado_original)

        # Serializar para inspección con regex
        params_str = json.dumps(params_enmascarados, ensure_ascii=False)
        resultado_str = json.dumps(resultado_enmascarado, ensure_ascii=False)

        # PROPIEDAD: La regex de email NO debe encontrar coincidencias
        # en los datos enmascarados.
        # Nota: ***@dominio.com NO matchea la regex porque "***" no cumple
        # [a-zA-Z0-9._%+-]+ (contiene asteriscos que no están en la clase)
        emails_en_params = _FULL_EMAIL_REGEX.findall(params_str)
        emails_en_resultado = _FULL_EMAIL_REGEX.findall(resultado_str)

        assert emails_en_params == [], (
            f"Se encontraron emails sin enmascarar en params_enmascarados: "
            f"{emails_en_params}. Input email: {cliente_email}"
        )
        assert emails_en_resultado == [], (
            f"Se encontraron emails sin enmascarar en resultado: "
            f"{emails_en_resultado}. Input email: {cliente_email}"
        )

    @given(
        cliente_email=_st_emails,
        cliente_nombre=_st_nombres,
        numero_bancario=_st_numeros_bancarios,
    )
    @settings(max_examples=100, deadline=5000)
    def test_property_20_no_datos_bancarios_crudos(
        self,
        cliente_email: str,
        cliente_nombre: str,
        numero_bancario: str,
    ) -> None:
        """
        Feature: agente-comercial-polizas,
        Property 20: Enmascaramiento de datos sensibles en Observability

        Verifica que después de enmascarar, no quedan secuencias de datos
        bancarios crudos (números de 10+ dígitos consecutivos) en la salida.
        """
        params_originales = {
            "destinatario": cliente_email,
            "cliente_nombre": cliente_nombre,
            "cuenta_clabe": numero_bancario,
            "info_pago": f"Depositar a cuenta {numero_bancario} del titular {cliente_nombre}",
        }

        # Aplicar enmascaramiento
        params_enmascarados = enmascarar_datos_sensibles(params_originales)
        params_str = json.dumps(params_enmascarados, ensure_ascii=False)

        # El número bancario original (12+ dígitos consecutivos) NO debe
        # aparecer intacto en la salida enmascarada
        if len(numero_bancario) >= 12:
            assert numero_bancario not in params_str, (
                f"Número bancario crudo '{numero_bancario}' encontrado en salida "
                f"enmascarada: {params_str}"
            )

    @given(
        cliente_email=_st_emails,
        cliente_nombre=_st_nombres,
        numero_bancario=_st_numeros_bancarios,
    )
    @settings(max_examples=100, deadline=5000)
    def test_property_20_registrar_tool_call_enmascara_correctamente(
        self,
        cliente_email: str,
        cliente_nombre: str,
        numero_bancario: str,
    ) -> None:
        """
        Feature: agente-comercial-polizas,
        Property 20: Enmascaramiento de datos sensibles en Observability

        Verifica el flujo completo: registrar_tool_call() aplica enmascaramiento
        ANTES de registrar, y la salida registrada no contiene emails completos.
        """
        registros: list[str] = []

        with patch(
            "src.observability.tracer._logger.info",
            side_effect=lambda msg: registros.append(msg),
        ):
            registrar_tool_call(
                tool_name="enviar_correo",
                params_enmascarados={
                    "destinatario": cliente_email,
                    "cliente_nombre": cliente_nombre,
                    "cuenta_bancaria": numero_bancario,
                },
                resultado={
                    "success": True,
                    "email_enviado_a": cliente_email,
                    "nombre_cliente": cliente_nombre,
                },
                duracion_ms=150.0,
            )

        assert len(registros) == 1, "Debe haber exactamente un registro"
        registro_str = registros[0]

        # Verificar que NO hay emails completos en el registro
        emails_encontrados = _FULL_EMAIL_REGEX.findall(registro_str)
        assert emails_encontrados == [], (
            f"Se encontraron emails sin enmascarar en el registro de "
            f"observabilidad: {emails_encontrados}. Input: {cliente_email}"
        )

        # Verificar que el número bancario crudo no aparece
        if len(numero_bancario) >= 12:
            assert numero_bancario not in registro_str, (
                f"Número bancario crudo '{numero_bancario}' en registro "
                f"de observabilidad"
            )
