"""Gera as figuras do TCC a partir de um CSV de resultados do experimento.

Produz três figuras em escala de cinza, legíveis em impressão preto e branco,
distinguindo as séries por marcador e traço (não por cor):

  fig1_latencia_carga.png   — latência p95 por faixa de carga, um traço por cenário
  fig2_funil.png            — funil enviado→clique→submissão, por cenário
  fig3_throughput_carga.png — vazão (eventos/s) por faixa de carga

As figuras vão para ../figures/. Uso:
    python experiments/make_figures.py [caminho_do_csv]
Sem argumento, usa o CSV mais recente em ../data/.

Requer matplotlib (dependência de análise, não da plataforma; ver
requirements-figs.txt).
"""
from __future__ import annotations

import csv
import glob
import os
import statistics as st
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(_HERE), "data")
FIG_DIR = os.path.join(os.path.dirname(_HERE), "figures")

# Escala de cinza + marcador + traço por cenário (identidade sem cor).
STYLE = {
    "baixo": {"color": "0.0", "marker": "o", "ls": "-", "label": "Funil baixo"},
    "base": {"color": "0.35", "marker": "s", "ls": "--", "label": "Funil base"},
    "alto": {"color": "0.6", "marker": "^", "ls": ":", "label": "Funil alto"},
}
SCEN_ORDER = ["baixo", "base", "alto"]

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.grid": True,
    "grid.color": "0.85",
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 300,
})


def load_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def agg(rows, key_scenario, key_load, field, fn=st.mean):
    """Média (ou outra função) de `field` por (cenário, carga)."""
    g = defaultdict(list)
    for r in rows:
        g[(r["scenario"], int(r["load"]))].append(float(r[field]))
    return {k: fn(v) for k, v in g.items()}


def loads_sorted(rows) -> list[int]:
    return sorted({int(r["load"]) for r in rows})


def fig_latencia(rows, out):
    loads = loads_sorted(rows)
    p95 = agg(rows, "scenario", "load", "lat_p95_ms")
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for sc in SCEN_ORDER:
        ys = [p95.get((sc, L)) for L in loads]
        if any(y is None for y in ys):
            continue
        s = STYLE[sc]
        ax.plot(loads, ys, color=s["color"], marker=s["marker"], linestyle=s["ls"],
                linewidth=1.6, markersize=6, label=s["label"])
    ax.set_xscale("log")
    ax.set_xticks(loads)
    ax.set_xticklabels([f"{L:,}".replace(",", ".") for L in loads])
    ax.set_xlabel("Eventos por execução (escala logarítmica)")
    ax.set_ylabel("Latência p95 de persistência (ms)")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, loc="center")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def fig_funil(rows, out):
    # Funil normalizado (% dos enviados): enviado, clique, submissão.
    click = agg(rows, "scenario", "load", "click_of_sent")
    submit = agg(rows, "scenario", "load", "submit_of_click")
    # média entre as cargas (o funil independe da carga por construção)
    stages = ["Enviado", "Clique", "Submissão"]
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    width = 0.26
    x = range(len(stages))
    for i, sc in enumerate(SCEN_ORDER):
        cs = [click[k] for k in click if k[0] == sc]
        ss = [submit[k] for k in submit if k[0] == sc]
        if not cs:
            continue
        c = st.mean(cs)
        s_ = st.mean(ss)
        vals = [100.0, 100.0 * c, 100.0 * c * s_]
        pos = [xi + (i - 1) * width for xi in x]
        st_ = STYLE[sc]
        bars = ax.bar(pos, vals, width=width, color=st_["color"],
                      edgecolor="black", linewidth=0.5, label=st_["label"])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.1f}",
                    ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(stages)
    ax.set_ylabel("Proporção sobre os e-mails enviados (%)")
    ax.set_ylim(0, 108)
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def fig_throughput(rows, out):
    loads = loads_sorted(rows)
    thr = defaultdict(list)
    for r in rows:
        thr[(r["scenario"], int(r["load"]))].append(
            float(r["emitted"]) / float(r["elapsed_s"]))
    thr = {k: st.mean(v) for k, v in thr.items()}
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for sc in SCEN_ORDER:
        ys = [thr.get((sc, L)) for L in loads]
        if any(y is None for y in ys):
            continue
        s = STYLE[sc]
        ax.plot(loads, ys, color=s["color"], marker=s["marker"], linestyle=s["ls"],
                linewidth=1.6, markersize=6, label=s["label"])
    ax.set_xscale("log")
    ax.set_xticks(loads)
    ax.set_xticklabels([f"{L:,}".replace(",", ".") for L in loads])
    ax.set_xlabel("Eventos por execução (escala logarítmica)")
    ax.set_ylabel("Vazão de persistência (eventos/s)")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        candidates = sorted(glob.glob(os.path.join(DATA_DIR, "experimento-*.csv")))
        if not candidates:
            raise SystemExit("Nenhum CSV encontrado em data/.")
        csv_path = candidates[-1]

    rows = load_rows(csv_path)
    os.makedirs(FIG_DIR, exist_ok=True)
    print(f"CSV: {os.path.basename(csv_path)} ({len(rows)} execuções)")

    fig_latencia(rows, os.path.join(FIG_DIR, "fig1_latencia_carga.png"))
    fig_funil(rows, os.path.join(FIG_DIR, "fig2_funil.png"))
    fig_throughput(rows, os.path.join(FIG_DIR, "fig3_throughput_carga.png"))
    print("Figuras geradas em:", FIG_DIR)


if __name__ == "__main__":
    main()
