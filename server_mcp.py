from mcp.server.fastmcp import FastMCP
from database import create_database, register_event, list_events


mcp = FastMCP("gophish-tcc-server")


@mcp.tool()
def register_simulated_event(
    campaign_name: str,
    event_type: str,
    source: str = "mcp_server"
) -> dict:
    """
    Registra um evento simulado no banco SQLite.
    """
    create_database()

    event_id = register_event(
        campaign_name=campaign_name,
        event_type=event_type,
        source=source
    )

    return {
        "status": "success",
        "event_id": event_id,
        "campaign_name": campaign_name,
        "event_type": event_type,
        "source": source
    }


@mcp.tool()
def get_registered_events() -> dict:
    """
    Consulta os eventos registrados no banco SQLite.
    """
    create_database()
    events = list_events()

    return {
        "total": len(events),
        "events": [
            {
                "id": row[0],
                "campaign_name": row[1],
                "event_type": row[2],
                "source": row[3],
                "created_at": row[4]
            }
            for row in events
        ]
    }


@mcp.tool()
def generate_basic_metrics() -> dict:
    """
    Gera métricas preliminares a partir dos eventos armazenados.
    """
    create_database()
    events = list_events()

    metrics = {}

    for event in events:
        event_type = event[2]
        metrics[event_type] = metrics.get(event_type, 0) + 1

    return {
        "total_events": len(events),
        "events_by_type": metrics
    }


if __name__ == "__main__":
    mcp.run()