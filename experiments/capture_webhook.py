"""Captura ponta a ponta do webhook real do Gophish.

Sobe o receptor de eventos da plataforma — a mesma validação de assinatura, a
mesma normalização e a mesma persistência de `ingestion.py` — e, além de
processar cada requisição, registra em um arquivo de evidência tudo o que
efetivamente chegou: cabeçalhos, corpo bruto, veredito da assinatura e desfecho
da ingestão. Serve para confirmar que a plataforma recebe o Gophish real, e não
uma reconstrução do seu formato.

Uso:
    GOPHISH_WEBHOOK_SECRET=<segredo> python experiments/capture_webhook.py
    (ou passe --secret <segredo>)

O segredo deve ser idêntico ao configurado no webhook do Gophish. O receptor
escuta em http://127.0.0.1:9099/ por padrão. Encerre com Ctrl+C.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_HERE)
sys.path.insert(0, _RAIZ)

import database    # noqa: E402
import ingestion   # noqa: E402

DATA_DIR = os.path.join(_RAIZ, "data")
CAPTURE_DB = os.path.join(_RAIZ, "captura-webhook.db")


class CaptureHandler(BaseHTTPRequestHandler):
    """Receptor real, acrescido de um registro de evidência por requisição.

    Reaproveita `valid_signature` e `handle_event` de `ingestion.py`: a lógica
    exercitada é exatamente a da plataforma, sem simulacro. O único acréscimo é
    a gravação do que chegou, para inspeção posterior.
    """

    secret = ""
    db_path = CAPTURE_DB
    evidencia = os.path.join(DATA_DIR, "captura-webhook.jsonl")

    def _responder(self, code: int, obj: dict) -> None:
        corpo = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _registrar(self, registro: dict) -> None:
        registro["recebido_em"] = datetime.now(timezone.utc).isoformat()
        with open(self.evidencia, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
        print("\n=== requisição recebida do Gophish ===")
        print("  cabeçalho de assinatura:", registro.get("assinatura_recebida"))
        print("  assinatura válida:", registro.get("assinatura_valida"))
        print("  corpo bruto:", registro.get("corpo_bruto"))
        print("  desfecho da ingestão:", registro.get("desfecho"))
        sys.stdout.flush()

    def do_POST(self) -> None:
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(tamanho) if tamanho > 0 else b""
        assinatura = self.headers.get(ingestion.SIGNATURE_HEADER)
        valida = ingestion.valid_signature(self.secret, corpo, assinatura)

        registro = {
            "corpo_bruto": corpo.decode("utf-8", "replace"),
            "assinatura_recebida": assinatura,
            "assinatura_valida": valida,
            "cabecalhos": {k: v for k, v in self.headers.items()},
        }

        if not valida:
            registro["desfecho"] = "rejeitado: assinatura inválida"
            self._registrar(registro)
            return self._responder(401, {"status": "error", "reason": "assinatura inválida"})

        try:
            payload = json.loads(corpo)
        except json.JSONDecodeError:
            registro["desfecho"] = "rejeitado: JSON malformado"
            self._registrar(registro)
            return self._responder(400, {"status": "error", "reason": "JSON malformado"})

        try:
            resultado = ingestion.handle_event(payload, self.db_path)
        except Exception as exc:                                    # noqa: BLE001
            registro["desfecho"] = f"erro: {type(exc).__name__}"
            self._registrar(registro)
            return self._responder(503, {"status": "error", "reason": type(exc).__name__})

        registro["desfecho"] = resultado
        self._registrar(registro)
        self._responder(200, resultado)

    def log_message(self, fmt, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Captura do webhook real do Gophish.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9099)
    parser.add_argument("--secret", default=os.environ.get("GOPHISH_WEBHOOK_SECRET", ""))
    args = parser.parse_args()

    if not args.secret:
        raise SystemExit("Defina o segredo por --secret ou GOPHISH_WEBHOOK_SECRET.")

    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(CAPTURE_DB):
        os.remove(CAPTURE_DB)
    database.create_database(CAPTURE_DB)

    CaptureHandler.secret = args.secret
    CaptureHandler.db_path = CAPTURE_DB
    servidor = ThreadingHTTPServer((args.host, args.port), CaptureHandler)
    print(f"Receptor de captura ouvindo em http://{args.host}:{args.port}/")
    print(f"Evidência em: {CaptureHandler.evidencia}")
    print("Aguardando eventos do Gophish... (Ctrl+C para encerrar)")
    sys.stdout.flush()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
        servidor.shutdown()


if __name__ == "__main__":
    main()
