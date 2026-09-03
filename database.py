"""Camada de persistência da plataforma.

Esquema orientado à apuração de funil de campanhas simuladas de engenharia
social. Cada evento guarda o instante de origem (quando ocorreu) separado do
instante de ingestão (quando foi persistido); a diferença entre os dois é a
latência de propagação medida no trabalho.

Sem dependências externas: apenas a biblioteca padrão do Python.
"""
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = "events.db"

# Tipos de evento normalizados (degraus do funil, na ordem canônica).
EMAIL_SENT = "EMAIL_SENT"
EMAIL_OPENED = "EMAIL_OPENED"
LINK_CLICKED = "LINK_CLICKED"
DATA_SUBMITTED = "DATA_SUBMITTED"
EMAIL_REPORTED = "EMAIL_REPORTED"

FUNNEL_ORDER = [EMAIL_SENT, EMAIL_OPENED, LINK_CLICKED, DATA_SUBMITTED]

# Mapeamento das mensagens emitidas pelo GoPhish para os tipos normalizados.
GOPHISH_MESSAGE_MAP = {
    "Email Sent": EMAIL_SENT,
    "Email Opened": EMAIL_OPENED,
    "Clicked Link": LINK_CLICKED,
    "Submitted Data": DATA_SUBMITTED,
    "Email Reported": EMAIL_REPORTED,
}


def _now() -> str:
    """Instante atual em UTC, com precisão de milissegundos e formato estável."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def pseudonymize(target: str) -> str:
    """Deriva um identificador pseudonimizado e estável a partir do alvo.

    Aplica SHA-256 e retorna os 16 primeiros dígitos hexadecimais. É
    determinístico (o mesmo alvo produz o mesmo identificador) e não reversível,
    de modo que nenhum endereço real é persistido.
    """
    return hashlib.sha256(target.encode("utf-8")).hexdigest()[:16]


def create_database(db_path: str = DB_PATH) -> None:
    """Cria o esquema, caso ainda não exista.

    Duas tabelas: `campaigns`, que normaliza a campanha, antes tratada como
    texto livre; e `events`, com os campos necessários à apuração de funil,
    à idempotência e à medição de latência.
    """
    conn = _connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id  INTEGER UNIQUE,
            name         TEXT NOT NULL,
            created_at   TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id        INTEGER NOT NULL REFERENCES campaigns(id),
            target_id          TEXT,
            message_id         TEXT,
            external_event_id  TEXT UNIQUE,
            event_type         TEXT NOT NULL,
            source             TEXT NOT NULL,
            origin_ts          TEXT NOT NULL,
            ingest_ts          TEXT NOT NULL,
            raw_payload        TEXT
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_campaign_type "
                "ON events (campaign_id, event_type)")

    conn.commit()
    conn.close()


def _get_or_create_campaign(conn: sqlite3.Connection, name: str,
                            external_id: int | None = None) -> int:
    cur = conn.cursor()
    if external_id is not None:
        row = cur.execute("SELECT id FROM campaigns WHERE external_id = ?",
                           (external_id,)).fetchone()
        if row:
            return row[0]
    else:
        row = cur.execute("SELECT id FROM campaigns WHERE name = ? "
                          "AND external_id IS NULL", (name,)).fetchone()
        if row:
            return row[0]
    cur.execute("INSERT INTO campaigns (external_id, name, created_at) "
                "VALUES (?, ?, ?)", (external_id, name, _now()))
    return cur.lastrowid


def register_event(campaign_name: str, event_type: str, source: str = "mcp_server",
                   *, external_event_id: str | None = None, target: str | None = None,
                   message_id: str | None = None, origin_ts: str | None = None,
                   raw_payload: str | None = None, campaign_external_id: int | None = None,
                   db_path: str = DB_PATH) -> tuple[int | None, bool]:
    """Persiste um evento de forma idempotente.

    A idempotência apoia-se em `external_event_id`: reentregar um evento já
    processado não cria registro duplicado. Retorna a tupla
    (id_do_evento, foi_inserido). Quando o evento já existia, foi_inserido é
    False e id_do_evento é o do registro original.

    Se `origin_ts` não for informado, assume-se o instante de ingestão — caso
    dos eventos gerados diretamente pela camada de orquestração, sem trânsito.
    """
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        campaign_id = _get_or_create_campaign(conn, campaign_name, campaign_external_id)

        if external_event_id is None:
            external_event_id = uuid.uuid4().hex

        # Idempotência: se o external_event_id já existe, devolve o registro.
        existing = cur.execute(
            "SELECT id FROM events WHERE external_event_id = ?",
            (external_event_id,)).fetchone()
        if existing:
            return existing[0], False

        ingest_ts = _now()
        target_id = pseudonymize(target) if target else None
        cur.execute("""
            INSERT INTO events (campaign_id, target_id, message_id,
                                external_event_id, event_type, source,
                                origin_ts, ingest_ts, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (campaign_id, target_id, message_id, external_event_id, event_type,
              source, origin_ts or ingest_ts, ingest_ts, raw_payload))
        conn.commit()
        return cur.lastrowid, True
    finally:
        conn.close()


