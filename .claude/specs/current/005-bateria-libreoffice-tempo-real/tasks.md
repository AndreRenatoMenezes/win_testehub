# Tasks — 005: Módulo 5 (Bateria v2.0 — LibreOffice + Tempo Real)

Contrato: [`spec.md`](spec.md) · Plano: [`plan.md`](plan.md).  
Lanes: `planejado → fazendo → revisão → pronto`.

---

## 📋 planejado

### WP-01 — Módulo compartilhado `Testes/_lib/libreoffice_workload.py`
- **Arquivos:** `Testes/_lib/libreoffice_workload.py`
- **Depende de:** —
- **Escopo:**
  - Extrair de forma limpa e testável (sem alterar `1_automacao_performance.py`) as rotinas de descoberta do LibreOffice (`find_libreoffice_executable`), URI de perfil (`build_user_installation_uri`), seed de registro (`seed_lo_profile`), geração determinística de `workload_doc.odt` e planilha R2 `workload_calc_r2.xlsx` (`generate_odt_fixture`, `generate_r2_xlsx`, `generate_odf_fixtures`), rastreamento/encerramento isolado por `wintesthub_lo_profile` (`is_test_libreoffice_proc`, `lo_tree_procs`, `kill_test_libreoffice`) e controle de janelas Win32 (`launch_app`, `wait_lo_idle`, `focus_window`, `verify_window_focused`, `is_window_alive`).
  - Aceitar `check_stop_fn` e `sleep_fn` injetáveis para interrompibilidade em ≤ 0,5 s no Módulo 5 e testabilidade headless no CI Linux/Windows.
- **Critério de pronto:** Módulo importável no Windows e Linux, fora do menu do `hub.ps1` (`Test-GetScriptsOrder.ps1` verde), `ruff` e `compileall` limpos.

### WP-02 — Refatoração do Módulo 5 (`5_teste_bateria.py` v2.0)
- **Arquivos:** `Testes/5_bateria/5_teste_bateria.py`
- **Depende de:** WP-01
- **Escopo:**
  - Elevar `VERSAO_TESTE = "2.0"`, definir `PROTECAO_BATERIA_PCT = 10`, `DURACAO_WPR_ESCRITORIO_S = 60 * 60`, `MODO_ENERGIA_ALVO = MODO_EQUILIBRADO`, `INTERVALO_RECALC_CALC_S = 5 * 60`, `WRITER_MAX_PARAGRAFOS = 60`.
  - Remover toda a lógica legada de Edge/Google Docs/Sheets/PDF e adicionar checagem de LibreOffice no pré-voo mantendo rede com internet e carga ≥ 95%.
  - Trocar padronização do modo de energia na bateria, conferência efetiva e detecção de desvios de `Melhor desempenho` para `Equilibrado`.
  - Implementar fase ativa contínua no LibreOffice (Writer + Calc R2 em ritmo realista, recálculo completo a cada ~5 min, anti-bloat no Writer a cada 60 parágrafos, recuperação de foco/app caído) sem teto de tempo até 10%, encerrando e salvando o trace WPR na marca de 60 min ativos (`fim_wpr_escritorio`) e continuando a descarga sem WPR.
  - Implementar checkpoint contínuo atômico (`bateria_checkpoint.json`), detector de hibernação inesperada (`hibernacao_inesperada`) e progresso/overlay para fase ativa de duração aberta.
  - Reordenar encerramento ao atingir 10%: encerramento rápido (~15 s) gravando `batteryreport depois`, `bateria.csv` e executando `restaurar_tudo()` + `manter_tela_ligada(False)` **antes** do diálogo de reconexão do carregador que dispara `wpaexporter`, `srumutil` e `powercfg /energy` (com opções *"Continuar na bateria"* e *"Pular exportação e finalizar"*).
  - Implementar `calcular_metricas_globais()`, novas métricas de tempo real e normalização `100%→0%` no `bateria.csv`, e atualizar `decidir_exit_code()` (PASS sem mínimo de 30 min na ativa, exigindo ociosa completa + ativa iniciada + `protecao_bateria`).
  - Tornar imports Windows-only seguros para importação em testes unitários no CI Linux.
