"""Gera o diagrama arquitetural da plataforma (Figura 1 do TCC).

Desenho em escala de cinza, legível em impressão preto e branco, das quatro
camadas da solução e das interfaces de comunicação entre elas. Componentes
implementados neste trabalho aparecem com contorno sólido e preenchimento
cinza; ferramentas externas (a de simulação e o agente de modelo de linguagem)
aparecem com contorno tracejado e fundo branco.

A saída vai para ../figures/fig_arquitetura.png. Uso:
    python experiments/make_arch_figure.py
Requer matplotlib (ver requirements-figs.txt).
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(os.path.dirname(_HERE), "figures")

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "figure.dpi": 300,
})

CINZA = "0.90"     # preenchimento dos componentes implementados
PRETO = "0.0"


def caixa(ax, x, y, w, h, titulo, linhas, implementado=True):
    """Desenha um componente. Sólido/cinza se implementado; tracejado/branco se não.

    `titulo` pode conter quebra de linha; o corpo vem logo abaixo. As duas
    linhas de título mantêm os rótulos dentro da largura da caixa.
    """
    estilo = dict(boxstyle="round,pad=0.02,rounding_size=0.06",
                  linewidth=1.4, edgecolor=PRETO)
    if implementado:
        estilo.update(facecolor=CINZA, linestyle="solid")
    else:
        estilo.update(facecolor="white", linestyle=(0, (4, 2)))
    ax.add_patch(FancyBboxPatch((x, y), w, h, **estilo))
    n_tit = titulo.count("\n") + 1
    ax.text(x + w / 2, y + h - 0.26, titulo, ha="center", va="top",
            fontweight="bold", fontsize=8, linespacing=1.15)
    ax.text(x + w / 2, y + h - 0.30 - 0.42 * n_tit, "\n".join(linhas),
            ha="center", va="top", fontsize=7.2, color="0.15", linespacing=1.2)


def seta(ax, p0, p1, rotulo, dx=0.0, dy=0.0, ha="center", va="center"):
    ax.add_patch(FancyArrowPatch(
        p0, p1, arrowstyle="-|>", mutation_scale=13, linewidth=1.3,
        color=PRETO, shrinkA=2, shrinkB=2))
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    ax.text(mx + dx, my + dy, rotulo, ha=ha, va=va, fontsize=7.4,
            color="0.0", style="italic",
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                      edgecolor="none"))


def main() -> None:
    fig, ax = plt.subplots(figsize=(6.8, 4.4))
    ax.set_xlim(0, 12.4)
    ax.set_ylim(0, 8)
    ax.axis("off")

    W, H = 3.7, 2.25
    xL, xM, xR = 0.15, 4.35, 8.55
    y_top, y_bot = 5.4, 0.35

    # Percurso de coleta (linha superior, esquerda -> direita)
    caixa(ax, xL, y_top, W, H, "Camada de\nsimulação",
          ["Gophish (externa);", "gerador de eventos"], implementado=False)
    caixa(ax, xM, y_top, W, H, "Camada de\ningestão",
          ["receptor de webhook;", "assinatura, normalização"], implementado=True)
    caixa(ax, xR, y_top, W, H, "Camada de\npersistência",
          ["SQLite; idempotência;", "pseudonimização"], implementado=True)

    # Percurso analítico (linha inferior)
    caixa(ax, xM, y_bot, W, H, "Agente de modelo\nde linguagem",
          ["(externo);", "consultas em", "linguagem natural"], implementado=False)
    caixa(ax, xR, y_bot, W, H, "Camada de\norquestração",
          ["servidor MCP;", "registro, consulta,", "consolidação"], implementado=True)

    ym_top = y_top + H / 2
    # Coleta: simulação -> ingestão -> persistência
    seta(ax, (xL + W, ym_top), (xM, ym_top),
         "webhook HTTP\nHMAC-SHA256", dy=0.62, va="bottom")
    seta(ax, (xM + W, ym_top), (xR, ym_top),
         "registro\nidempotente", dy=0.62, va="bottom")
    # Análise: agente -> orquestração (protocolo MCP), orquestração -> persistência (SQL)
    seta(ax, (xM + W, y_bot + H / 2), (xR, y_bot + H / 2),
         "protocolo MCP", dy=0.55, va="bottom")
    seta(ax, (xR + W / 2, y_bot + H), (xR + W / 2, y_top),
         "consulta e\nconsolidação (SQL)", dx=0.25, ha="left")

    fig.tight_layout()
    os.makedirs(FIG_DIR, exist_ok=True)
    out = os.path.join(FIG_DIR, "fig_arquitetura.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("Diagrama gerado em:", out)


if __name__ == "__main__":
    main()
