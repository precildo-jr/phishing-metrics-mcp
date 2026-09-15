"""Verificação experimental da decisão arquitetural da camada de orquestração.

Submete dez perguntas analíticas sobre as campanhas simuladas a um agente
conectado ao servidor MCP e registra, para cada uma, se a resposta foi obtida
por composição das ferramentas já expostas ou se demandaria a implementação de
um novo ponto de acesso — procedimento que permite contrastar a abordagem
adotada com uma interface de consultas predefinidas.

A conexão é real: o servidor de `server_mcp.py` é iniciado como subprocesso e
interrogado pelo protocolo MCP sobre transporte padrão de entrada e saída. As
ferramentas são descobertas por `list_tools` e invocadas por `call_tool`, sem
que este arnês acesse a base de dados diretamente. O veredito de cada pergunta
é derivado da resposta efetivamente devolvida pelas ferramentas, e não
declarado de antemão: uma pergunta só é dada por resolvida quando a função
correspondente consegue produzir a resposta a partir do que as ferramentas
retornaram.

Uso:
    python experiments/analytical_questions.py
Os resultados vão para `../data/perguntas-analiticas-<carimbo>.csv`.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _RAIZ)

import database   # noqa: E402
import generator  # noqa: E402
import ingestion  # noqa: E402

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client             # noqa: E402

DATA_DIR = os.path.join(_RAIZ, "data")
CSV_FIELDS = ["id", "pergunta", "ferramentas_compostas", "desfecho", "resposta"]

SEMENTE = 20260914
CARGA = 2000


# --- preparação da base que o servidor MCP irá expor -------------------------
def preparar_base(dir_trabalho: str) -> str:
    """Popula a base que o servidor MCP lerá, no diretório de trabalho dele.

    O servidor resolve `events.db` relativamente ao diretório corrente, de modo
    que iniciá-lo com este diretório de trabalho o faz operar sobre esta base.

    A base reproduz as duas procedências que a plataforma admite: eventos
    simulados pelo gerador e notificações recebidas pela camada de ingestão,
    estas últimas acompanhadas do corpo bruto da notificação de origem. A
    latência de propagação é medida como no experimento principal — o instante
    de origem é capturado imediatamente antes da inserção.
    """
    db_path = os.path.join(dir_trabalho, "events.db")
    database.create_database(db_path)
    fmt = "%Y-%m-%d %H:%M:%S.%f"

    for nome_cenario, campanha in (("base", "campanha-comercial"),
                                   ("alto", "campanha-financeiro")):
        eventos = generator.generate_events(
            CARGA, funnel=generator.scenario(nome_cenario), seed=SEMENTE,
            campaign_name=campanha)
        for ev in eventos:
            origem = datetime.now(timezone.utc).strftime(fmt)[:-3]
            database.register_event(
                ev["campaign_name"], ev["event_type"], ev["source"],
                external_event_id=ev["external_event_id"], target=ev["target"],
                origin_ts=origem, db_path=db_path)

    # Terceira campanha, recebida pelo receptor de webhook em lugar de inserida
    # diretamente: as notificações percorrem a camada de ingestão, que preserva
    # o corpo bruto em `raw_payload`. O funil é o mesmo do gerador, de modo que
    # a campanha é comparável às demais.
    mensagem_de = {v: k for k, v in database.GOPHISH_MESSAGE_MAP.items()}
    eventos = generator.generate_events(
        CARGA // 2, funnel=generator.scenario("baixo"), seed=SEMENTE + 1,
        campaign_name="campanha-operacoes")
    for i, ev in enumerate(eventos):
        mensagem = mensagem_de.get(ev["event_type"])
        if mensagem is None:
            continue
        ingestion.handle_event({
            "campaign_id": 42,
            "email": ev["target"],
            "time": f"2026-09-14T13:{i // 60 % 60:02d}:{i % 60:02d}Z",
            "message": mensagem,
        }, db_path=db_path)

    return db_path


# --- as dez perguntas --------------------------------------------------------
# Cada entrada declara a pergunta, as ferramentas que o agente decidiu compor
# para respondê-la e a função que extrai a resposta do que elas devolveram.
# A função retorna None quando as ferramentas existentes não bastam.

def p01(ev, mt):
    return f"{mt['total_events']} eventos registrados"


def p02(ev, mt):
    fr = mt["funnel_rates"]
    return (f"{fr['clicked']} cliques sobre {fr['sent']} enviados "
            f"({100 * fr['clicked'] / fr['sent']:.2f}%)")


def p03(ev, mt):
    lat = mt["propagation_latency_ms"]
    return f"p50 = {lat['p50']} ms, p95 = {lat['p95']} ms, máximo = {lat['max']} ms"


def p04(ev, mt):
    alvos = {e["target_id"] for e in ev
             if e["event_type"] == "LINK_CLICKED" and e["target_id"]}
    return f"{len(alvos)} alvos distintos clicaram no link"


def p05(ev, mt):
    com_ts = [e for e in ev if e["origin_ts"]]
    if not com_ts:
        return None
    primeiro = min(com_ts, key=lambda e: e["origin_ts"])
    return (f"{primeiro['event_type']} da campanha {primeiro['campaign_name']} "
            f"em {primeiro['origin_ts']}")


def p06(ev, mt):
    clicaram = {e["target_id"] for e in ev if e["event_type"] == "LINK_CLICKED"}
    submeteram = {e["target_id"] for e in ev
                  if e["event_type"] == "DATA_SUBMITTED"}
    orfaos = submeteram - clicaram
    return (f"{len(orfaos)} alvos submeteram credenciais sem clique registrado "
            f"(de {len(submeteram)} submissões)")


def p07(ev, mt):
    por_campanha = defaultdict(Counter)
    for e in ev:
        por_campanha[e["campaign_name"]][e["event_type"]] += 1
    linhas = []
    for campanha, c in sorted(por_campanha.items()):
        enviados, cliques = c["EMAIL_SENT"], c["LINK_CLICKED"]
        if not enviados:
            continue
        linhas.append(f"{campanha}: {100 * cliques / enviados:.2f}%")
    return "; ".join(linhas) if linhas else None


def p08(ev, mt):
    origens = Counter(e["source"] for e in ev)
    return "; ".join(f"{k}: {v}" for k, v in sorted(origens.items()))


def p09(ev, mt):
    """Conteúdo bruto da notificação de origem de um evento."""
    # `get_registered_events` projeta id, campanha, tipo, origem, carimbos e
    # alvo — o campo `raw_payload`, persistido pela camada de ingestão, não
    # integra a projeção e não pode ser recomposto a partir dela.
    if not ev:
        return None
    return ev[0].get("raw_payload")


def p10(ev, mt):
    """Endereço de e-mail do alvo que submeteu credenciais."""
    # `target_id` é o pseudônimo irreversível gravado pela camada de
    # persistência; o endereço original não é armazenado em lugar algum.
    for e in ev:
        if e["event_type"] == "DATA_SUBMITTED":
            alvo = e.get("target_id") or ""
            if "@" in alvo:
                return alvo
    return None


PERGUNTAS = [
    ("Q01", "Quantos eventos foram registrados ao todo?",
     ["generate_basic_metrics"], p01),
    ("Q02", "Qual a taxa de clique sobre os e-mails enviados?",
     ["generate_basic_metrics"], p02),
    ("Q03", "Qual a latência de propagação dos eventos até a base?",
     ["generate_basic_metrics"], p03),
    ("Q04", "Quantos alvos distintos clicaram no link?",
     ["get_registered_events"], p04),
    ("Q05", "Qual foi o primeiro evento da série e quando ocorreu?",
     ["get_registered_events"], p05),
    ("Q06", "Algum alvo submeteu credenciais sem que houvesse clique registrado?",
     ["get_registered_events"], p06),
    ("Q07", "Qual campanha apresentou a maior taxa de clique?",
     ["get_registered_events"], p07),
    ("Q08", "Quantos eventos vieram de cada origem de coleta?",
     ["get_registered_events"], p08),
    ("Q09", "Qual o conteúdo bruto da notificação que originou um evento?",
     ["get_registered_events", "generate_basic_metrics"], p09),
    ("Q10", "Qual o endereço de e-mail do alvo que submeteu credenciais?",
     ["get_registered_events"], p10),
]


# --- execução contra o servidor MCP real -------------------------------------
def conteudo(resultado) -> dict:
    """Extrai o objeto JSON devolvido por uma chamada de ferramenta."""
    for bloco in resultado.content:
        if getattr(bloco, "type", None) == "text":
            return json.loads(bloco.text)
    raise RuntimeError("resposta da ferramenta sem conteúdo textual")


async def executar() -> list[dict]:
    dir_trabalho = tempfile.mkdtemp(prefix="perguntas_")
    try:
        preparar_base(dir_trabalho)
        params = StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(_RAIZ, "server_mcp.py")],
            cwd=dir_trabalho,
            env={**os.environ, "PYTHONPATH": _RAIZ, "PYTHONIOENCODING": "utf-8"},
        )
        async with stdio_client(params) as (leitura, escrita):
            async with ClientSession(leitura, escrita) as sessao:
                await sessao.initialize()
                disponiveis = [t.name for t in (await sessao.list_tools()).tools]
                print("Ferramentas expostas pelo servidor MCP:",
                      ", ".join(disponiveis))

                eventos = conteudo(
                    await sessao.call_tool("get_registered_events", {}))["events"]
                metricas = conteudo(
                    await sessao.call_tool("generate_basic_metrics", {}))
                print(f"Base exposta: {len(eventos)} eventos, "
                      f"{metricas['total_events']} contabilizados\n")

        linhas = []
        for qid, pergunta, ferramentas, fn in PERGUNTAS:
            for nome in ferramentas:
                if nome not in disponiveis:
                    raise RuntimeError(f"ferramenta ausente: {nome}")
            resposta = fn(eventos, metricas)
            resolvida = resposta is not None
            linhas.append({
                "id": qid,
                "pergunta": pergunta,
                "ferramentas_compostas": " + ".join(ferramentas),
                "desfecho": "Resolvida por composição" if resolvida
                            else "Exigiria novo ponto de acesso",
                "resposta": resposta if resolvida
                            else "não obtenível a partir das ferramentas expostas",
            })
        return linhas
    finally:
        shutil.rmtree(dir_trabalho, ignore_errors=True)


def main() -> None:
    linhas = asyncio.run(executar())

    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(DATA_DIR, f"perguntas-analiticas-{stamp}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(linhas)

    for l in linhas:
        print(f"[{l['id']}] {l['desfecho']:30} | {l['pergunta']}")
        print(f"       -> {l['resposta']}")
    resolvidas = sum(1 for l in linhas
                     if l["desfecho"] == "Resolvida por composição")
    print(f"\n{resolvidas}/{len(linhas)} resolvidas por composição das "
          f"ferramentas existentes")
    print(f"Resultados em: {out_path}")


if __name__ == "__main__":
    main()
