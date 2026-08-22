"""Testes da saúde dos robôs (telemetria de fragilidade).

Uso:  python tests/health_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import health  # noqa: E402
from app.db import Database  # noqa: E402


def run(step_index=1, rank=0, total=3, status="ok", started="2026-08-20", label="Exportar"):
    return {"step_index": step_index, "sel_rank": rank, "sel_total": total,
            "status": status, "started_at": started, "label": label, "action": "click"}


def _t(nome, cond):
    print(("  OK   " if cond else "  FALHA ") + nome)
    assert cond, nome


def test_saudavel():
    rows = [run(rank=0) for _ in range(5)]
    s = health.avaliar(rows)
    _t("candidato principal sempre -> ok", s.nivel == health.OK)
    _t("sem problemas listados", s.problemas == [])


def test_ruido_nao_alarma():
    """Uma queda isolada para a reserva NAO deve virar aviso."""
    rows = [run(rank=0), run(rank=2), run(rank=0), run(rank=0)]
    s = health.avaliar(rows)
    _t("queda isolada nao alarma", s.nivel == health.OK)


def test_degradacao_consistente():
    """Tres execucoes seguidas na 2a alternativa = o alvo principal mudou."""
    rows = [run(rank=1, started="2026-08-21"), run(rank=1, started="2026-08-20"),
            run(rank=1, started="2026-08-19"), run(rank=0, started="2026-08-18")]
    s = health.avaliar(rows)
    _t("degradacao consistente -> atencao", s.nivel == health.ATENCAO)
    p = s.problemas[0]
    _t("aponta o passo certo", p.step_index == 1)
    _t("informa a alternativa em uso", "2ª alternativa" in p.motivo)
    _t("informa desde quando", "2026-08-19" in p.motivo)
    _t("nomeia o passo", "Exportar" in p.motivo)


def test_ultimo_candidato_e_critico():
    rows = [run(rank=2, total=3) for _ in range(3)]
    s = health.avaliar(rows)
    _t("ultimo candidato -> critico", s.nivel == health.CRITICO)
    _t("explica o risco", "último candidato" in s.problemas[0].motivo)


def test_erro_e_quebrado():
    rows = [run(rank=-1, status="erro"), run(rank=0), run(rank=0)]
    s = health.avaliar(rows)
    _t("erro na ultima -> quebrado", s.nivel == health.QUEBRADO)


def test_goto_nao_conta():
    """Passos sem seletor (goto) gravam rank -1 e nao geram aviso."""
    rows = [run(step_index=0, rank=-1, total=0, label="") for _ in range(4)]
    s = health.avaliar(rows)
    _t("passo sem seletor -> ok", s.nivel == health.OK)


def test_dados_insuficientes():
    rows = [run(rank=1)]
    s = health.avaliar(rows)
    _t("uma unica execucao nao alarma", s.nivel == health.OK)


def test_pior_nivel_vence():
    rows = [run(step_index=1, rank=1) for _ in range(3)]
    rows += [run(step_index=2, rank=2, total=3) for _ in range(3)]
    s = health.avaliar(rows)
    _t("robo assume o pior nivel dos passos", s.nivel == health.CRITICO)
    _t("lista os dois problemas", len(s.problemas) == 2)


def test_integracao_com_banco():
    d = Database(os.path.join(tempfile.mkdtemp(), "saude.db"))
    for _ in range(3):
        eid = d.start_execution(7, "Robo X", "manual")
        d.add_step_runs(eid, [
            {"passo": 0, "acao": "goto", "campo": "https://x", "status": "ok",
             "seletor_rank": -1, "seletor_total": 0},
            {"passo": 1, "acao": "click", "campo": "Exportar", "status": "ok",
             "seletor_rank": 1, "seletor_total": 3, "seletor_tipo": "css"},
        ])
        d.finish_execution(eid, "ok", downloads=1, duration_ms=1000)

    s = health.avaliar(d.recent_step_runs(7))
    _t("ida e volta pelo banco detecta a degradacao", s.nivel == health.ATENCAO)
    _t("aponta o passo 1", s.problemas[0].step_index == 1)

    _t("historico gravado", len(d.list_executions(7)) == 3)
    d.prune_executions(7, manter=2)
    _t("prune mantem so as recentes", len(d.list_executions(7)) == 2)


def main():
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            print(nome)
            fn()
    print("\ntodos os testes de saude passaram")


if __name__ == "__main__":
    main()
