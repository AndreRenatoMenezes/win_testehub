# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto adota o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- **Reinício com retomada (Setup 10):** quando o WSL2 precisa de reinício, o Setup 10 sai com o código 3010 e o hub mostra `REINICIAR` (não mais FAIL) no console, no resumo e nos relatórios. O hub pergunta "Reiniciar agora? (S/N)": com S, grava a fila restante em `Traces/_retomar.json`, agenda a tarefa `WinTestHub-Retomar` (no logon, como administrador) e reinicia em 15 s; depois do logon o hub abre com `-Retomar`, remove a tarefa e roda a fila no mesmo cenário e no mesmo run. Na 3ª vez seguida que o mesmo setup pede reinício ele vira FAIL.
- **Teste de rede unificado (`3_teste_rede.py`):** o speedtest interno e o fast.com são medidos no mesmo teste, em rodadas intercaladas (10 de cada + 1 de aquecimento, configurável no bloco `Rede` do `config.json` ou com `HUB_REDE_RODADAS`). O resultado por fonte é a **mediana**, com P25, P75, CV % e `Estavel` (CV do download e do upload até 10%). Uma fonte fora do ar (URL não configurada, fast.com bloqueado, 3 falhas seguidas) vira **aviso**: o teste passa quando pelo menos uma fonte tem 8 ou mais rodadas válidas.
- **Menos variação na medição de rede:**
  - o interno espera o fim real do speedtest ("All done"), e não mais 60 s fixos;
  - o fast.com roda com duração e conexões fixas (20 s e 8, mínimo = máximo);
  - cada fonte usa um Edge com perfil temporário;
  - antes de cada rodada, o tráfego de fundo da interface é medido por 5 s, e acima de 1000 kbps a rodada fica fora da estatística (contaminada);
  - cada rodada registra cabo/Wi-Fi, o link e, no Wi-Fi, banda, canal, sinal e BSSID; o ping ICMP ao servidor interno é medido à parte.
  - Os avisos de fonte off/parcial, de medição instável, de Wi-Fi e de troca de AP vão para o `_relatorio`.
- **Setup 6:** também desliga o compartilhamento ponto a ponto do Delivery Optimization (`DODownloadMode = 0`), que gerava tráfego de atualizações em segundo plano.

