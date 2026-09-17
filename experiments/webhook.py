"""Utilitários comuns aos arneses que exercitam a camada de ingestão.

Reúne o que `run_experiment.py`, `robustness.py` e `concurrency.py` precisam
para falar com o receptor de webhook como o Gophish falaria: o segredo do
webhook, a assinatura HMAC do corpo e a subida do receptor real em porta
efêmera. Concentrar isso aqui evita que cada arnês repita a assinatura, que é
justamente o ponto onde uma divergência passaria despercebida.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ingestion  # noqa: E402

SECRET = "segredo-de-teste-do-experimento"
HOST = "127.0.0.1"


def sign(body: bytes) -> str:
    """Assina o corpo como o Gophish o assinaria."""
    return "sha256=" + hmac.new(SECRET.encode("utf-8"), body,
                                hashlib.sha256).hexdigest()


def post(port: int, payload, *, signature: str | None = None,
         raw: bytes | None = None, timeout: float = 60.0) -> tuple[int, dict]:
    """Envia uma requisição ao receptor. Devolve (código HTTP, corpo)."""
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json",
               ingestion.SIGNATURE_HEADER: signature if signature is not None
               else sign(body)}
    conn = http.client.HTTPConnection(HOST, port, timeout=timeout)
    try:
        conn.request("POST", "/", body=body, headers=headers)
        resp = conn.getresponse()
        dados = resp.read()
        try:
            return resp.status, json.loads(dados)
        except json.JSONDecodeError:
            return resp.status, {"raw": dados.decode("utf-8", "replace")}
    finally:
        conn.close()


class Receptor:
    """Sobe o receptor real em porta efêmera, com base de dados própria."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.server = ingestion.build_server(HOST, 0, SECRET, db_path)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def novo_db(prefixo: str = "arnes_") -> str:
    """Caminho de uma base temporária ainda inexistente."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix=prefixo)
    os.close(fd)
    os.remove(path)
    return path
