"""Orquestra a execução de um robô a partir do app.

- Resolve os valores ANTES de iniciar (fórmulas avaliadas com feriados BR; campos
  Manual perguntados por pop-up) e grava um manifesto resolvido temporário.
- Lança o executor em subprocesso (QProcess), lê o progresso (linhas JSON) e
  atualiza o status. Mantém um log por execução na subpasta runs/ do robô.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time as _time
from datetime import datetime

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtWidgets import QDialog, QMessageBox

from .. import formula
from ..robot_manifest import FIELD_FIXED, FIELD_FORMULA, FIELD_MANUAL, RobotManifest
from ..subproc import child_command
from . import dialogs

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ExecutionController(QObject):
    statusMessage = Signal(str)
    executionStarted = Signal(int)         # robot_id
    executionFinished = Signal(int, bool)  # robot_id, ok

    def __init__(self, db, mirror, parent_widget):
        super().__init__(parent_widget)
        self.db = db
        self.mirror = mirror
        self.parent = parent_widget
        self.proc: QProcess | None = None
        self._ctx: dict | None = None
        self._buf = ""
        self._cancelled = False

    def is_running(self) -> bool:
        return self.proc is not None

    def running_robot_id(self) -> int | None:
        return self._ctx.get("robot_id") if (self._ctx and self.proc is not None) else None

    def cancel(self) -> None:
        """Interrompe a execução em andamento (encerra o subprocesso)."""
        if self.proc is not None:
            self._cancelled = True
            self.statusMessage.emit("Interrompendo execução…")
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass

    # ----------------------------------------------------------------- run
    def run(self, robot_id: int) -> None:
        if self.is_running():
            dialogs.info(self.parent, "Execução em andamento",
                         "Aguarde a execução atual terminar.")
            return
        robot = self.db.get_robot(robot_id)
        if robot is None:
            return
        robot_dir = self.mirror.robot_dir(robot_id)
        manifest_path = os.path.join(robot_dir, "robot.json")
        if not os.path.isfile(manifest_path):
            dialogs.info(self.parent, "Robô sem caminho",
                         "Este robô ainda não foi gravado.\n"
                         "Use “Refazer caminho” para gravá-lo.")
            return
        try:
            manifest = RobotManifest.load(manifest_path)
        except (OSError, ValueError):
            dialogs.info(self.parent, "Robô inválido", "Não foi possível ler o robot.json.")
            return
        if not manifest.steps:
            dialogs.info(self.parent, "Robô vazio", "O robô não possui passos gravados.")
            return

        resolved = self._resolve(manifest)
        if resolved is None:
            self.statusMessage.emit("Execução cancelada.")
            return

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json").name
        resolved.save(tmp)

        runs_dir = os.path.join(robot_dir, "runs")
        os.makedirs(runs_dir, exist_ok=True)
        self._purge_old_logs(runs_dir)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = os.path.join(runs_dir, f"run_{ts}.log")
        session_path = os.path.join(robot_dir, "session.bin")

        exec_args = ["--manifest", tmp,
                     "--download-dir", robot_dir,
                     "--log", log_path]
        if os.path.isfile(session_path):
            exec_args += ["--session-in", session_path]
        from .. import config
        if config.get_execution_headed():
            exec_args.append("--headed")
        program, arguments = child_command("executor", exec_args)

        proc = QProcess(self)
        proc.setProgram(program)
        proc.setArguments(arguments)
        proc.setWorkingDirectory(PROJECT_ROOT)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        # Abre a execucao no banco ANTES de disparar o processo: se o executor
        # morrer, a execucao fica registrada como erro em vez de sumir.
        try:
            exec_id = self.db.start_execution(robot_id, robot.name, "manual")
        except Exception:  # noqa: BLE001 - historico nunca derruba a execucao
            exec_id = None
        self._ctx = {"robot_id": robot_id, "name": robot.name, "tmp": tmp,
                     "exec_id": exec_id, "log_path": log_path,
                     "t0": _time.monotonic()}
        self._buf = ""
        self._cancelled = False
        self.proc = proc
        self.statusMessage.emit(f"Executando “{robot.name}”…")
        proc.start()
        self.executionStarted.emit(robot_id)

    # --------------------------------------------------------- resolução
    def _resolve(self, manifest: RobotManifest):
        try:
            import holidays
            br = holidays.Brazil()
        except Exception:
            br = None

        # 1) Coleta todos os campos Manual e pergunta de uma vez, com o widget
        #    adequado a cada tipo de dado.
        manual_specs = []
        for i, step in enumerate(manifest.steps):
            if step.field and step.field.type == FIELD_MANUAL:
                manual_specs.append({
                    "index": i,
                    "name": step.field.name or step.field.prompt or step.label,
                    "prompt": step.field.prompt,
                    "data_type": step.field.data_type,
                    "fmt": step.field.fmt or "dd/mm/yyyy",
                    "options": step.field.options,
                })
        manual_values = {}
        if manual_specs:
            from .manual_input import ManualInputDialog
            dlg = ManualInputDialog(manual_specs, manifest.name, self.parent)
            if dlg.exec() != QDialog.Accepted:
                return None
            manual_values = dlg.values()

        # 2) Resolve cada campo para um valor fixo de execução.
        for i, step in enumerate(manifest.steps):
            if step.field is None:
                continue
            kind = step.field.type
            if kind == FIELD_FORMULA:
                try:
                    value = formula.evaluate(step.field.formula,
                                             fmt=step.field.fmt or "dd/mm/yyyy",
                                             holiday_calendar=br)
                except formula.FormulaError as e:
                    QMessageBox.warning(self.parent, "Fórmula inválida",
                                        f"{step.label or 'campo'}: {e}")
                    return None
            elif kind == FIELD_MANUAL:
                value = manual_values.get(i, "")
            else:  # fixo
                value = step.field.value
            step.field.value = value
            step.field.type = FIELD_FIXED
        return manifest

    # ------------------------------------------------------------ eventos
    def _on_stdout(self):
        if self.proc is None:
            return
        self._buf += bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            self._handle_event(obj)

    def _handle_event(self, obj):
        t = obj.get("type")
        if t == "log":
            self.statusMessage.emit(obj.get("msg", ""))
        elif t == "login_required":
            self.statusMessage.emit("Sessão expirada — faça login na janela do navegador que abriu…")
        elif t == "done" and self._ctx is not None:
            # O executor ja conta os downloads e descreve o erro. Guardar aqui
            # evita adivinhar depois olhando pastas.
            self._ctx["downloads"] = len(obj.get("downloads") or [])
            self._ctx["error"] = obj.get("error", "") or ""

    def _on_error(self, error):
        if self.proc is None:
            return
        if error == QProcess.FailedToStart:
            ctx = self._ctx
            self._reset()
            self.statusMessage.emit("Não foi possível iniciar o executor.")
            if ctx:
                self._persistir(ctx, "erro", "o executor nao pode ser iniciado")
                self._cleanup(ctx)
                self.executionFinished.emit(ctx["robot_id"], False)

    def _on_finished(self, code, _status):
        ctx = self._ctx
        cancelled = self._cancelled
        self._cancelled = False
        self._reset()
        if ctx is None:
            return
        if cancelled:
            self.statusMessage.emit(f"Execução de “{ctx['name']}” interrompida.")
        elif code == 0:
            self.statusMessage.emit(f"Robô “{ctx['name']}” executado com sucesso.")
        elif code == 2:
            self.statusMessage.emit("Execução cancelada.")
        else:
            self.statusMessage.emit(
                f"Robô “{ctx['name']}” terminou com erro (ver log em runs/).")
        if cancelled:
            status = "interrompido"
        elif code == 0:
            status = "ok"
        else:
            status = "erro"
        self._persistir(ctx, status)
        self._cleanup(ctx)
        self.executionFinished.emit(ctx["robot_id"], code == 0 and not cancelled)

    # --------------------------------------------------------- historico
    def _persistir(self, ctx, status: str, erro: str = "") -> None:
        """Grava a execucao e os passos no banco.

        Le o .csv que o executor ja escreve — assim a telemetria chega ao
        historico sem mudar o protocolo entre os processos. Falhar aqui nunca
        pode derrubar a execucao: o historico e util, nao essencial.
        """
        exec_id = (ctx or {}).get("exec_id")
        if not exec_id:
            return
        linhas = []
        try:
            log_path = ctx.get("log_path") or ""
            csv_path = (log_path[:-4] + ".csv") if log_path.lower().endswith(".log") \
                else log_path + ".csv"
            if os.path.isfile(csv_path):
                import csv as _csv
                with open(csv_path, newline="", encoding="utf-8-sig") as f:
                    linhas = list(_csv.DictReader(f, delimiter=";"))
        except Exception:  # noqa: BLE001
            linhas = []
        baixados = int(ctx.get("downloads", 0) or 0)
        erro = erro or str(ctx.get("error", "") or "")
        dur = int((_time.monotonic() - ctx.get("t0", _time.monotonic())) * 1000)
        try:
            self.db.add_step_runs(exec_id, linhas)
            self.db.finish_execution(exec_id, status, error=erro,
                                     downloads=baixados, duration_ms=dur)
            self.db.prune_executions(ctx["robot_id"], manter=100)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ helpers
    def _reset(self):
        if self.proc is not None:
            self.proc.deleteLater()
        self.proc = None

    def _cleanup(self, ctx):
        try:
            if os.path.isfile(ctx["tmp"]):
                os.remove(ctx["tmp"])
        except OSError:
            pass

    @staticmethod
    def _purge_old_logs(runs_dir: str) -> None:
        """Apaga logs/CSV de execução mais antigos que o limite de retenção."""
        import time

        from .. import config
        days = config.get_log_retention_days()
        if days <= 0:  # 0 = nunca apagar
            return
        cutoff = time.time() - days * 86400
        try:
            for fn in os.listdir(runs_dir):
                if not (fn.lower().endswith(".log") or fn.lower().endswith(".csv")):
                    continue
                p = os.path.join(runs_dir, fn)
                try:
                    if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                        os.remove(p)
                except OSError:
                    pass
        except OSError:
            pass
