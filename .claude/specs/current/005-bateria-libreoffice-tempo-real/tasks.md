# Tasks — 005: Módulo 5 (Bateria v2.0 — LibreOffice + Tempo Real)

Contrato: [`spec.md`](spec.md) · Plano: [`plan.md`](plan.md).  
Lanes: `planejado → fazendo → revisão → pronto`.

---

## 📋 planejado

_(nenhuma WP planejada)_

---

## 🔨 fazendo

_(nenhuma WP em andamento)_

---

## 🔍 revisão

_(nenhuma WP em revisão)_

---

## ✅ pronto

### WP-01 — Módulo compartilhado `Testes/_lib/libreoffice_workload.py`
- **Arquivos:** `Testes/_lib/libreoffice_workload.py`
- **Entrega (Software Engineer, 2026-11-27):** `Testes/_lib/libreoffice_workload.py` (R2 byte-a-byte idêntica à do Módulo 1; `launch_app`/`wait_lo_idle`/`focus_window` com `check_stop_fn`/`sleep_fn`); `Test-GetScriptsOrder.ps1` verde.
- **Revisão (Review Agent, 2026-11-27):** Aprovada após ajuste em `launch_app` (`headless = (os.name != "nt") and (find_window_fn is None)`) para respeitar `find_window_fn` injetado fora do Windows.

### WP-02 — Refatoração do Módulo 5 (`5_teste_bateria.py` v2.0)
- **Arquivos:** `Testes/5_bateria/5_teste_bateria.py`
- **Entrega (Software Engineer, 2026-11-27):** v2.0 sem Edge/Google; item `LibreOffice` nas checagens rápidas; modo `Equilibrado`; fase ativa até 10% com WPR só na 1ª hora (`fim_wpr_escritorio`); `bateria_checkpoint.json` atômico; `hibernacao_inesperada`; `finalizar_medicao_rapido` → `aguardar_reconexao_para_pos_medicao` → `pos_medicao_pesada`; imports/DLLs seguros fora do Windows.
- **Revisão (Review Agent, 2026-11-27):** Aprovada após correções: `aguardar_reconexao_para_pos_medicao` pula exportação pesada em `Ctrl+Q`/`parada_segura` mesmo na tomada; `recuperar_app_se_fechou` protegido contra exceção no loop; `click_safe_content_area` antes do anti-bloat do Writer; `check_stop()` após `encerrar_wpr_primeira_hora`; checagem dinâmica de `FailSafeException`; `encerrar_fase_medida` fecha LibreOffice e coleta amostra final antes do `wpr -stop`; guarda `winreg is None` e eliminação de duplo `fsync` em `amostra_marco`. Falta validação em notebook real no lab.

### WP-03 — Integração no `hub.ps1` e atualização de `Test-Preflight.ps1`
- **Arquivos:** `hub.ps1`, `.github/scripts/Test-Preflight.ps1`
- **Entrega (Software Engineer, 2026-11-27):** `Get-PreflightFindings` cobre `5_teste_bateria.*`; sobras de `5_bateria` = wpr/wpaexporter/libreoffice (sem edge). `Test-Preflight.ps1`, `Test-ThematicCSVs.ps1` e `Test-GetScriptsOrder.ps1` com exit 0.
- **Revisão (Review Agent, 2026-11-27):** Aprovada sem ressalvas.

### WP-04 — Testes unitários Python (`test_bateria.py`) e CI
- **Arquivos:** `.github/scripts/test_bateria.py`, `.github/workflows/ci.yml`
- **Entrega (Software Engineer, 2026-11-27):** `test_bateria.py` + passo no job `python` do CI.
- **Revisão (Review Agent, 2026-11-27):** Aprovada após inclusão dos testes de `hwnd == 4242`, falha em `recuperar_app_se_fechou`, `FailSafeException`, ordem de `encerrar_fase_medida` e `Ctrl+Q`/`parada_segura` na tomada. Verde no Windows e em simulação de CI Linux.

### WP-05 — Documentação (`README.md`, metodologia, manual e HTMLs)
- **Arquivos:** `README.md`, `docs/metodologia-de-testes.md`, `docs/manual-de-execucao.md`, `docs/metodologia-de-testes.html`, `docs/manual-de-execucao.html`
- **Entrega (Software Engineer, 2026-11-27):** README, Seção 9 da metodologia (+ escopo e glossário), Seção 4.6 e troubleshooting do manual; HTMLs regerados.
- **Revisão (Review Agent, 2026-11-27):** Aprovada após ajuste de redação no `README.md` e atualização de `"seção Bateria"` → `"seção Escritório"` nos docs + regeneração dos HTMLs.
