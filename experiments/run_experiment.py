"""Arnês de experimento: varredura de carga × funil × repetições.

Para cada combinação de faixa de carga (número de eventos por execução),
cenário de funil (varredura de sensibilidade) e repetição, o arnês:

  1. gera os eventos de forma determinística a partir de uma semente registrada;
  2. reinicia a base a um estado conhecido;
  3. submete os eventos à camada de persistência, contando os emitidos;
  4. apura os persistidos e calcula perda, latência e taxas de funil;
  5. grava uma linha no CSV de resultados.

A ordem das faixas de carga é alternada entre repetições, para que efeitos
cumulativos não favoreçam sistematicamente uma faixa. Os resultados vão para
`../data/`, e todo número do TCC deve ser rastreável até uma linha desse CSV.

Uso (execução completa do trabalho):
    python experiments/run_experiment.py --loads 100,1000,10000 --reps 30 --seed 20260910

Uso (verificação rápida):
    python experiments/run_experiment.py --loads 100,500 --reps 3
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

# Permite executar tanto da raiz do repositório quanto de dentro de experiments/.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

import database          # noqa: E402
import generator         # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(_HERE), "data")

CSV_FIELDS = [
    "scenario", "load", "rep", "seed",
    "emitted", "persisted", "loss_rate",
    "lat_p50_ms", "lat_p95_ms", "lat_max_ms",
    "click_of_sent", "submit_of_click", "elapsed_s",
]


def run_one(load: int, scenario_name: str, rep: int, seed: int) -> dict:
    """Executa uma repetição e devolve a linha de resultado."""
    funnel = generator.scenario(scenario_name)
    events = generator.generate_events(load, funnel=funnel, seed=seed,
                                       campaign_name=f"{scenario_name}-{load}-{rep}")

    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="exp_")
    os.close(fd)
    os.remove(db_path)  # register_event/create_database recriam do zero
    try:
        database.create_database(db_path)
        emitted = 0
        fmt = "%Y-%m-%d %H:%M:%S.%f"
        t0 = time.perf_counter()
        for ev in events:
            # origin_ts = instante de emissão, capturado imediatamente antes da
            # inserção. A latência medida (ingestão − origem) é, portanto, o
            # tempo real de processamento da persistência, sem atraso sintético.
            origin = datetime.now(timezone.utc).strftime(fmt)[:-3]
            database.register_event(
                ev["campaign_name"], ev["event_type"], ev["source"],
                external_event_id=ev["external_event_id"], target=ev["target"],
                origin_ts=origin, db_path=db_path)
            emitted += 1
        elapsed = time.perf_counter() - t0

        counts = database.count_by_type(db_path)
        persisted = sum(counts.values())
        loss = (emitted - persisted) / emitted if emitted else 0.0
        lat = database.latency_summary(db_path)
        fr = database.funnel_rates(db_path)
        click_of_sent = round(fr["clicked"] / fr["sent"], 4) if fr["sent"] else 0.0

        return {
            "scenario": scenario_name, "load": load, "rep": rep, "seed": seed,
            "emitted": emitted, "persisted": persisted,
            "loss_rate": round(loss, 6),
            "lat_p50_ms": lat["p50"], "lat_p95_ms": lat["p95"],
            "lat_max_ms": lat["max"],
            "click_of_sent": click_of_sent,
            "submit_of_click": fr["submit_rate"],
            "elapsed_s": round(elapsed, 3),
        }
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Arnês de experimento de carga.")
    parser.add_argument("--loads", default="100,1000,10000",
                        help="faixas de carga separadas por vírgula")
    parser.add_argument("--reps", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--scenarios", default="baixo,base,alto")
    args = parser.parse_args()

    loads = [int(x) for x in args.loads.split(",")]
    scenarios = [s.strip() for s in args.scenarios.split(",")]

    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(DATA_DIR, f"experimento-{stamp}.csv")

    total = len(scenarios) * len(loads) * args.reps
    done = 0
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for rep in range(1, args.reps + 1):
            # Alterna a ordem das faixas de carga a cada repetição.
            ordered = loads if rep % 2 else list(reversed(loads))
            for scenario_name in scenarios:
                for load in ordered:
                    seed = args.seed + rep * 1000 + load
                    row = run_one(load, scenario_name, rep, seed)
                    writer.writerow(row)
                    fh.flush()
                    done += 1
                    print(f"[{done:4}/{total}] {scenario_name:5} N={load:6} "
                          f"rep={rep:2} | perda={row['loss_rate']:.4f} "
                          f"p95={row['lat_p95_ms']:.1f}ms")

    print(f"\nResultados em: {out_path}")


if __name__ == "__main__":
    main()
