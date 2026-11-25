# 🛣️ Roadmap

Mantido pelo Arquiteto. Cada spec aparece em exatamente uma seção; ideias de origem apontam para [`IDEIAS.md`](IDEIAS.md). A ordem de **Próximas** é decisão sua — o Arquiteto sugere, você confirma.

## 🚧 Em execução

| Spec | Ideias | Onde roda | Desde |
|---|---|---|---|
| [001 — Módulo 1 com workloads locais no LibreOffice](current/001-cpu-memo-libreoffice/spec.md) | #1 | Ground | 2026-11-25 |

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

## 🗑️ Descartadas

| Ideia | Motivo | Data |
|---|---|---|
