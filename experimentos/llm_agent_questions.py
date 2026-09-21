"""Verificação da decisão arquitetural com um agente de modelo de linguagem real.

O arnês `analytical_questions.py` verifica se as ferramentas expostas pelo
servidor MCP *bastam* para responder cada pergunta, mas a composição é decidida
em tempo de escrita, por funções fixas. Este arnês fecha essa lacuna: as
perguntas são entregues em linguagem natural a um modelo de linguagem, que
descobre as ferramentas pelo protocolo, decide sozinho quais invocar e em que
ordem, recebe os retornos e formula a resposta.

O que se registra, por pergunta: as ferramentas que o modelo escolheu, a ordem
em que as chamou, quantas rodadas de conversa gastou, o veredito que ele mesmo
emitiu sobre ter ou não conseguido responder, e os tokens consumidos. O veredito
deixa, assim, de ser afirmação do autor e passa a ser comportamento observado.

A ponte entre os dois protocolos é direta: as ferramentas descobertas por
`list_tools` do MCP são convertidas no formato de funções que a API de conversa
espera, e cada `tool_call` devolvido pelo modelo é executado por `call_tool` do
MCP, sem que o modelo acesse a base diretamente.

Requer uma chave de API em `DEEPSEEK_API`, no ambiente ou em um arquivo `.env`
nesta pasta ou na pasta acima. A chave nunca é registrada nos resultados.

Uso:
    python experiments/llm_agent_questions.py [--load 200] [--model deepseek-chat]
Os resultados vão para `../data/agente-llm-<carimbo>.csv`.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)
_HERE = os.path.dirname(os.path.abspath(__file__))

from experimentos.analytical_questions import (  # noqa: E402
    PERGUNTAS, conteudo, preparar_base)

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client             # noqa: E402

DATA_DIR = os.path.join(_RAIZ, "data")
API_URL = "https://api.deepseek.com/chat/completions"
CHAVE_ENV = "DEEPSEEK_API"

# Teto do retorno de ferramenta repassado ao modelo. Existe porque
# `get_registered_events` devolve a base inteira, sem recorte nem paginação:
# sem teto, um único retorno excede a janela de contexto. Quando o teto atua,
# o fato é registrado — é resultado, não detalhe de implementação.
TETO_RETORNO_PADRAO = 60_000
MAX_RODADAS = 6

CSV_FIELDS = ["id", "pergunta", "ferramentas_invocadas", "rodadas", "truncou",
              "respondida", "resposta", "justificativa", "tokens"]

INSTRUCAO = (
    "Você analisa dados de campanhas simuladas de phishing consultando as "
    "ferramentas disponíveis. Use as ferramentas para obter os dados; não "
    "invente números. Quando tiver terminado, responda APENAS com um objeto "
    "JSON, sem cercas de código, no formato: "
    '{"respondida": true|false, "resposta": "<a resposta, ou vazio>", '
    '"justificativa": "<por que conseguiu ou não conseguiu responder>"}. '
    "Use respondida=false quando as ferramentas disponíveis não permitirem "
    "obter o dado pedido."
)


def carregar_chave() -> str:
    """Lê a chave do ambiente ou de um `.env`, sem jamais registrá-la."""
    if os.environ.get(CHAVE_ENV):
        return os.environ[CHAVE_ENV].strip()
    for pasta in (_RAIZ, os.path.dirname(_RAIZ)):
        caminho = os.path.join(pasta, ".env")
        if not os.path.exists(caminho):
            continue
        with open(caminho, encoding="utf-8") as fh:
            for linha in fh:
                if linha.strip().startswith(CHAVE_ENV):
                    return linha.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(
        f"Defina {CHAVE_ENV} no ambiente ou em um arquivo .env nesta pasta "
        f"ou na pasta acima.")


def mcp_para_funcao(ferramenta) -> dict:
    """Converte a descrição MCP de uma ferramenta no formato da API de conversa."""
    esquema = ferramenta.inputSchema or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": ferramenta.name,
            "description": (ferramenta.description or "").strip(),
            "parameters": esquema,
        },
    }


def conversar(chave: str, modelo: str, mensagens: list, ferramentas: list) -> dict:
    corpo = {"model": modelo, "messages": mensagens, "tools": ferramentas,
             "temperature": 0}
    req = urllib.request.Request(
        API_URL, data=json.dumps(corpo).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + chave,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"API respondeu {exc.code}: {detalhe}")


def extrair_veredito(texto: str) -> dict:
    """Lê o objeto JSON do veredito, tolerando cercas de código."""
    limpo = (texto or "").strip()
    if limpo.startswith("```"):
        limpo = limpo.split("```")[1]
        if limpo.startswith("json"):
            limpo = limpo[4:]
    ini, fim = limpo.find("{"), limpo.rfind("}")
    if ini != -1 and fim > ini:
        try:
            return json.loads(limpo[ini:fim + 1])
        except json.JSONDecodeError:
            pass
    return {"respondida": None, "resposta": limpo[:400], "justificativa": ""}


async def executar(load: int, modelo: str, teto: int) -> list[dict]:
    chave = carregar_chave()
    dir_trabalho = tempfile.mkdtemp(prefix="agente_")
    try:
        preparar_base(dir_trabalho, carga=load)
        params = StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(_RAIZ, "plataforma", "orquestracao.py")],
            cwd=dir_trabalho,
            env={**os.environ, "PYTHONPATH": _RAIZ, "PYTHONIOENCODING": "utf-8"},
        )
        linhas = []
        async with stdio_client(params) as (leitura, escrita):
            async with ClientSession(leitura, escrita) as sessao:
                await sessao.initialize()
                descobertas = (await sessao.list_tools()).tools
                ferramentas = [mcp_para_funcao(f) for f in descobertas]
                print("Ferramentas descobertas pelo protocolo:",
                      ", ".join(f.name for f in descobertas))
                print(f"Base exposta: carga {load} por campanha\n")

                for qid, pergunta, _sugeridas, _fn in PERGUNTAS:
                    mensagens = [{"role": "system", "content": INSTRUCAO},
                                 {"role": "user", "content": pergunta}]
                    invocadas, rodadas, truncou, tokens = [], 0, False, 0

                    while rodadas < MAX_RODADAS:
                        rodadas += 1
                        resposta = conversar(chave, modelo, mensagens, ferramentas)
                        uso = resposta.get("usage") or {}
                        tokens += uso.get("total_tokens", 0)
                        msg = resposta["choices"][0]["message"]
                        chamadas = msg.get("tool_calls") or []
                        mensagens.append({
                            "role": "assistant",
                            "content": msg.get("content") or "",
                            "tool_calls": chamadas,
                        } if chamadas else
                            {"role": "assistant", "content": msg.get("content") or ""})

                        if not chamadas:
                            break

                        for chamada in chamadas:
                            nome = chamada["function"]["name"]
                            invocadas.append(nome)
                            try:
                                args = json.loads(
                                    chamada["function"].get("arguments") or "{}")
                            except json.JSONDecodeError:
                                args = {}
                            try:
                                bruto = json.dumps(
                                    conteudo(await sessao.call_tool(nome, args)),
                                    ensure_ascii=False)
                            except Exception as exc:                # noqa: BLE001
                                bruto = json.dumps({"erro": str(exc)})
                            if len(bruto) > teto:
                                truncou = True
                                bruto = (bruto[:teto] +
                                         f'... [RETORNO TRUNCADO: a ferramenta devolveu '
                                         f'{len(bruto)} caracteres, acima do teto de '
                                         f'{teto}; os registros seguintes '
                                         f'foram omitidos]')
                            mensagens.append({"role": "tool",
                                              "tool_call_id": chamada["id"],
                                              "content": bruto})

                    veredito = extrair_veredito(mensagens[-1].get("content", ""))
                    linha = {
                        "id": qid,
                        "pergunta": pergunta,
                        "ferramentas_invocadas": " -> ".join(invocadas) or "(nenhuma)",
                        "rodadas": rodadas,
                        "truncou": "sim" if truncou else "nao",
                        "respondida": {True: "sim", False: "nao"}.get(
                            veredito.get("respondida"), "indeterminado"),
                        "resposta": (veredito.get("resposta") or "")[:500],
                        "justificativa": (veredito.get("justificativa") or "")[:400],
                        "tokens": tokens,
                    }
                    linhas.append(linha)
                    print(f"[{qid}] respondida={linha['respondida']:13} "
                          f"rodadas={rodadas} truncou={linha['truncou']} "
                          f"tokens={tokens:6} | {linha['ferramentas_invocadas']}")
                    if linha["resposta"]:
                        print(f"       -> {linha['resposta'][:110]}")
        return linhas
    finally:
        shutil.rmtree(dir_trabalho, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Perguntas analíticas submetidas a um agente real.")
    parser.add_argument("--load", type=int, default=200,
                        help="eventos gerados por campanha na base exposta")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--max-tool-chars", type=int, default=TETO_RETORNO_PADRAO,
                        help="teto do retorno de ferramenta repassado ao modelo")
    args = parser.parse_args()

    linhas = asyncio.run(executar(args.load, args.model, args.max_tool_chars))

    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(DATA_DIR, f"agente-llm-{stamp}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(linhas)

    respondidas = sum(1 for l in linhas if l["respondida"] == "sim")
    truncadas = sum(1 for l in linhas if l["truncou"] == "sim")
    print(f"\n{respondidas}/{len(linhas)} respondidas pelo agente por composição "
          f"das ferramentas existentes")
    print(f"{truncadas}/{len(linhas)} perguntas tiveram retorno de ferramenta truncado")
    print(f"tokens consumidos: {sum(l['tokens'] for l in linhas)}")
    print(f"Resultados em: {out_path}")


if __name__ == "__main__":
    main()
