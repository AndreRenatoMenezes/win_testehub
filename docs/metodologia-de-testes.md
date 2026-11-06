# Metodologia de Testes — Hardware Test Hub

**Versão:** 1.0  
**Data:** 2026-04-15  
**Público-alvo:** Equipe técnica, gestores, auditoria

---

## Sumário

1. [Introdução](#1-introdução)
2. [Arquitetura do Framework](#2-arquitetura-do-framework)
3. [Fase de Setup — Preparação do Ambiente](#3-fase-de-setup--preparação-do-ambiente)
4. [Módulo 1 — CPU e Memória](#4-módulo-1--cpu-e-memória)
5. [Módulo 2 — Disco](#5-módulo-2--disco)
6. [Módulo 3 — Rede](#6-módulo-3--rede)
7. [Módulo 4 — Boot e Shutdown](#7-módulo-4--boot-e-shutdown)
8. [Módulo 5 — Bateria](#8-módulo-5--bateria)
9. [Módulo 6 — Wi-Fi Fast Transition (802.11r)](#9-módulo-6--wi-fi-fast-transition-80211r)
10. [Rastreabilidade e Evidências](#10-rastreabilidade-e-evidências)
11. [Formatos de Relatório](#11-formatos-de-relatório)
12. [Glossário](#12-glossário)

---

## 1. Introdução

### 1.1 Objetivo

O **Hardware Test Hub** é um framework de validação de hardware projetado para avaliar o desempenho e a estabilidade dos principais componentes de uma máquina Windows: processador, memória, disco, rede, ciclo de boot/shutdown, consumo de bateria e roaming Wi-Fi com Fast Transition (802.11r). Os testes simulam cenários de uso intensivo e coletam métricas objetivas para determinar se o equipamento atende aos padrões operacionais esperados.

### 1.2 Escopo

**O que é testado:**
- Desempenho de CPU e memória sob estresse sustentado
- Velocidade de leitura e escrita do disco principal
- Velocidade de conexão de rede (download, upload, latência, jitter)
- Tempo de inicialização (boot) e desligamento (shutdown) do Windows
- Consumo de energia na bateria (máquina ociosa e sob carga de escritório) e autonomia projetada
- Roaming Wi-Fi entre APs com Fast Transition (802.11r) e compatibilidade de adaptador, driver e BIOS

**O que NÃO é testado:**
- Periféricos (teclado, mouse, webcam, impressora)
- GPU / desempenho gráfico
- Saúde da bateria, ciclos de carga e descarga completa (a saúde é registrada pelo setup `1_captura_infos_pc`)
- Conformidade de software (licenciamento, versões)

### 1.3 Como Usar Este Documento para Auditoria `[Gestão]`

Este documento descreve o **procedimento padronizado** de cada teste. Para auditar uma execução:

1. Identifique o **cenário** em `Traces/` (pasta com nome, hostname e data)
2. Abra o `_relatorio.html` para ver o resumo de resultados
3. Compare os procedimentos descritos neste documento com as evidências coletadas
4. Verifique a cadeia de custódia usando o `_state.json` (seção 10)

---

## 2. Arquitetura do Framework

### 2.1 Fluxo de Execução

O hub opera em **duas fases sequenciais**:

```
┌─────────────────────────────────────────────────────┐
│                    hub.bat                           │
│              (elevação UAC → Admin)                  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                    hub.ps1                           │
│              (orquestrador principal)                │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌─── Fase 1: Setup ────────────────────────────┐   │
│  │ Preparação do ambiente (9 scripts)           │   │
│  │ Pode ser ignorada via config.json            │   │
│  └──────────────────────────────────────────────┘   │
│                       │                             │
│                       ▼                             │
│  ┌─── Fase 2: Testes ───────────────────────────┐   │
│  │ Módulos de teste (5 categorias)              │   │
│  │ Seleção via menu checkbox interativo         │   │
│  └──────────────────────────────────────────────┘   │
│                       │                             │
│                       ▼                             │
│  ┌─── Saídas ───────────────────────────────────┐   │
│  │ Logs/  → resultados por run                  │   │
│  │ Traces/→ evidências por cenário              │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

> ![Diagrama de Arquitetura](img/placeholder-diagrama-arquitetura.png)  
> *Insira aqui: diagrama visual do fluxo de execução do framework*

### 2.2 Sistema de Cenários

Cada sessão de testes pertence a um **cenário** — uma unidade lógica que agrupa execuções (runs) e suas evidências. Cenários permitem:

- Testar uma máquina ao longo de vários dias
- Re-executar testes falhos sem perder evidências anteriores
- Gerar relatórios consolidados de todo o ciclo de validação

O cenário é identificado pelo formato: `{NomeDoCenario}_{Hostname}_{Data}`

### 2.3 Contrato de Exit Codes `[Técnico]`

O orquestrador (`hub.ps1`) determina o resultado de cada teste com base no **exit code** do processo:

| Exit Code | Status | Regra |
|-----------|--------|-------|
| `0` | **PASS** | O teste concluiu com sucesso e todas as verificações passaram |
| `≠ 0` | **FAIL** | O teste encontrou uma falha, erro ou não completou corretamente |

Todos os scripts de teste são obrigados a retornar exit codes explícitos:
- **Python:** `sys.exit(0)` para sucesso, `sys.exit(1)` para falha
- **PowerShell:** `exit 0` para sucesso, `exit 1` para falha

### 2.4 Variáveis de Ambiente Injetadas `[Técnico]`

O hub injeta variáveis de ambiente antes de executar cada teste, definindo onde salvar evidências:

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `HUB_EVIDENCE_DIR` | Pasta de evidências para o teste atual | `Traces/Cenario_PC01_2026-04-15/2_disco/` |
| `HUB_TRACE_DIR` | Idêntica a `HUB_EVIDENCE_DIR` | (mesmo acima) |
| `HUB_TRACE_ROOT` | Pasta raiz do cenário | `Traces/Cenario_PC01_2026-04-15/` |

Os testes **nunca devem salvar arquivos na pasta raiz do projeto**. Toda evidência deve ser direcionada para `HUB_EVIDENCE_DIR`.

---

## 3. Fase de Setup — Preparação do Ambiente

### 3.1 Objetivo

Padronizar a configuração da máquina de teste antes da execução dos módulos de diagnóstico. Isso garante que todos os equipamentos são testados em condições equivalentes, eliminando variáveis de configuração que poderiam influenciar os resultados.

### 3.2 Scripts de Preparação

| # | Script | Descrição | Justificativa |
|---|--------|-----------|---------------|
| 1 | `captura_infos_pc` | Coleta informações do sistema (CPU, RAM, disco, bateria, SO) em CSV | Registro de identidade da máquina para rastreabilidade |
| 2 | `opcoes_energia` | Configura plano de energia para alto desempenho | Evita throttling de CPU e suspensão durante testes |
| 3 | `softwares_msStore` | Instala aplicativos da Microsoft Store | Garante ferramentas auxiliares necessárias |
| 4 | `install_python` | Instala o runtime Python 3 | Pré-requisito para os scripts de teste em Python |
| 5 | `install_py_dependencies` | Cria `.venv` e instala pacotes Python | Isola dependências e garante versões corretas |
| 6 | `pausa_WinUpdate` | Pausa o Windows Update | Evita downloads e reinicializações durante testes |
| 7 | `enable_diagnostics` | Habilita diagnósticos de performance do Windows | Necessário para o teste de boot/shutdown (Event Log) |
| 8 | `AdicionarTecladoUSInt` | Adiciona layout de teclado US International | Padronização de ambiente |

### 3.3 Justificativa da Padronização `[Gestão]`

A Fase de Setup é essencial para a **comparabilidade dos resultados**. Sem ela, diferenças de configuração entre máquinas (plano de energia, atualizações em andamento, falta de dependências) poderiam gerar variações nos resultados que não refletem o desempenho real do hardware. A padronização garante que diferenças nos resultados entre máquinas são atribuíveis ao hardware, não à configuração de software.

---

## 4. Módulo 1 — CPU e Memória

### 4.1 Objetivo

Avaliar o desempenho e a estabilidade do processador e da memória sob carga sustentada, simulando um cenário de uso intensivo prolongado.

### 4.2 Ferramenta Utilizada

- **Microsoft Edge** via Selenium WebDriver — para gerar carga de CPU através de workloads web
- **Windows Performance Analyzer (WPA)** — para perfilamento detalhado do comportamento do sistema durante a carga
- **psutil** — para monitoramento de métricas de CPU em tempo real

### 4.3 Procedimento

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Abertura do Microsoft Edge com 3 abas de workload | ~10s |
| 2 | Início do ciclo de estresse | — |
| 3 | **Carga ativa** — CPU sob estresse sustentado | 300 segundos (5 min) |
| 4 | **Cooldown** — aguarda CPU cair abaixo de 15% | até 300 segundos (5 min) |
| 5 | Repetição dos passos 3-4 por **5 ciclos** | ~50 min total |
| 6 | Coleta de perfil WPA e geração de relatório | ~30s |

**Ciclo visual:**

```
Ciclo 1          Ciclo 2          Ciclo 3          Ciclo 4          Ciclo 5
┌──────┬──────┐ ┌──────┬──────┐ ┌──────┬──────┐ ┌──────┬──────┐ ┌──────┬──────┐
│Carga │Cool- │ │Carga │Cool- │ │Carga │Cool- │ │Carga │Cool- │ │Carga │Cool- │
│ 5min │down  │ │ 5min │down  │ │ 5min │down  │ │ 5min │down  │ │ 5min │down  │
└──────┴──────┘ └──────┴──────┘ └──────┴──────┘ └──────┴──────┘ └──────┴──────┘
```

### 4.4 Métricas Coletadas

| Métrica | Fonte | Formato |
|---------|-------|---------|
| Perfil de desempenho WPA | Windows Performance Analyzer | `.wpaProfile` |
| Tempos de cada ciclo (carga + cooldown) | Script Python | CSV |
| Uso de CPU ao longo do teste | psutil | Log textual |

### 4.5 Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| Todos os 5 ciclos completados sem erro | **PASS** (exit code 0) |
| Qualquer ciclo falha, crash ou timeout | **FAIL** (exit code 1) |

### 4.6 O que um FAIL Significa `[Gestão]`

Uma falha neste teste indica que o processador ou a memória da máquina não conseguiram sustentar carga contínua por 5 ciclos de estresse. Possíveis causas:

- **Superaquecimento** — o processador ativou proteção térmica (thermal throttling)
- **Instabilidade de memória** — erros de memória causaram crash no processo
- **Driver ou firmware** — incompatibilidades de software afetando a performance
- **Recurso insuficiente** — memória RAM insuficiente para a carga aplicada

**Ação recomendada:** Investigar logs detalhados em `Logs/run_*.log` e verificar se o hardware apresenta defeitos.

### 4.7 Interrupção Segura

O operador pode interromper o teste a qualquer momento pressionando `Ctrl+Q`. O teste será encerrado de forma controlada e registrará o status parcial.

---

## 5. Módulo 2 — Disco

### 5.1 Objetivo

Medir a velocidade de leitura e escrita sustentada do disco principal, avaliando o desempenho de I/O sob operações sequenciais com blocos grandes.

### 5.2 Ferramenta Utilizada

- **Microsoft DiskSPD** (`diskspd.exe`) — ferramenta oficial da Microsoft para benchmarking de disco
- **psutil** — para identificação do disco principal

### 5.3 Procedimento

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Identificação do disco principal e espaço disponível | ~2s |
| 2 | Início da bateria de testes | — |
| 3 | **Leitura sequencial** — blocos de 1 MB em arquivo de 8 GB | 10 segundos |
| 4 | **Escrita sequencial** — blocos de 1 MB em arquivo de 8 GB | 10 segundos |
| 5 | **Intervalo** entre baterias | 60 segundos |
| 6 | Repetição dos passos 3-5 por **10 baterias** | ~25 min total |
| 7 | Cálculo de médias e geração de CSV | ~5s |

**Parâmetros do DiskSPD:**

| Parâmetro | Valor |
|-----------|-------|
| Tamanho do bloco | 1 MB |
| Tamanho do arquivo de teste | 8 GB |
| Duração por operação | 10 segundos |
| Tipo de I/O | Sequencial |
| Número de baterias | 10 |
| Intervalo entre baterias | 60 segundos |

### 5.4 Métricas Coletadas

| Métrica | Unidade | Descrição |
|---------|---------|-----------|
| Velocidade de leitura (por bateria) | MB/s | Throughput de leitura sequencial |
| Velocidade de escrita (por bateria) | MB/s | Throughput de escrita sequencial |
| Média de leitura | MB/s | Média aritmética das 10 baterias |
| Média de escrita | MB/s | Média aritmética das 10 baterias |

**Exemplo de saída CSV:**

| Bateria | Leitura (MB/s) | Escrita (MB/s) |
|---------|----------------|----------------|
| 1 | 520.3 | 480.1 |
| 2 | 518.7 | 478.5 |
| ... | ... | ... |
| 10 | 521.0 | 479.8 |
| **Média** | **519.5** | **479.2** |

> ![Exemplo CSV Disco](img/placeholder-csv-disco.png)  
> *Insira aqui: screenshot de um CSV real gerado pelo teste de disco*

### 5.5 Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| Todas as 10 baterias completadas e CSV gerado | **PASS** (exit code 0) |
| Falha em qualquer bateria ou CSV não gerado | **FAIL** (exit code 1) |

### 5.6 Como Interpretar os Valores `[Gestão]`

Os valores de velocidade dependem do tipo de disco:

| Tipo de disco | Leitura esperada | Escrita esperada |
|---------------|------------------|------------------|
| HDD (7200 RPM) | 100–200 MB/s | 80–160 MB/s |
| SSD SATA | 400–550 MB/s | 300–520 MB/s |
| SSD NVMe | 1500–7000 MB/s | 1000–5000 MB/s |

Valores **significativamente abaixo** do esperado para o tipo de disco podem indicar: disco com defeito, driver desatualizado, superaquecimento, ou fragmentação excessiva (HDD).

---

## 6. Módulo 3 — Rede

### 6.1 Objetivo

Aferir a velocidade de conexão de rede da máquina, medindo download, upload, latência (ping) e variação de latência (jitter) através de múltiplas aferições.

### 6.2 Ferramenta Utilizada

- **Microsoft Edge** via Selenium WebDriver — para acessar o servidor de speedtest
- **Servidor de speedtest interno** (URL em `config.local.json` → `SpeedtestUrl`, não versionada) — ponto de medição padronizado

### 6.3 Procedimento

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Abertura do Microsoft Edge via Selenium | ~5s |
| 2 | Navegação para o servidor de speedtest | ~3s |
| 3 | **Aferição** — clica em "Start" e aguarda conclusão | ~60 segundos |
| 4 | Captura de screenshot como evidência | ~2s |
| 5 | Extração de métricas via regex do texto da página | ~1s |
| 6 | Repetição dos passos 3-5 por **5 aferições** | ~6 min total |
| 7 | Geração de CSV consolidado | ~2s |

### 6.4 Métricas Coletadas

| Métrica | Unidade | Descrição |
|---------|---------|-----------|
| Download | Mbps | Velocidade de download |
| Upload | Mbps | Velocidade de upload |
| Ping | ms | Latência de ida e volta |
| Jitter | ms | Variação da latência entre pacotes |

As métricas são coletadas **5 vezes**, e todas as medições individuais são registradas no CSV.

### 6.5 Evidências Geradas

Para cada aferição, é salvo:

- **Screenshot** da página de resultado (`Evidencia_Afericao_N.png`)
- **Linha no CSV** com timestamp e valores medidos

> ![Exemplo Evidência Rede](img/placeholder-evidencia-rede.png)  
> *Insira aqui: screenshot de uma das evidências de aferição de rede*

### 6.6 Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| 5 aferições capturadas com sucesso e CSV gerado | **PASS** (exit code 0) |
| Edge não encontrado ou aferições incompletas | **FAIL** (exit code 1) |

### 6.7 Referência de Valores Aceitáveis `[Gestão]`

> **Nota:** A tabela abaixo deve ser preenchida pela equipe conforme os padrões da organização.

| Métrica | Mínimo aceitável | Ideal |
|---------|-------------------|-------|
| Download | ___ Mbps | ___ Mbps |
| Upload | ___ Mbps | ___ Mbps |
| Ping | ___ ms (máximo) | ___ ms |
| Jitter | ___ ms (máximo) | ___ ms |

### 6.8 Teste Complementar — Speedtest na Internet (fast.com)

#### Objetivo e motivação

O teste das seções 6.1–6.7 mede contra um servidor de speedtest **interno**. Em máquinas com agente **zero trust**, o tráfego para destinos internos pode não ser inspecionado nem roteado pelo agente (bypass da rede corporativa ou túnel distinto), enquanto o tráfego para a internet passa pelo proxy/túnel e pela inspeção SSL do agente. O teste complementar mede a velocidade num speedtest **público da internet**, pelo mesmo caminho do tráfego real do usuário, para capturar o impacto do agente na navegação.

O script é `Testes/3_rede_internet/3-1_teste_rede_internet.py`. Ele aparece no menu do hub na seção **Rede Internet**, logo após **Rede**, e tem PASS/FAIL próprio (um bloqueio na internet não reprova o teste interno, e vice-versa).

#### Ferramenta Utilizada

- **Microsoft Edge** via Selenium WebDriver — driver obtido automaticamente pelo Selenium Manager
- **fast.com** (Netflix) — speedtest público e gratuito, sem anúncios, que inicia a medição sozinho e usa servidores de borda da Netflix próximos ao cliente (ex.: Rio de Janeiro e Barueri)
- Erros de certificado **não** são ignorados: a inspeção SSL do agente atua como atuaria para o usuário

> **Nota:** o `speed.cloudflare.com` foi avaliado e descartado porque exige verificação antirrobô ("Confirme que é humano") antes de iniciar a medição, o que impede a execução desassistida.

#### Procedimento

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Abertura do Microsoft Edge via Selenium | ~5s |
| 2 | Acesso a `https://fast.com/` — a medição inicia automaticamente | ~2s |
| 3 | **Aferição** — aguarda a conclusão de download, latência e upload (sem espera fixa; limite de 120 s) | ~20–45 segundos |
| 4 | Leitura das métricas na página e captura de screenshot | ~2s |
| 5 | Repetição dos passos 2-4 por **5 aferições** | ~3 min total |
| 6 | Geração dos CSVs | ~1s |

#### Métricas Coletadas

| Métrica | Unidade | Descrição |
|---------|---------|-----------|
| Download | Mbps | Velocidade de download |
| Upload | Mbps | Velocidade de upload |
| Ping | ms | Latência sem carga ("Não carregados" no fast.com) |
| Latência sob carga | ms | Latência medida durante a transferência ("Carregada") — indica formação de fila (bufferbloat) |
| Local do cliente | texto | Localização de saída vista pelo serviço |
| IP de saída | texto | IP público pelo qual o tráfego saiu para a internet |
| Servidores | texto | Localização dos servidores de medição usados |

O fast.com não reporta jitter nem perda de pacotes.

#### Evidências Geradas

Na pasta `3_rede_internet/` do cenário:

- `teste_rede_internet_<data_hora>.log` — log completo da execução
- `resultado_afericoes_internet.csv` — uma linha por aferição (separador `;`, decimal com vírgula): `Afericao;Data_Hora;Download;Upload;Ping;Latencia_Carga;Local_Cliente;IP_Saida;Servidores;Status;Print`
- `rede_internet.csv` — CSV temático (`Metrica,Valor,Unidade`) com aferições executadas/válidas, médias, mínimos e máximos, local, IP de saída e servidores; é copiado para `Resultados/`
- `Evidencia_Internet_Afericao_N_<data_hora>.png` — screenshot de cada aferição
- `Evidencia_Internet_Bloqueio_<data_hora>.png` — somente quando o site está inacessível ou bloqueado

#### Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| 5 aferições com Download, Upload e Ping capturados e CSVs gerados | **PASS** (exit code 0) |
| Site inacessível ou bloqueado (política do agente zero trust/proxy, sem internet) — falha rápida, com screenshot da tela exibida | **FAIL** (exit code 1) |
| Menos de 5 aferições válidas (timeout ou valores ausentes) | **FAIL** (exit code 1) |
| Edge não encontrado ou driver do Edge não obtido | **FAIL** (exit code 1) |

#### Como Interpretar `[Gestão]`

- Compare o `rede_internet.csv` do cenário **baseline** (sem agente) com o do cenário **com agente**, executados na mesma rede e na mesma janela de horário.
- **Local do cliente** e **IP de saída** mostram por onde o tráfego saiu. Com o agente zero trust ativo, espera-se ver o IP/local do nó de saída do provedor do agente; se continuarem iguais aos do baseline, o tráfego provavelmente não passou pelo agente.
- O fast.com mede até a borda de conteúdo da Netflix mais próxima (muitas vezes dentro do próprio provedor de internet). O resultado representa a navegação cotidiana, não o trânsito internacional.

---

## 7. Módulo 4 — Boot e Shutdown

### 7.1 Objetivo

Avaliar o tempo de inicialização e desligamento do Windows através de múltiplos ciclos de reinicialização, identificando degradações e gargalos no processo de boot.

### 7.2 Ferramenta Utilizada

- **Agendador de Tarefas do Windows** (Task Scheduler) — para automatizar reinicializações
- **Event Log de Diagnósticos do Windows** (`Microsoft-Windows-Diagnostics-Performance/Operational`) — fonte de métricas de boot/shutdown
- **PowerShell** (`boot_shutdown_duration.ps1`) — para análise dos eventos

### 7.3 Procedimento

Este teste opera em **duas etapas** com reinicializações automáticas:

#### Etapa 1 — Ciclos de Reinicialização (automático)

| Ciclo | Ação |
|-------|------|
| 1 | Cria tarefa agendada no Task Scheduler, agenda shutdown em 5 min |
| 2 | Máquina reinicia → script executa automaticamente via ONLOGON, aguarda 5 min, reinicia |
| 3 | (repete) |
| 4 | (repete) |
| 5 | (repete) |
| 6 | Último ciclo → executa análise dos eventos e limpa tarefa agendada |

**Tempo total estimado:** ~30-40 minutos (5 ciclos × ~6-7 min cada)

> **Importante:** Durante os ciclos de reinicialização, **a máquina reinicia automaticamente 5 vezes**. Não interrompa o processo. O hub retoma automaticamente após cada reinicialização.

#### Etapa 2 — Análise de Eventos

Após os 5 ciclos, o script `boot_shutdown_duration.ps1` consulta o Event Log dos últimos 3 dias e coleta:

| Evento | ID | O que mede |
|--------|-----|------------|
| Boot completo | 100 | `MainPathBootTime` e `BootPostBootTime` |
| Shutdown completo | 200 | Tempo total de desligamento |
| Degradação de boot | 101-110 | Drivers, serviços e apps que atrasaram o boot |
| Atraso no shutdown | 201-203 | Processos que atrasaram o desligamento |

### 7.4 Métricas Coletadas

| Métrica | Unidade | Descrição |
|---------|---------|-----------|
| MainPathBootTime | milissegundos | Tempo do caminho principal de boot |
| BootPostBootTime | milissegundos | Tempo de atividades pós-boot |
| ShutdownDuration | milissegundos | Tempo total de desligamento |
| Eventos de degradação | texto | Detalhamento de causas de lentidão |

### 7.5 Critérios de Avaliação

O teste utiliza **limiares progressivos**:

| Métrica | Normal | Aviso (Warning) | Crítico |
|---------|--------|-----------------|---------|
| Tempo de boot | < 30s | 30s – 60s | > 60s |
| Tempo de shutdown | < 20s | 20s – 60s | > 60s |

### 7.6 Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| Nenhum evento **crítico** nos boots do dia atual | **PASS** (exit code 0) |
| Pelo menos um evento crítico encontrado | **FAIL** (exit code 1) |

> **Nota:** Eventos de "aviso" (warning) são registrados no relatório mas **não causam FAIL**. Apenas eventos críticos reprovam o teste.

### 7.7 Impacto de Degradação de Boot `[Gestão]`

Tempos de boot elevados afetam diretamente a produtividade:

| Cenário | Impacto estimado |
|---------|------------------|
| Boot > 60s em 100 máquinas, 1 reinício/dia | ~1.7 horas/dia perdidas pela operação |
| Boot > 60s com 5 reinícios/semana | ~8.3 horas/semana por 100 máquinas |

Causas comuns de degradação:
- **Drivers desatualizados** — frequentemente o maior contribuinte
- **Serviços de terceiros** — antivírus, agentes de monitoramento
- **Aplicativos no startup** — programas configurados para iniciar com o Windows
- **Disco lento** — HDD degradado ou SSD com firmware desatualizado

---

## 8. Módulo 5 — Bateria

### 8.1 Objetivo

Medir o consumo de energia do notebook na bateria em duas fases padronizadas — **60 minutos ociosa**, com a tela ligada, e **60 minutos sob carga de escritório** — para comparar o cenário **baseline** (sem agente) com o cenário **com agente de segurança** na mesma máquina. Antes de medir, o teste padroniza a máquina sozinho (**pré-voo**), relê cada ajuste e registra o valor antes e depois como evidência.

O script é `Testes/5_bateria/5_teste_bateria.py`. Ele aparece no menu do hub na seção **Bateria**, logo após **Boot Shutdown**, e precisa de um operador para desconectar o carregador. O teste substitui o procedimento manual anterior (`cpu_stress_controller_pro.exe` com 60% de CPU por 120 minutos e a linha de comando do `Comando_Bateria.txt`); os resultados novos **não são comparáveis** com as medições antigas.

### 8.2 Ferramentas Utilizadas

- **WMI de bateria** (`root\wmi`): `BatteryStatus` (energia restante em mWh, taxa de descarga, tensão), `BatteryFullChargedCapacity` e `BatteryCycleCount`, lidos por um único processo PowerShell que fica aberto durante o teste — a leitura custa poucos milissegundos por amostra e não pesa na fase ociosa
- **API do Windows**: `GetSystemPowerStatus` (fonte de alimentação, % de carga e estado da Economia de energia) e `powrprof` (modo de energia)
- **powercfg**: plano e configurações de energia da bateria, relatório de bateria (`/batteryreport`, antes e depois), SRUM (`/srumutil`) e relatório de energia (`/energy`)
- **Windows Performance Recorder** (`wpr.exe`, perfil `Power.light`) — um trace por fase — e **WPA Exporter** (`wpaexporter.exe`) com o perfil `Agentes_SI_Bateria_Profile.wpaProfile`, o mesmo do procedimento anterior
- **Microsoft Edge** com Google Docs, Google Sheets e um PDF — a mesma simulação de uso do Módulo 1, de forma contínua
- **psutil** — top 10 processos por CPU

### 8.3 Pré-voo de Padronização

O pré-voo roda **na tomada**, antes de pedir a desconexão do carregador. Cada item vira uma linha do `bateria_preflight.csv` com `Esperado`, `Antes`, `Acao`, `Depois`, `Situacao` (`ok`, `ajustado`, `não aplicável` ou `falhou`) e `Observacao`.

| Grupo | Item | Esperado | Como é tratado |
|-------|------|----------|----------------|
| Conferidos | Bateria presente | sim | Sem bateria (desktop ou bateria não reconhecida): falha em segundos, sem alterar nada |
| Conferidos | Carga inicial | ≥ 95% | Abaixo do mínimo: informa a carga atual e pede para carregar |
| Conferidos | Ferramentas de captura | `wpr.exe` e `wpaexporter.exe` no PATH | Perfil WPA ausente gera só aviso (a exportação CSV é ignorada) |
| Conferidos | Conexão de rede | com acesso à internet | Registra `tipo \| rede \| sinal`; SSID ou sinal indisponíveis não reprovam |
| Conferidos | Monitor externo | nenhum | Também pega a tampa fechada com monitor externo |
| Conferidos | Edge e conta Google | prontos | Boas-vindas do Edge ou login do Google: janela pede o login (até 3 vezes), como no Módulo 1. Usa as páginas de lista do Docs/Sheets, sem criar documentos |
| Ajustados | Plano de energia | Equilibrado | O mesmo plano do setup `2_opcoes_energia` |
| Ajustados | Modo de energia na bateria | Melhor desempenho | Sem a API do modo na bateria (Windows antigo): aplicado e conferido já na bateria |
| Ajustados | Economia de energia | desligada, limite 0% | Limite 0% = não liga sozinha; ligada manualmente: `falhou` (desligar nas Configurações) |
| Ajustados | Brilho na bateria | 50% | Valor de bateria do plano |
| Ajustados | Esmaecimento da tela na bateria | nunca | |
| Ajustados | Brilho adaptável na bateria | desligado | `não aplicável` sem sensor de luz ambiente |
| Ajustados | Bluetooth | desligado | `não aplicável` sem rádio Bluetooth |
| Ajustados | Suspensão na bateria | nunca | |
| Ajustados | Hibernação na bateria | nunca | |
| Ajustados | Desligar vídeo na bateria | nunca | |
| Físicos | Carregador desconectado | desconectado | Detectado automaticamente |
| Físicos | Periféricos e dock desconectados | sim | Confirmado pelo operador |
| Físicos | Luz do teclado apagada | sim | Confirmado pelo operador |
| Na bateria | Brilho efetivo | 50% | Conferido na estabilização; se o driver não aplicou, é reaplicado uma vez |
| Na bateria | Modo de energia efetivo | Melhor desempenho | Conferido na estabilização |
| Na bateria | Economia de energia efetiva | desligada | Conferida na estabilização |

Regras:

- Os itens **ajustados** são aplicados, relidos e registrados; todo ajuste é **restaurado** ao final, por qualquer caminho de saída.
- O teste **não contorna política corporativa**: item bloqueado por GPO ou pelo sistema fica `falhou` com "bloqueado por política".
- Algum item `falhou`: o teste **não mede**, restaura o que já tinha alterado, lista os pendentes numa janela e sai com exit 1.
- Recurso inexistente na máquina (sem Bluetooth, sem sensor de luz, configuração ausente no plano) é `não aplicável` e não reprova.

### 8.4 Procedimento

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Checagens rápidas: bateria, carga, ferramentas e perfil WPA | segundos |
| 2 | Rede com internet e ausência de monitor externo | ~5 s |
| 3 | Prontidão do Edge e da conta Google (na tomada) | ~30 s (+ login, se pedido) |
| 4 | Ajustes de energia, brilho e Bluetooth; grava `bateria_preflight.csv` | ~15 s |
| 5 | Relatório de bateria "antes" (HTML e XML) | ~5 s |
| 6 | **Aviso único**: desconectar o carregador e confirmar o checklist físico | até 10 min |
| 7 | **Estabilização** na bateria, fora da medição, com a conferência de brilho, modo e Economia | 5 min |
| 8 | **Fase ociosa**: tela ligada, nenhum aplicativo aberto pelo teste, nenhuma entrada simulada; trace WPR | 60 min |
| 9 | Transição: salva o trace, confere se a sessão está bloqueada e abre o Edge com documento, planilha e PDF | ~1–5 min |
| 10 | **Fase de escritório**: simulação contínua do Módulo 1, sem ciclos nem cooldown; trace WPR | 60 min |
| 11 | Encerramento: salva o trace, amostra final, fecha o Edge, relatório de bateria "depois" e aviso de que o carregador pode ser reconectado | ~1–5 min |
| 12 | Pós-medição: exportação WPA dos traces, SRUM, relatório de energia (60 s de observação), `bateria.csv` e restauração | ~5–20 min |

**Tempo total estimado:** ~2h20–2h40.

Durante toda a medição:

- A tela fica ligada e a sessão não é bloqueada por inatividade, sem simular teclado ou mouse (`SetThreadExecutionState`).
- Uma **amostra** da bateria é gravada a cada 60 s e o **top 10 processos** a cada 5 min.
- Uma **vigia** a cada 5 s encerra a medição de forma controlada se o carregador for reconectado, se a carga chegar a **7%** (proteção de bateria) ou se o operador pressionar Ctrl+Q.
- O overlay mostra fase, carga e minutos restantes, atualizado só a cada amostra para não gerar atividade de tela na fase ociosa.

### 8.5 Métricas Coletadas

As métricas de cada fase saem de duas amostras-marco tiradas nos limites exatos da fase (`inicio_fase` e `fim_fase`). A **energia em mWh é a medida principal**; o percentual de carga é complementar.

| Métrica (`bateria.csv`) | Unidade | Como é calculada |
|-------------------------|---------|------------------|
| `Ociosa_Duracao_Medida` / `Escritorio_Duracao_Medida` | min | Tempo entre os dois marcos da fase |
| `Ociosa_Energia_Consumida` / `Escritorio_Energia_Consumida` | mWh | Energia restante no início − energia restante no fim |
| `Ociosa_Taxa_Media_Descarga` / `Escritorio_Taxa_Media_Descarga` | W | Energia consumida ÷ duração |
| `Ociosa_Queda_Carga` / `Escritorio_Queda_Carga` | pp | % de carga no início − % no fim |
| `Ociosa_Queda_Carga_Hora` / `Escritorio_Queda_Carga_Hora` | pp/h | Queda de carga ÷ duração |
| `Ociosa_Autonomia_Projetada` / `Escritorio_Autonomia_Projetada` | h | Capacidade de carga cheia ÷ taxa média de descarga |
| `Energia_Estimada` | texto | `sim` quando a bateria não informa mWh (ou informa capacidade em unidade relativa): a energia é estimada pela queda de % × capacidade de carga cheia |
| `Carga_Bateria_Inicial` / `Carga_Bateria_Final` | % | Carga no início da fase ociosa e na amostra final |
| `Capacidade_Carga_Cheia` / `Capacidade_Projeto` | mWh | WMI de bateria; a capacidade de projeto vem do relatório de bateria quando o WMI não a informa |
| `Ciclos_Carga` | un | Ciclos de carga informados pela bateria |
| `Plano_Energia` | texto | Plano após o pré-voo |
| `Modo_Energia` / `Brilho` | texto / % | Valor predominante nas amostras das fases medidas |
| `Bluetooth` | texto | `desligado` ou `ausente` |
| `Desvios_Padronizacao` | un | Amostras das fases medidas com brilho ≠ 50%, modo ≠ Melhor desempenho ou Economia ligada |
| `Versao_Teste`, `Coleta_Valida`, `Motivo_Encerramento` | texto | Versão do teste, `sim`/`nao` e o motivo do fim da medição |

`Motivo_Encerramento`: `concluido`, `protecao_bateria`, `carregador_reconectado`, `parada_segura`, `sessao_bloqueada`, `login_exigido`, `padronizacao_na_bateria` ou `erro`. Fase sem dados = `N/A`. Formato: separador `,`, decimal com ponto e 2 casas.

### 8.6 Evidências Geradas

Na pasta `5_bateria/` do cenário:

- `teste_bateria_<data_hora>.log` — log completo da execução
- `bateria_preflight.csv` — uma linha por item do pré-voo (separador `;`): `Item;Esperado;Antes;Acao;Depois;Situacao;Observacao`. A coluna `Antes` permite restaurar a máquina à mão se o processo for encerrado à força
- `bateria_relatorio_antes.html` / `bateria_relatorio_antes.xml` e `bateria_relatorio_depois.html` — relatório de bateria do Windows antes e depois da medição
- `bateria_amostras.csv` — uma amostra a cada 60 s e os marcos de cada fase (separador `;`, decimal com vírgula): `Data_Hora;Fase;Tipo;Decorrido_Fase_s;Carga_Pct;Energia_Restante_mWh;Taxa_Descarga_mW;Tensao_mV;Fonte;Brilho_Pct;Modo_Energia;Economia_Energia;Desvio`. `Fase` = `estabilizacao`, `ociosa`, `transicao`, `escritorio` ou `encerramento`; `Tipo` = `periodica`, `inicio_fase` ou `fim_fase`
- `bateria_top_processos.csv` — top 10 processos por CPU a cada 5 min: `Data_Hora;Fase;Posicao;Processo;PID;CPU_Pct;Memoria_MB`. `CPU_Pct` é a média do processo na janela de 5 min, em % da máquina
- `Trace_Bateria_Ociosa_<data_hora>.etl` e `Trace_Bateria_Escritorio_<data_hora>.etl` — um trace de energia por fase (parcial, se a medição encerrou antes)
- `CSV_Ociosa_<data_hora>/` e `CSV_Escritorio_<data_hora>/` — exportação dos traces pelo perfil WPA de bateria
- `bateria_srum.csv` — relatório SRUM (`powercfg /srumutil`)
- `bateria_relatorio_energia.html` — relatório de energia (`powercfg /energy`, 60 s)
- `bateria.csv` — CSV temático (`Metrica,Valor,Unidade`), copiado para `Resultados/`. É gravado sempre que a medição começou, inclusive em encerramento antecipado

Nada é gravado em `C:\BATERIA`, em `C:\Traces` nem na raiz do projeto.

### 8.7 Critério de Aprovação

O PASS/FAIL decide se a **coleta é válida**; não há limiar de autonomia ou consumo.

| Condição | Resultado |
|----------|-----------|
| Pré-voo e conferência na bateria ok, fase ociosa completa, fase de escritório com pelo menos 30 min medidos (completa ou encerrada pela proteção de bateria depois desse mínimo), leitura de energia (medida ou estimada) nas duas fases, `bateria.csv` e `bateria_amostras.csv` gravados | **PASS** (exit code 0) |
| Sem bateria, carga abaixo de 95%, ferramentas ausentes, item fora do padrão ou bloqueado por política, sem internet, monitor externo, Edge/Google não prontos — antes de pedir a desconexão | **FAIL** (exit code 1) |
| Carregador não desconectado em 10 minutos | **FAIL** (exit code 1) |
| Brilho, modo ou Economia fora do padrão já na bateria (`padronizacao_na_bateria`) | **FAIL** (exit code 1) |
| Carregador reconectado durante a estabilização ou a medição | **FAIL** (exit code 1) |
| Proteção de bateria (7%) na fase ociosa ou antes de 30 min da fase de escritório | **FAIL** (exit code 1) |
| Sessão bloqueada no início da fase de escritório | **FAIL** (exit code 1) |
| Login pedido ao abrir o Edge já na bateria (`login_exigido`) | **FAIL** (exit code 1) |
| Sem leitura de energia numa das fases (bateria sem mWh e sem capacidade de carga cheia) | **FAIL** (exit code 1) |
| Parada segura (Ctrl+Q) ou erro inesperado | **FAIL** (exit code 1) |

> **Nota:** desvios de padronização durante a medição e falhas nas evidências complementares (exportação CSV, SRUM, relatório de energia) **não reprovam**: ficam como aviso no log e, no caso dos desvios, em `Desvios_Padronizacao`.

### 8.8 Como Interpretar `[Gestão]`

- Compare o `bateria.csv` do cenário **baseline** com o do cenário **com agente**, executados na **mesma máquina**, na **mesma rede** e com a **mesma versão do teste** (`Versao_Teste`).
- A **fase ociosa** mostra o custo de fundo do agente — é onde 1–2 W de diferença aparecem com mais clareza. A **fase de escritório** representa o uso real.
- Use a **taxa média de descarga (W)** e a **energia consumida (mWh)** como medidas principais; a queda em % tem resolução de 1 ponto e é complementar.
- Só compare execuções com `Coleta_Valida = sim` e `Desvios_Padronizacao = 0`. `Energia_Estimada = sim` indica menor precisão.
- A **autonomia projetada** é uma extrapolação linear do consumo da fase, não uma descarga completa.
- O `bateria_top_processos.csv` e os traces `.etl` (no WPA) ajudam a atribuir a diferença de consumo a processos específicos.
- Os resultados **não são comparáveis** com as medições antigas de 60% de CPU por 120 minutos.

### 8.9 Interrupção Segura

Assim como no Módulo 1, o teste pode ser interrompido com **Ctrl+Q**. Fechar a janela do monitor do teste (pela barra de tarefas ou Alt+F4) e um Ctrl+C recebido pelo teste têm o mesmo efeito. A parada segura salva o trace parcial, grava o que já foi medido (`bateria.csv` com `Coleta_Valida = nao`), restaura as configurações alteradas, fecha o Edge e sai com exit code 1.

Se o processo for encerrado à força (por exemplo, fechando a janela do hub), a restauração automática não roda: use a coluna `Antes` do `bateria_preflight.csv` para voltar brilho, Bluetooth e configurações de energia aos valores anteriores.

---

## 9. Módulo 6 — Wi-Fi Fast Transition (802.11r)

### 9.1 Objetivo

Verificar se a máquina (adaptador Wi-Fi + driver + firmware/BIOS + Windows) faz **roaming com Fast BSS Transition (802.11r)** ao trocar de AP dentro da mesma rede. Sem FT, cada troca de AP passa por uma reautenticação completa (4-way handshake e, em redes 802.1X, o RADIUS), o que gera interrupções perceptíveis em chamadas de voz/vídeo e VPN. O teste também coleta tudo o que interfere nessa compatibilidade, para explicar um FAIL.

### 9.2 Ferramentas Utilizadas

- **API nativa de WLAN do Windows (`wlanapi.dll`)**, lida pelo script: BSSID, RSSI e qualidade a cada 250 ms; notificações de associação/roaming; cache de varredura com os *Information Elements* de cada AP.
- **`netsh wlan show interfaces`**: AKM da associação atual (`akm = 00-0f-ac:NN`), relida a cada 2 s e logo após cada troca de AP.
- **`netsh wlan show drivers` / `wirelesscapabilities`**: capacidades declaradas pelo driver (Transição Rápida, 802.11k, 802.11v, SAE, MFP).
- **Ping ICMP (`IcmpSendEcho`)** a cada 200 ms para o gateway e para a internet (`8.8.8.8`).
- **Painel ao vivo** no navegador (servidor local em `127.0.0.1`), sem dependência de internet.

O teste **não altera nenhuma configuração** do sistema, do adaptador ou da rede, e não força varreduras Wi-Fi.

### 9.3 Procedimento

1. **Pré-voo:** exige o Wi-Fi conectado — a rede conectada é a rede testada. Registra SSID, BSSID inicial, autenticação, cifra, AKM, banda, canal, RSSI e gateway.
2. **Coleta de compatibilidade:** adaptador e propriedades avançadas (Roaming Aggressiveness, banda preferida, MIMO Power Save...), driver (versão, data, fornecedor, INF), capacidades sem fio, BIOS, modelo, SO/build, plano e economia de energia do adaptador sem fio, adaptadores virtuais/VPN ativos e perfil WLAN (**sem a senha**).
3. **Inventário de APs:** para cada BSSID do SSID no cache de varredura, AKMs anunciadas (RSN IE), Mobility Domain/MDID (802.11r), 802.11k (RM) e 802.11v (BSS Transition).
4. **Caminhada (5 min):** o painel abre no navegador; o operador clica em **Iniciar caminhada** (ou o início é automático após 60 s) e anda pelo escritório passando por áreas de APs diferentes. O painel mostra AP atual, RSSI, gráficos de RSSI e latência, e destaca cada troca com a classificação.
5. **Pós-processamento:** exportação do log `WLAN-AutoConfig/Operational` do período, relatório WLAN do Windows (`wlanreport`), classificação de cada troca, CSVs e relatório HTML.

### 9.4 Classificação de Cada Troca de AP

| Classificação | Regra |
|---------------|-------|
| **FT** | Após a troca, a AKM conectada é de Fast Transition — FT-802.1X (`00-0f-ac:03`), FT-PSK (`:04`), FT-SAE (`:09`), FT-802.1X-SHA384 (`:0d`), FT-FILS (`:10`/`:11`), FT-PSK-SHA384 (`:13`), FT-SAE-EXT-KEY (`:19`) — **e não houve desconexão** |
| **Não FT** | A AKM após a troca não é de FT (ex.: PSK, 802.1X, SAE), ou a troca passou por desconexão (reconexão completa) |
| **Indeterminado** | A AKM após a troca não pôde ser lida (driver não informa) |

O tempo de troca vem das notificações WLAN do Windows, quando disponíveis, e é dividido em duas fases:

- **Reassociação:** início do roaming → autenticação no AP novo. É a troca pelo ar (autenticação FT e reassociação) e a parte comparável ao tempo de roaming mostrado pela controladora (WLC).
- **Conclusão no Windows:** autenticação → roaming concluído (instalação de chaves, liberação da porta e aviso aos programas). A WLC não enxerga essa fase.

Sem notificações, só o total pela amostragem (resolução de 250 ms). O início é procurado desde o fim do roaming anterior, porque tentativas demoradas começam segundos antes de o BSSID mudar; trocas acima de 1 s são sinalizadas como **demoradas**. Os carimbos usam relógio de alta resolução (< 1 ms). A interrupção é o maior intervalo sem resposta do gateway em torno da troca.

### 9.5 Métricas Coletadas

O `wifi_ft.csv` (formato `Metrica,Valor,Unidade`) traz: SSID, autenticação, cifra, AKM conectada, adaptador, versão/data/fornecedor do driver, firmware, BIOS, build do SO, suporte declarado a FT/802.11k/802.11v, APs vistos/com FT anunciado/utilizados, duração da caminhada, roamings (total, FT, não FT, indeterminados, com desconexão, demorados), tempo de troca total, de reassociação e de conclusão no Windows (média, mediana e máximo), interrupção média/máxima (gateway e internet), perda e latência média/p95 (gateway e internet), RSSI mínimo/médio/máximo e resultado.

### 9.6 Evidências Geradas

| Arquivo | Conteúdo |
|---------|----------|
| `wifi_ft_relatorio.html` | Relatório com gráficos (RSSI × tempo com marcadores de roaming, linha do tempo de APs, latência/perda, tempo de troca e interrupção por roaming), tabelas de roamings, achados de compatibilidade, APs e informações técnicas. Abre sem internet |
| `wifi_ft.csv` | CSV temático (copiado para `Resultados/`) |
| `wifi_ft_roamings.csv` | Uma linha por troca de AP |
| `wifi_ft_amostras.csv` | Série de 250 ms: BSSID, RSSI, qualidade, canal, taxas |
| `wifi_ft_pings.csv` | Todos os pings (gateway e internet) |
| `wifi_ft_eventos_wlan.csv` | Notificações WLAN (associação, roaming, desconexão) |
| `wifi_ft_compatibilidade.json` | Toda a coleta de compatibilidade e os achados |
| `brutos/` | Saídas de `netsh`/PowerShell/`powercfg`, log `WLAN-AutoConfig` (`.evtx` e `.txt`) e `wlan-report.html` |

### 9.7 Critério de Aprovação

| Resultado | Condição |
|-----------|----------|
| **PASS** | Pelo menos **1** troca de AP classificada como **FT** |
| **FAIL** | Wi-Fi desconectado no início; nenhuma troca de AP; apenas trocas Não FT; ou apenas trocas indeterminadas |

Tempo de troca e perda de pacotes são registrados, mas não reprovam. Ping para a internet bloqueado vira `N/A` e não reprova.

### 9.8 Como Interpretar `[Gestão]`

- **FAIL "nenhuma troca de AP":** o operador não se afastou o suficiente do AP inicial, ou só há 1 AP do SSID no percurso. Não indica problema da máquina.
- **FAIL "nenhum com Fast Transition" com o achado "a rede usa PSK/802.1X/SAE":** o 802.11r não está habilitado no SSID (configuração da controladora/AP), não é problema da máquina.
- **FAIL com a rede anunciando FT, mas a máquina conectando sem FT:** suspeite do driver/adaptador (veja "Transição Rápida" nas capacidades e a idade do driver) ou de política do Windows.
- **Interrupções altas mesmo com FT:** verifique economia de energia do adaptador, Roaming Aggressiveness, adaptadores virtuais/VPN e RSSI muito baixo antes da troca (o cliente esperou demais para trocar).

---

## 10. Rastreabilidade e Evidências

### 10.1 Estrutura de Armazenamento

Toda execução gera evidências organizadas em dois níveis:

```
Traces/
└── ImagemLimpa_DESKTOP-ABC_2026-04-15/     ← cenário
    ├── _state.json                          ← estado e histórico
    ├── _relatorio.html                      ← relatório consolidado
    ├── _relatorio.csv
    ├── _relatorio.json
    ├── 1_cpu_memo/                          ← evidências do teste de CPU
    │   ├── perfil_wpa.csv
    │   └── log_ciclos.csv
    ├── 2_disco/                             ← evidências do teste de disco
    │   └── resultado_validacao_disco_*.csv
    ├── 3_rede/                              ← evidências do teste de rede
    │   ├── resultado_afericoes.csv
    │   ├── Evidencia_Afericao_1.png
    │   ├── Evidencia_Afericao_2.png
    │   ├── Evidencia_Afericao_3.png
    │   ├── Evidencia_Afericao_4.png
    │   └── Evidencia_Afericao_5.png
    ├── 3_rede_internet/                     ← evidências do teste de rede na internet
    │   ├── teste_rede_internet_*.log
    │   ├── resultado_afericoes_internet.csv
    │   ├── rede_internet.csv
    │   ├── Evidencia_Internet_Afericao_1_*.png
    │   ├── ...
    │   └── Evidencia_Internet_Afericao_5_*.png
    ├── 4_boot_shutdown/                     ← evidências do teste de boot
    │   └── BootShutdown_2026-04-15.csv
    ├── 5_bateria/                           ← evidências do teste de bateria
    │   ├── teste_bateria_*.log
    │   ├── bateria_preflight.csv
    │   ├── bateria_relatorio_antes.html
    │   ├── bateria_relatorio_antes.xml
    │   ├── bateria_amostras.csv
    │   ├── bateria_top_processos.csv
    │   ├── Trace_Bateria_Ociosa_*.etl
    │   ├── Trace_Bateria_Escritorio_*.etl
    │   ├── CSV_Ociosa_*/
    │   ├── CSV_Escritorio_*/
    │   ├── bateria_relatorio_depois.html
    │   ├── bateria_srum.csv
    │   ├── bateria_relatorio_energia.html
    │   └── bateria.csv
    ├── 6_wifi_fast_transition/              ← evidências do teste de Wi-Fi FT
    │   ├── teste_wifi_ft_*.log
    │   ├── wifi_ft_relatorio.html
    │   ├── wifi_ft.csv
    │   ├── wifi_ft_roamings.csv
    │   ├── wifi_ft_amostras.csv
    │   ├── wifi_ft_pings.csv
    │   ├── wifi_ft_eventos_wlan.csv
    │   ├── wifi_ft_compatibilidade.json
    │   └── brutos/
    └── _anterior/                           ← evidências de runs anteriores
        ├── run1_2026-04-15 09-30-00/
        └── run2_2026-04-15 14-00-00/
```

> ![Estrutura de Pastas](img/placeholder-estrutura-traces.png)  
> *Insira aqui: screenshot do Windows Explorer mostrando a estrutura de pastas de um cenário real*

### 10.2 Ciclo de Vida das Evidências

1. **Primeira execução:** Evidências são salvas diretamente nas subpastas do cenário
2. **Re-execução:** Evidências anteriores são movidas para `_anterior/run{N}_{timestamp}/` e novas evidências são geradas
3. **Consolidação:** O relatório `_relatorio.*` é atualizado com os resultados de todas as runs

**Nenhuma evidência é apagada.** O histórico completo de todas as tentativas é preservado.

### 10.3 O Arquivo _state.json `[Técnico]`

O `_state.json` é a fonte de verdade para o estado do cenário. Exemplo de estrutura:

```json
{
  "scenario": "ImagemLimpa",
  "machine": "DESKTOP-ABC",
  "createdAt": "2026-04-15T09:00:00",
  "lastRunAt": "2026-04-15T14:00:00",
  "runs": [
    {
      "runId": 1,
      "timestamp": "2026-04-15T09:00:00",
      "tests": [
        {
          "name": "1_automacao_performance.py",
          "folder": "1_cpu_memo",
          "status": "PASS",
          "exitCode": 0,
          "duration": 361.5
        }
      ]
    }
  ]
}
```

### 10.4 Cadeia de Custódia `[Gestão]`

Para auditar uma execução e validar a integridade dos resultados:

| Etapa de auditoria | O que verificar | Onde encontrar |
|---------------------|----------------|----------------|
| **1. Identificação** | Máquina, data, operador | `_state.json` → `machine`, `createdAt` |
| **2. Escopo** | Quais testes foram executados | `_state.json` → `runs[].tests[]` |
| **3. Resultados** | PASS/FAIL de cada teste | `_relatorio.html` ou `_state.json` |
| **4. Evidências** | Dados brutos que suportam o resultado | Subpastas do cenário (CSVs, screenshots, logs) |
| **5. Histórico** | Re-execuções e tentativas anteriores | `_anterior/` e múltiplas entries em `runs[]` |
| **6. Ambiente** | Configuração da máquina no momento do teste | `1_cpu_memo/` → CSV de informações do PC (gerado pelo setup) |

---

## 11. Formatos de Relatório

### 11.1 Relatório HTML

Relatório visual com tabela formatada, badges de status coloridos e resumo estatístico. Ideal para apresentação e compartilhamento.

**Conteúdo:**
- Cabeçalho com nome do cenário, máquina, data
- Resumo: total de testes, PASS, FAIL, ERR
- Tabela com cada teste: nome, status (badge colorido), duração, evidências
- Para testes FAIL: snippet das últimas linhas de erro

> ![Exemplo Relatório HTML](img/placeholder-relatorio-html-exemplo.png)  
> *Insira aqui: screenshot de um relatório HTML real*

### 11.2 Relatório CSV

Dados tabulares com uma linha por teste. Ideal para importação em Excel ou ferramentas de BI.

**Colunas:**

| Coluna | Descrição |
|--------|-----------|
| Timestamp | Data e hora da execução |
| Kind | `setup` ou `test` |
| Name | Nome do script |
| Type | Extensão (`.ps1` ou `.py`) |
| Status | `PASS`, `FAIL` ou `ERR` |
| Duration_s | Duração em segundos |
| ExitCode | Código de saída do processo |
| TraceCount | Quantidade de arquivos de evidência |
| TraceDir | Caminho da pasta de evidências |

### 11.3 Relatório JSON

Dados estruturados com metadados completos. Ideal para integração com APIs e sistemas de monitoramento.

**Campos principais:**

```json
{
  "RunTimestamp": "2026-04-15 09:00:00",
  "Host": "DESKTOP-ABC",
  "TotalScripts": 4,
  "Pass": 3,
  "Fail": 1,
  "Error": 0,
  "TotalDuration": 5432.1,
  "Scripts": [ ... ]
}
```

### 11.4 Qual Relatório Usar `[Gestão]`

| Necessidade | Formato recomendado |
|-------------|---------------------|
| Apresentar resultado a stakeholders | **HTML** (`_relatorio.html`) |
| Alimentar planilha de acompanhamento | **CSV** (`_relatorio.csv`) |
| Integrar com sistema de gestão de ativos | **JSON** (`_relatorio.json`) |
| Investigar causa de falha | **LOG** (`Logs/run_*.log`) |
| Auditoria de processo | **JSON** (`_state.json`) + evidências |

---

## 12. Glossário

| Termo | Definição |
|-------|-----------|
| **Aferição** | Uma medição individual dentro de um teste. Ex: cada uma das 5 medições de velocidade de rede |
| **Autonomia projetada** | Tempo que a bateria cheia duraria no ritmo de consumo medido numa fase: capacidade de carga cheia ÷ taxa média de descarga. É uma extrapolação linear, não uma descarga completa |
| **Bateria (teste de disco)** | Um ciclo completo de operações dentro de um teste. Ex: cada uma das 10 baterias de leitura/escrita do teste de disco |
| **Bateria (Módulo 5)** | O teste de consumo de energia na bateria do notebook (seção 8) |
| **Cenário** | Sessão de testes associada a uma máquina e data, agrupando runs e evidências |
| **Cooldown** | Período de espera entre ciclos de estresse para a CPU retornar ao estado ocioso |
| **DiskSPD** | Ferramenta de benchmarking de disco da Microsoft |
| **Economia de energia** | Recurso do Windows (antes "Economia de bateria") que reduz brilho e atividade em segundo plano; liga sozinho abaixo de um limite de carga. O teste o deixa desligado e sem acionamento automático |
| **Evidência** | Arquivo gerado por um teste que comprova o resultado (CSV, screenshot, log) |
| **Exit Code** | Código numérico retornado por um processo ao encerrar. `0` = sucesso, `≠ 0` = falha |
| **Fase de escritório** | Fase de 60 min do teste de bateria com a simulação de uso do Módulo 1 (documento, planilha e PDF no Edge), contínua |
| **Fase ociosa** | Fase de 60 min do teste de bateria com a tela ligada, sem aplicativos abertos pelo teste e sem entrada simulada; mede o consumo de fundo |
| **Hub** | O orquestrador (`hub.ps1`) que gerencia a execução dos testes |
| **Jitter** | Variação na latência de rede entre pacotes consecutivos |
| **Modo de energia** | Ajuste do Windows sobre o plano de energia (Melhor eficiência energética, Equilibrado, Melhor desempenho), configurado separadamente para a bateria |
| **mWh** | Miliwatt-hora: unidade da energia restante informada pela bateria; medida principal do teste de bateria |
| **Overlay** | Janela visual transparente exibida sobre a área de trabalho durante a execução de um teste |
| **Ping** | Tempo de ida e volta de um pacote de rede (latência) |
| **Pré-voo** | Etapa inicial do teste de bateria, na tomada: confere e ajusta o padrão da máquina e registra o antes/depois em `bateria_preflight.csv` |
| **Run** | Uma execução do hub (uma sessão de testes). Um cenário pode ter múltiplas runs |
| **Setup** | Fase de preparação do ambiente (instalação de dependências e configurações) |
| **State** | Arquivo `_state.json` que rastreia o estado de um cenário |
| **Throttling** | Redução automática de desempenho do processador por superaquecimento |
| **Throughput** | Quantidade de dados transferidos por unidade de tempo (MB/s ou Mbps) |
| **Trace** | Conjunto de evidências de uma execução |
| **WPA** | Windows Performance Analyzer — ferramenta de análise de desempenho do Windows |
