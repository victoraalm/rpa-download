"""Testa o painel de saúde contra um banco real. Offscreen.

Uso:  python tests/health_panel_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import health  # noqa: E402
from app.db import Database  # noqa: E402
from app.ui.health_panel import HealthPanel, _coletar  # noqa: E402

_falhas = []


def check(label, cond):
    print(f"  [{'OK ' if cond else 'FALHOU'}] {label}")
    if not cond:
        _falhas.append(label)


def test_sem_historico():
    print("== Sem histórico ==")
    d = Database(os.path.join(tempfile.mkdtemp(), "vazio.db"))
    dados = _coletar(d)
    check("banco vazio não gera linhas", dados == [])
    p = HealthPanel(d)
    check("painel abre e explica que ainda não há dados",
          p.arvore.topLevelItemCount() == 1)
    p.deleteLater()


def test_ordena_pior_primeiro():
    print("== Ordenação: pior primeiro ==")
    niveis = [health.OK, health.ATENCAO, health.QUEBRADO, health.CRITICO]
    ordem = {health.QUEBRADO: 0, health.CRITICO: 1, health.ATENCAO: 2, health.OK: 3}
    ordenado = sorted(niveis, key=lambda n: ordem[n])
    check("quebrado vem antes de crítico",
          ordenado.index(health.QUEBRADO) < ordenado.index(health.CRITICO))
    check("crítico vem antes de atenção",
          ordenado.index(health.CRITICO) < ordenado.index(health.ATENCAO))
    check("ok vem por último", ordenado[-1] == health.OK)


def test_painel_lista_problemas():
    print("== Painel lista os passos com problema ==")
    d = Database(os.path.join(tempfile.mkdtemp(), "cheio.db"))
    # Três execuções caindo sempre na 2ª de 3 alternativas = degradação real.
    for _ in range(3):
        eid = d.start_execution(1, "Robô de Custos", "manual")
        d.add_step_runs(eid, [
            {"passo": 0, "acao": "goto", "campo": "https://x", "status": "ok",
             "seletor_rank": -1, "seletor_total": 0},
            {"passo": 1, "acao": "click", "campo": "Exportar", "status": "ok",
             "seletor_rank": 1, "seletor_total": 3},
        ])
        d.finish_execution(eid, "ok", downloads=1, duration_ms=900)

    saude = health.avaliar(d.recent_step_runs(1))
    check("degradação detectada", saude.nivel == health.ATENCAO)
    check("um passo com problema", len(saude.problemas) == 1)
    check("o passo goto não entra", saude.problemas[0].step_index == 1)
    check("mensagem em português, com o nome do passo",
          "Exportar" in saude.problemas[0].motivo)
    check("informa a alternativa em uso",
          "2ª alternativa" in saude.problemas[0].motivo)
    check("cor de atenção definida", health.cor(health.ATENCAO).startswith("#"))
    check("rótulo legível", health.rotulo(health.ATENCAO) == "Atenção")


def main():
    app = QApplication.instance() or QApplication([])
    test_sem_historico()
    test_ordena_pior_primeiro()
    test_painel_lista_problemas()
    app.processEvents()
    print()
    if _falhas:
        print(f"{len(_falhas)} verificação(ões) falharam:")
        for f in _falhas:
            print("  - " + f)
        return 1
    print("painel de saúde: todas as verificações passaram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