def list_events(db_path: str = DB_PATH) -> list[tuple]:
    """Retorna os eventos com o nome da campanha resolvido, mais recentes primeiro."""
    conn = _connect(db_path)
    try:
        return conn.execute("""
            SELECT e.id, c.name, e.event_type, e.source, e.origin_ts,
                   e.ingest_ts, e.target_id, e.external_event_id
            FROM events e
            JOIN campaigns c ON c.id = e.campaign_id
            ORDER BY e.id DESC
        """).fetchall()
    finally:
        conn.close()


def count_by_type(db_path: str = DB_PATH) -> dict[str, int]:
    """Contagem de eventos por tipo, apurada em SQL."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
        ).fetchall()
        return {t: n for t, n in rows}
    finally:
        conn.close()


def funnel_rates(db_path: str = DB_PATH) -> dict[str, float | int]:
    """Contagens e taxas de conversão de cada degrau do funil.

    Cada taxa é a razão entre o degrau e o imediatamente anterior; a taxa global
    é a razão entre submissões e envios. Degraus sem base de comparação recebem
    taxa nula, evitando divisão por zero.
    """
    counts = count_by_type(db_path)
    sent = counts.get(EMAIL_SENT, 0)
    opened = counts.get(EMAIL_OPENED, 0)
    clicked = counts.get(LINK_CLICKED, 0)
    submitted = counts.get(DATA_SUBMITTED, 0)

    def rate(part: int, whole: int) -> float:
        return round(part / whole, 4) if whole else 0.0

    return {
        "sent": sent,
        "opened": opened,
        "clicked": clicked,
        "submitted": submitted,
        "open_rate": rate(opened, sent),
        "click_rate": rate(clicked, opened),
        "submit_rate": rate(submitted, clicked),
        "overall_rate": rate(submitted, sent),
    }


def _percentile(values: list[float], q: float) -> float:
    """Percentil por interpolação linear, sem depender de bibliotecas externas."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    pos = q * (len(ordered) - 1)
    low = int(pos)
    frac = pos - low
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * frac, 3)


def latency_summary(db_path: str = DB_PATH) -> dict[str, float | int]:
    """Resumo da latência de propagação, em milissegundos.

    A latência de cada evento é a diferença entre o instante de ingestão e o de
    origem. Reporta os percentis 50 e 95 e o máximo, em razão da assimetria
    esperada dessa distribuição, que torna a média isoladamente pouco informativa.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT origin_ts, ingest_ts FROM events").fetchall()
    finally:
        conn.close()

    fmt = "%Y-%m-%d %H:%M:%S.%f"
    latencies = []
    for origin_ts, ingest_ts in rows:
        try:
            delta = datetime.strptime(ingest_ts, fmt) - datetime.strptime(origin_ts, fmt)
            latencies.append(delta.total_seconds() * 1000.0)
        except (ValueError, TypeError):
            continue

    return {
        "measured_events": len(latencies),
        "p50": _percentile(latencies, 0.50),
        "p95": _percentile(latencies, 0.95),
        "max": round(max(latencies), 3) if latencies else 0.0,
    }


if __name__ == "__main__":
    create_database()

    event_id, inserted = register_event(
        campaign_name="campanha_teste_tcc",
        event_type=EMAIL_SENT,
        source="mcp_server",
        target="alvo@exemplo.invalido",
    )
    print(f"Evento registrado. ID: {event_id} | inserido: {inserted}")

    # Reentrega do mesmo external_event_id não deve duplicar.
    fixed = "evt-verificacao-idempotencia"
    register_event("campanha_teste_tcc", EMAIL_OPENED, external_event_id=fixed)
    _id, again = register_event("campanha_teste_tcc", EMAIL_OPENED, external_event_id=fixed)
    print(f"Idempotência: segunda gravação inseriu? {again} (esperado: False)")

    print("\nEventos armazenados:")
    for row in list_events():
        print(" ", row)
    print("\nContagem por tipo:", count_by_type())
