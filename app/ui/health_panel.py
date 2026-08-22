"""Painel de saúde: mostra quais robôs estão vivos por reserva.

Um robô que caiu para o seletor de reserva continua verde e continua entregando
o arquivo — até o dia em que a reserva também some. Este painel existe para que
esse dia não seja uma surpresa: ele lê o histórico de execução e diz, em
português, qual passo mudou de comportamento e desde quando.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .. import health

_SEM_HISTORICO = (
    "Nenhuma execução registrada ainda.\n\n"
    "O painel se enche sozinho conforme os robôs rodam: cada execução guarda "
    "qual alternativa de cada passo funcionou."
)


def _coletar(db):
    """Devolve [(robo, SaudeRobo, nº de execuções)] ordenado pelo pior primeiro."""
    linhas = []
    for screen in db.list_screens():
        for bloco in db.list_blocks(screen.id):
            for robo in db.list_robots(bloco.id):
                execucoes = db.list_executions(robo.id, limit=10)
                if not execucoes:
                    continue
                saude = health.avaliar(db.recent_step_runs(robo.id, execucoes=10))
                linhas.append((robo, saude, execucoes))
    ordem = {health.QUEBRADO: 0, health.CRITICO: 1, health.ATENCAO: 2, health.OK: 3}
    linhas.sort(key=lambda x: (ordem.get(x[1].nivel, 9), x[0].name.lower()))
    return linhas


class HealthPanel(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Saúde dos robôs")
        self.resize(880, 560)

        layout = QVBoxLayout(self)

        cabecalho = QLabel(
            "Um passo que vem usando a alternativa de reserva já mudou de "
            "comportamento, mesmo que o robô continue funcionando. Aqui aparecem "
            "esses casos, do mais urgente para o menos."
        )
        cabecalho.setWordWrap(True)
        layout.addWidget(cabecalho)

        self.resumo = QLabel()
        f = QFont()
        f.setBold(True)
        self.resumo.setFont(f)
        layout.addWidget(self.resumo)

        self.arvore = QTreeWidget()
        self.arvore.setColumnCount(4)
        self.arvore.setHeaderLabels(["Robô / passo", "Situação", "Alternativa", "Desde"])
        self.arvore.setAlternatingRowColors(True)
        self.arvore.header().setStretchLastSection(False)
        self.arvore.setColumnWidth(0, 420)
        self.arvore.setColumnWidth(1, 110)
        self.arvore.setColumnWidth(2, 130)
        layout.addWidget(self.arvore, 1)

        rodape = QHBoxLayout()
        rodape.addStretch(1)
        botoes = QDialogButtonBox(QDialogButtonBox.Close)
        botoes.rejected.connect(self.reject)
        rodape.addWidget(botoes)
        layout.addLayout(rodape)

        self.recarregar()

    # ------------------------------------------------------------------ dados
    def recarregar(self) -> None:
        self.arvore.clear()
        try:
            dados = _coletar(self.db)
        except Exception as e:  # noqa: BLE001 - painel nunca derruba o programa
            self.resumo.setText(f"Não consegui ler o histórico: {e}")
            return

        if not dados:
            self.resumo.setText("")
            item = QTreeWidgetItem([_SEM_HISTORICO, "", "", ""])
            self.arvore.addTopLevelItem(item)
            return

        com_aviso = [d for d in dados if d[1].nivel != health.OK]
        if com_aviso:
            self.resumo.setText(
                f"{len(com_aviso)} de {len(dados)} robô(s) precisam de atenção."
            )
        else:
            self.resumo.setText(
                f"Os {len(dados)} robô(s) com histórico estão usando o alvo principal."
            )

        for robo, saude, execucoes in dados:
            topo = QTreeWidgetItem([
                robo.name,
                health.rotulo(saude.nivel),
                "",
                f"{len(execucoes)} execução(ões)",
            ])
            cor = QColor(health.cor(saude.nivel))
            topo.setForeground(1, cor)
            fonte = topo.font(0)
            fonte.setBold(True)
            topo.setFont(0, fonte)
            self.arvore.addTopLevelItem(topo)

            for passo in saude.problemas:
                filho = QTreeWidgetItem([
                    f"passo {passo.step_index} — {passo.motivo}",
                    health.rotulo(passo.nivel),
                    (f"{passo.rank_atual + 1} de {passo.total_candidatos}"
                     if passo.total_candidatos else ""),
                    (passo.desde or "")[:10],
                ])
                filho.setForeground(1, QColor(health.cor(passo.nivel)))
                filho.setToolTip(0, passo.motivo)
                topo.addChild(filho)

            topo.setExpanded(saude.nivel != health.OK)


def open_health_panel(db, parent=None) -> None:
    HealthPanel(db, parent).exec()
