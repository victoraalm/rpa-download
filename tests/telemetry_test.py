"""Testa a telemetria de fragilidade no executor real (navegador de verdade).

O que precisa ser verdade para o painel de saúde significar alguma coisa:
  1. o executor registra QUAL candidato de seletor funcionou (sel_rank);
  2. o log grava o seletor realmente usado — antes daqui saía sempre o primeiro
     da lista, mesmo quando quem funcionou era o terceiro candidato.

Uso:  python tests/telemetry_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright  # noqa: E402

from app.executor.executor_core import ExecutionEngine  # noqa: E402
from app.robot_manifest import RobotManifest, Selector, Step  # noqa: E402

_falhas = []


def check(label, cond):
    print(f"  [{'OK ' if cond else 'FALHOU'}] {label}")
    if not cond:
        _falhas.append(label)


def _pagina(d, nome, html):
    p = os.path.join(d, nome)
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    return "file:///" + p.replace("\\", "/")


HTML = '<button id="btn-real" onclick="this.textContent=\'clicado\'">Exportar</button>'


def _rodar(pw, d, seletores):
    """Executa um clique com a lista de candidatos dada e devolve o passo gravado."""
    url = _pagina(d, "alvo.html", HTML)
    manifest = RobotManifest(
        name="t", start_url=url,
        steps=[
            Step(action="goto", url=url),
            Step(action="click", name="Exportar", selectors=seletores),
        ],
    )
    browser = pw.chromium.launch()
    try:
        page = browser.new_page()
        eng = ExecutionEngine(page, manifest, d, max_attempts=1,
                              action_timeout=1500, backoff_base=0)
        eng.run()
        return [r for r in eng.step_results if r["acao"] == "click"][0]
    finally:
        browser.close()


def test_candidato_principal(pw, d):
    print("== Candidato principal funciona ==")
    r = _rodar(pw, d, [Selector(type="css", value="#btn-real")])
    check("status ok", r["status"] == "ok")
    check("rank 0 (principal)", r["seletor_rank"] == 0)
    check("total de candidatos = 1", r["seletor_total"] == 1)
    check("registra o tipo", r["seletor_tipo"] == "css")


def test_cai_para_reserva(pw, d):
    print("== Cai para o candidato de reserva ==")
    r = _rodar(pw, d, [
        Selector(type="css", value="#nao-existe"),
        Selector(type="css", value="#tambem-nao"),
        Selector(type="css", value="#btn-real"),
    ])
    check("status ok (a reserva salvou)", r["status"] == "ok")
    check("rank 2 = terceiro candidato", r["seletor_rank"] == 2)
    check("total de candidatos = 3", r["seletor_total"] == 3)
    check("grava o seletor REALMENTE usado, nao o primeiro",
          r["seletor"] == "#btn-real")
    check("conta as tentativas gastas", r["tentativas"] >= 3)
    check("mede a duracao", r["duracao_ms"] >= 0)


def test_telemetria_alimenta_a_saude(pw, d):
    print("== Telemetria -> painel de saude ==")
    from app import health
    r = _rodar(pw, d, [
        Selector(type="css", value="#nao-existe"),
        Selector(type="css", value="#btn-real"),
    ])
    # Tres execucoes iguais: e o que o health exige para nao alarmar com ruido.
    linhas = [{"step_index": r["passo"], "sel_rank": r["seletor_rank"],
               "sel_total": r["seletor_total"], "status": "ok",
               "label": r["campo"], "action": r["acao"],
               "started_at": "2026-08-21"} for _ in range(3)]
    s = health.avaliar(linhas)
    # Só há 2 candidatos, e ele caiu para o segundo — ou seja, o último. Não sobra
    # reserva, então o nível correto é CRITICO e não ATENCAO.
    check("degradacao vira aviso", s.nivel == health.CRITICO)
    check("aviso explica que nao ha mais reserva", "último candidato" in s.resumo)
    check("o aviso nomeia o passo", "Exportar" in s.resumo)


def test_passo_sem_seletor_nao_conta(pw, d):
    print("== Passo sem seletor (goto) ==")
    url = _pagina(d, "alvo.html", HTML)
    manifest = RobotManifest(name="t", start_url=url,
                             steps=[Step(action="goto", url=url)])
    browser = pw.chromium.launch()
    try:
        page = browser.new_page()
        eng = ExecutionEngine(page, manifest, d, max_attempts=1, backoff_base=0)
        eng.run()
        r = eng.step_results[0]
        check("goto grava rank -1 (nao aplicavel)", r["seletor_rank"] == -1)
    finally:
        browser.close()


def main():
    with tempfile.TemporaryDirectory() as d, sync_playwright() as pw:
        test_candidato_principal(pw, d)
        test_cai_para_reserva(pw, d)
        test_telemetria_alimenta_a_saude(pw, d)
        test_passo_sem_seletor_nao_conta(pw, d)
    print()
    if _falhas:
        print(f"{len(_falhas)} verificação(ões) falharam:")
        for f in _falhas:
            print("  - " + f)
        return 1
    print("telemetria: todas as verificações passaram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
