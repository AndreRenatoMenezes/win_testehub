# 💡 Ideias

Teve uma ideia? Escreva aqui antes de esquecer: **uma por item, numerada, do jeito que vier.** Não precisa estar clara nem completa — tirar a dúvida é o trabalho da descoberta.

Quando quiser transformar as ideias em spec, rode `/sdd-maestri:descobrir` (ou `/sdd-maestri:descobrir 2 5` para só algumas). O Arquiteto lê esta lista, debate o que está em aberto com você, pesquisa se já existe solução open source e escreve a spec.

> **Como ler o status.** Item sem `⟶` é ideia nova. Tudo depois de `⟶` é escrito pelo Arquiteto — o seu texto ele nunca muda, reordena nem renumera.
>
> 🗺️ mapeada (spec escrita) · 🛣️ no roadmap · 🚧 em execução · ✅ implementada · 🗑️ descartada
>
> Roadmap completo: [`ROADMAP.md`](ROADMAP.md)

1. Subistituir o teste 1 cpu e memoria, para workloads usando o libre office, a ideia é não precisar mais fazer login no google para usar a suite deles, tornar os teste 100% atumático, e medindo tempo para abertura dos apps, consumo de CPU e RAM durante a execução e performance para calculos de formulas muito complexas. Acho que isso pode acabar ajudadando os analista verem se os agentes de segurança estão inpactando o fluxo de trabalho de escritório. ⟶ 🚧 [001](current/001-cpu-memo-libreoffice/spec.md)

2. Criar teste 0 para medir o consumo basal de CPU e RAM da máquina sem nehum app ou teste rodando. Objetivo é verificar o quando a máquina consome parada e quando colocado os agente de segurança o quanto consome parado. ⟶ 🛣️ #1 · [002](mapeadas/002-teste-0-consumo-basal/spec.md)

3. Criar uma secção de testes, como escritório com os teste de 0 a 5, Dev com teste de 7 a 11, e opcional com os teste 1.1, 2.2 e 6. Deixe somente pre selecionado os teste de escritório. ⟶ ✅ [003](archive/operacao/005-secoes-de-testes-no-menu/spec.md)

4. Monitoramento aovivo, semelhante ao que faço no projeto EVL (https://github.com/AndreRenatoMenezes/ELV) quem tem um monitoramento aovivo durante a execução dos teste. ⟶ ✅ [004](archive/operacao/006-monitoramento-ao-vivo/spec.md)
