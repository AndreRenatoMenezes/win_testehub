# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto adota o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Corrigido

- **Módulo 3 (Rede interna):** falhas de pré-requisito (navegador ou driver ausente) encerravam só a thread de trabalho, e o teste saía com código 0, registrando **PASS** sem medir nada. Agora elas resultam em **FAIL**, com o motivo no log.
- **Módulo 3 (Rede interna):** o teste dependia de Google Chrome e de um `chromedriver.exe` local, que não fazem parte do projeto, e mandava rodar o setup `7_install_google_chrome`, que não existe. Agora ele usa o Microsoft Edge, com o driver obtido pelo Selenium Manager, como o Módulo 3.1 e como já dizia a documentação.
- **Módulos 1 e 1.1 (CPU e Memória):** os dois testes gravavam na mesma pasta, então um sobrescrevia o `cpu_memoria.csv` e o `Resultados_Consolidados/` do outro, e a consolidação de quem rodasse por último misturava nas médias os CSVs exportados pelo outro teste. A variante 1.1 agora grava em `1_cpu_memo/dlp_usb/`, com o CSV temático `cpu_memoria_dlp.csv`.
- **Módulo 1.1 (CPU e Memória, DLP/USB):** a parada segura (`Ctrl+Q`) escapava do tratamento de erros: o teste registrava **PASS** e a captura WPR continuava gravando em segundo plano. Agora a interrupção resulta em **FAIL** e cancela o WPR, como nos demais módulos.
- `.gitignore`: os arquivos de carga das variantes DLP/USB (100 MB e 2 GB, criados na pasta do script) não podem mais ser versionados por engano.
- **Documentação:** o manual e a metodologia descreviam pastas, configurações e comportamentos antigos. Entre eles: `Logs/` e `Traces/` no lugar de `Execucoes/` e `Resultados/`, 9 scripts de setup em vez de 10, um `config.json` obsoleto, `_anterior/` no lugar errado, a tarefa agendada `BootShutdownTest` (o nome real é `HardwareTestHub_Reiniciador`), o plano de energia "alto desempenho" (o real é Equilibrado), a tecla `P` como se marcasse os testes que falharam e arquivos de evidência que os testes não geram. As versões HTML estavam ainda mais defasadas: não tinham os módulos 5 e 6 e descreviam o teste de rede com o Chrome.

### Adicionado

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
