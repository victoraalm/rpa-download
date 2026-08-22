"""Janela principal: barra superior (título + alternância de tema) e o Dashboard."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config
from .dashboard import Dashboard
from .theme import build_qss
from .update_controller import UpdateController


class MainWindow(QMainWindow):
    def __init__(self, db, mirror, retry_worker, theme_name: str):
        super().__init__()
        self.db = db
        self.mirror = mirror
        self.retry = retry_worker
        self.theme_name = theme_name

        self.setWindowTitle(config.APP_DISPLAY_NAME)
        self.resize(1180, 760)

        self.updater = UpdateController(self)
        self.updater.availability.connect(self._on_update_availability)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_top_bar())

        self.dashboard = Dashboard(
            db, mirror, retry_worker, theme_name,
            status_cb=self._set_status,
        )
        outer.addWidget(self.dashboard, 1)

        self.setCentralWidget(central)
        self.statusBar().setObjectName("StatusBar")
        self._set_status("Pronto.")

        if retry_worker is not None:
            retry_worker.pendingChanged.connect(self._on_pending_changed)

        self.updater.check_async()  # verifica atualização em segundo plano

    def _on_update_availability(self, info) -> None:
        if info:
            self.update_btn.setText(f"⬆  Atualizar para {info['tag']}")
            self.update_btn.setObjectName("Primary")
            self.update_btn.setStyleSheet("")  # reaplica o estilo do objectName
            self.style().unpolish(self.update_btn)
            self.style().polish(self.update_btn)
            self._set_status(f"Atualização disponível: {info['tag']}")
        else:
            self.update_btn.setText("🔄  Atualizar")

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(config.APP_DISPLAY_NAME)
        title.setObjectName("AppTitle")
        subtitle = QLabel(config.get_data_root() or "")
        subtitle.setObjectName("AppSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)

        self.headed_check = QCheckBox("👁  Navegador visível")
        self.headed_check.setToolTip(
            "Mostra o navegador durante a execução (passo a passo).\n"
            "Desmarque para rodar de forma invisível."
        )
        self.headed_check.setChecked(config.get_execution_headed())
        self.headed_check.toggled.connect(config.set_execution_headed)
        layout.addWidget(self.headed_check)

        self.health_btn = QPushButton("🩺  Saúde")
        self.health_btn.setToolTip(
            "Mostra os robôs que estão funcionando pela alternativa de reserva "
            "— ou seja, que mudaram de comportamento e ainda não quebraram.")
        self.health_btn.clicked.connect(self.open_health)
        layout.addWidget(self.health_btn)

        self.guide_btn = QPushButton("📖  Guia")
        self.guide_btn.setToolTip("Abrir o guia passo a passo de como usar")
        self.guide_btn.clicked.connect(self.open_guide)
        layout.addWidget(self.guide_btn)

        self.update_btn = QPushButton("🔄  Atualizar")
        self.update_btn.setToolTip("Verificar e instalar a versão mais recente")
        self.update_btn.clicked.connect(self.updater.check_and_prompt)
        layout.addWidget(self.update_btn)

        self.theme_btn = QPushButton()
        self.theme_btn.setToolTip("Alternar tema claro/escuro")
        self._update_theme_button()
        self.theme_btn.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_btn)

        return bar

    def open_health(self) -> None:
        """Abre o painel de saúde dos robôs."""
        from .health_panel import open_health_panel
        open_health_panel(self.db, self)

    def open_guide(self) -> None:
        from .guide import GuideDialog
        GuideDialog(self).exec()

    def _update_theme_button(self) -> None:
        if self.theme_name == "dark":
            self.theme_btn.setText("☀  Modo claro")
        else:
            self.theme_btn.setText("🌙  Modo escuro")

    def toggle_theme(self) -> None:
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        config.set_theme(self.theme_name)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(build_qss(self.theme_name))
        self._update_theme_button()
        self.dashboard.set_theme(self.theme_name)

    def _set_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    def _on_pending_changed(self, count: int) -> None:
        if count:
            self._set_status(f"⚠ {count} operação(ões) de pasta pendente(s) — tentando em background…")
        else:
            self._set_status("Pronto.")

    def closeEvent(self, event):
        if getattr(self, "updater", None) is not None:
            self.updater.shutdown()
        if self.retry is not None:
            self.retry.stop()
            self.retry.wait(2000)
        super().closeEvent(event)
