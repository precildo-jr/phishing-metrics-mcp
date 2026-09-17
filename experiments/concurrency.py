"""Varredura de concorrência sobre a camada de ingestão.

A varredura de carga principal (`run_experiment.py`) submete os eventos em
sequência, e nesse regime a taxa de perda é nula. Este arnês responde à
pergunta seguinte: o que ocorre quando vários ingestores escrevem ao mesmo
tempo?

Para cada grau de concorrência, N escritores simultâneos submetem eventos ao
receptor de webhook em operação real, sobre HTTP, contra uma base própria. Ao
final compara-se o número de requisições aceitas com o de registros
persistidos. Um evento que receba resposta de erro e não chegue à base é perda.

O arnês foi escrito para expor duas falhas encontradas na versão 1.0.0 da
plataforma, ambas corrigidas na versão seguinte: a condição de corrida na
resolução da campanha, em que dois ingestores tentavam criá-la e o segundo
violava a restrição de unicidade; e a ausência de espera por bloqueio de
escrita, que fazia o segundo escritor receber "database is locked" de imediato.

Uso:
    python experiments/concurrency.py [--writers 1,4,8,16] [--events 60]
Os resultados vão para `../data/concorrencia-<carimbo>.csv`.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

import http.client  # noqa: E402

import database     # noqa: E402
import ingestion    # noqa: E402
from robustness import HOST, Receptor, sign  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(_HERE), "data")
CSV_FIELDS = ["escritores", "eventos_por_escritor", "emitidos", "persistidos",
              "perdidos", "loss_rate", "desfechos", "elapsed_s",
              "vazao_eventos_s"]


def submeter(port: int, escritor: int, quantos: int,
             contagem: collections.Counter, trava: threading.Lock) -> None:
    local = collections.Counter()
    for i in range(quantos):
        payload = {
            "campaign_id": 1,
            "email": f"alvo{escritor:02d}_{i:04d}@exemplo.test",
            "time": "2026-09-17T10:00:00Z",
            "message": "Clicked Link",
        }
        corpo = json.dumps(payload).encode("utf-8")
        try:
            conn = http.client.HTTPConnection(HOST, port, timeout=60)
            conn.request("POST", "/", body=corpo, headers={
                "Content-Type": "application/json",
                ingestion.SIGNATURE_HEADER: sign(corpo)})
            resp = conn.getresponse()
            corpo_resp = json.loads(resp.read())
            conn.close()
            local[f"{resp.status} {corpo_resp.get('status') or corpo_resp.get('reason')}"] += 1
        except Exception as exc:                       # falha de transporte
            local[f"EXC {type(exc).__name__}"] += 1
    with trava:
        contagem.update(local)


def rodar(escritores: int, por_escritor: int) -> dict:
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="concorrencia_")
    os.close(fd)
    os.remove(db_path)
    try:
        contagem = collections.Counter()
        trava = threading.Lock()
        with Receptor(db_path) as receptor:
            t0 = time.perf_counter()
            threads = [threading.Thread(target=submeter,
                                        args=(receptor.port, w, por_escritor,
                                              contagem, trava))
                       for w in range(escritores)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            elapsed = time.perf_counter() - t0

        conn = sqlite3.connect(db_path)
        try:
            persistidos = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            conn.close()

        emitidos = escritores * por_escritor
        perdidos = emitidos - persistidos
        return {
            "escritores": escritores,
            "eventos_por_escritor": por_escritor,
            "emitidos": emitidos,
            "persistidos": persistidos,
            "perdidos": perdidos,
            "loss_rate": round(perdidos / emitidos, 6) if emitidos else 0.0,
            "desfechos": "; ".join(f"{k}={v}" for k, v in sorted(contagem.items())),
            "elapsed_s": round(elapsed, 3),
            "vazao_eventos_s": round(emitidos / elapsed, 1) if elapsed else 0.0,
        }
    finally:
        for sufixo in ("", "-wal", "-shm"):
            if os.path.exists(db_path + sufixo):
                os.remove(db_path + sufixo)


def main() -> None:
    parser = argparse.ArgumentParser(description="Varredura de concorrência.")
    parser.add_argument("--writers", default="1,4,8,16",
                        help="graus de concorrência separados por vírgula")
    parser.add_argument("--events", type=int, default=60,
                        help="eventos submetidos por escritor")
    args = parser.parse_args()

    graus = [int(x) for x in args.writers.split(",")]

    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(DATA_DIR, f"concorrencia-{stamp}.csv")

    linhas = []
    for grau in graus:
        linha = rodar(grau, args.events)
        linhas.append(linha)
        print(f"[{grau:3} escritores] emitidos={linha['emitidos']:5} "
              f"persistidos={linha['persistidos']:5} "
              f"perda={linha['loss_rate']:.4f} "
              f"vazao={linha['vazao_eventos_s']:7.1f} ev/s | {linha['desfechos']}")

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(linhas)

    total_perdido = sum(l["perdidos"] for l in linhas)
    total_emitido = sum(l["emitidos"] for l in linhas)
    print(f"\n{total_emitido} eventos submetidos, {total_perdido} perdidos "
          f"({100 * total_perdido / total_emitido:.2f}%)")
    print(f"Resultados em: {out_path}")
    if total_perdido:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
