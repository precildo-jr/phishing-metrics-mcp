"""Camada de orquestração: servidor MCP.

Expõe os eventos consolidados como ferramentas descritas e invocáveis por
agentes baseados em modelos de linguagem. É essa exposição — e não um conjunto
fixo de pontos de acesso REST — que permite formular consultas analíticas em
linguagem natural, compostas a partir das ferramentas existentes.
"""
from mcp.server.fastmcp import FastMCP

import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from plataforma import persistencia

mcp = FastMCP("gophish-tcc-server")


@mcp.tool()
def register_simulated_event(
    campaign_name: str,
    event_type: str,
    source: str = "mcp_server",
) -> dict:
    """Registra um evento simulado, de forma idempotente."""
    persistencia.create_database()
    event_id, inserted = persistencia.register_event(campaign_name, event_type, source)
    return {
        "status": "success" if inserted else "duplicate",
        "event_id": event_id,
        "campaign_name": campaign_name,
        "event_type": event_type,
        "source": source,
    }


@mcp.tool()
def get_registered_events() -> dict:
    """Consulta os eventos persistidos, mais recentes primeiro."""
    persistencia.create_database()
    events = persistencia.list_events()
    return {
        "total": len(events),
        "events": [
            {
                "id": r[0],
                "campaign_name": r[1],
                "event_type": r[2],
                "source": r[3],
                "origin_ts": r[4],
                "ingest_ts": r[5],
                "target_id": r[6],
            }
            for r in events
        ],
    }


@mcp.tool()
def generate_basic_metrics() -> dict:
    """Consolida indicadores a partir dos eventos armazenados.

    Reúne, em uma única resposta, a contagem por tipo, as taxas de conversão de
    cada degrau do funil e um resumo da latência de propagação, todos apurados
    em SQL sobre a base persistida.
    """
    persistencia.create_database()
    counts = persistencia.count_by_type()
    return {
        "total_events": sum(counts.values()),
        "events_by_type": counts,
        "funnel_rates": persistencia.funnel_rates(),
        "propagation_latency_ms": persistencia.latency_summary(),
    }


if __name__ == "__main__":
    mcp.run()