- **Checagem antes da fila:** depois de escolher os testes, o hub confere só o que eles precisam e mostra no resumo pré-execução o que vai falhar (`[X]`: `.wpaProfile` dos módulos 1 e 5 ausente, `wpr`/`wpaexporter` fora do PATH, URL do speedtest não configurada, ferramenta de dev ausente ou abaixo da mínima do `cargas.json`, `podman machine` desligada, notebook na bateria nas cargas de dev) e o que pode comprometer a medição (`[!]`: bateria, sem internet, pouco disco, processo usando muita CPU). Com `[X]`, o `Enter` não inicia: `R` tira os testes afetados, `C` continua mesmo assim, `Esc` volta. A escolha fica no log, e cada teste tirado com `R` entra nos avisos da rodada com o motivo.
- **Sobras de teste:** a checagem aponta processos que testes anteriores deixaram abertos (sessão do WPR, Edge da automação, `wpaexporter`, `diskspd`, Python de `Testes\`, build servers do .NET, stack do módulo 10, `podman machine`) e `F` os encerra do jeito certo de cada um (`wpr -cancel`, `podman compose down -v`...). Os build servers do .NET aparecem só como aviso antes da fila (podem ser do Visual Studio). Entre um teste e outro, o hub encerra sozinho as sobras do teste que acabou, incluindo os build servers do teste 7, só entre os processos que o próprio teste abriu.
- **Avisos da rodada no `_relatorio.html`/`.json`:** checagem, sobras encerradas, módulo sem evidência na exportação, CSV temático faltando, carga de dev com status diferente de OK (com o motivo), carga sensível à rede e throttling. Os avisos ficam no `_state.json` e se acumulam entre runs.
- **Frequência da CPU por módulo:** `<módulo>/frequencia_cpu.csv` com uso, desempenho, MHz efetivo e temperatura ACPI a cada 5 s, resumido no `_relatorio` (MHz médio, início/fim sob carga, queda). Queda acima de 20% vira aviso de throttling. Configurável na seção `CpuSampler` do `config.json`; não roda nos setups nem no teste 5.
- **Setup 7 com plano B:** quando o winget não executa na conta (ex.: sessão elevada com outra conta) ou não resolve um item, o setup baixa o instalador oficial e só o executa com assinatura digital válida do fabricante (Git, .NET SDK, Go) ou com o SHA256 publicado no release (uv, docker-compose). A tabela final mostra status, via e versão de cada ferramenta, e o que faltar sai com o mesmo texto da checagem antes da fila. O PATH da máquina é alterado pelo registro, preservando `%SystemRoot%` e o tipo `REG_EXPAND_SZ`.
- Testes de regressão no CI: `Test-Preflight.ps1`, `Test-RunWarnings.ps1`, `Test-LiteralPath.ps1`, `Test-Setup7Verificacao.ps1` e `test_rede_estatistica.py` (este cobre também o reparo dos nomes de servidor do fast.com).

- **Pasta `Exportar/` pronta para o Drive:** ao fim de cada execução, o hub gera `Exportar/<cenário>/<modelo> - <patrimônio>/`, uma cópia de `Traces/` sem os arquivos `.etl` (200 a 400 MB cada), sem `.log`, sem pastas `logs/` e sem pastas vazias. `Traces/` não é alterada. O hub mostra quantos arquivos e MB foram exportados e quanto ficou de fora, e avisa quando um módulo some da exportação por ter só `.etl` e logs (ex.: `1_cpu_memo` sem o `.wpaProfile`). Isso substitui a limpeza manual antes de subir as evidências.
- **Modelo e patrimônio/serial na criação do cenário:** além do nome, o hub pergunta o modelo e o patrimônio da máquina, que ficam no `_state.json`, nomeiam a pasta de exportação e aparecem no `_relatorio.json`/`.html` e no `maquina.csv`. Cenários antigos perguntam os dois uma única vez.
- Teste de regressão da exportação (`Test-ExportTraces.ps1`) no CI.

- **Módulos 7 a 11 — cargas de desenvolvimento** (origem: homologação de notebooks para desenvolvimento): `7_dev_dotnet` (build limpo, incremental e testes de unidade), `8_dev_go` (`go build` e `go test`), `9_dev_python` (`pip install` e `pytest -n auto`), `10_dev_containers` (`podman build` multi-stage e stack SQL Server + RabbitMQ + Redis até `healthy`) e `11_dev_git_arquivos` (20 mil arquivos pequenos e `git clone --local` + `git status`). Só repositórios open source fixados por tag e imagens públicas; cargas internas opcionais no `workloads.local.json` (não versionado). Mediana de 3 execuções; **FAIL** se a carga quebrar, passar de 10x a referência do `referencia.json` (1ª execução contra a fria, demais contra a mediana; gerado com `--calibrar` no notebook de referência), faltar ferramenta ou a máquina estiver na bateria. Biblioteca comum em `Testes/_lib/dev_cargas.py`.
- Setups `7_install_devtools_dev` (Git, .NET SDK 10, Go, uv, docker-compose), `10_preparar_podman` (WSL2, Podman CLI e `podman machine` rootful) e `11_ca_corporativa_dev` (opcional; só age em rede com inspeção TLS).
- CSVs temáticos `dev_dotnet.csv`, `dev_go.csv`, `dev_python.csv`, `dev_containers.csv` e `dev_git_arquivos.csv`.
- Teste de regressão da ordem do menu (`Test-GetScriptsOrder.ps1`) no CI.
- Teste de regressão da parada da fila por Ctrl+Q (`Test-StopSignal.ps1`) no CI.

### Alterado

- **Incompatível — teste 3.1 removido:** o `Testes/3_rede_internet/3-1_teste_rede_internet.py` foi incorporado ao `3_teste_rede.py`. A pasta `3_rede_internet/` e o `rede_internet.csv` deixam de ser gerados. O `rede.csv` muda de formato (`Versao_Teste = 2.0`, blocos `Interno_*` e `Internet_*`, mediana no lugar da média como número principal) e o `resultado_afericoes.csv` passa a ter uma linha por rodada das duas fontes, com a coluna `Fonte`. Quem lê esses CSVs (ex.: `relatorio_lab`) precisa se adaptar. Cenários antigos continuam abrindo, com o 3.1 como histórico.
- **Checagem antes da fila no teste 3:** sem a URL interna ou sem internet passa a ser **Atenção** (a outra fonte é medida); só as duas juntas são **Impede**.
- **Fim da pasta `Resultados/`:** o hub não gera mais `Resultados/<cenário>/`. A chave `Paths.ResultadosDir` do `config.json` vira `Paths.ExportarDir` (um `config.json` antigo continua funcionando, com `Exportar` como padrão).
  - `maquina.csv` passa a ser gravado em `Traces/`, com o modelo e o patrimônio informados. Ele é o único lugar com fabricante, modelo e serial do equipamento.
  - `cenario.csv` deixa de existir: os mesmos dados estão em `_relatorio.csv`/`.json` e `_state.json`. A coluna "Exit Code" dele gravava o número da run por engano.
  - Os CSVs temáticos não são mais copiados: ficam em `Traces/<módulo>/` e seguem na exportação. A função `Copy-ThematicCSVs` vira `Test-ThematicCSVs`, que só avisa quando um teste rodou sem gerar o CSV; o contador "ausente" não inclui mais os testes não executados.
- **ZIP e opção `[E]`:** o ZIP compacta só a pasta exportada da máquina (`<modelo> - <patrimônio>.zip`, ao lado dela) e **não apaga mais** a pasta do cenário em `Execucoes/`. A opção `[E]` regera a exportação de um cenário existente e oferece o ZIP.
- **Nome do cenário:** caracteres inválidos em nome de pasta, além de `[` e `]`, são removidos do nome do cenário, do modelo e do patrimônio.

- **Janela flutuante das cargas dev:** o cronômetro agora anda em todas as fases. Fora da medição (preparo, setup, cleanup e download dos repositórios), ele aparece em amarelo com o nome da fase. Uma linha extra mostra a CPU da máquina e a última saída do comando, para o operador saber que o teste não travou. Antes, no preparo longo do A5c, a janela ficava parada com a carga anterior.
- **Ctrl+Q para a fila inteira:** nos testes com parada segura (1, 1.1, 2.1, 5 e 7 a 11), o Ctrl+Q agora interrompe o teste atual **e** os testes seguintes, que aparecem como *cancelado*. O relatório é gerado com o que já rodou. Antes, o hub seguia para o próximo teste. O hub também descarta as teclas apertadas durante um teste antes de perguntar "Deseja continuar?".
- **Menu do hub:** ordenação numérica natural dos scripts (`10_` depois de `9_`). Na Fase de Setup, `12_remover_appx_bloatware` e `13_remover_onedrive` passam a aparecer no fim da lista, e não mais antes do `1_`.

### Corrigido

- **Hub em pasta com `[` ou `]`:** o hub não encontrava os cenários, porque os colchetes viravam curinga. Todos os acessos a arquivo usam `-LiteralPath`, e a listagem de testes não depende mais de `-Include`.
- **Módulo 3.1 (fast.com):** o nome do servidor chegava como `S�o Jo�o de Meriti`. O acento já vem perdido da própria página do fast.com (o print da aferição mostra o mesmo), então o teste restaura os nomes de uma lista de cidades conhecidas, só quando o nome bate inteiro; fora da lista, o texto fica como veio.
- **Tracebacks `UnicodeEncodeError` no log do hub:** os testes 1, 1.1, 2.1, 3 e 3.1 escreviam no console em cp1252 caracteres que ele não representa. Agora o console troca esses caracteres em vez de derrubar a linha de log (como já faziam os testes 5 e 6).

- **Módulo 3 (Rede interna):** falhas de pré-requisito (navegador ou driver ausente) encerravam só a thread de trabalho, e o teste saía com código 0, registrando **PASS** sem medir nada. Agora elas resultam em **FAIL**, com o motivo no log.
- **Módulo 3 (Rede interna):** o teste dependia de Google Chrome e de um `chromedriver.exe` local, que não fazem parte do projeto, e mandava rodar o setup `7_install_google_chrome`, que não existe. Agora ele usa o Microsoft Edge, com o driver obtido pelo Selenium Manager, como o Módulo 3.1 e como já dizia a documentação.
- **Módulos 1 e 1.1 (CPU e Memória):** os dois testes gravavam na mesma pasta, então um sobrescrevia o `cpu_memoria.csv` e o `Resultados_Consolidados/` do outro, e a consolidação de quem rodasse por último misturava nas médias os CSVs exportados pelo outro teste. A variante 1.1 agora grava em `1_cpu_memo/dlp_usb/`, com o CSV temático `cpu_memoria_dlp.csv`.
- **Módulo 1.1 (CPU e Memória, DLP/USB):** a parada segura (`Ctrl+Q`) escapava do tratamento de erros: o teste registrava **PASS** e a captura WPR continuava gravando em segundo plano. Agora a interrupção resulta em **FAIL** e cancela o WPR, como nos demais módulos.
- `.gitignore`: os arquivos de carga das variantes DLP/USB (100 MB e 2 GB, criados na pasta do script) não podem mais ser versionados por engano.
- **Documentação:** o manual e a metodologia descreviam pastas, configurações e comportamentos antigos. Entre eles: `Logs/` e `Traces/` no lugar de `Execucoes/` e `Resultados/`, 9 scripts de setup em vez de 10, um `config.json` obsoleto, `_anterior/` no lugar errado, a tarefa agendada `BootShutdownTest` (o nome real é `HardwareTestHub_Reiniciador`), o plano de energia "alto desempenho" (o real é Equilibrado), a tecla `P` como se marcasse os testes que falharam e arquivos de evidência que os testes não geram. As versões HTML estavam ainda mais defasadas: não tinham os módulos 5 e 6 e descreviam o teste de rede com o Chrome.

### Adicionado

- **Identidade visual WinTestHub:** logo (janela com check), ícone, favicon e imagem de prévia do repositório em `docs/assets/brand/`. A marca entra no README, no banner do console, nos relatórios HTML do hub (`run_*.html` e `_relatorio.html`), na documentação HTML e nos painéis do Módulo 6. O título padrão dos relatórios passa a ser `WinTestHub - Relatorio Final`; a tarefa agendada `HardwareTestHub_Reiniciador` mantém o nome.
- Documentação das variantes DLP/USB (seções 4.8 e 5.7 da metodologia) e da opção `[E]` de exportação do menu.
- `docs/gerar_html.py`: gera os HTML da documentação a partir dos `.md`, com o visual original (`docs/assets/estilo.css`). O CI falha se os dois formatos divergirem.

- O hub copia para `Resultados/` os CSVs das variantes DLP/USB (`cpu_memoria_dlp.csv` e `disco_usb.csv`), quando elas são executadas.
- Teste de regressão da cópia de CSVs temáticos do hub, executado pelo CI no Windows PowerShell 5.1.

## [1.0.0] - 2026-11-06

Primeira versão publicada no GitHub.

### Adicionado

- Hub interativo (`hub.bat` + `hub.ps1`) com fase de preparação e fase de testes, menu de seleção múltipla, cenários persistentes, re-execução com preservação de evidências e relatórios HTML, CSV e JSON, por execução e consolidados por cenário.
- Exportação de cenário para ZIP com validação da contagem de arquivos.
- 10 scripts de preparação do ambiente em `Setup/environment`.
- Módulos de teste: CPU e Memória (e variante DLP/USB), Disco (e variante DLP/USB), Rede interna, Rede internet (fast.com), Boot e Shutdown, Bateria e Wi-Fi Fast Transition (802.11r).
- Documentação: manual de execução e metodologia de testes.
- Configuração do repositório: CI (sintaxe Python e PowerShell, PSScriptAnalyzer e bloqueio de conteúdo sensível), Dependabot, modelos de issue e de PR e CODEOWNERS.

### Alterado

- A URL do speedtest interno saiu do código. Agora ela vem de `config.local.json`, que não é versionado (modelo em `config.local.example.json`), ou da variável `HUB_SPEEDTEST_URL`.
- No Módulo 1, o `msedgedriver.exe` local passou a ser opcional: sem ele, o Selenium Manager obtém o driver compatível com o Edge instalado.

[Não lançado]: https://github.com/AndreRenatoMenezes/win_testehub/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/AndreRenatoMenezes/win_testehub/releases/tag/v1.0.0
