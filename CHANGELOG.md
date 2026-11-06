# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto adota o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

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
