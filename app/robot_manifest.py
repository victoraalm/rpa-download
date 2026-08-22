"""Schema do robot.json — o manifesto portátil de cada robô.

Guarda os passos gravados (com candidatos de seletor priorizados), os tipos de
campo, a configuração de login/sessão e o questionário de limites do site.
É versionado para permitir migrações futuras.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

SCHEMA_VERSION = 1

# Tipos de campo de preenchimento.
FIELD_FIXED = "fixed"      # valor literal (ex.: 23/06/2026)
FIELD_FORMULA = "formula"  # fórmula dinâmica (ex.: WORKDAY(TODAY(); -1))
FIELD_MANUAL = "manual"    # solicitar informação a cada execução

# Tipos de dado (campos Manual) — definem o widget no preenchimento.
DT_TEXT = "text"
DT_INT = "int"
DT_DECIMAL = "decimal"
DT_DATE = "date"
DT_DATETIME = "datetime"
DT_BOOL = "bool"
DT_CHOICE = "choice"

# Ações de passo.
ACTION_GOTO = "goto"
ACTION_CLICK = "click"
ACTION_FILL = "fill"
ACTION_SELECT = "select"
ACTION_PRESS = "press"
ACTION_DOWNLOAD = "download"


@dataclass
class Selector:
    type: str   # css | xpath | id | text | role
    value: str

    @classmethod
    def from_dict(cls, d):
        return cls(type=d.get("type", "css"), value=d.get("value", ""))


@dataclass
class FieldConfig:
    type: str = FIELD_FIXED
    value: str = ""       # usado quando type == fixed
    formula: str = ""     # usado quando type == formula
    prompt: str = ""      # rótulo do pop-up quando type == manual
    fmt: str = "dd/mm/yyyy"  # formato de saída para datas
    data_type: str = DT_TEXT     # tipo de dado (campos manual): define o widget
    name: str = ""               # nome do campo (rótulo amigável)
    options: list = field(default_factory=list)  # opções (data_type == choice)

    @classmethod
    def from_dict(cls, d):
        if not d:
            return None
        return cls(
            type=d.get("type", FIELD_FIXED),
            value=d.get("value", ""),
            formula=d.get("formula", ""),
            prompt=d.get("prompt", ""),
            fmt=d.get("fmt", "dd/mm/yyyy"),
            data_type=d.get("data_type", DT_TEXT),
            name=d.get("name", ""),
            options=list(d.get("options", []) or []),
        )


@dataclass
class Step:
    action: str
    selectors: list[Selector] = field(default_factory=list)
    url: str = ""              # para goto
    value: str = ""           # valor bruto gravado (fill) ou tecla (press)
    tag: str = ""             # tag do elemento (contexto)
    label: str = ""           # rótulo/aria-label/placeholder (ajuda na revisão)
    field: FieldConfig | None = None  # só para fill/select
    description: str = ""
    name: str = ""            # nome amigável dado pelo usuário (organização/log)
    optional: bool = False    # passo opcional (ex.: clique em pop-up que às vezes aparece)

    @classmethod
    def from_dict(cls, d):
        return cls(
            action=d.get("action", ""),
            selectors=[Selector.from_dict(s) for s in d.get("selectors", [])],
            url=d.get("url", ""),
            value=d.get("value", ""),
            tag=d.get("tag", ""),
            label=d.get("label", ""),
            field=FieldConfig.from_dict(d.get("field")),
            description=d.get("description", ""),
            name=d.get("name", ""),
            optional=bool(d.get("optional", False)),
        )


@dataclass
class SiteLimit:
    enabled: bool = False
    max_rows: int = 0
    strategy: str = "date_partition"   # date_partition | pagination
    start_date_step: int = -1          # índice do passo que define a data inicial
    end_date_step: int = -1            # índice do passo que define a data final

    @classmethod
    def from_dict(cls, d):
        if not d:
            return cls()
        return cls(
            enabled=d.get("enabled", False),
            max_rows=d.get("max_rows", 0),
            strategy=d.get("strategy", "date_partition"),
            start_date_step=d.get("start_date_step", -1),
            end_date_step=d.get("end_date_step", -1),
        )


@dataclass
class RobotManifest:
    name: str
    schema_version: int = SCHEMA_VERSION
    created_at: str = ""
    start_url: str = ""
    has_login: bool = False
    session_file: str = ""            # nome do arquivo de sessão criptografada
    download_mode: str = "accumulate"  # accumulate (data/hora no nome) | overwrite
    site_limit: SiteLimit = field(default_factory=SiteLimit)
    steps: list[Step] = field(default_factory=list)
    # Transferências para planilha, executadas DEPOIS que os downloads saem.
    # Lista vazia = robô só baixa, que é o comportamento de sempre.
    planilhas: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d.get("name", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            created_at=d.get("created_at", ""),
            start_url=d.get("start_url", ""),
            has_login=d.get("has_login", False),
            session_file=d.get("session_file", ""),
            download_mode=d.get("download_mode", "accumulate"),
            site_limit=SiteLimit.from_dict(d.get("site_limit")),
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            planilhas=list(d.get("planilhas") or []),
        )

    def save(self, path: str) -> None:
        if not self.created_at:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "RobotManifest":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
