"""Leva os dados baixados para dentro de uma planilha de indicador.

Baixar o arquivo é metade do trabalho: o dado só vira indicador quando entra na
planilha certa, na coluna certa, sem quebrar o que já está lá. Este módulo faz
essa metade, com as travas que a prática mostrou serem necessárias:

* **planilha aberta** — gravar com o arquivo aberto no Excel falha no meio do
  caminho. Aqui isso é detectado antes de tocar em qualquer coisa;
* **backup antes de escrever** — sempre, com retenção;
* **conferência de cabeçalho** — se o site mudar a ordem ou a quantidade de
  colunas exportadas, os dados entrariam embaralhados sem nenhum erro aparente
  (valor caindo em coluna de data). A conferência para antes disso;
* **redimensionamento da Tabela** — sem ele, linhas além do tamanho atual ficam
  fora da Tabela do Excel e as colunas calculadas não acompanham;
* **número em texto pt-BR** — o SAP e vários portais exportam valor como texto
  (`-1.506,61`). Gravado assim, ler o número passa a depender do formato
  regional do Windows: `VALUE()` só funciona num PC em português. Convertido
  para número, a célula funciona em qualquer idioma.

A escrita usa o Excel via COM porque é o único caminho que preserva fórmulas,
formatação e Tabelas do arquivo de destino. O import é preguiçoso: quem não usa
passo de planilha não precisa ter o pywin32 instalado.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as _time, timedelta
from pathlib import Path

# "-1.506,61" ou "559,33". A vírgula decimal é exigida de propósito: assim um
# código como "5.100" continua texto, que é o que ele é.
_NUMERO_BR = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d+$|^-?\d+,\d+$")

MINIMO_CABECALHO_PADRAO = 0.70


class ErroPlanilha(Exception):
    """Falha ao gravar na planilha, com mensagem pronta para a tela."""


# --------------------------------------------------------------------- modelo
@dataclass
class Transferencia:
    """Descreve um arquivo baixado indo para um pedaço de uma planilha."""

    arquivo: str = ""              # nome ou padrão do arquivo baixado (ex.: "Base*.xlsx")
    planilha: str = ""             # caminho completo do .xlsx de destino
    aba: str = ""
    tabela: str = ""               # nome da Tabela do Excel na aba ("" = não há)
    linha_inicial: int = 2         # primeira linha de dados no arquivo baixado
    colunas: int = 0               # quantas colunas copiar (0 = todas as lidas)
    linha_destino: int = 2
    coluna_destino: int = 1
    limpar_ate_col: int = 0        # última coluna a limpar (0 = só as gravadas)
    conferir_cabecalho: bool = True
    minimo_cabecalho: float = MINIMO_CABECALHO_PADRAO
    colunas_numero_br: list = field(default_factory=list)   # 1-based, no arquivo baixado
    backups: int = 10

    @classmethod
    def from_dict(cls, d: dict) -> "Transferencia":
        conhecidos = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (d or {}).items() if k in conhecidos})

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Resultado:
    ok: bool
    mensagem: str = ""
    linhas: int = 0
    colunas: int = 0
    backup: str = ""
    cabecalho_iguais: int = 0
    cabecalho_total: int = 0


# ------------------------------------------------------------------ conversão
def numero_br(valor):
    """'-1.506,61' -> -1506.61. Devolve o valor intacto se não for número pt-BR."""
    if not isinstance(valor, str):
        return valor
    t = valor.strip()
    if not _NUMERO_BR.match(t):
        return valor
    return float(t.replace(".", "").replace(",", "."))


def valor_para_excel(valor):
    """Converte o que a ponte COM recusa.

    `datetime.time` é o caso clássico: o Excel via COM levanta
    'Objects of type datetime.time can not be converted to a COM VARIANT'.
    """
    if valor is None or isinstance(valor, (str, int, float, bool, datetime)):
        return valor
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day)
    if isinstance(valor, _time):
        return valor.strftime("%H:%M:%S")
    if isinstance(valor, timedelta):
        return str(valor)
    return str(valor)


# Conectivos que não distinguem uma coluna de outra. "Nome fornecedor" e
# "Nome do fornecedor" são a mesma coluna escrita de dois jeitos.
_IRRELEVANTES = {"de", "do", "da", "dos", "das", "e", "o", "a", "os", "as",
                 "no", "na", "em", "of", "the"}


def normalizar(texto) -> str:
    return " ".join(str(texto or "").lower().replace(".", " ").split())


def _tokens(texto) -> set:
    return {p for p in normalizar(texto).split() if p not in _IRRELEVANTES}


def mesmo_rotulo(a, b) -> bool:
    """Dois rótulos designam a mesma coluna?

    A conferência existe para pegar coluna TROCADA DE LUGAR, não coluna
    renomeada. Por isso a comparação é permissiva quanto à escrita e rígida
    quanto à posição: o que reprova é a ordem mudar, não o texto.
    """
    na, nb = normalizar(a), normalizar(b)
    if not na and not nb:
        return True
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return ta == tb or ta <= tb or tb <= ta


# -------------------------------------------------------------------- guardas
def esta_aberta(caminho) -> bool:
    """True se a planilha estiver aberta no Excel (ou travada por outro processo).

    O Excel cria um arquivo de bloqueio `~$nome.xlsx` ao abrir. Checar só isso
    não basta (o arquivo sobra quando o Excel morre), então também tentamos
    abrir para escrita — que é o teste que realmente importa.
    """
    p = Path(caminho)
    if not p.exists():
        return False
    lock = p.with_name("~$" + p.name)
    try:
        with open(p, "r+b"):
            pass
    except OSError:
        return True
    return lock.exists()


def ler_base(caminho, linha_inicial: int = 2, colunas: int = 0):
    """Lê o arquivo baixado e devolve (cabecalho, linhas), sem abrir o Excel."""
    try:
        import openpyxl
    except ImportError as e:  # pragma: no cover - ambiente sem a dependência
        raise ErroPlanilha(
            "O openpyxl é necessário para ler o arquivo baixado. "
            "Instale com: pip install openpyxl"
        ) from e

    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        lc = max(1, linha_inicial - 1)
        cabecalho = next(ws.iter_rows(min_row=lc, max_row=lc, values_only=True), ())
        linhas = [tuple(valor_para_excel(v) for v in linha)
                  for linha in ws.iter_rows(min_row=linha_inicial, values_only=True)]
    finally:
        wb.close()

    # Descarta as linhas totalmente vazias do fim.
    while linhas and all(v is None or str(v).strip() == "" for v in linhas[-1]):
        linhas.pop()

    if colunas:
        linhas = ajustar_largura(linhas, colunas)
        cabecalho = tuple(cabecalho[:colunas])
    return cabecalho, linhas


def ajustar_largura(linhas: list, colunas: int) -> list:
    """Recorta ou completa cada linha para ter exatamente `colunas` valores."""
    return [tuple(l[:colunas]) + (None,) * max(0, colunas - len(l)) for l in linhas]


def converter_numeros_br(linhas: list, colunas: list) -> list:
    """Converte para número as colunas (1-based) que vieram como texto pt-BR."""
    if not colunas:
        return linhas
    idx = [int(c) - 1 for c in colunas]
    saida = []
    for linha in linhas:
        v = list(linha)
        for i in idx:
            if 0 <= i < len(v):
                v[i] = numero_br(v[i])
        saida.append(tuple(v))
    return saida


def comparar_cabecalho(cab_base, cab_destino) -> tuple:
    """Compara dois cabeçalhos posicionalmente.

    Devolve (iguais, total, divergentes). Aceita rótulos escritos de forma
    diferente ("Nome fornecedor" x "Nome do fornecedor"): o que não pode mudar é
    a ORDEM, porque a gravação é posicional.
    """
    total = max(len(cab_base), len(cab_destino))
    iguais, divergentes = 0, []
    for i in range(total):
        crua_b = cab_base[i] if i < len(cab_base) else ""
        crua_d = cab_destino[i] if i < len(cab_destino) else ""
        b, d = normalizar(crua_b), normalizar(crua_d)
        if mesmo_rotulo(crua_b, crua_d):
            iguais += 1
        else:
            divergentes.append(f"coluna {i + 1}: baixado='{b or '(vazia)'}' "
                               f"planilha='{d or '(vazia)'}'")
    return iguais, total, divergentes


def fazer_backup(caminho, pasta=None, manter: int = 10) -> str:
    """Copia a planilha antes de alterar e apaga as cópias mais antigas."""
    p = Path(caminho)
    destino = Path(pasta) if pasta else p.parent / "backup"
    destino.mkdir(parents=True, exist_ok=True)
    # Milissegundos no nome resolvem dois problemas de uma vez: duas
    # transferências para a MESMA planilha caem no mesmo segundo (uma
    # sobrescreveria a outra) e, com contador, a retenção liberava um nome que a
    # chamada seguinte reusava — fazendo o backup novo parecer o mais antigo e
    # ser apagado. Nome sempre crescente elimina os dois.
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    copia = destino / f"{p.stem} {marca}{p.suffix}"
    shutil.copy2(p, copia)

    if manter and manter > 0:
        # Ordena pelo NOME, nao pelo mtime: varias copias no mesmo segundo tem
        # mtime igual e a ordem por tempo fica indefinida, podendo apagar a mais
        # nova. O nome carrega data, hora e contador, entao e deterministico.
        antigas = sorted(destino.glob(f"{p.stem} *{p.suffix}"), key=lambda x: x.name)
        for velha in antigas[:-manter]:
            try:
                velha.unlink()
            except OSError:
                pass
    return str(copia)


def localizar_arquivo(pasta, padrao: str) -> str:
    """Acha o arquivo baixado mais recente que casa com o padrão."""
    if not padrao:
        return ""
    achados = sorted(Path(pasta).glob(padrao), key=lambda p: p.stat().st_mtime,
                     reverse=True)
    return str(achados[0]) if achados else ""


# --------------------------------------------------------------------- escrita
def _com(descricao, funcao, tentativas: int = 8, espera: float = 1.5):
    """Repete a chamada quando o Excel responde 'ocupado'.

    O Excel recusa comandos COM enquanto está com uma célula em edição ou um
    diálogo aberto ('Call was rejected by callee'). Tentar de novo resolve;
    desistir na primeira faz a etapa falhar sem motivo real.
    """
    ultimo = None
    for k in range(tentativas):
        try:
            return funcao()
        except Exception as e:  # noqa: BLE001 - erros COM não têm tipo estável
            ultimo = e
            texto = str(e).lower()
            ocupado = ("rejected by callee" in texto or "0x8001010a" in texto
                       or "busy" in texto)
            if not ocupado or k == tentativas - 1:
                break
            time.sleep(espera)
    raise ErroPlanilha(f"{descricao}: {ultimo}")


def gravar(transf: Transferencia, arquivo_baixado: str,
           pasta_backup=None, log=None) -> Resultado:
    """Grava o arquivo baixado no pedaço da planilha descrito por `transf`."""
    log = log or (lambda m: None)

    if not transf.planilha:
        raise ErroPlanilha("A transferência não informa a planilha de destino.")
    if not os.path.isfile(transf.planilha):
        raise ErroPlanilha(
            f"A planilha de destino não existe:\n  {transf.planilha}\n"
            "O robô não cria planilha do zero — gravar num arquivo novo faria os "
            "dados irem parar onde ninguém olha."
        )
    if not arquivo_baixado or not os.path.isfile(arquivo_baixado):
        raise ErroPlanilha("O arquivo baixado não foi encontrado para esta transferência.")

    if esta_aberta(transf.planilha):
        raise ErroPlanilha(
            f"A planilha está aberta no Excel:\n  {os.path.basename(transf.planilha)}\n"
            "Feche o arquivo e rode de novo. Gravar com ele aberto falha no meio."
        )

    log(f"lendo {os.path.basename(arquivo_baixado)}…")
    cabecalho, linhas = ler_base(arquivo_baixado, transf.linha_inicial, transf.colunas)
    if not linhas:
        return Resultado(True, "O arquivo baixado não tem linhas de dados.", 0, 0)
    linhas = converter_numeros_br(linhas, transf.colunas_numero_br)
    n_col = transf.colunas or len(linhas[0])
    linhas = ajustar_largura(linhas, n_col)
    log(f"{len(linhas)} linha(s) x {n_col} coluna(s)")

    try:
        import win32com.client as win32
    except ImportError as e:  # pragma: no cover - ambiente sem a dependência
        raise ErroPlanilha(
            "O pywin32 é necessário para gravar na planilha. "
            "Instale com: pip install pywin32"
        ) from e

    backup = fazer_backup(transf.planilha, pasta_backup, transf.backups)
    log(f"backup: {os.path.basename(backup)}")

    # DispatchEx: instância própria, para nunca encostar num Excel que o usuário
    # tenha aberto por conta.
    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    # Sem estes, um diálogo invisível (links, macro de abertura) trava a
    # instância e todas as chamadas seguintes passam a ser recusadas.
    for prop, valor in (("AskToUpdateLinks", False), ("EnableEvents", False),
                        ("ScreenUpdating", False)):
        try:
            setattr(excel, prop, valor)
        except Exception:  # noqa: BLE001 - propriedade opcional
            pass
    wb = None
    try:
        wb = _com("abrir a planilha",
                  lambda: excel.Workbooks.Open(os.path.abspath(transf.planilha),
                                               UpdateLinks=0))
        # Em somente leitura o Excel aceita as edições em memória e o Save()
        # não faz nada: a gravação "dá certo" sem gravar. Esse é exatamente o
        # tipo de falha silenciosa que o robô não pode ter.
        if bool(_com("checar somente leitura", lambda: wb.ReadOnly)):
            raise ErroPlanilha(
                "O Excel abriu a planilha em SOMENTE LEITURA:\n  "
                + os.path.basename(transf.planilha) + "\n"
                "Nada foi gravado. Causas comuns: o arquivo está aberto em outro "
                "lugar, está marcado como somente leitura, ou o Office está "
                "pedindo ativação. Resolva e rode de novo."
            )

        ws = _com(f"abrir a aba '{transf.aba}'", lambda: wb.Sheets(transf.aba))

        iguais = total = 0
        if transf.conferir_cabecalho:
            linha_cab = max(1, transf.linha_destino - 1)
            destino_cab = [
                _com("ler o cabeçalho",
                     lambda i=i: ws.Cells(linha_cab, transf.coluna_destino + i).Value)
                for i in range(n_col)
            ]
            iguais, total, divergentes = comparar_cabecalho(cabecalho, destino_cab)
            proporcao = iguais / total if total else 1.0
            log(f"cabeçalho: {iguais}/{total} colunas conferem ({proporcao * 100:.0f}%)")
            if proporcao < transf.minimo_cabecalho:
                raise ErroPlanilha(
                    f"O layout do arquivo baixado não corresponde ao da planilha "
                    f"({iguais} de {total} colunas conferem).\n  "
                    + "\n  ".join(divergentes[:8])
                    + (f"\n  … e mais {len(divergentes) - 8}"
                       if len(divergentes) > 8 else "")
                    + "\nGravar assim colocaria cada dado numa coluna errada."
                )

        ate_col = transf.limpar_ate_col or (transf.coluna_destino + n_col - 1)
        ultima = _com("medir a área usada", lambda: ws.UsedRange.Rows.Count) + 1
        if ultima >= transf.linha_destino:
            _com("limpar a área antiga", lambda: ws.Range(
                ws.Cells(transf.linha_destino, transf.coluna_destino),
                ws.Cells(ultima, ate_col)).ClearContents())

        if transf.tabela:
            # Sem redimensionar, as linhas além do tamanho atual ficam FORA da
            # Tabela e as colunas calculadas não acompanham.
            def redimensionar():
                lo = ws.ListObjects(transf.tabela)
                topo = lo.Range.Row
                lo.Resize(ws.Range(
                    ws.Cells(topo, lo.Range.Column),
                    ws.Cells(topo + len(linhas), lo.Range.Column
                             + lo.Range.Columns.Count - 1)))
            _com(f"redimensionar a tabela '{transf.tabela}'", redimensionar)

        _com("gravar os dados", lambda: setattr(
            ws.Range(ws.Cells(transf.linha_destino, transf.coluna_destino),
                     ws.Cells(transf.linha_destino + len(linhas) - 1,
                              transf.coluna_destino + n_col - 1)),
            "Value", [list(l) for l in linhas]))

        _com("salvar", wb.Save)
        if not bool(_com("confirmar o salvamento", lambda: wb.Saved)):
            raise ErroPlanilha(
                "O Excel aceitou os dados mas não confirmou o salvamento. "
                "A planilha foi deixada como estava; o backup está em:\n  "
                + backup)
        log(f"{os.path.basename(transf.planilha)} salvo")
        return Resultado(True, "", len(linhas), n_col, backup, iguais, total)
    finally:
        try:
            if wb is not None:
                _com("fechar", lambda: wb.Close(SaveChanges=False), tentativas=2)
        except Exception:  # noqa: BLE001
            pass
        try:
            excel.Quit()
        except Exception:  # noqa: BLE001
            pass


def gravar_todas(transferencias: list, pasta_downloads: str,
                 pasta_backup=None, log=None) -> list:
    """Executa as transferências de um robô. Uma falha não impede as outras."""
    log = log or (lambda m: None)
    resultados = []
    for t in transferencias:
        t = t if isinstance(t, Transferencia) else Transferencia.from_dict(t)
        alvo = (t.arquivo if os.path.isabs(t.arquivo)
                else localizar_arquivo(pasta_downloads, t.arquivo))
        rotulo = f"{os.path.basename(t.planilha)} / {t.aba}"
        log(f"planilha: {rotulo}")
        try:
            resultados.append(gravar(t, alvo, pasta_backup, log))
        except ErroPlanilha as e:
            log(f"ERRO em {rotulo}: {e}")
            resultados.append(Resultado(False, str(e)))
    return resultados
