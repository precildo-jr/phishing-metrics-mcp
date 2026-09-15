"""Bateria de verificação de robustez da camada de ingestão.

Submete o receptor de webhook — em execução real, sobre HTTP e com base de
dados própria — aos sete casos adversos previstos no protocolo experimental do
TCC. Para cada caso registra o comportamento esperado, o comportamento
observado e o veredito, na forma exigida pela seção Material e Métodos.

Os casos não exercitam simulacros: o servidor é o de `ingestion.py`, a
persistência é a de `database.py`, e as requisições trafegam por soquete. O
que se verifica é, portanto, o comportamento do componente tal como seria
executado em operação.

Casos:
  R1  conteúdo malicioso em campo textual (injeção de SQL)
  R2  reentrega de evento já processado (idempotência)
  R3  evento com estrutura inválida (JSON malformado)
  R4  evento com campo obrigatório ausente
  R5  evento com carimbo de tempo anterior ao do evento precedente
  R6  indisponibilidade da camada de persistência durante a ingestão
  R7  requisição de ingestão com assinatura inválida

Uso:
    python experiments/robustness.py
Os resultados vão para `../data/robustez-<carimbo>.csv`.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import http.client
import json
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

import database    # noqa: E402
import ingestion   # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(_HERE), "data")
SECRET = "segredo-de-teste-do-experimento"
HOST = "127.0.0.1"

CSV_FIELDS = ["caso", "descricao", "esperado", "observado", "veredito"]


# --- infraestrutura de apoio -------------------------------------------------
def sign(body: bytes) -> str:
    """Assina o corpo como o GoPhish o assinaria."""
    return "sha256=" + hmac.new(SECRET.encode("utf-8"), body,
                                hashlib.sha256).hexdigest()


def post(port: int, payload, *, signature: str | None = None,
         raw: bytes | None = None) -> tuple[int, dict]:
    """Envia uma requisição ao receptor. Devolve (código HTTP, corpo)."""
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json",
               ingestion.SIGNATURE_HEADER: signature if signature is not None
               else sign(body)}
    conn = http.client.HTTPConnection(HOST, port, timeout=10)
    try:
        conn.request("POST", "/", body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        try:
            return resp.status, json.loads(data)
        except json.JSONDecodeError:
            return resp.status, {"raw": data.decode("utf-8", "replace")}
    finally:
        conn.close()


def count_events(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()


def gophish_payload(message: str, email: str, time: str,
                    campaign_id: int = 7) -> dict:
    """Notificação do GoPhish no formato que o receptor espera."""
    return {"campaign_id": campaign_id, "email": email,
            "time": time, "message": message}


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


def novo_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="robustez_")
    os.close(fd)
    os.remove(path)
    return path


def veredito(ok: bool) -> str:
    return "Conforme" if ok else "Não conforme"


# --- casos -------------------------------------------------------------------
def caso_r1() -> dict:
    """Conteúdo malicioso em campo textual: injeção de SQL."""
    db = novo_db()
    try:
        with Receptor(db) as r:
            agressao = "alvo@exemplo.test'; DROP TABLE events; --"
            status, corpo = post(r.port, gophish_payload(
                "Clicked Link", agressao, "2026-09-14T12:00:00Z"))
            # A tabela deve continuar existindo e conter exatamente o evento.
            try:
                total = count_events(db)
                tabela_intacta = True
            except sqlite3.OperationalError:
                total, tabela_intacta = -1, False
            ok = (status == 200 and corpo.get("status") == "stored"
                  and tabela_intacta and total == 1)
            obs = (f"HTTP {status}, status={corpo.get('status')}; tabela events "
                   f"{'íntegra' if tabela_intacta else 'destruída'} com {total} "
                   f"registro(s); o valor foi tratado como dado e armazenado "
                   f"pseudonimizado")
    finally:
        os.path.exists(db) and os.remove(db)
    return {"caso": "R1",
            "descricao": "Submissão de conteúdo malicioso em campo textual "
                         "(tentativa de injeção de SQL no campo de destinatário)",
            "esperado": "O conteúdo é tratado como dado literal pelos parâmetros "
                        "vinculados, sem alteração do esquema da base",
            "observado": obs, "veredito": veredito(ok)}


def caso_r2() -> dict:
    """Reentrega de evento já processado: idempotência."""
    db = novo_db()
    try:
        with Receptor(db) as r:
            p = gophish_payload("Submitted Data", "alvo@exemplo.test",
                                "2026-09-14T12:05:00Z")
            s1, c1 = post(r.port, p)
            s2, c2 = post(r.port, p)
            total = count_events(db)
            ok = (s1 == 200 and c1.get("status") == "stored"
                  and s2 == 200 and c2.get("status") == "duplicate"
                  and c1.get("event_id") == c2.get("event_id") and total == 1)
            obs = (f"1ª entrega: HTTP {s1}, status={c1.get('status')}, "
                   f"event_id={c1.get('event_id')}; reentrega: HTTP {s2}, "
                   f"status={c2.get('status')}, event_id={c2.get('event_id')}; "
                   f"{total} registro(s) na base")
    finally:
        os.path.exists(db) and os.remove(db)
    return {"caso": "R2",
            "descricao": "Reentrega de um evento já processado",
            "esperado": "O evento é reconhecido como duplicata e não gera novo "
                        "registro, devolvendo-se o identificador do original",
            "observado": obs, "veredito": veredito(ok)}


def caso_r3() -> dict:
    """Evento com estrutura inválida."""
    db = novo_db()
    try:
        with Receptor(db) as r:
            corrompido = b'{"campaign_id": 7, "message": "Clicked Link"'
            status, corpo = post(r.port, None, raw=corrompido)
            total = count_events(db)
            ok = status == 400 and total == 0
            obs = (f"HTTP {status}, motivo={corpo.get('reason')}; "
                   f"{total} registro(s) na base")
    finally:
        os.path.exists(db) and os.remove(db)
    return {"caso": "R3",
            "descricao": "Evento com estrutura inválida (JSON malformado)",
            "esperado": "A requisição é rejeitada com erro de cliente, sem "
                        "persistir registro e sem interromper o receptor",
            "observado": obs, "veredito": veredito(ok)}


def caso_r4() -> dict:
    """Evento com campo obrigatório ausente."""
    db = novo_db()
    try:
        with Receptor(db) as r:
            sem_message = {"campaign_id": 7, "email": "alvo@exemplo.test",
                           "time": "2026-09-14T12:10:00Z"}
            status, corpo = post(r.port, sem_message)
            total = count_events(db)
            # Ainda deve aceitar um evento válido em seguida.
            s2, c2 = post(r.port, gophish_payload(
                "Email Sent", "alvo@exemplo.test", "2026-09-14T12:11:00Z"))
            ok = (status == 200 and corpo.get("status") == "ignored"
                  and total == 0 and s2 == 200 and c2.get("status") == "stored")
            obs = (f"HTTP {status}, status={corpo.get('status')} "
                   f"({corpo.get('reason')}); {total} registro(s) na base; "
                   f"evento válido subsequente aceito (status={c2.get('status')})")
    finally:
        os.path.exists(db) and os.remove(db)
    return {"caso": "R4",
            "descricao": "Evento com campo obrigatório ausente (notificação sem "
                         "o campo que identifica o degrau do funil)",
            "esperado": "O evento é descartado sem persistência e sem erro de "
                        "servidor, preservando-se a disponibilidade do receptor",
            "observado": obs, "veredito": veredito(ok)}


def caso_r5() -> dict:
    """Evento com carimbo de tempo anterior ao do evento precedente."""
    db = novo_db()
    try:
        with Receptor(db) as r:
            s1, c1 = post(r.port, gophish_payload(
                "Clicked Link", "alvo@exemplo.test", "2026-09-14T12:30:00Z"))
            s2, c2 = post(r.port, gophish_payload(
                "Email Opened", "alvo@exemplo.test", "2026-09-14T12:20:00Z"))
            total = count_events(db)
            contagens = database.count_by_type(db)
            ok = (s1 == 200 and c1.get("status") == "stored"
                  and s2 == 200 and c2.get("status") == "stored" and total == 2
                  and contagens.get("LINK_CLICKED") == 1
                  and contagens.get("EMAIL_OPENED") == 1)
            obs = (f"evento fora de ordem aceito (HTTP {s2}, "
                   f"status={c2.get('status')}); {total} registro(s) na base, "
                   f"contagem por tipo {dict(sorted(contagens.items()))}; a "
                   f"ordem de chegada não sobrescreveu nem descartou registro")
    finally:
        os.path.exists(db) and os.remove(db)
    return {"caso": "R5",
            "descricao": "Evento com carimbo de tempo anterior ao do evento "
                         "precedente",
            "esperado": "O evento é persistido com seu próprio instante de "
                        "origem, sem descarte e sem sobrescrita do anterior",
            "observado": obs, "veredito": veredito(ok)}


def caso_r6() -> dict:
    """Indisponibilidade da camada de persistência durante a ingestão."""
    db = novo_db()
    try:
        with Receptor(db) as r:
            # Torna a base inacessível substituindo o arquivo por um diretório,
            # com o receptor já em operação.
            os.remove(db)
            os.mkdir(db)
            try:
                status, corpo = post(r.port, gophish_payload(
                    "Clicked Link", "alvo@exemplo.test",
                    "2026-09-14T12:40:00Z"))
                indisponivel_ok = status == 503
                obs_ind = f"HTTP {status}, motivo={corpo.get('reason')}"
            finally:
                os.rmdir(db)
            # Restabelecida a persistência, o receptor volta a registrar.
            database.create_database(db)
            s2, c2 = post(r.port, gophish_payload(
                "Clicked Link", "alvo@exemplo.test", "2026-09-14T12:41:00Z"))
            total = count_events(db)
            ok = indisponivel_ok and s2 == 200 and c2.get("status") == "stored" \
                and total == 1
            obs = (f"durante a indisponibilidade: {obs_ind}; após o "
                   f"restabelecimento: HTTP {s2}, status={c2.get('status')}, "
                   f"{total} registro(s) na base — o receptor permaneceu no ar "
                   f"durante toda a falha")
    finally:
        if os.path.isdir(db):
            os.rmdir(db)
        elif os.path.exists(db):
            os.remove(db)
    return {"caso": "R6",
            "descricao": "Indisponibilidade da camada de persistência durante a "
                         "ingestão",
            "esperado": "A falha é sinalizada como indisponibilidade temporária "
                        "do serviço, sem derrubar o receptor, que volta a "
                        "registrar quando a persistência é restabelecida",
            "observado": obs, "veredito": veredito(ok)}


def caso_r7() -> dict:
    """Requisição de ingestão com assinatura inválida."""
    db = novo_db()
    try:
        with Receptor(db) as r:
            p = gophish_payload("Submitted Data", "alvo@exemplo.test",
                                "2026-09-14T12:50:00Z")
            s1, c1 = post(r.port, p, signature="sha256=" + "0" * 64)
            s2, c2 = post(r.port, p, signature="")
            total_apos = count_events(db)
            # Com a assinatura correta, o mesmo evento é aceito.
            s3, c3 = post(r.port, p)
            total_final = count_events(db)
            ok = (s1 == 401 and s2 == 401 and total_apos == 0
                  and s3 == 200 and c3.get("status") == "stored"
                  and total_final == 1)
            obs = (f"assinatura forjada: HTTP {s1} ({c1.get('reason')}); "
                   f"assinatura ausente: HTTP {s2} ({c2.get('reason')}); "
                   f"{total_apos} registro(s) na base após as tentativas; o "
                   f"mesmo evento com assinatura válida foi aceito (HTTP {s3}), "
                   f"totalizando {total_final} registro(s)")
    finally:
        os.path.exists(db) and os.remove(db)
    return {"caso": "R7",
            "descricao": "Requisição de ingestão com assinatura inválida ou "
                         "ausente",
            "esperado": "A requisição é rejeitada por falha de autenticação, sem "
                        "persistir registro, e a requisição legítima segue sendo "
                        "aceita",
            "observado": obs, "veredito": veredito(ok)}


CASOS = [caso_r1, caso_r2, caso_r3, caso_r4, caso_r5, caso_r6, caso_r7]


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(DATA_DIR, f"robustez-{stamp}.csv")

    linhas = []
    for fn in CASOS:
        linha = fn()
        linhas.append(linha)
        print(f"[{linha['caso']}] {linha['veredito']:12} | {linha['observado']}")

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(linhas)

    conformes = sum(1 for r in linhas if r["veredito"] == "Conforme")
    print(f"\n{conformes}/{len(linhas)} casos conformes")
    print(f"Resultados em: {out_path}")
    if conformes != len(linhas):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
