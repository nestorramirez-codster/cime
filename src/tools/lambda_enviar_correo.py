"""
Lambda Action Group — enviar_correo

Esta Lambda es invocada por el Bedrock Agent cuando decide enviar un correo.
Recibe los parámetros del agente y ejecuta el envío via SES.
"""

import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ses = boto3.client("ses", region_name="us-east-1")

SENDER = "CIME Power Systems <agente-comercial@ses.codster.mx>"


def handler(event, context):
    """
    Handler para Action Group de Bedrock Agent.

    El evento tiene la estructura estándar de Action Groups:
    {
        "actionGroup": "enviar_correo_group",
        "function": "enviar_correo",
        "parameters": [
            {"name": "destinatario", "value": "..."},
            {"name": "asunto", "value": "..."},
            {"name": "cuerpo", "value": "..."}
        ]
    }
    """
    logger.info(f"Evento recibido: {json.dumps(event, default=str)}")

    # Extraer parámetros del evento de Action Group
    parameters = {}
    for param in event.get("parameters", []):
        parameters[param["name"]] = param.get("value", "")

    # También soportar el formato alternativo con "function"
    if not parameters and "function" in event:
        func_params = event.get("parameters", event.get("requestBody", {}).get("content", {}).get("application/json", {}).get("properties", []))
        if isinstance(func_params, list):
            for param in func_params:
                parameters[param["name"]] = param.get("value", "")

    destinatario = parameters.get("destinatario", "")
    asunto = parameters.get("asunto", "")
    cuerpo = parameters.get("cuerpo", "")

    logger.info(f"Enviando correo a: {destinatario}, asunto: {asunto}")

    if not destinatario or not asunto or not cuerpo:
        return _build_response(event, "error", "Faltan parametros: destinatario, asunto y cuerpo son obligatorios.")

    try:
        response = ses.send_email(
            Source=SENDER,
            Destination={"ToAddresses": [destinatario]},
            Message={
                "Subject": {"Data": asunto, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": cuerpo, "Charset": "UTF-8"}},
            },
        )
        message_id = response["MessageId"]
        logger.info(f"Correo enviado exitosamente. MessageId: {message_id}")
        return _build_response(event, "success", f"Correo enviado exitosamente a {destinatario}. MessageId: {message_id}")

    except Exception as e:
        logger.error(f"Error enviando correo: {e}")
        return _build_response(event, "error", f"Error al enviar correo: {str(e)}")


def _build_response(event, status, message):
    """Construye la respuesta en el formato esperado por Bedrock Agent Action Groups."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", ""),
            "function": event.get("function", ""),
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": json.dumps({"status": status, "message": message})
                    }
                }
            }
        }
    }
