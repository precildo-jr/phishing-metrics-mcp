"""Camada de persistência da plataforma.

Esquema orientado à apuração de funil de campanhas simuladas de engenharia
social. Cada evento guarda o instante de origem (quando ocorreu) separado do
instante de ingestão (quando foi persistido); a diferença entre os dois é a
latência de propagação medida no trabalho.

Sem dependências externas: apenas a biblioteca padrão do Python.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

DB_PATH = "events.db"

# Espera máxima por um bloqueio de escrita. O SQLite serializa escritores; sem
# esta espera, um segundo escritor recebe "database is locked" de imediato e o
# evento se perde. Não afeta a escrita sequencial, apenas a concorrente.
BUSY_TIMEOUT_S = 30.0

# Variável de ambiente que guarda a chave de derivação dos pseudônimos.
PSEUDONYM_KEY_ENV = "MCP_TCC_PSEUDONYM_KEY"

_key_cache: dict[str, bytes] = {}
_key_lock = threading.Lock()

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
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_S)
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_S * 1000)}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _pseudonym_key(db_path: str = DB_PATH) -> bytes:
    """Chave de derivação dos pseudônimos, com a chave fora da base de preferência.

    A variável de ambiente é a via preferencial: mantida fora do arquivo, o
    vazamento da base não basta para reverter os pseudônimos. Na falta dela,
    gera-se uma chave aleatória por base, registrada em `meta`, o que preserva a
    estabilidade dos identificadores mas oferece proteção menor, uma vez que
    chave e dados passam a coabitar no mesmo arquivo.
    """
    do_ambiente = os.environ.get(PSEUDONYM_KEY_ENV)
    if do_ambiente:
        return do_ambiente.encode("utf-8")

    with _key_lock:
        if db_path in _key_cache:
            return _key_cache[db_path]
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'pseudonym_key'").fetchone()
            if row is None:
                gerada = secrets.token_hex(32)
                conn.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    ("pseudonym_key", gerada))
                conn.commit()
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = 'pseudonym_key'").fetchone()
        finally:
            conn.close()
        chave = row[0].encode("utf-8")
        _key_cache[db_path] = chave
        return chave


def pseudonymize(target: str, db_path: str = DB_PATH) -> str:
    """Deriva um identificador pseudonimizado e estável a partir do alvo.

    Usa HMAC-SHA256 com chave, e não um resumo simples: endereços de correio
    formam um domínio de baixa entropia, sobre o qual um resumo sem segredo
    cederia à enumeração de candidatos. Sem a chave, o pseudônimo não pode ser
    associado de volta ao endereço. É determinístico dentro de uma mesma base,
    de modo que a apuração por alvo distinto continua possível.
    """
    return hmac.new(_pseudonym_key(db_path), target.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:16]


def create_database(db_path: str = DB_PATH) -> None:
    """Cria o esquema, caso ainda não exista.

    Três tabelas: `campaigns`, que normaliza a campanha, antes tratada como
    texto livre; `events`, com os campos necessários à apuração de funil, à
    idempotência e à medição de latência; e `meta`, que guarda a chave de
    derivação dos pseudônimos quando ela não vem do ambiente.
    """
    conn = _connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key    TEXT PRIMARY KEY,
            value  TEXT NOT NULL
        )
    """)

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

    # Semeia a chave de pseudonimização já na criação, quando ela não vem do
    # ambiente, para que a derivação em tempo de ingestão seja apenas leitura.
    if not os.environ.get(PSEUDONYM_KEY_ENV):
        cur.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    ("pseudonym_key", secrets.token_hex(32)))

    conn.commit()
    conn.close()


def _get_or_create_campaign(conn: sqlite3.Connection, name: str,
                            external_id: int | None = None) -> int:
    """Resolve a campanha, criando-a se necessário, sem condição de corrida.

    Consultar e depois inserir não basta sob concorrência: dois ingestores
    podem não encontrar a campanha e tentar criá-la, e o segundo viola a
    restrição de unicidade. Quando isso ocorre, a inserção alheia é acolhida e
    o registro relido, em lugar de propagar o erro e perder o evento.
    """
    cur = conn.cursor()

    def buscar():
        if external_id is not None:
            return cur.execute("SELECT id FROM campaigns WHERE external_id = ?",
                               (external_id,)).fetchone()
        return cur.execute("SELECT id FROM campaigns WHERE name = ? "
                           "AND external_id IS NULL", (name,)).fetchone()

    row = buscar()
    if row:
        return row[0]

    try:
        cur.execute("INSERT INTO campaigns (external_id, name, created_at) "
                    "VALUES (?, ?, ?)", (external_id, name, _now()))
        return cur.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        row = buscar()
        if row:
            return row[0]
        raise


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
        target_id = pseudonymize(target, db_path) if target else None
        try:
            cur.execute("""
                INSERT INTO events (campaign_id, target_id, message_id,
                                    external_event_id, event_type, source,
                                    origin_ts, ingest_ts, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (campaign_id, target_id, message_id, external_event_id, event_type,
                  source, origin_ts or ingest_ts, ingest_ts, raw_payload))
        except sqlite3.IntegrityError:
            # Reentrega simultânea do mesmo evento: outro ingestor inseriu entre
            # a consulta acima e esta gravação. O desfecho é o mesmo de uma
            # duplicata detectada pela consulta — devolve-se o registro original.
            conn.rollback()
            existing = cur.execute(
                "SELECT id FROM events WHERE external_event_id = ?",
                (external_event_id,)).fetchone()
            if existing:
                return existing[0], False
            raise
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
