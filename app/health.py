"""Saúde dos robôs: transforma o histórico de execução em aviso antecipado.

O executor guarda vários candidatos de seletor por passo e tenta um por um até
algum funcionar. Isso mantém o robô vivo quando o site muda — mas, sem medir
nada, esconde a mudança: o robô "funciona" e ninguém percebe que ele passou a
depender da reserva.

Este módulo lê o `sel_rank` gravado a cada execução (0 = candidato principal) e
responde à pergunta que importa: *este passo ainda está saudável, ou já está
vivo por sorte?*

Regra de ruído: um passo só é sinalizado quando a degradação se **repete** na
janela inteira. Uma queda isolada para a reserva costuma ser lentidão de rede ou
um pop-up, não mudança de site — sinalizar isso treinaria a equipe a ignorar o
aviso, que é o pior resultado possível.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Níveis, do melhor para o pior. A ordem é usada para resumir um robô inteiro.
OK = "ok"
ATENCAO = "atencao"
CRITICO = "critico"
QUEBRADO = "quebrado"

_ORDEM = {OK: 0, ATENCAO: 1, CRITICO: 2, QUEBRADO: 3}

JANELA_PADRAO = 3
MINIMO_PARA_AVISAR = 2


@dataclass
class SaudePasso:
    step_index: int
    label: str = ""
    action: str = ""
    nivel: str = OK
    motivo: str = ""
    rank_atual: int = -1
    total_candidatos: int = 0
    desde: str = ""
    execucoes: int = 0

    @property
    def precisa_atencao(self) -> bool:
        return self.nivel != OK


@dataclass
class SaudeRobo:
    nivel: str = OK
    passos: list = field(default_factory=list)

    @property
    def problemas(self) -> list:
        return [p for p in self.passos if p.precisa_atencao]

    @property
    def resumo(self) -> str:
        if self.nivel == OK:
            return "Todos os passos estão usando o alvo principal."
        piores = sorted(self.problemas, key=lambda p: -_ORDEM[p.nivel])
        p = piores[0]
        extra = ""
        if len(piores) > 1:
            extra = f" (e mais {len(piores) - 1} passo(s) com aviso)"
        return p.motivo + extra


def _ordinal(n: int) -> str:
    return {1: "1ª", 2: "2ª", 3: "3ª", 4: "4ª", 5: "5ª"}.get(n, f"{n}ª")


def _agrupar(rows: list[dict]) -> dict[int, list[dict]]:
    """Agrupa por passo, preservando a ordem recebida (mais recente primeiro)."""
    por_passo: dict[int, list[dict]] = {}
    for r in rows:
        por_passo.setdefault(int(r.get("step_index", -1)), []).append(r)
    return por_passo


def avaliar_passo(runs: list[dict], janela: int = JANELA_PADRAO) -> SaudePasso:
    """Avalia um passo a partir das suas execuções, da mais recente para a mais antiga."""
    if not runs:
        return SaudePasso(step_index=-1)

    atual = runs[0]
    s = SaudePasso(
        step_index=int(atual.get("step_index", -1)),
        label=str(atual.get("label") or ""),
        action=str(atual.get("action") or ""),
        rank_atual=int(atual.get("sel_rank", -1)),
        total_candidatos=int(atual.get("sel_total", 0) or 0),
        execucoes=len(runs),
    )
    nome = s.label or s.action or f"passo {s.step_index}"

    # Quebrado tem prioridade: a última execução falhou neste passo.
    if str(atual.get("status", "")) == "erro":
        s.nivel = QUEBRADO
        s.motivo = f"O passo {s.step_index} ({nome}) falhou na última execução."
        s.desde = str(atual.get("started_at") or "")
        return s

    # Só passos que de fato usaram seletor entram na conta. 'goto' e passos
    # pulados gravam rank -1 e não dizem nada sobre fragilidade.
    com_seletor = [r for r in runs if int(r.get("sel_rank", -1)) >= 0]
    if len(com_seletor) < MINIMO_PARA_AVISAR:
        return s

    recentes = com_seletor[:janela]
    if not all(int(r.get("sel_rank", 0)) > 0 for r in recentes):
        return s  # em alguma das recentes o alvo principal ainda funcionou

    pior_rank = max(int(r.get("sel_rank", 0)) for r in recentes)
    total = int(recentes[0].get("sel_total", 0) or 0)
    s.desde = str(recentes[-1].get("started_at") or "")

    # Último candidato da lista = não há mais reserva depois deste.
    if total and pior_rank >= total - 1:
        s.nivel = CRITICO
        s.motivo = (f"O passo {s.step_index} ({nome}) está no último candidato "
                    f"disponível ({pior_rank + 1} de {total}). Se este parar, o robô quebra.")
    else:
        s.nivel = ATENCAO
        s.motivo = (f"O passo {s.step_index} ({nome}) está usando a "
                    f"{_ordinal(s.rank_atual + 1)} alternativa"
                    + (f" desde {s.desde[:10]}" if s.desde else "")
                    + ". O alvo principal provavelmente mudou.")
    return s


def avaliar(rows: list[dict], janela: int = JANELA_PADRAO) -> SaudeRobo:
    """Avalia um robô a partir de `Database.recent_step_runs()`."""
    passos = [avaliar_passo(runs, janela) for _, runs in sorted(_agrupar(rows).items())]
    nivel = OK
    for p in passos:
        if _ORDEM[p.nivel] > _ORDEM[nivel]:
            nivel = p.nivel
    return SaudeRobo(nivel=nivel, passos=passos)


def rotulo(nivel: str) -> str:
    return {
        OK: "Saudável",
        ATENCAO: "Atenção",
        CRITICO: "Crítico",
        QUEBRADO: "Quebrado",
    }.get(nivel, nivel)


def cor(nivel: str) -> str:
    """Cor de destaque por nível (hex), para a interface."""
    return {
        OK: "#2C6E49",
        ATENCAO: "#9A6206",
        CRITICO: "#A63A2A",
        QUEBRADO: "#A63A2A",
    }.get(nivel, "#666666")
