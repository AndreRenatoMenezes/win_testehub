# Spec 001 — WPs

Contrato: `spec.md`; plano: `plan.md`. Somente o Maestro atualiza lanes.

### WP-03 — Documentação
- Lane: revisão ⚠ Rex atingiu cota ao enviar relatório; revisão inclui validação das correções no disco.
- Dono: Rex
- Possui: `README.md`, `docs/metodologia-de-testes.md`, `docs/manual-de-execucao.md`, `docs/metodologia-de-testes.html`, `docs/manual-de-execucao.html`.
- Fora de escopo: código, Setup e hub.
- Objetivo: atualizar documentação e HTMLs para o comportamento da spec.
- Aceite: documentação reflete a spec e `python docs/gerar_html.py --check` passa.
- Evidência: saída real do gerador/check e arquivos alterados.
- Plano: seção 2.4; depende de: nenhuma; execução sequencial por disponibilidade de executor.
