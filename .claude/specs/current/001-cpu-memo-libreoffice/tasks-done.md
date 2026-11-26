# WPs concluídas — spec 001

### WP-01 — Módulo LibreOffice e testes Python
- Dono: Rex; revisão independente: Ahsoka, aprovada após correções.
- Commit: `de1c04da90968f148afd5fb6eda1b85e762d5d2c`.
- Evidência: suíte Python, reprodução independente pandas/stdlib e compileall passaram; execução real Windows, GUI, LibreOffice e WPR não exercitada.

### WP-02 — Setup e integração do hub
- Dono: Rex; revisão independente: Ahsoka, aprovada após correções.
- Commit: `f715790fec6e40dfc3a87a70ea8c0192b2e8c86b`.
- Evidência: Test-Preflight e parser passaram no PowerShell 7 macOS; taskkill, winget e Windows PowerShell 5.1 reais não exercitados.

### WP-03 — Documentação
- Dono: Rex; revisão independente: Ahsoka devolveu (metodologia 610, 624, 662, 1130: bateria citando a simulação do Módulo 1); correções conferidas e aprovadas por Claude Code (Review Agent) em 25/11/2026.
- Commit: `24cf2cec6645671f45f0509672cce75732086ba5`.
- Evidência: `python docs/gerar_html.py --check` → "HTML da documentação em sincronia com o Markdown." (exit 0); `compileall` ok; README (módulos, Setup 3, requisitos, sem `msedgedriver` do módulo 1), metodologia 3.2/4 e manual 2.2/3.3/4.9 conferidos contra a spec. Na mesma máquina (Windows 11, PowerShell 5.1), `Test-Preflight.ps1` e `test_cpu_memo_libreoffice.py` passaram. `ruff` não disponível localmente (fica com a CI).

### Validação real no lab (25/11/2026)
- Máquina: DESKTOP-N3AUVKT (Dell 5440, 10C/12T, 32 GB), Windows 11, LibreOffice 26.8.3 instalado pelo pacote winget do Setup 3, hub elevado, cenário `teste_libre`.
- Resultado: `1_automacao_performance.py` **PASS** em 1.852,6 s (5/5 ciclos, cooldown de 30 s); `.etl` + `CSV_*_RunN` por ciclo, `Resultados_Consolidados/`, `cpu_memoria.csv` e `ciclos_libreoffice.csv` gerados e exportados para `Exportar/teste_libre`; nenhum `soffice` do teste sobrou.
- Números (média dos 5 ciclos): cálculo/PDF 3,89 s (3,72–4,03), abertura do Writer 10,29 s, do Calc 11,80 s; 13 parágrafos e 26 linhas editados por ciclo; CPU do sistema 4,3% (pico 16%); LibreOffice 0,4% de CPU (pico 1,3%) e 566 MB de RAM (pico 598 MB). O WPA confirma a ordem de grandeza: `soffice.bin` com 0,67% do peso de CPU.
- Execução anterior (run 1) caiu com FAIL no ciclo 3 porque o operador mexeu na máquina (foco foi para o VS Code); o teste detectou, cancelou o WPR, fechou o LibreOffice e não deixou sobras — o caminho de falha também ficou validado.

### WP-04 — Planilha R2 e Etapa 1 com CPU do cálculo (26/11/2026)
- Dono: Claude Code (Engineer); revisão: Claude Code (Review Agent) — devolvida 1x (banner do log com "Versao 2.0" fixo), corrigida e aprovada.
- Evidência: `test_cpu_memo_libreoffice.py` passa (R2: abas, 100.000 fórmulas com texto exato, sem cache, `activeTab=2`, bytes idênticos; semente do perfil; `Sentinel`/erros; Etapa 1 reprova com Sentinel 0/ausente; CSVs 2.1); `ruff` E9/F63/F7/F82/F401/F811/F841 limpo; `compileall` ok. Etapa 1 real na DESKTOP-N3AUVKT (LibreOffice 26.8.3): geração 0,39 s, 5,8 s de relógio, **18,4 s de CPU**, `Sentinel.A2 = 996865,173`, só os 50 `#N/A` esperados em `f6`.
- Achado na implementação: os 50 `#N/A` de `f6` (`VLOOKUP(MOD(seq,100))` com chave 0) são da própria R2; critério da spec ajustado de "zero erros" para "só `f6 = 50`" (`R2_EXPECTED_ERRORS`).

### WP-06 — Documentação da revisão 2 (26/11/2026)
- Dono: Claude Code (Engineer); revisão: Claude Code (Review Agent), aprovada.
- Evidência: metodologia seção 4 (ferramenta, Etapas 1/3/4, métricas `CPU_Calculo_Formulas_*`, `Versao_Teste 2.1`, nota de não-comparabilidade 2.0 × 2.1) e README; `python docs/gerar_html.py --check` → em sincronia.


### WP-05 — Calc GUI sobre a R2 e validação real no lab (26/11/2026)
- Dono: Claude Code (Engineer); revisão: Claude Code (Review Agent); fechamento/validação: Antigravity.
- Correção aplicada antes da rodada final: rastreamento da árvore `soffice` via `_lo_tree_procs` (sem varrer `cmdline` de todos os processos nos laços cronometrados), corrigindo `CPU_Calculo_Formulas_s = 0,00` sob execução elevada (confirmado antes na sonda elevada: `8,48 s` relógio / `20,64 s` CPU) e reduzindo a latência de medição de abertura.
- Máquina: DESKTOP-N3AUVKT (Dell 5440, 10C/12T, 32 GB), Windows 11, LibreOffice 26.8.3, hub elevado, cenário `Teste_livre_v2` (RunId 2, `15:04:30`–`15:35:20`).
- Resultado: `1_automacao_performance.py` **PASS** em `1.851,6 s` (5/5 ciclos, cooldown `30,0 s`, zero warnings/erros no log, sem diálogos abertos, nenhum `soffice` sobrando); evidência em `Exportar/Teste_livre_v2/5440 - 045163/1_cpu_memo/`.
- Números (média dos 5 ciclos, `Versao_Teste = 2.1`):
  - Cálculo R2 (Etapa 1): `5,53 s` de relógio (`5,35–5,70 s`), **`17,87 s` de CPU** (`17,45–18,33 s`, critério `≥ 10 s`), `Sentinel.A2 = 996865.173` e `.ods` de `1.592.815 bytes` confirmados nos 5 ciclos.
  - Abertura: Writer `2,90 s` (máx `3,47 s`), Calc `4,92 s` (máx `5,00 s`, ocioso `1,5–2,0 s` após a janela).
  - Edição GUI: `24` linhas no Calc e `12` parágrafos no Writer em todos os 5 ciclos.
  - Recursos: CPU sistema `9,0%` (pico `96,8%`); LibreOffice `5,6%` de CPU (pico `97,1%`) e `606,3 MB` de RAM (pico `659,4 MB`).
- Regressão local: `test_cpu_memo_libreoffice.py`, `Test-Preflight.ps1`, `Test-ThematicCSVs.ps1`, `compileall` e `python docs/gerar_html.py --check` passando.
