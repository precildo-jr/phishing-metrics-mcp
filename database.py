import sqlite3
from datetime import datetime


DB_PATH = "events.db"


def create_database() -> None:
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()


def register_event(campaign_name: str, event_type: str, source: str) -> int:
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO events (campaign_name, event_type, source, created_at)
        VALUES (?, ?, ?, ?)
    """, (campaign_name, event_type, source, created_at))

    event_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return event_id


def list_events() -> list[tuple]:
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, campaign_name, event_type, source, created_at
        FROM events
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()
    connection.close()

    return rows


if __name__ == "__main__":
    create_database()

    event_id = register_event(
        campaign_name="campanha_teste_tcc",
        event_type="SIMULATED_EVENT",
        source="mcp_server"
    )

    print(f"Evento registrado com sucesso. ID: {event_id}")

    for event in list_events():
        print(event)