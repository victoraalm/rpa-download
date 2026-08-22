"""Camada de acesso ao banco SQLite.

Guarda os metadados que as pastas físicas não conseguem representar de forma
confiável (ordem das telas/blocos/robôs, descrições, tamanho de ícone) e a
fila persistente de operações de arquivo pendentes (fila de retry).

Conexões são por-thread (a UI e o RetryWorker rodam em threads diferentes).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime

from .models import Block, Robot, Screen


def _int(v, padrao=0):
    """int() tolerante: o CSV do executor entrega tudo como texto, e campo
    vazio e comum em passos que nao usam seletor."""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return padrao

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS screens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    position    INTEGER NOT NULL,
    folder_name TEXT NOT NULL,
    is_home     INTEGER NOT NULL DEFAULT 0,
    is_trash    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_id   INTEGER NOT NULL,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    position    INTEGER NOT NULL,
    folder_name TEXT NOT NULL,
    FOREIGN KEY (screen_id) REFERENCES screens (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS robots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id      INTEGER NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT DEFAULT '',
    position      INTEGER NOT NULL,
    folder_name   TEXT NOT NULL,
    size          TEXT NOT NULL DEFAULT 'large',
    manifest_path TEXT DEFAULT '',
    FOREIGN KEY (block_id) REFERENCES blocks (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pending_ops (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    op_type    TEXT NOT NULL,            -- create | move | remove
    src_path   TEXT,
    dst_path   TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

-- Historico de execucao. Sem estas duas tabelas nao ha como medir nada ao
-- longo do tempo: cada execucao esquecia tudo o que aprendeu.
CREATE TABLE IF NOT EXISTS executions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    robot_id    INTEGER,
    robot_name  TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL,
    finished_at TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'rodando',  -- rodando | ok | erro | interrompido
    origin      TEXT NOT NULL DEFAULT 'manual',   -- manual | agendado
    error       TEXT DEFAULT '',
    downloads   INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS step_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id INTEGER NOT NULL,
    step_index   INTEGER NOT NULL,
    action       TEXT NOT NULL DEFAULT '',
    label        TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT '',
    error        TEXT DEFAULT '',
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    attempts     INTEGER NOT NULL DEFAULT 0,
    -- Telemetria de fragilidade: sel_rank 0 = candidato principal funcionou;
    -- maior que 0 = o alvo original mudou e o passo vive de reserva; -1 = n/a.
    sel_rank     INTEGER NOT NULL DEFAULT -1,
    sel_total    INTEGER NOT NULL DEFAULT 0,
    sel_type     TEXT DEFAULT '',
    sel_value    TEXT DEFAULT '',
    FOREIGN KEY (execution_id) REFERENCES executions (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_step_runs_exec  ON step_runs (execution_id);
CREATE INDEX IF NOT EXISTS ix_step_runs_index ON step_runs (execution_id, step_index);
CREATE INDEX IF NOT EXISTS ix_exec_robot      ON executions (robot_id, id DESC);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._local = threading.local()
        with self.conn() as c:
            c.executescript(_SCHEMA)
            # Migração: bancos antigos não têm a coluna is_trash.
            cols = [r["name"] for r in c.execute("PRAGMA table_info(screens)").fetchall()]
            if "is_trash" not in cols:
                c.execute("ALTER TABLE screens ADD COLUMN is_trash INTEGER NOT NULL DEFAULT 0")

    # ------------------------------------------------------------------ infra
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA busy_timeout = 5000")
            c.execute("PRAGMA journal_mode = WAL")
            self._local.conn = c
        return c

    # --------------------------------------------------------------- settings
    def get_setting(self, key: str, default=None):
        row = self.conn().execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
    # ------------------------------------------------------- execucoes
    def start_execution(self, robot_id, robot_name: str, origin: str = "manual") -> int:
        """Abre uma execucao e devolve o id. Fechar com finish_execution()."""
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO executions (robot_id, robot_name, started_at, status, origin) "
                "VALUES (?, ?, ?, 'rodando', ?)",
                (robot_id, robot_name, datetime.now().isoformat(timespec="seconds"), origin),
            )
            return int(cur.lastrowid)

    def finish_execution(self, execution_id: int, status: str, *, error: str = "",
                         downloads: int = 0, duration_ms: int = 0) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE executions SET finished_at = ?, status = ?, error = ?, "
                "downloads = ?, duration_ms = ? WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds"), status, error,
                 downloads, duration_ms, execution_id),
            )

    def add_step_runs(self, execution_id: int, rows: list[dict]) -> int:
        """Persiste o resultado passo a passo vindo do executor.

        Aceita as chaves do step_results do ExecutionEngine. Campos ausentes
        viram o padrao, para que manifestos antigos continuem gravando.
        """
        if not rows:
            return 0
        dados = [
            (execution_id,
             _int(r.get("passo"), -1),
             str(r.get("acao", "")),
             str(r.get("campo", "")),
             str(r.get("status", "")),
             str(r.get("erro", "")),
             _int(r.get("duracao_ms"), 0),
             _int(r.get("tentativas"), 0),
             _int(r.get("seletor_rank"), -1),
             _int(r.get("seletor_total"), 0),
             str(r.get("seletor_tipo", "")),
             str(r.get("seletor", "")))
            for r in rows
        ]
        with self.conn() as c:
            c.executemany(
                "INSERT INTO step_runs (execution_id, step_index, action, label, status,"
                " error, duration_ms, attempts, sel_rank, sel_total, sel_type, sel_value)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                dados,
            )
        return len(dados)

    def list_executions(self, robot_id=None, limit: int = 50) -> list[dict]:
        if robot_id is None:
            rows = self.conn().execute(
                "SELECT * FROM executions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = self.conn().execute(
                "SELECT * FROM executions WHERE robot_id = ? ORDER BY id DESC LIMIT ?",
                (robot_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def recent_step_runs(self, robot_id: int, execucoes: int = 10) -> list[dict]:
        """Passos das N execucoes mais recentes do robo, da mais nova para a mais antiga."""
        rows = self.conn().execute(
            "SELECT sr.*, e.id AS exec_id, e.started_at FROM step_runs sr "
            "JOIN executions e ON e.id = sr.execution_id "
            "WHERE e.robot_id = ? AND e.status <> 'rodando' "
            "AND e.id IN (SELECT id FROM executions WHERE robot_id = ? "
            "             AND status <> 'rodando' ORDER BY id DESC LIMIT ?) "
            "ORDER BY e.id DESC, sr.step_index ASC",
            (robot_id, robot_id, execucoes)).fetchall()
        return [dict(r) for r in rows]

    def prune_executions(self, robot_id: int, manter: int = 100) -> int:
        """Mantem so as N execucoes mais recentes do robo (o resto cai em cascata)."""
        with self.conn() as c:
            cur = c.execute(
                "DELETE FROM executions WHERE robot_id = ? AND id NOT IN "
                "(SELECT id FROM executions WHERE robot_id = ? ORDER BY id DESC LIMIT ?)",
                (robot_id, robot_id, manter))
            return cur.rowcount or 0


    # ---------------------------------------------------------------- screens
    def list_screens(self) -> list[Screen]:
        rows = self.conn().execute(
            "SELECT * FROM screens ORDER BY position, id"
        ).fetchall()
        return [Screen.from_row(r) for r in rows]

    def get_screen(self, screen_id: int) -> Screen | None:
        r = self.conn().execute(
            "SELECT * FROM screens WHERE id = ?", (screen_id,)
        ).fetchone()
        return Screen.from_row(r) if r else None

    def get_home_screen(self) -> Screen | None:
        r = self.conn().execute(
            "SELECT * FROM screens WHERE is_home = 1 ORDER BY position LIMIT 1"
        ).fetchone()
        return Screen.from_row(r) if r else None

    def get_trash_screen(self) -> Screen | None:
        r = self.conn().execute(
            "SELECT * FROM screens WHERE is_trash = 1 ORDER BY position LIMIT 1"
        ).fetchone()
        return Screen.from_row(r) if r else None

    def screen_folder_names(self, exclude_id: int | None = None) -> set[str]:
        rows = self.conn().execute("SELECT id, folder_name FROM screens").fetchall()
        return {r["folder_name"] for r in rows if r["id"] != exclude_id}

    def add_screen(self, name, description, folder_name, is_home=0, is_trash=0) -> int:
        with self.conn() as c:
            pos = c.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM screens").fetchone()["p"]
            cur = c.execute(
                "INSERT INTO screens (name, description, position, folder_name, is_home, is_trash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, description, pos, folder_name, is_home, is_trash),
            )
            return cur.lastrowid

    def update_screen(self, screen_id, name, description, folder_name) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE screens SET name = ?, description = ?, folder_name = ? WHERE id = ?",
                (name, description, folder_name, screen_id),
            )

    def delete_screen(self, screen_id) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM screens WHERE id = ?", (screen_id,))

    def set_screen_positions(self, ordered_ids: list[int]) -> None:
        with self.conn() as c:
            for pos, sid in enumerate(ordered_ids):
                c.execute("UPDATE screens SET position = ? WHERE id = ?", (pos, sid))

    # ----------------------------------------------------------------- blocks
    def list_blocks(self, screen_id: int) -> list[Block]:
        rows = self.conn().execute(
            "SELECT * FROM blocks WHERE screen_id = ? ORDER BY position, id",
            (screen_id,),
        ).fetchall()
        return [Block.from_row(r) for r in rows]

    def get_block(self, block_id: int) -> Block | None:
        r = self.conn().execute(
            "SELECT * FROM blocks WHERE id = ?", (block_id,)
        ).fetchone()
        return Block.from_row(r) if r else None

    def first_block_of_screen(self, screen_id: int) -> Block | None:
        r = self.conn().execute(
            "SELECT * FROM blocks WHERE screen_id = ? ORDER BY position, id LIMIT 1",
            (screen_id,),
        ).fetchone()
        return Block.from_row(r) if r else None

    def block_folder_names(self, screen_id: int, exclude_id: int | None = None) -> set[str]:
        rows = self.conn().execute(
            "SELECT id, folder_name FROM blocks WHERE screen_id = ?", (screen_id,)
        ).fetchall()
        return {r["folder_name"] for r in rows if r["id"] != exclude_id}

    def add_block(self, screen_id, name, description, folder_name) -> int:
        with self.conn() as c:
            pos = c.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM blocks WHERE screen_id = ?",
                (screen_id,),
            ).fetchone()["p"]
            cur = c.execute(
                "INSERT INTO blocks (screen_id, name, description, position, folder_name) "
                "VALUES (?, ?, ?, ?, ?)",
                (screen_id, name, description, pos, folder_name),
            )
            return cur.lastrowid

    def update_block(self, block_id, name, description, folder_name) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE blocks SET name = ?, description = ?, folder_name = ? WHERE id = ?",
                (name, description, folder_name, block_id),
            )

    def delete_block(self, block_id) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM blocks WHERE id = ?", (block_id,))

    def set_block_positions(self, screen_id, ordered_ids: list[int]) -> None:
        with self.conn() as c:
            for pos, bid in enumerate(ordered_ids):
                c.execute(
                    "UPDATE blocks SET position = ? WHERE id = ? AND screen_id = ?",
                    (pos, bid, screen_id),
                )

    def move_block(self, block_id, new_screen_id, new_folder_name) -> None:
        with self.conn() as c:
            pos = c.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM blocks WHERE screen_id = ?",
                (new_screen_id,),
            ).fetchone()["p"]
            c.execute(
                "UPDATE blocks SET screen_id = ?, position = ?, folder_name = ? WHERE id = ?",
                (new_screen_id, pos, new_folder_name, block_id),
            )

    # ----------------------------------------------------------------- robots
    def list_robots(self, block_id: int) -> list[Robot]:
        rows = self.conn().execute(
            "SELECT * FROM robots WHERE block_id = ? ORDER BY position, id",
            (block_id,),
        ).fetchall()
        return [Robot.from_row(r) for r in rows]

    def get_robot(self, robot_id: int) -> Robot | None:
        r = self.conn().execute(
            "SELECT * FROM robots WHERE id = ?", (robot_id,)
        ).fetchone()
        return Robot.from_row(r) if r else None

    def robot_folder_names(self, block_id: int, exclude_id: int | None = None) -> set[str]:
        rows = self.conn().execute(
            "SELECT id, folder_name FROM robots WHERE block_id = ?", (block_id,)
        ).fetchall()
        return {r["folder_name"] for r in rows if r["id"] != exclude_id}

    def add_robot(self, block_id, name, description, folder_name, size="large") -> int:
        with self.conn() as c:
            pos = c.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM robots WHERE block_id = ?",
                (block_id,),
            ).fetchone()["p"]
            cur = c.execute(
                "INSERT INTO robots (block_id, name, description, position, folder_name, size) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (block_id, name, description, pos, folder_name, size),
            )
            return cur.lastrowid

    def update_robot(self, robot_id, *, name=None, description=None,
                     folder_name=None, size=None, manifest_path=None) -> None:
        cur = self.get_robot(robot_id)
        if cur is None:
            return
        with self.conn() as c:
            c.execute(
                "UPDATE robots SET name = ?, description = ?, folder_name = ?, "
                "size = ?, manifest_path = ? WHERE id = ?",
                (
                    cur.name if name is None else name,
                    cur.description if description is None else description,
                    cur.folder_name if folder_name is None else folder_name,
                    cur.size if size is None else size,
                    cur.manifest_path if manifest_path is None else manifest_path,
                    robot_id,
                ),
            )

    def delete_robot(self, robot_id) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM robots WHERE id = ?", (robot_id,))

    def set_robot_positions(self, block_id, ordered_ids: list[int]) -> None:
        with self.conn() as c:
            for pos, rid in enumerate(ordered_ids):
                c.execute(
                    "UPDATE robots SET position = ? WHERE id = ? AND block_id = ?",
                    (pos, rid, block_id),
                )

    def move_robot(self, robot_id, new_block_id, new_folder_name) -> None:
        with self.conn() as c:
            pos = c.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM robots WHERE block_id = ?",
                (new_block_id,),
            ).fetchone()["p"]
            c.execute(
                "UPDATE robots SET block_id = ?, position = ?, folder_name = ? WHERE id = ?",
                (new_block_id, pos, new_folder_name, robot_id),
            )

    # ------------------------------------------------------------ pending_ops
    def add_pending(self, op_type, src_path, dst_path, error="") -> None:
        # Evita duplicar a mesma operação ainda pendente.
        existing = self.conn().execute(
            "SELECT id FROM pending_ops WHERE op_type = ? AND IFNULL(src_path,'') = ? "
            "AND IFNULL(dst_path,'') = ?",
            (op_type, src_path or "", dst_path or ""),
        ).fetchone()
        with self.conn() as c:
            if existing:
                c.execute(
                    "UPDATE pending_ops SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                    (error, existing["id"]),
                )
            else:
                c.execute(
                    "INSERT INTO pending_ops (op_type, src_path, dst_path, last_error, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (op_type, src_path, dst_path, error, datetime.now().isoformat(timespec="seconds")),
                )

    def list_pending(self) -> list[sqlite3.Row]:
        return self.conn().execute(
            "SELECT * FROM pending_ops ORDER BY id"
        ).fetchall()

    def count_pending(self) -> int:
        return self.conn().execute("SELECT COUNT(*) AS n FROM pending_ops").fetchone()["n"]

    def delete_pending(self, op_id) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM pending_ops WHERE id = ?", (op_id,))

    def bump_pending(self, op_id, error) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE pending_ops SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                (error, op_id),
            )
