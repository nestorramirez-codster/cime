"""
Tool enviar_correo para el Agente Comercial IA de CIME Power Systems.

Envía correos electrónicos vía Amazon SES con soporte para adjuntos (S3 keys).
Incluye retry automático (1 intento tras 60s) para errores técnicos y
validación de email RFC 5321 antes de enviar.

Requisitos: 2.1, 2.6, 2.7, 4.5, 4.8
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.models.constants import (
    RETRY_BACKOFF_CORREO_SEGUNDOS,
    RETRY_MAX_INTENTOS_CORREO,
)
from src.models.data_models import EmailResult
from src.observability.tracer import registrar_error, registrar_tool_call

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expresión regular para validación de email (RFC 5321 — subconjunto práctico)
# Misma expresión utilizada en src/models/validators.py
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

# Dirección de origen configurada por variable de entorno
_SENDER_EMAIL = os.environ.get("CIME_SES_SENDER", "noreply@cimepower.com")

# Región AWS para SES
_SES_REGION = os.environ.get("CIME_SES_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# Excepciones personalizadas
# ---------------------------------------------------------------------------


class InvalidEmailError(Exception):
    """Error de email inválido. No se debe reintentar; escalar a humano (Req 2.7)."""

    def __init__(self, email: str, message: Optional[str] = None):
        self.email = email
        self.message = message or f"Dirección de correo inválida: '{email}'"
        super().__init__(self.message)


class SESError(Exception):
    """Error técnico de Amazon SES tras agotar reintentos (Req 2.6).

    Se debe escalar a humano cuando se lanza esta excepción.
    """

    def __init__(self, error_code: str, message: Optional[str] = None):
        self.error_code = error_code
        self.message = message or f"Error técnico SES: {error_code}"
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Funciones internas
# ---------------------------------------------------------------------------


def _es_email_valido(email: str) -> bool:
    """Valida formato de email RFC 5321 (subconjunto práctico)."""
    if not isinstance(email, str) or not email.strip():
        return False
    return bool(_EMAIL_RE.match(email.strip()))


def _is_mock_mode() -> bool:
    """Verifica si el sistema está en modo mock para desarrollo local."""
    return os.environ.get("CIME_MOCK_MODE", "").lower() == "true"


def _get_ses_client():
    """Obtiene el cliente boto3 SES (lazy, no cached — cada llamada es independiente)."""
    import boto3

    return boto3.client("ses", region_name=_SES_REGION)


def _send_simple_email(
    client, destinatario: str, asunto: str, cuerpo: str
) -> str:
    """Envía un correo simple (sin adjuntos) usando SES send_email."""
    response = client.send_email(
        Source=_SENDER_EMAIL,
        Destination={"ToAddresses": [destinatario]},
        Message={
            "Subject": {"Data": asunto, "Charset": "UTF-8"},
            "Body": {
                "Html": {"Data": cuerpo, "Charset": "UTF-8"},
                "Text": {"Data": cuerpo, "Charset": "UTF-8"},
            },
        },
    )
    return response["MessageId"]


def _send_raw_email_with_attachments(
    client, destinatario: str, asunto: str, cuerpo: str, adjuntos: list[str]
) -> str:
    """Envía un correo con adjuntos usando SES send_raw_email.

    Los adjuntos son S3 keys que se descargan y adjuntan al mensaje MIME.
    """
    import boto3

    msg = MIMEMultipart("mixed")
    msg["Subject"] = asunto
    msg["From"] = _SENDER_EMAIL
    msg["To"] = destinatario

    # Cuerpo del mensaje
    body_part = MIMEText(cuerpo, "html", "utf-8")
    msg.attach(body_part)

    # Descargar y adjuntar archivos desde S3
    s3_client = boto3.client("s3", region_name=_SES_REGION)
    bucket = os.environ.get("CIME_S3_BUCKET", "cime-attachments")

    for s3_key in adjuntos:
        try:
            s3_response = s3_client.get_object(Bucket=bucket, Key=s3_key)
            file_content = s3_response["Body"].read()
            filename = s3_key.split("/")[-1] if "/" in s3_key else s3_key

            attachment = MIMEApplication(file_content)
            attachment.add_header(
                "Content-Disposition", "attachment", filename=filename
            )
            msg.attach(attachment)
            logger.info(f"Adjunto añadido: {filename} ({len(file_content)} bytes)")
        except Exception as e:
            logger.warning(f"No se pudo adjuntar {s3_key}: {e}")
            # Continúa sin el adjunto — el correo se envía igual

    response = client.send_raw_email(
        Source=_SENDER_EMAIL,
        Destinations=[destinatario],
        RawMessage={"Data": msg.as_string()},
    )
    return response["MessageId"]


def _mock_enviar_correo(
    destinatario: str, asunto: str, adjuntos: Optional[list[str]]
) -> EmailResult:
    """Simula el envío de correo en modo mock para desarrollo local."""
    fake_message_id = f"mock-{uuid.uuid4().hex[:16]}"
    adjuntos_info = f" con {len(adjuntos)} adjuntos" if adjuntos else ""
    logger.info(
        f"[MOCK] Correo enviado a {destinatario}: '{asunto}'{adjuntos_info} "
        f"(message_id={fake_message_id})"
    )
    return EmailResult(
        success=True,
        message_id=fake_message_id,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Función principal: enviar_correo
# ---------------------------------------------------------------------------


def enviar_correo(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    adjuntos: Optional[list[str]] = None,
) -> EmailResult:
    """
    Envía un correo electrónico via Amazon SES.

    Args:
        destinatario: Dirección de correo RFC 5321 válida.
        asunto: Línea de asunto del correo.
        cuerpo: Contenido HTML o texto plano del correo.
        adjuntos: Lista de S3 keys de archivos adjuntos (opcional).

    Returns:
        EmailResult con success=True y message_id si el envío fue exitoso.

    Raises:
        InvalidEmailError: Si la dirección es inválida (escalar_humano, Req 2.7).
            NO se reintenta.
        SESError: Error técnico tras agotar 1 reintento (60s backoff, Req 2.6).
            El agente debe escalar a humano.
    """
    _start_time = time.time()

    # 1. Validar formato de email
    if not _es_email_valido(destinatario):
        logger.error(f"Email inválido detectado: '{destinatario}'")
        registrar_error(
            tipo_error="InvalidEmailError",
            componente="ses",
            mensaje_error=f"Dirección de correo inválida: '{destinatario}'",
            num_reintento=0,
            accion_mitigacion="escalar_humano",
        )
        raise InvalidEmailError(destinatario)

    # 2. Modo mock para desarrollo local
    if _is_mock_mode():
        result = _mock_enviar_correo(destinatario, asunto, adjuntos)
        _duration_ms = (time.time() - _start_time) * 1000
        registrar_tool_call(
            tool_name="enviar_correo",
            params_enmascarados={
                "destinatario": destinatario,
                "asunto": asunto,
                "adjuntos": adjuntos,
            },
            resultado={"success": result.success, "message_id": result.message_id},
            duracion_ms=_duration_ms,
        )
        return result

    # 3. Envío real con retry para errores técnicos
    client = _get_ses_client()
    intentos = 0
    max_intentos = 1 + RETRY_MAX_INTENTOS_CORREO  # 1 intento inicial + 1 retry

    last_error_code: Optional[str] = None
    last_error_msg: Optional[str] = None

    while intentos < max_intentos:
        try:
            logger.info(
                f"Enviando correo a {destinatario} (intento {intentos + 1}/{max_intentos})"
            )

            if adjuntos:
                message_id = _send_raw_email_with_attachments(
                    client, destinatario, asunto, cuerpo, adjuntos
                )
            else:
                message_id = _send_simple_email(
                    client, destinatario, asunto, cuerpo
                )

            logger.info(f"Correo enviado exitosamente: message_id={message_id}")
            _duration_ms = (time.time() - _start_time) * 1000
            result = EmailResult(
                success=True,
                message_id=message_id,
                timestamp=datetime.now(timezone.utc),
            )
            registrar_tool_call(
                tool_name="enviar_correo",
                params_enmascarados={
                    "destinatario": destinatario,
                    "asunto": asunto,
                    "adjuntos": adjuntos,
                },
                resultado={"success": True, "message_id": message_id},
                duracion_ms=_duration_ms,
            )
            return result

        except Exception as e:
            error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "Unknown")
            error_msg = str(e)

            # Errores de email inválido de SES → no reintentar
            if error_code in (
                "InvalidParameterValue",
                "MessageRejected",
                "MailFromDomainNotVerifiedException",
            ):
                logger.error(
                    f"SES rechazó el destinatario '{destinatario}': {error_code}"
                )
                registrar_error(
                    tipo_error="InvalidEmailError",
                    componente="ses",
                    mensaje_error=f"SES rechazó: {error_code} - {error_msg}",
                    num_reintento=intentos,
                    accion_mitigacion="escalar_humano",
                )
                raise InvalidEmailError(
                    destinatario,
                    f"SES rechazó el correo: {error_code} - {error_msg}",
                )

            # Error técnico → registrar y posiblemente reintentar
            last_error_code = error_code
            last_error_msg = error_msg
            intentos += 1

            registrar_error(
                tipo_error="SESError",
                componente="ses",
                mensaje_error=f"{error_code}: {error_msg}",
                num_reintento=intentos,
                accion_mitigacion="retry" if intentos < max_intentos else "escalar_humano",
            )

            if intentos < max_intentos:
                logger.warning(
                    f"Error técnico SES ({error_code}), "
                    f"reintentando en {RETRY_BACKOFF_CORREO_SEGUNDOS}s..."
                )
                time.sleep(RETRY_BACKOFF_CORREO_SEGUNDOS)
            else:
                logger.error(
                    f"Error técnico SES tras {max_intentos} intentos: "
                    f"{error_code} - {error_msg}"
                )

    # Todos los intentos fallaron → lanzar SESError
    _duration_ms = (time.time() - _start_time) * 1000
    registrar_tool_call(
        tool_name="enviar_correo",
        params_enmascarados={
            "destinatario": destinatario,
            "asunto": asunto,
            "adjuntos": adjuntos,
        },
        resultado={"success": False, "error_code": last_error_code},
        duracion_ms=_duration_ms,
    )
    raise SESError(
        error_code=last_error_code or "Unknown",
        message=f"Fallo tras {max_intentos} intentos: {last_error_msg}",
    )
