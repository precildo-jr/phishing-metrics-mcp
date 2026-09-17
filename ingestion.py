"""Camada de ingestão: receptor de eventos do GoPhish via webhook.

Recebe as notificações que o GoPhish emite ao longo de uma campanha, valida a
assinatura HMAC-SHA256 do corpo da requisição, normaliza cada evento para o
vocabulário interno de funil e o persiste de forma idempotente.

O GoPhish assina o corpo bruto da requisição com o segredo configurado no
webhook e envia o resultado no cabeçalho `X-Gophish-Signature`, no formato
`sha256=<hexdigest>`. A validação usa comparação de tempo constante.

Sem dependências externas: apenas a biblioteca padrão do Python.

Uso:
    GOPHISH_WEBHOOK_SECRET=<segredo> python ingestion.py [--host H] [--port P]
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import database

SIGNATURE_HEADER = "X-Gophish-Signature"
MAX_BODY_BYTES = 1_048_576  # 1 MiB; um evento de campanha é muito menor

# Substitui o endereço do destinatário no corpo bruto preservado para auditoria.
# O pseudônimo correspondente permanece disponível no campo `target_id`.
REDACTED = "[endereco-suprimido]"


def valid_signature(secret: str, body: bytes, header_value: str | None) -> bool:
    """Confere a assinatura HMAC-SHA256 do corpo bruto, em tempo constante.

    Aceita tanto `sha256=<hex>` quanto o hexdigest puro, por robustez.
    """
    if not header_value:
        return False
    received = header_value.split("=", 1)[1] if header_value.startswith("sha256=") \
        else header_value
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received, expected)


def normalize(payload: dict) -> dict | None:
    """Converte um evento do GoPhish no registro interno.

    Retorna None para mensagens que não correspondem a um degrau do funil
    (por exemplo, "Campaign Created"), que são descartadas silenciosamente.

    O identificador externo do evento, base da idempotência, é derivado dos
    campos que identificam univocamente a ocorrência — campanha, alvo, tipo e
    instante — de modo que a reentrega da mesma notificação produza a mesma
    chave.

    O corpo bruto é preservado para auditoria, mas com o endereço do
    destinatário suprimido: retê-lo em texto claro anularia a pseudonimização
    aplicada ao campo de alvo, já que bastaria ler o corpo para recuperá-lo.
    """
    message = payload.get("message")
    event_type = database.GOPHISH_MESSAGE_MAP.get(message)
    if event_type is None:
        return None

    campaign_external_id = payload.get("campaign_id")
    email = payload.get("email") or ""
    origin_ts = payload.get("time") or ""

    fingerprint = f"{campaign_external_id}|{email}|{event_type}|{origin_ts}"
    external_event_id = "gp-" + hashlib.sha256(
        fingerprint.encode("utf-8")).hexdigest()[:24]

    auditavel = dict(payload)
    if auditavel.get("email"):
        auditavel["email"] = REDACTED

    return {
        "campaign_name": f"gophish-campaign-{campaign_external_id}",
        "campaign_external_id": campaign_external_id,
        "event_type": event_type,
        "source": "gophish_webhook",
        "external_event_id": external_event_id,
        "target": email or None,
        "origin_ts": origin_ts or None,
        "raw_payload": json.dumps(auditavel, ensure_ascii=False),
    }


def handle_event(payload: dict, db_path: str = database.DB_PATH) -> dict:
    """Normaliza e persiste um evento. Retorna o desfecho da operação."""
    record = normalize(payload)
    if record is None:
        return {"status": "ignored", "reason": "tipo fora do funil"}

    event_id, inserted = database.register_event(
        record["campaign_name"], record["event_type"], record["source"],
        external_event_id=record["external_event_id"], target=record["target"],
        origin_ts=record["origin_ts"], raw_payload=record["raw_payload"],
        campaign_external_id=record["campaign_external_id"], db_path=db_path)

    return {
        "status": "stored" if inserted else "duplicate",
        "event_id": event_id,
        "event_type": record["event_type"],
    }


class WebhookHandler(BaseHTTPRequestHandler):
    secret = ""
    db_path = database.DB_PATH

    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return self._reply(400, {"status": "error", "reason": "corpo inválido"})

        body = self.rfile.read(length)

        if not valid_signature(self.secret, body, self.headers.get(SIGNATURE_HEADER)):
            return self._reply(401, {"status": "error", "reason": "assinatura inválida"})

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return self._reply(400, {"status": "error", "reason": "JSON malformado"})

        try:
            result = handle_event(payload, self.db_path)
        except Exception as exc:  # persistência indisponível não pode derrubar o receptor
            return self._reply(503, {"status": "error", "reason": type(exc).__name__})

        self._reply(200, result)

    def log_message(self, fmt, *args):  # silencia o log padrão do http.server
        pass


def build_server(host: str, port: int, secret: str,
                 db_path: str = database.DB_PATH) -> ThreadingHTTPServer:
    database.create_database(db_path)
    WebhookHandler.secret = secret
    WebhookHandler.db_path = db_path
    return ThreadingHTTPServer((host, port), WebhookHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Receptor de webhook do GoPhish.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9099)
    args = parser.parse_args()

    secret = os.environ.get("GOPHISH_WEBHOOK_SECRET", "")
    if not secret:
        raise SystemExit("Defina GOPHISH_WEBHOOK_SECRET no ambiente antes de iniciar.")

    server = build_server(args.host, args.port, secret)
    print(f"Receptor de webhook ouvindo em http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
