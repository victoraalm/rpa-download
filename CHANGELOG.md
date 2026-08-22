# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.
O formato segue, de forma simplificada, o [Keep a Changelog](https://keepachangelog.com/pt-BR/)
e o versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [1.10.0] - 2026-08-21

### Adicionado (telemetria de fragilidade)

- O executor já tentava vários candidatos de seletor por passo, mas descartava
  qual deles funcionou. Agora registra o candidato vencedor (posição, tipo e
  valor), quantas tentativas gastou e quanto tempo levou.
- Tabelas `executions` e `step_runs` guardam o histórico por execução — antes
  cada execução esquecia tudo o que aprendeu e nada podia ser medido ao longo
  do tempo.
- `app/health.py` traduz esse histórico em aviso: um passo que vem caindo para
  a reserva em execuções seguidas já mudou de comportamento, mesmo continuando
  verde. Só sinaliza quando a degradação se repete na janela inteira — queda
  isolada costuma ser rede ou pop-up, e alarme falso ensina a ignorar o aviso.

### Adicionado (gravação em planilha)

- `app/spreadsheet.py`: leva o arquivo baixado para a planilha de destino, com
  detecção de planilha aberta, backup com retenção, conferência de cabeçalho,
  redimensionamento da Tabela do Excel e conversão de número em texto pt-BR
  (`-1.506,61`) para número de verdade.
- `RobotManifest.planilhas` descreve as transferências. Vazio (padrão) mantém o
  comportamento de sempre: o robô só baixa. Manifestos antigos carregam sem
  alteração.

### Corrigido

- O log por passo gravava sempre `selectors[0]`, mesmo quando quem funcionou
  era o terceiro candidato — ou seja, informava o seletor errado justamente nas
  execuções em que a informação importava.
- O `.venv` do repositório apontava para um Python que não existe nesta
  máquina; recriado com o 3.13.

### Notas

- Novas dependências: `openpyxl` e `pywin32`, ambas com import preguiçoso —
  quem não usa transferência para planilha não precisa delas.
- Em repositório dentro do OneDrive, o git exige
  `git config windows.appendAtomically false` (a sincronização quebra a escrita
  atômica do reflog).

## [1.9.2] - 2026-06-29

### Corrigido (login SSO sendo repetido)

- O robô falhava ao tentar **repetir o clique de login** (ex.: "SSO Ambev") quando a
  sessão já estava válida (já logado) — o botão não existia mais → timeout →
  `TargetClosedError`.
- **Reconhecimento de SSO ampliado**: além de Microsoft/Okta/ADFS, agora também
  **Keycloak/OpenID Connect** (`/realms/…/protocol/openid-connect/…`) e a **página
  de escolha de provedor** (realm chooser). O **gravador** deixa de gravar essas
  páginas e o **executor** as trata como login (sessão + login manual).
- **Rede de segurança**: se um clique que parece de login (ex.: "SSO …") falhar e a
  página **não** for de login (ou seja, já logado), o passo é **pulado** em vez de
  derrubar a execução.

> Recomendado **regravar** robôs de SSO uma vez, para o login sair dos passos.

## [1.9.1] - 2026-06-28

### Home, Lixeira e execução

- **Tela Home repensada**: deixa de ser "lixeira". Agora é a **tela padrão** (robôs
  sem uma tela definida ficam nela); robôs criados dentro de outra tela permanecem
  nela. Na instalação, **só a Home** é criada.
- **Lixeira separada (🗑)**: excluir um robô agora o move para a **Lixeira** (criada
  sob demanda). Excluir de novo **lá dentro** remove definitivamente. Dá para
  arrastar de volta. (Bancos antigos: o texto da Home é corrigido automaticamente.)
- **Interromper execução**: botão direito num robô em execução → **⏹ Interromper**.
- **Indicador visual**: o robô em execução aparece destacado com **▶**.
- Um robô **em execução** não pode ser excluído (peça para interromper antes).

## [1.9.0] - 2026-06-28

### Fórmulas (muito ampliadas)

- **Editor de fórmula** com **prévia do resultado ao vivo** (verde = ok / vermelho =
  erro) e **lista de funções pesquisável** (duplo-clique insere o exemplo). O botão
  **ƒ Fórmulas disponíveis** também ganhou **busca**.
- **Combinar fórmulas e aritmética** (já no motor): `TODAY()+1`, `(2+3)*4`,
  `ROUND(10/3; 2)`.
- Novas funções: **Números** (ROUND, ROUNDUP/DOWN, INT, TRUNC, ABS, MOD, POWER,
  SQRT, CEILING, FLOOR, MIN, MAX, SUM, AVERAGE); **Texto** (CONCAT, UPPER, LOWER,
  TRIM, LEFT, RIGHT, MID, LEN, ZEROPAD, SUBSTITUTE, VALUE); **Lógica** (IF, AND, OR,
  NOT e comparações `= <> < > <= >=`); **Datas** (WORKDAYS, SOMONTH, WEEKDAY,
  WEEKNUM, QUARTER, HOUR/MINUTE/SECOND).
- **Formato decimal** no `TEXT` (vírgula BR): `TEXT(1234.5; "#.##0,00")` → `1.234,50`.

### Revisão / telas

- Ao escolher o **tipo de campo**, abre a tela correspondente: **Manual** → config do
  campo; **Fórmula** → editor de fórmula.
- Nova opção de **download por robô**: **Acumular** (padrão) ou **Sobrescrever**.
- **Tela de revisão** e **tela de valores** não abrem mais maximizadas; larguras
  ajustadas para não cortar textos.

### Execução / uso

- **Duplo clique** num robô agora o **executa**.
- **Clique em itens de menu** mais robusto: rola até o elemento e passa o mouse
  (hover) antes de clicar — ajuda em submenus que abrem no hover.
- **Retenção de logs**: execuções com mais de **30 dias** (configurável) são apagadas
  automaticamente da pasta `runs/`.
- Botão de tema agora mostra apenas **"Modo claro" / "Modo escuro"**.

## [1.8.1] - 2026-06-28

### Adicionado (tela de Guia)

- Novo botão **📖 Guia** na barra superior abre um **passo a passo** de como usar o
  programa (instalar, gravar, revisar, executar, fórmulas, atualizar, etc.).
- O guia tem **fonte única** (`GUIA.md`): o mesmo arquivo é **renderizado no app**
  e fica visível **no GitHub** (linkado no README). Assim, basta editar um arquivo
  para atualizar os dois lugares conforme o programa evolui.

## [1.8.0] - 2026-06-28

### Alterado (distribuição em .zip / modo pasta)

- A distribuição passa a ser um **`.zip` (modo pasta)** em vez de um `.exe` único.
  **Ganhos:** abertura **muito mais rápida** (sem extrair ~85 MB a cada execução),
  **fim das sobras `_MEI*`** e **menos alarme de antivírus**. **Custo:** é preciso
  **extrair o `.zip`** antes de abrir o `RPA Download.exe` da pasta.
- **Auto-instalação adaptada**: na 1ª execução o programa copia a **pasta inteira**
  para `%LOCALAPPDATA%\Programs\RPA Download` e passa a rodar de lá.
- **Auto-update adaptado**: o botão **"🔄 Atualizar"** agora baixa o **`.zip`**,
  extrai e **substitui a pasta inteira** (esperando por PID, oculto), e reabre.
- A limpeza de sobras `_MEI*` agora varre também o `%TEMP%` (remove o que o antigo
  modo onefile possa ter deixado).

> ⚠️ **Transição:** instalações em `.exe` único (≤ 1.7.2) têm um atualizador que
> procura um `.exe`. **Baixe o `RPA-DOWNLOAD.zip` da 1.8.0 manualmente uma vez**;
> a partir dela o auto-update (.zip → .zip) funciona sozinho.

## [1.7.2] - 2026-06-28

### Corrigido (sobras de pasta temporária `_MEI*`)

- O executável (PyInstaller onefile) extrai-se numa pasta `_MEI*` em `%TEMP%` a cada
  execução e a **remove ao sair normalmente**; porém, se o processo for **morto ou
  travar** (ex.: o updater antigo travado, fechar pelo Gerenciador de Tarefas, ou
  cancelar no meio), a pasta ficava para trás ocupando espaço.
- Agora, ao iniciar, o programa **limpa as sobras `_MEI*` dele mesmo**, de forma
  segura: só remove as que têm o seu marcador e que **não estão em uso** (tenta
  renomear antes de apagar — uma pasta em uso não pode ser renomeada no Windows).
  Pastas de **outros** programas PyInstaller não são tocadas.

## [1.7.1] - 2026-06-28

### Corrigido (auto-atualizador travando)

- A atualização chegava a 100%, o app fechava e abria um **CMD vazio que travava**
  (e nada acontecia). Causa: o script de troca esperava o app fechar **pelo nome
  do processo** (`RPA Download.exe`); com a auto-instalação da 1.7.0 podia haver
  **mais de uma** instância, então a espera nunca terminava. Agora a troca:
  - espera **pelo PID** desta instância (não pelo nome) — com teto de tempo;
  - roda **oculta** via PowerShell (`-WindowStyle Hidden`), sem janela de console;
  - **copia com novas tentativas** (em vez de mover) para não perder o download.
- ⚠️ Como o atualizador antigo está embutido nas versões já instaladas, **baixe a
  1.7.1 manualmente uma vez**; a partir dela o botão **"🔄 Atualizar"** volta a
  funcionar sozinho.

### Alterado (telas em tela cheia)

- A **janela principal** abre **maximizada**.
- A **janela de valores** (preenchimento na hora de executar) abre **maximizada**.
- O **navegador de execução** já abria maximizado (`--start-maximized` +
  `no_viewport`).

## [1.7.0] - 2026-06-28

### Alterado (instalação como app profissional)

- **Não pede mais o caminho na 1ª execução.** O programa cria a pasta de dados
  automaticamente no melhor local, **sem admin** e **fora do OneDrive**:
  `%LOCALAPPDATA%\RPA Download` (banco, robôs, downloads, sessões), com o **ícone
  do programa** na pasta.
- **Auto-instalação do executável**: na 1ª execução o `.exe` se copia para
  `%LOCALAPPDATA%\Programs\RPA Download` e passa a rodar de lá (você pode apagar o
  `.exe` baixado). Isso também deixa o **auto-atualizador mais confiável** (pasta
  sempre gravável, ao contrário de Program Files).
- **Migração automática**: quem tinha os dados num caminho escolhido em versões
  anteriores tem o conteúdo **movido** para o novo local na primeira abertura.
- Nova variável `RPA_DATA_ROOT` para apontar a pasta de dados (usada em testes).

## [1.6.3] - 2026-06-28

### Adicionado

- **Licença proprietária** (`LICENSE`): todos os direitos reservados — sem
  concessão de uso, cópia, modificação, redistribuição ou engenharia reversa sem
  autorização prévia e por escrito do titular.
- Aviso de copyright (`LegalCopyright`) embutido nos metadados do `.exe` e seção
  **Licença** no README.

## [1.6.2] - 2026-06-28

### Alterado

- **Remoção de menções de marca**: nomes/descrições dos temas, metadados do
  executável e a documentação não fazem mais referência a empresas específicas.
  Os temas passam a ser descritos por cor (claro: azul/branco; escuro:
  preto/dourado). Sem mudança de comportamento.

## [1.6.1] - 2026-06-25

### Adicionado

- **Atalhos do Windows**: na primeira execução o programa cria um atalho na pasta
  **Documentos** e um no **Menu Iniciar** — este último torna o app
  **pesquisável** no Windows (digite "RPA Download" no menu Iniciar). O atalho do
  Menu Iniciar é recriado se faltar; o de Documentos respeita exclusão posterior.

## [1.6.0] - 2026-06-25

### Corrigido (gravação de cliques)

- **Cliques que mudam de página não se perdem mais**: são capturados no
  `pointerdown` (antes da navegação descarregar a página), com de-duplicação.
- **Detecção de página de login mais estrita** (somente provedores de identidade
  e caminhos específicos de SSO). Antes, rotas do app cujo caminho contivesse
  `login`/`sso`/`signin` eram tratadas como login, e o gravador/executor
  **ignorava cliques e ações reais** nessas páginas.

### Adicionado (modelo de revisão "o que fazer com cada passo")

- A revisão agora lista **cada passo** (clique/tecla/preencher/selecionar) com um
  **nome sugerido editável** e a opção **"O que fazer"**:
  - Clique/Tecla: **"Repetir (normal)"** ou **"Clicar se aparecer (opcional)"** —
    este último para **pop-ups/avaliações** que às vezes aparecem (na execução é
    **pulado sem erro** se não estiver presente).
  - Preencher/Selecionar: **"Fixo (repete o gravado)"**, "Fórmula" ou "Manual".
- O log `.csv` de execução passa a usar o **nome do passo**.

## [1.5.2] - 2026-06-25

### Corrigido (auto-atualizador)

- A troca do executável durante a atualização travava: o `.bat` era iniciado
  **sem console**, o que impedia a etapa de espera (`timeout`). Agora usa `ping`
  como pausa (não depende de console) e roda com **console oculto** — a
  substituição do `.exe` e o reinício funcionam de forma confiável.
- ⚠️ **Instalações v1.5.0/v1.5.1** já trazem a versão antiga (com falha) do
  atualizador embutido. **Baixe a v1.5.2 manualmente uma vez**; a partir dela, o
  botão **"🔄 Atualizar"** passa a funcionar sozinho.

## [1.5.1] - 2026-06-25

### Alterado

- **Migração do repositório para a conta `victoraalm`** (mesmo nome do repo). O
  atualizador automático passa a usar `victoraalm/rpa-download`. Instalações já
  distribuídas continuam se atualizando graças ao **redirecionamento** que o GitHub
  cria após a transferência.

## [1.5.0] - 2026-06-25

### Adicionado

- **Atualizador automático embutido**: o programa verifica a release mais recente
  no GitHub e instala com um clique (botão **"Atualizar"** na barra superior); ao
  iniciar, avisa se há versão nova. (Baixa o novo `.exe` e o substitui sozinho.)
- **Execução com navegador visível** (passo a passo) por padrão, com o interruptor
  **"👁 Navegador visível"** para rodar de forma invisível quando preferir.

### Alterado

- **Repositório tornado público**, habilitando o atualizador para qualquer usuário
  (sem necessidade de login no GitHub).
- No modo visível, o **login de SSO é feito na própria janela** da execução (não
  abre uma segunda janela).

## [1.4.2] - 2026-06-25

### Alterado (aparência / dimensionamento)

- **Nome do robô aparece completo**: a célula do ícone agora ajusta a altura para
  **quebrar o texto em várias linhas**; nomes muito longos limitam-se a algumas
  linhas e o **tooltip** mostra o nome inteiro. As células ficam alinhadas (altura
  uniforme pela maior).
- Ícones e células de robô redimensionados para melhor legibilidade.
- Título e descrição dos blocos passam a **quebrar em linhas** (não cortam mais).

## [1.4.1] - 2026-06-25

### Corrigido (robô não baixava o arquivo)

- O executor agora **escuta downloads globalmente** e salva **qualquer arquivo
  baixado** durante a execução (com timestamp + checagem de integridade), **sem
  depender de um "marcador"** após o clique. Aguarda relatórios que demoram a
  gerar no servidor.
- Cliques em **ícones/imagens/spans dentro de um botão ou link** agora capturam o
  **elemento clicável** (o botão), gerando seletores estáveis (ex.: `#btn-x` em vez
  de `#btn-x > img`) — corrige o clique de download que falhava por timeout.

> Para aproveitar a captura estável do botão, **regrave o robô** que estava
> falhando.

## [1.4.0] - 2026-06-25

### Adicionado

- **Lista de fórmulas** (botão "ƒ Fórmulas disponíveis") com descrição e exemplo.
- **Autocomplete de fórmulas** ao digitar no campo de fórmula.
- **Tipos de dado nos campos Manual**: ao marcar um campo como Manual, define-se o
  **nome** e o **tipo** (texto, inteiro, decimal, data, data/hora, sim/não, lista).
  No preenchimento, cada tipo abre o **widget adequado** (calendário para datas,
  número com dica "0", lista suspensa, etc.).
- Menu do robô (botão direito): **"Abrir pasta de downloads"**.

### Corrigido / Alterado (login SSO — análise dos logs)

- O robô **não automatiza mais o login**: páginas de login (Microsoft/SSO) não são
  gravadas nem repetidas na execução — o login é tratado por **sessão + fallback
  manual**.
- **Detecção de login ampliada**: por URL de SSO e por **campo de e-mail** (não só
  senha), corrigindo o Azure AD, que pede o e-mail primeiro.
- A heurística de seletor não descarta mais ids estáveis curtos (ex.: `i0116`).

> Recomendação: **regrave robôs de SSO uma vez** para o login sair dos passos.

## [1.3.0] - 2026-06-25

### Alterado

- **Renomeado para "RPA Download"**; a pasta de dados criada passa a se chamar
  **`RPA-DOWNLOAD`** (instalações novas; instalações existentes mantêm a pasta já
  configurada).

### Adicionado

- **Ícone próprio** do programa (janela, executável e **na pasta de dados** no
  Windows Explorer via desktop.ini).

### Mitigações de antivírus (falso positivo)

- Executável agora tem **metadados** (empresa/produto/versão), **ícone** e é
  compilado **sem UPX** — reduz a chance de o antivírus sinalizar.
- Observação: sem **assinatura digital (Authenticode)**, ainda pode haver alertas
  em alguns ambientes. Veja o README para como reportar falso positivo / liberar.

## [1.2.1] - 2026-06-25

### Corrigido

- **Painel de gravação** não é mais esticado/deformado pelo CSS do site: os
  estilos críticos (tamanho/posição) são aplicados com `!important` e reforçados
  periodicamente, mantendo o painel pequeno no canto inferior direito.
- **"Refazer caminho"** agora **descarta a sessão/cookies anteriores** daquele
  robô — o login (e similares) é refeito durante a nova gravação.

## [1.2.0] - 2026-06-25

### Adicionado

- **Log detalhado em CSV por execução** (`runs/run_<data>.csv`): uma linha por
  passo com data/hora, período, ação, campo, seletor, valor, **status** e **erro** —
  para analisar exatamente onde falhou. (separador `;`, abre no Excel BR)
- **"Redefinir campos"** no menu do robô (botão direito): altera **valor e tipo**
  (Fixo/Fórmula/Manual) dos campos capturados **sem regravar** o caminho.
- **Painel de gravação compacto** no canto inferior direito, mostrando em tempo
  real o **histórico de campos reconhecidos e valores**.

### Alterado / Corrigido

- O gravador agora reconhece **seletores de data e campos preenchidos via
  JavaScript** (captura por foco + saída do campo + snapshot ao concluir); antes
  esses campos podiam não ser reconhecidos.
- Todos os campos tocados viram campos editáveis (padrão **Fixo** = repete o valor).
- O navegador de gravação abre **maximizado e sem a margem cinza** (no_viewport).
- A execução tenta **digitar a data no campo** (fallback para campos readonly/JS).

## [1.1.1] - 2026-06-25

### Adicionado

- **Executável único (`.exe` onefile)** pronto para uso no release — basta baixar
  e abrir, sem extrair `.zip`. O `.zip` (modo pasta, abertura mais rápida)
  continua disponível como alternativa.
- `tools/build_app.py` agora também gera o `.exe` único (`build_onefile`).

## [1.1.0] - 2026-06-25

### Adicionado

- **Aplicativo standalone (`.exe`)**: o programa principal agora pode ser
  empacotado num executável que **não exige Python** no computador do usuário
  (distribuído como `.zip`, com `LEIAME.txt`). O navegador (Chromium) é baixado no
  primeiro uso.
- Scripts de build/validação: `tools/build_app.py`, `build_app.bat`,
  `tools/validate_app.py`.

### Alterado

- Subprocessos de execução/gravação agora funcionam no app congelado via um
  **despachante** no próprio executável (substitui `python -m ...`).
- `PLAYWRIGHT_BROWSERS_PATH` é fixado em um local estável; navegador baixado sob
  demanda também no app principal.

### Observações

- No app empacotado, a exportação de robô individual em `.exe` fica desabilitada
  (requer a versão por código, com PyInstaller).

## [1.0.0] - 2026-06-25

Primeira versão completa — todas as 5 fases implementadas e cobertas por testes.

### Adicionado

- **Fundação**
  - Estrutura visual (Telas → Blocos → Robôs) espelhada em pastas físicas no Windows.
  - Higienização de nomes inválidos e deduplicação automática.
  - Fila de retentativas para operações de pasta bloqueadas (arquivo em uso).
  - Dashboard em PySide6 com temas claro e escuro.
  - Drag-and-drop de Telas, Blocos e Robôs; Tela Home como destino pré-exclusão.
- **Gravação ("Aprender")**
  - Gravador baseado em Playwright (subprocesso) com mapeamento por DOM
    (seletores priorizados: id → data-* → name/aria → texto → CSS → XPath).
  - Sessão/login salvos criptografados (DPAPI do Windows).
  - Tipos de campo: Fixo, Fórmula e Manual.
  - Motor de fórmulas seguro (sem `eval`): `TODAY`, `WORKDAY` (feriados BR),
    `EOMONTH`, `EDATE`, `DATE`, `TEXT`, etc.
  - Revisão pós-gravação e fail-safe (não salva alterações se abandonado).
- **Execução**
  - Smart waits, auto-retry com backoff exponencial e evasão de pop-ups.
  - Fallback de seletor e fallback de login (sessão expirada → login manual).
  - Validação de integridade do download e nomeação `[timestamp] - [nome]`.
- **Limites do site**
  - Particionamento recursivo de datas até o site liberar o download.
- **Exportação**
  - Geração de `.exe` independente por robô (runner leve; baixa o navegador no
    primeiro uso).
- **Infra**
  - Suíte de testes automatizados (11 conjuntos) e documentação.

[1.0.0]: https://github.com/victoraalm/rpa-download/releases/tag/v1.0.0
