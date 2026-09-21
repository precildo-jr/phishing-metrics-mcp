"""Gerador probabilístico de eventos de campanha simulada.

Produz o fluxo de eventos de uma campanha de phishing como uma cadeia de
ensaios de Bernoulli condicionais — cada degrau do funil só ocorre se o
anterior tiver ocorrido — sobre uma linha do tempo em que as chegadas seguem
um processo de Poisson e o atraso de propagação segue distribuição log-normal.

Os parâmetros do funil-base vêm de dados empíricos: Oliveira, Sá e Barboza
(2025) mediram, com o GoPhish em uma empresa real, 293 e-mails, 49 cliques
(≈16,7% dos enviados; ≈42% dos que abriram) e 23 submissões de credenciais
(≈47% dos que clicaram). Esses valores são o centro da varredura de
sensibilidade; os cenários "baixo" e "alto" deslocam a taxa de clique para
verificar se a confiabilidade da coleta independe do formato do funil.

Sem dependências externas: apenas a biblioteca padrão do Python.
"""
from __future__ import annotations

import math
import os
import random
import sys
from dataclasses import dataclass

# Permite importar a camada de persistência tanto da raiz do repositório
# quanto de dentro de experiments/.
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from plataforma import persistencia  # noqa: E402


@dataclass(frozen=True)
class FunnelParams:
    """Probabilidades condicionais de cada degrau do funil.

    A abertura é registrada com ressalva: Oliveira, Sá e Barboza (2025)
    observam que clientes de e-mail móveis marcam mensagens como abertas
    automaticamente, o que torna essa métrica pouco confiável quando medida —
    mas ela permanece útil como parâmetro de geração, pois o que importa ao
    experimento é a taxa de clique sobre os enviados, aqui ≈ p_open × p_click.
    """
    name: str = "base"
    p_deliver: float = 0.98   # entrega | envio
    p_open: float = 0.40      # abertura | entrega
    p_click: float = 0.42     # clique | abertura   (0,40 × 0,42 ≈ 0,167)
    p_submit: float = 0.47    # submissão | clique
    p_report: float = 0.05    # reporte | abertura  (parâmetro menos ancorado)


# Cenários da varredura de sensibilidade. A taxa de clique sobre os enviados
# é p_open × p_click: 0,10 / 0,17 / 0,30. O piso e o teto cobrem a faixa
# reportada na literatura brasileira (Carvalho et al., 2024: >30% de clique).
FUNNEL_SCENARIOS = {
    "baixo": FunnelParams(name="baixo", p_open=0.40, p_click=0.25, p_submit=0.47),
    "base": FunnelParams(name="base", p_open=0.40, p_click=0.42, p_submit=0.47),
    "alto": FunnelParams(name="alto", p_open=0.60, p_click=0.50, p_submit=0.47),
}


@dataclass(frozen=True)
class TimingParams:
    """Parâmetros temporais da geração.

    `arrival_rate_per_s` é a taxa λ do processo de Poisson que espaça as
    chegadas. `delay_ln_*` parametrizam a log-normal do atraso de propagação,
    em milissegundos: a mediana é exp(mu) e a dispersão cresce com sigma. Os
    padrões produzem mediana de ~300 ms com cauda à direita até alguns segundos.
    """
    arrival_rate_per_s: float = 20.0
    delay_ln_mu: float = math.log(300.0)   # mediana ≈ 300 ms
    delay_ln_sigma: float = 0.8


def generate_events(n_events: int, *, funnel: FunnelParams = FunnelParams(),
                    timing: TimingParams = TimingParams(), seed: int,
                    campaign_name: str = "sim") -> list[dict]:
    """Gera exatamente `n_events` eventos, determinísticos para a mesma semente.

    Cada evento carrega o intervalo de chegada em relação ao anterior (`gap_s`,
    exponencial — o processo de Poisson) e um atraso de campanha (`delay_ms`,
    log-normal), ambos derivados apenas da semente. São o modelo temporal
    reprodutível da campanha; o experimento de carga alimenta os eventos em
    rajada e mede a latência real de persistência (o arnê define `origin_ts`
    como o instante de emissão, imediatamente antes da inserção), de modo que a
    mesma semente reproduz exatamente o mesmo conjunto de eventos.
    """
    rng = random.Random(seed)
    events: list[dict] = []
    target_seq = 0

    while len(events) < n_events:
        target_seq += 1
        target = f"alvo-{target_seq:06d}@sim.invalido"
        gap_s = rng.expovariate(timing.arrival_rate_per_s)

        if rng.random() > funnel.p_deliver:
            continue  # não entregue: nenhum evento para este alvo

        steps = [persistencia.EMAIL_SENT]
        if rng.random() < funnel.p_open:
            steps.append(persistencia.EMAIL_OPENED)
            if rng.random() < funnel.p_click:
                steps.append(persistencia.LINK_CLICKED)
                if rng.random() < funnel.p_submit:
                    steps.append(persistencia.DATA_SUBMITTED)
            if rng.random() < funnel.p_report:
                steps.append(persistencia.EMAIL_REPORTED)

        for event_type in steps:
            delay_ms = rng.lognormvariate(timing.delay_ln_mu, timing.delay_ln_sigma)
            events.append({
                "campaign_name": campaign_name,
                "event_type": event_type,
                "target": target,
                "external_event_id": f"{campaign_name}-{seed}-{len(events):08d}",
                "delay_ms": delay_ms,
                "gap_s": gap_s,
                "source": "generator",
            })
            if len(events) >= n_events:
                break

    return events


def scenario(name: str) -> FunnelParams:
    """Retorna os parâmetros de funil de um cenário nomeado da varredura."""
    return FUNNEL_SCENARIOS[name]


if __name__ == "__main__":
    # Demonstração: gera um pequeno lote e resume o funil produzido.
    for sc in FUNNEL_SCENARIOS.values():
        evs = generate_events(2000, funnel=sc, seed=42)
        by = {}
        for e in evs:
            by[e["event_type"]] = by.get(e["event_type"], 0) + 1
        sent = by.get(persistencia.EMAIL_SENT, 0)
        clicked = by.get(persistencia.LINK_CLICKED, 0)
        submitted = by.get(persistencia.DATA_SUBMITTED, 0)
        click_of_sent = clicked / sent if sent else 0
        submit_of_click = submitted / clicked if clicked else 0
        print(f"cenário {sc.name:5} | enviados={sent:4} "
              f"clique/enviados={click_of_sent:.3f} "
              f"submissão/clique={submit_of_click:.3f}")
