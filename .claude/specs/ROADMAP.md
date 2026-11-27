# 🛣️ Roadmap

Mantido pelo Arquiteto. Cada spec aparece em exatamente uma seção; ideias de origem apontam para [`IDEIAS.md`](IDEIAS.md). A ordem de **Próximas** é decisão sua — o Arquiteto sugere, você confirma.

## 🚧 Em execução

| Spec | Ideias | Onde roda | Desde |
|---|---|---|---|
| [005 — Módulo 5 (Bateria v2.0): LibreOffice + tempo real de bateria](current/005-bateria-libreoffice-tempo-real/spec.md) | — | `feat/005-bateria-libreoffice-tempo-real` | 2026-11-27 |

## 🛣️ Próximas, em ordem

| # | Spec | Ideias | Depende de | Solução open source |
|---|---|---|---|---|
| 1 | [002 — Teste 0 de consumo basal (CPU e RAM em repouso)](mapeadas/002-teste-0-consumo-basal/spec.md) | #2 | — | Construir sobre stack existente (`psutil`, `pandas`, `pynput`) + WPT (`wpr.exe`/`wpaexporter.exe`) |

<!-- Com duas ou mais próximas dependentes entre si, o Arquiteto desenha aqui:
```mermaid
flowchart LR
  S004["004 · exportar PDF"] --> S006["006 · agendar envio"]
```
-->

## 🗺️ Mapeadas, sem prioridade

| Spec | Ideias | Em uma frase |
|---|---|---|

## ✅ Implementadas

| Spec | Ideias | Entrega | Data |
|---|---|---|---|
| [001 — Módulo 1 com workloads locais no LibreOffice](current/001-cpu-memo-libreoffice/spec.md) — revisão 2 (carga R2) | #1 | `feat/001-cpu-memo-libreoffice` | 2026-11-26 |
| [003 — Seções de testes no menu da Fase 2](archive/operacao/005-secoes-de-testes-no-menu/spec.md) | #3 | `feat/003-secoes-menu` | 2026-11-27 |
| [004 — Monitoramento ao vivo no terminal (TUI)](archive/operacao/006-monitoramento-ao-vivo/spec.md) | #4 | `feat/003-secoes-menu` | 2026-11-27 |

## 🗑️ Descartadas

| Ideia | Motivo | Data |
|---|---|---|