- **Critério de pronto:** Sintaxe e lint limpos, zero referências residuais a Edge/Google no script, fluxo completo aderente à `spec.md`.

### WP-03 — Integração no `hub.ps1` e atualização de `Test-Preflight.ps1`
- **Arquivos:** `hub.ps1`, `.github/scripts/Test-Preflight.ps1`
- **Depende de:** —
- **Escopo:**
  - Em `Get-PreflightFindings` (`hub.ps1`): validar `Test-LibreOfficeAvailable` também quando `5_teste_bateria.*` estiver selecionado na fila (`Impede` orientando `Setup 3_softwares_msStore`).
  - Em `Get-TestLeftovers` (`hub.ps1`): incluir `"5_bateria"` em `wpr`, `wpaexporter` e `libreoffice`; remover `"5_bateria"` de `edge`.
  - Atualizar `.github/scripts/Test-Preflight.ps1` para cobrir o bloqueio `Impede` sem LibreOffice no Módulo 5 e as novas sobras esperadas para `5_bateria`.
- **Critério de pronto:** `Test-Preflight.ps1`, `Test-ThematicCSVs.ps1` e `Test-GetScriptsOrder.ps1` passando com exit code `0`.

### WP-04 — Testes unitários Python (`test_bateria.py`) e CI
- **Arquivos:** `.github/scripts/test_bateria.py`, `.github/workflows/ci.yml`
- **Depende de:** WP-01, WP-02
- **Escopo:**
  - Criar `.github/scripts/test_bateria.py` cobrindo `libreoffice_workload.py`, cálculos de métricas de fase e globais (tempo real + normalizado 100%→0% + fallback por `%` + taxa da 1ª hora), `decidir_exit_code()` (incluindo bateria desgastada < 30 min), `linhas_bateria_csv()` (schema v2.0), checkpoint atômico, detector de hibernação e garantia de ordem de encerramento (`bateria.csv` + `restaurar_tudo()` antes da pós-medição pesada).
  - Registrar `test_bateria.py` no job `python` do `.github/workflows/ci.yml`.
- **Critério de pronto:** `test_bateria.py` e `test_cpu_memo_libreoffice.py` passando com exit code `0`; `ruff check` e `python -m compileall Testes/ docs/` verdes.

### WP-05 — Documentação (`README.md`, metodologia, manual e HTMLs)
- **Arquivos:** `README.md`, `docs/metodologia-de-testes.md`, `docs/manual-de-execucao.md`, `docs/metodologia-de-testes.html`, `docs/manual-de-execucao.html`
- **Depende de:** WP-02, WP-03
- **Escopo:**
  - Atualizar requisitos do Módulo 5 no `README.md` (LibreOffice em vez de Edge/Google).
  - Atualizar Seção 9 de `docs/metodologia-de-testes.md` para v2.0 (LibreOffice Writer + Calc R2, modo Equilibrado, descarga real até 10%, WPR na 1ª hora, novas métricas de tempo real e normalização 100%→0%, encerramento seguro, novo critério PASS/FAIL e incompatibilidade com v1.0).
  - Atualizar Seção 4.6 de `docs/manual-de-execucao.md` com o passo a passo atualizado do operador (sem login Google, duração variável até 10%, diálogo de reconexão para exportação WPA/SRUM).
  - Regerar os HTMLs com `python docs/gerar_html.py` e verificar com `python docs/gerar_html.py --check`.
- **Critério de pronto:** `python docs/gerar_html.py --check` retorna exit code `0` e docs refletem fielmente a v2.0.

---

## 🔨 fazendo

_(nenhuma WP em andamento)_

---

## 🔍 revisão

_(nenhuma WP em revisão)_

---

## ✅ pronto

_(nenhuma WP concluída ainda)_
