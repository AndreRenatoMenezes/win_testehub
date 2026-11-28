# Metodologia de Testes — Hardware Test Hub

**Versão:** 1.2  
**Data:** 2026-11-23  
**Público-alvo:** Equipe técnica, gestores, auditoria

---

## Sumário

1. [Introdução](#1-introdução)
2. [Arquitetura do Framework](#2-arquitetura-do-framework)
3. [Fase de Setup — Preparação do Ambiente](#3-fase-de-setup--preparação-do-ambiente)
4. [Módulo 0 — Consumo Basal](#4-módulo-0--consumo-basal)
5. [Módulo 1 — CPU e Memória](#5-módulo-1--cpu-e-memória)
6. [Módulo 2 — Disco](#6-módulo-2--disco)
7. [Módulo 3 — Rede](#7-módulo-3--rede)
8. [Módulo 4 — Boot e Shutdown](#8-módulo-4--boot-e-shutdown)
9. [Módulo 5 — Bateria](#9-módulo-5--bateria)
10. [Módulo 6 — Wi-Fi Fast Transition (802.11r)](#10-módulo-6--wi-fi-fast-transition-80211r)
11. [Módulos 7 a 11 — Cargas de Desenvolvimento](#11-módulos-7-a-11--cargas-de-desenvolvimento)
12. [Rastreabilidade e Evidências](#12-rastreabilidade-e-evidências)
13. [Formatos de Relatório](#13-formatos-de-relatório)
14. [Glossário](#14-glossário)

---

## 1. Introdução

### 1.1 Objetivo

O **WinTestHub** (Hardware Test Hub) é um framework de validação de hardware projetado para avaliar o desempenho e a estabilidade dos principais componentes de uma máquina Windows: processador, memória, disco, rede, ciclo de boot/shutdown, consumo de bateria e roaming Wi-Fi com Fast Transition (802.11r). Os testes simulam cenários de uso intensivo e coletam métricas objetivas para determinar se o equipamento atende aos padrões operacionais esperados.

### 1.2 Escopo

**O que é testado:**
- Consumo basal de CPU e RAM da máquina em repouso (sistema total, Top 15 processos e agentes de segurança)
- Desempenho de CPU e memória sob estresse sustentado
- Velocidade de leitura e escrita do disco principal
- Velocidade de conexão de rede (download, upload, latência, jitter) no speedtest interno e na internet (fast.com)
- Tempo de inicialização (boot) e desligamento (shutdown) do Windows
- Consumo de energia na bateria (máquina ociosa e sob carga de escritório no LibreOffice) e tempo real de bateria até 10%, com a autonomia normalizada para 100% → 0%
- Roaming Wi-Fi entre APs com Fast Transition (802.11r) e compatibilidade de adaptador, driver e BIOS
- Tempo de tarefas reais de desenvolvimento (build .NET e Go, testes, `pip install`, containers, git e arquivos pequenos) com repositórios open source fixados

**O que NÃO é testado:**
- Periféricos (teclado, mouse, webcam, impressora)
- GPU / desempenho gráfico
- Saúde da bateria, ciclos de carga e descarga abaixo de 10% (a saúde é registrada pelo setup `1_captura_infos_pc`)
- Conformidade de software (licenciamento, versões)

### 1.3 Como Usar Este Documento para Auditoria `[Gestão]`

Este documento descreve o **procedimento padronizado** de cada teste. Para auditar uma execução:

1. Identifique o **cenário** em `Execucoes/` (pasta com nome, hostname e data)
2. Abra o `Traces/_relatorio.html` do cenário para ver o resumo de resultados
3. Compare os procedimentos descritos neste documento com as evidências coletadas
4. Verifique a cadeia de custódia usando o `_state.json` (seção 12)

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
│  │ Preparação do ambiente (13 scripts)          │   │
│  │ Pode ser ignorada via config.json            │   │
│  └──────────────────────────────────────────────┘   │
│                       │                             │
│                       ▼                             │
│  ┌─── Fase 2: Testes ───────────────────────────┐   │
│  │ 12 módulos de teste + 2 variantes            │   │
│  │ Seleção via menu checkbox interativo         │   │
│  │ Checagem antes da fila (pré-requisitos e     │   │
│  │ sobras de teste); sobras limpas entre testes │   │
│  │ Frequência da CPU amostrada em cada teste    │   │
│  └──────────────────────────────────────────────┘   │
│                       │                             │
│                       ▼                             │
│  ┌─── Saídas ───────────────────────────────────┐   │
│  │ Execucoes/  → logs, traces e estado          │   │
│  │ Exportar/   → traces prontos p/ o Drive      │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

> ![Diagrama de Arquitetura](img/placeholder-diagrama-arquitetura.png)  
> *Insira aqui: diagrama visual do fluxo de execução do framework*

#### Controles que protegem a medição

- **Checagem antes da fila.** Antes de iniciar, o hub confere o que os testes selecionados precisam: o perfil `.wpaProfile` dos módulos 0, 1 e 5 (o módulo 0 reutiliza o de `1_cpu_memo` quando não há cópia própria), o Windows Performance Toolkit, o LibreOffice (`soffice.exe`) para o `1_automacao_performance.py`, a URL do speedtest, as ferramentas de dev e a `podman machine`, a tomada, a internet e o espaço em disco. O que impede um teste precisa de uma decisão explícita do operador (tirar o teste da fila ou continuar); a decisão fica registrada.
- **Sobras de teste.** Processos que um teste abriu e não fechou (sessão do WPR, `wpaexporter`, LibreOffice da automação com perfil `wintesthub_lo_profile`, Edge da automação, `diskspd`, Python de teste, build servers do .NET, stack do Podman) consomem recursos e contaminariam o teste seguinte. A checagem aponta essas sobras, e entre um teste e outro o hub encerra as do teste que acabou. Entre testes, só são encerrados os processos que o próprio teste abriu (o hub compara com os processos que já existiam antes do teste); antes da fila, os build servers do .NET aparecem só como aviso, porque podem ser do Visual Studio do usuário. A sessão do WPR, a stack do Podman e a `podman machine` seguem a pasta do teste que as usa.
- **Frequência da CPU.** Durante cada teste (exceto setups, o módulo 0 de consumo basal e o teste 5 de bateria), o hub registra a cada 5 s o uso da CPU, o desempenho relativo ao clock base, o MHz efetivo e a maior temperatura das zonas térmicas ACPI, em `<módulo>/frequencia_cpu.csv`. Uma queda do clock sob carga de 20% ou mais entre o 1º e o último minuto vira aviso de **throttling**: uma máquina que esquenta mede pior, e isso não deve ser atribuído ao agente. A leitura usa CIM (não `Get-Counter`, cujos nomes mudam no Windows pt-BR); o custo é uma consulta a cada 5 s, bem abaixo de 1% de CPU, e fica ativo também durante o módulo 1. As zonas ACPI servem para comparar máquinas sob a mesma carga, não como temperatura absoluta do processador. No módulo 0, o amostrador é desligado via `CpuSampler.SkipFolders` para evitar ruído de consultas WMI paralelas durante o repouso.
- **Avisos da rodada.** Tudo o que pode qualificar um resultado (checagem, sobras, módulo sem evidência, CSV faltando, carga de dev com falha ou sensível à rede, throttling) fica no `_state.json` e aparece no `_relatorio.html`/`.json`, junto das evidências exportadas.

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
| `HUB_EVIDENCE_DIR` | Pasta de evidências para o teste atual | `Execucoes/Cenario_PC01_2026-04-15/Traces/2_disco/` |
| `HUB_TRACE_DIR` | Idêntica a `HUB_EVIDENCE_DIR` | (mesmo acima) |
| `HUB_TRACE_ROOT` | Pasta `Traces` do cenário | `Execucoes/Cenario_PC01_2026-04-15/Traces/` |

Os testes **nunca devem salvar arquivos na pasta raiz do projeto**. Toda evidência deve ser direcionada para `HUB_EVIDENCE_DIR`.

---

## 3. Fase de Setup — Preparação do Ambiente

### 3.1 Objetivo

Padronizar a configuração da máquina de teste antes da execução dos módulos de diagnóstico. Isso garante que todos os equipamentos são testados em condições equivalentes, eliminando variáveis de configuração que poderiam influenciar os resultados.

### 3.2 Scripts de Preparação

| Script | Descrição | Justificativa |
|--------|-----------|---------------|
| `1_captura_infos_pc` | Coleta informações do sistema (CPU, RAM, disco, bateria, SO) em `informacoes_maquina.csv` | Registro de identidade da máquina para rastreabilidade |
| `2_opcoes_energia` | Aplica o plano **Equilibrado**, desativa a suspensão e o desligamento da tela (na tomada e na bateria) e define "nada a fazer" ao fechar a tampa | Evita suspensão durante os testes e mantém o mesmo plano em todas as máquinas |
| `3_softwares_msStore` | Instala via winget o Windows ADK, o CrystalDiskMark, o CrystalDiskInfo e o LibreOffice | Garante as ferramentas auxiliares e a suíte de escritório local do Módulo 1 |
| `4_install_python` | Instala o Python 3.12 oficial e remove o alias da Microsoft Store | Pré-requisito para os scripts de teste em Python |
| `5_install_py_dependencies` | Cria `.venv` e instala pacotes Python | Isola dependências e garante versões corretas |
| `6_pausa_WinUpdate` | Pausa o Windows Update por 35 dias e desliga o compartilhamento ponto a ponto do Delivery Optimization (`DODownloadMode = 0`) | Evita downloads, reinicializações e tráfego de atualizações em segundo plano durante os testes (inclusive o de rede) |
| `7_install_devtools_dev` | Instala Git, .NET SDK 10, Go, uv e docker-compose (idempotente). Via winget; quando o winget não executa na conta (ex.: sessão elevada com outra conta) ou não resolve um item, baixa o instalador oficial e só o executa com assinatura digital válida do fabricante (Git, .NET, Go) ou com o SHA256 publicado no release (uv, docker-compose) | Ferramentas exigidas pelos módulos 7 a 11 |
| `8_enable_diagnostics` | Desativa a Inicialização Rápida e habilita os serviços DPS e SysMain e a política WDI de diagnóstico de boot | Necessário para o teste de boot/shutdown (eventos 100 e 200 no Event Log) |
| `9_AdicionarTecladoUSInt` | Adiciona o layout de teclado EUA-Internacional ao idioma pt-BR | Padronização de ambiente |
| `10_preparar_podman` | Confere a virtualização, ativa o WSL2 (pede reinício quando preciso), instala o Podman CLI e liga a `podman machine` rootful | Pré-requisito do módulo 10 (containers) |
| `11_ca_corporativa_dev` | Opcional: detecta inspeção TLS; só se houver, exporta a cadeia confiável do Windows para PEM, define as variáveis de CA e instala o PEM na VM do Podman | Em redes sem inspeção (como a do laboratório) não altera nada |
| `12_remover_appx_bloatware` | Remove aplicativos pré-instalados (Xbox, Copilot, Teams, Notícias, Solitaire, LinkedIn, WhatsApp, To Do) | Reduz processos em segundo plano que variam entre imagens |
| `13_remover_onedrive` | Desinstala o OneDrive e bloqueia a reinstalação por política | Evita sincronização em segundo plano durante as medições |

### 3.3 Justificativa da Padronização `[Gestão]`

A Fase de Setup é essencial para a **comparabilidade dos resultados**. Sem ela, diferenças de configuração entre máquinas (plano de energia, atualizações em andamento, falta de dependências) poderiam gerar variações nos resultados que não refletem o desempenho real do hardware. A padronização garante que diferenças nos resultados entre máquinas são atribuíveis ao hardware, não à configuração de software.

---

## 4. Módulo 0 — Consumo Basal

### 4.1 Objetivo

Medir o consumo basal de CPU e RAM da máquina 100% em repouso (sem carga de trabalho aberta), separando o consumo total do Windows, os 15 processos mais pesados e a fatia exata dos agentes de segurança (EDR, DLP, AV, Zero Trust). O módulo permite comparar a imagem limpa contra a imagem com agentes instalados com evidência rastreável.

O script é `Testes/0_consumo_basal/0_teste_consumo_basal.py` e aparece no topo da Fase 2 do hub (seção **Consumo Basal**, antes do Módulo 1).

### 4.2 Ferramentas Utilizadas

- **`psutil`** — amostragem contínua a cada `1,0 s` de CPU total do sistema (`%`), frequência atual (`MHz`), RAM usada (`MB` e `%`), RAM disponível (`MB`) e uso de CPU/RAM RSS por processo (agrupado pelo nome do executável, excluindo `System Idle Process`/PID 0 e o próprio processo Python do Teste 0)
- **Windows Performance Recorder (`wpr.exe`) e Windows Performance Analyzer (`wpaexporter.exe`)** — captura `Power.light` + `VirtualAllocation.light` e exportação CSV usando `Agentes_SI_Profile.wpaProfile` (procurado em `Testes/0_consumo_basal/` ou reutilizado automaticamente de `Testes/1_cpu_memo/`)
- **`pynput`** — monitoramento passivo de teclado e mouse (marca `Interacao_Detectada = sim` no ciclo se o operador tocar na máquina, exceto `Ctrl+Q`)
- **`tkinter`** — overlay *click-through* com o aviso `"Não utilize mouse ou teclado — medindo consumo basal"`

### 4.3 Procedimento

Antes de iniciar, o hub desliga o `CpuSampler` externo em PowerShell (`0_consumo_basal` está em `CpuSampler.SkipFolders` no `config.json`), evitando ruído de consultas WMI paralelas durante a coleta ociosa.

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Verificação de pré-requisitos (`wpr.exe`, `wpaexporter.exe`, módulos Python e resolução do `.wpaProfile`) | segundos |
| 2 | **Estabilização inicial** — aguarda a dissipação do pico de inicialização do Python/Tkinter com a máquina parada | 60 segundos |
| 3 | **3 ciclos ociosos** — em cada ciclo: inicia captura WPR (`Power.light` + `VirtualAllocation.light`), coleta amostras `psutil` a cada `1,0 s` e monitora interações humanas | 3 × 180 segundos (3 min cada) |
| 4 | Salva `Trace_Basal_<data>_Run<N>.etl` e exporta via `wpaexporter.exe` (quando o `.wpaProfile` está disponível) | ~15–30 s por ciclo |
| 5 | **Cooldown** entre ciclos (após os ciclos 1 e 2) | 30 segundos |
| 6 | Consolidação das amostras `psutil` e dos CSVs do WPA em `consumo_basal.csv`, `ciclos_basal.csv`, `top_processos_basal.csv` e `Resultados_Consolidados/` | ~5 s |

**Tempo total estimado:** ~11 minutos.

### 4.4 Métricas Coletadas

| Arquivo | Conteúdo |
|---------|----------|
| `consumo_basal.csv` | CSV temático (`Metrica,Valor,Unidade`): `Versao_Teste` (`1.0`), `Ciclos_Executados` (`3`), `Duracao_Por_Ciclo` (`180`), `Estabilizacao_Inicial` (`60`), `Amostras_Totais` (`~540`), `Interacao_Humana_Detectada` (`nao`/`sim`), `CPU_Sistema_Media`, `_Mediana`, `_P95`, `_Pico`, `_Min` (`%`), `RAM_Total_GB`, `RAM_Usada_Media_MB`, `_Mediana_MB`, `_Pico_MB`, `RAM_Usada_Media_Pct`, `RAM_Disponivel_Media_GB`, `Self_Overhead_CPU_Media`, `Self_Overhead_RAM_Media_MB`, `Top1_CPU_Processo`/`_Media`, `Top1_RAM_Processo`/`_Media_MB` e métricas WPA (`WPA_<Arquivo>_<Metrica>_Soma_Media`, `_Media`, `_Max`) |
| `ciclos_basal.csv` | Uma linha por ciclo: `Ciclo,Timestamp_Inicio,Duracao_s,Amostras,Interacao_Detectada,CPU_Media_Pct,CPU_Mediana_Pct,CPU_P95_Pct,CPU_Pico_Pct,RAM_Usada_Media_MB,RAM_Usada_Pico_MB,RAM_Usada_Media_Pct` |
| `top_processos_basal.csv` | Top 15 processos por CPU média (`Ranking_Por=CPU`) e Top 15 por RAM RSS média (`Ranking_Por=RAM`), somando instâncias do mesmo executável e excluindo Idle e o próprio Teste 0 |
| `Resultados_Consolidados/` | CSVs consolidados por perfil (`Media_*.csv`), `Relatorio_Resumo.csv` e `Relatorio_Resumo.html` (incluindo `Soma_Media`, o peso agregado de todos os agentes filtrados pelo `.wpaProfile`) |

> **Imagem limpa:** quando nenhum processo do filtro do `.wpaProfile` está ativo (caso esperado na imagem sem agentes de segurança), os CSVs exportados pelo WPA vêm vazios (0 linhas de dados); o teste não falha e registra `0.00` em `WPA_*_Soma_Media`, `_Media` e `_Max`.

### 4.5 Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| Os 3 ciclos completam sem erro e gravam `consumo_basal.csv`, `ciclos_basal.csv` e `top_processos_basal.csv` | **PASS** (exit code 0) |
| Falha no WPR/`wpaexporter`, falta de pré-requisitos, ciclos incompletos ou `Ctrl+Q` | **FAIL** (exit code 1) |

### 4.6 Como Interpretar `[Gestão]`

- Compare `consumo_basal.csv` do cenário **ImagemLimpa** com o do cenário **ComAgentes** na mesma máquina.
- **`CPU_Sistema_Mediana` e `CPU_Sistema_P95`** mostram o impacto basal real no sistema, sem distorção de picos pontuais.
- **`WPA_*_Soma_Media`** mostra o peso agregado de todos os agentes de segurança monitorados pelo `.wpaProfile`.
- **`Self_Overhead_*`** registra o custo residual do próprio script de medição (já excluído de `top_processos_basal.csv`).
- Execuções com `Interacao_Humana_Detectada = sim` tiveram movimento de mouse ou tecla durante um ciclo; confira `ciclos_basal.csv` para saber em qual ciclo ocorreu antes de comparar cenários.

### 4.7 Interrupção Segura e Detecção de Interação

Movimentos de mouse ou teclas comuns durante um ciclo ativo são registrados como aviso no log e marcam `Interacao_Detectada = sim` no ciclo, sem interromper nem reprovar a execução. Pressionar **`Ctrl+Q`** cancela imediatamente a captura WPR (`wpr.exe -cancel`), fecha o overlay, sinaliza a parada da fila ao hub e encerra com exit code 1.

---

## 5. Módulo 1 — CPU e Memória

### 5.1 Objetivo

Avaliar o desempenho e a estabilidade do processador e da memória sob carga de escritório local e 100% offline no **LibreOffice** (Writer e Calc), medindo o tempo de abertura dos aplicativos, o tempo de relógio e a CPU consumida no recálculo de uma planilha pesada (a **planilha R2**: 5.000 linhas e 100.000 fórmulas, a mesma carga do teste do macOS) e o consumo contínuo de CPU e RAM do sistema e do LibreOffice sob captura WPR/WPA.

### 5.2 Ferramenta Utilizada

- **LibreOffice Writer e Calc** (`soffice.exe` / `soffice.bin`) — executados com subperfis temporários isolados (`-env:UserInstallation=file:///.../wintesthub_lo_profile_<papel>` onde `<papel>` é `batch`, `writer` ou `calc`) e flags `--norestore --nologo --nodefault --nolockcheck`, garantindo *cold start* real, processos independentes e execução 100% offline sem necessidade de login
- **Gerador determinístico das planilhas de carga** (`zipfile` + XML da stdlib Python) — cria localmente `workload_doc.odt` (título e 20 parágrafos iniciais) e `workload_calc_r2.xlsx`, a **planilha R2** do teste do macOS (`gen_cpu_r2_workload.py`): aba `Data` com 5.000 linhas (`seq`, `value`, `category`, `date`), aba `Calc` com 5.000 × 20 fórmulas — agregações condicionais sobre a coluna inteira (`SUMIFS`, `COUNTIFS`, `AVERAGEIFS`, `MAXIFS`), buscas (`INDEX`/`MATCH`, `VLOOKUP`, `XLOOKUP`, `INDIRECT`), estatística em janela móvel (`STDEV`, `VAR`, `PERCENTILE`, `RANK`), financeiras (`NPV`, `PMT`, `FV`, `IPMT`) e texto/lógica —, aba `Trigger` (onde a edição GUI digita) e aba `Sentinel` (soma os cantos da aba `Calc` e prova que o recálculo aconteceu). As fórmulas são gravadas sem valor em cache, então o LibreOffice calcula as 100.000; o texto é idêntico ao do macOS, só `MAXIFS` e `XLOOKUP` levam o prefixo `_xlfn.` do Excel (sem ele o LibreOffice mostra `#NOME?`)
- **Windows Performance Recorder (`wpr.exe`) e Windows Performance Analyzer (`wpaexporter.exe`)** — captura `Power.light` + `VirtualAllocation.light` e exportação CSV com o perfil `Agentes_SI_Profile.wpaProfile`
- **`psutil` + `pyautogui` / `pyperclip`** — thread amostradora contínua (intervalo de 1,0 s) coletando CPU (%) e RAM (MB e %) do sistema e da árvore de processos `soffice.exe`/`soffice.bin` do teste, combinada com automação GUI real no Writer e no Calc

### 5.3 Procedimento

Antes do Ciclo 1, o script valida a presença do `soffice.exe` (via `HUB_LIBREOFFICE_PATH`, `PATH` ou caminhos padrão em `C:\Program Files\LibreOffice\program\soffice.exe` e `C:\Program Files (x86)\LibreOffice\program\soffice.exe`) e gera os arquivos `workload_doc.odt` e `workload_calc_r2.xlsx` em pasta temporária. Os subperfis `batch` e `calc` nascem configurados para sempre recalcular `.xlsx` ao abrir e para gravar `.xlsx` sem o diálogo de formato.

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Estabilização inicial do ciclo e criação de cópias limpas dos arquivos ODF e dos 3 subperfis `wintesthub_lo_profile_*` | 15 segundos |
| 2 | Início da captura WPR (`Power.light` + `VirtualAllocation.light`) e do amostrador `psutil` (1,0 s) | — |
| 3 | **Etapa 1 — Cálculo de fórmulas complexas (`Tempo_Calculo_Formulas_s` e `CPU_Calculo_Formulas_s`):** executa `soffice.exe --headless --convert-to ods` com subperfil `wintesthub_lo_profile_batch` sobre a planilha R2, cronometrando o tempo de relógio até o término e somando a CPU (usuário + sistema, todos os núcleos) dos processos `soffice` desse subperfil. Confere no `.ods` gerado que `Sentinel.A2` tem valor diferente de zero (senão o ciclo é FAIL) e conta as células com erro da aba `Calc` — o esperado são 50 `#N/A` na coluna `f6`, da própria planilha R2 | dentro da janela de 300 s (timeout 180 s) |
| 4 | **Etapa 2 — Abertura do Writer (`Tempo_Abertura_Writer_s`):** inicia `soffice.exe --writer` com subperfil `wintesthub_lo_profile_writer` abrindo `workload_doc.odt`, cronometrando até o processo `soffice.bin` estar ativo e sua janela principal visível | dentro da janela de 300 s (timeout 60 s) |
| 5 | **Etapa 3 — Abertura do Calc (`Tempo_Abertura_Calc_s`):** inicia `soffice.exe --calc` com subperfil `wintesthub_lo_profile_calc` abrindo a planilha R2 (que é recalculada inteira ao abrir), cronometrando até o processo `soffice.bin` estar ativo e sua janela principal visível; antes da edição, espera o Calc terminar o recálculo (CPU do `soffice.bin` abaixo de 5% de um núcleo) | dentro da janela de 300 s (timeout 180 s) |
| 6 | **Etapa 4 — Edição GUI contínua:** no restante da janela de 300 s, alterna o foco confirmado (`SetForegroundWindow`/`GetForegroundWindow`) entre Writer (digitação de parágrafos, negrito `Ctrl+A`/`Ctrl+B`, `Ctrl+S`) e Calc (na aba `Trigger`: inserção de linhas, recálculo completo forçado `Ctrl+Shift+F9` das 100.000 fórmulas, espera até o Calc ficar ocioso e `Ctrl+S` mantendo `.xlsx`) | restante dos 300 segundos (5 min) |
| 7 | Encerramento seletivo dos processos `soffice` do teste (`wintesthub_lo_profile`), parada do WPR (`.etl`) e exportação via `wpaexporter.exe` | ~30s |
| 8 | **Cooldown inteligente** — aguarda 3 leituras consecutivas de CPU < 15% a cada 10 s | até 300 segundos (5 min) |
| 9 | Repetição dos passos 1–8 por **5 ciclos** e consolidação final (`cpu_memoria.csv`, `ciclos_libreoffice.csv` e `Resultados_Consolidados/`) | ~50 min total |

**Ciclo visual:**

```
Ciclo 1          Ciclo 2          Ciclo 3          Ciclo 4          Ciclo 5
┌──────┬──────┐ ┌──────┬──────┐ ┌──────┬──────┐ ┌──────┬──────┐ ┌──────┬──────┐
│Carga │Cool- │ │Carga │Cool- │ │Carga │Cool- │ │Carga │Cool- │ │Carga │Cool- │
│ 5min │down  │ │ 5min │down  │ │ 5min │down  │ │ 5min │down  │ │ 5min │down  │
└──────┴──────┘ └──────┴──────┘ └──────┴──────┘ └──────┴──────┘ └──────┴──────┘
```

### 5.4 Métricas Coletadas

| Arquivo / Métrica | Fonte | Formato / Descrição |
|-------------------|-------|---------------------|
| `cpu_memoria.csv` | Script Python + `psutil` + WPA | CSV temático (`Metrica,Valor,Unidade`): `Versao_Teste` (`2.1`), `Ciclos_Executados`, `Duracao_Por_Ciclo`, `Tempo_Abertura_Writer_Media`/`_Max`, `Tempo_Abertura_Calc_Media`/`_Max`, `Tempo_Calculo_Formulas_Media`/`_Max`/`_Min`, `CPU_Calculo_Formulas_Media`/`_Max`/`_Min` (CPU do cálculo, em s), `CPU_Sistema_Media`/`_Pico`, `RAM_Sistema_Media_MB`/`_Pico_MB`/`_Media_Pct`/`_Pico_Pct`, `LibreOffice_CPU_Media`/`_Pico`, `LibreOffice_RAM_Media_MB`/`_Pico_MB`, métricas legadas de hardware (`CPU_Frequencia_*`, `CPU_Nucleos_*`, `RAM_*`) e `WPA_<Arquivo>_<Metrica>_Soma_Media`/`_Media`/`_Max`/`_Min` |
| `ciclos_libreoffice.csv` | Script Python + `psutil` | CSV detalhado por ciclo (5 linhas, ciclos `1` a `5`): `Ciclo,Timestamp_Inicio,Tempo_Abertura_Writer_s,Tempo_Abertura_Calc_s,Tempo_Calculo_Formulas_s,CPU_Calculo_Formulas_s,Linhas_Editadas_Calc,Paragrafos_Digitados_Writer,CPU_Sistema_Media_Pct,CPU_Sistema_Pico_Pct,RAM_Sistema_Media_MB,RAM_Sistema_Pico_MB,RAM_Sistema_Media_Pct,RAM_Sistema_Pico_Pct,LibreOffice_CPU_Media_Pct,LibreOffice_CPU_Pico_Pct,LibreOffice_RAM_Media_MB,LibreOffice_RAM_Pico_MB,Cooldown_Duracao_s` |
| `Resultados_Consolidados/` | Windows Performance Analyzer (`wpaexporter.exe`) | CSVs consolidados por perfil `.wpaProfile` (`Media_*.csv`), `Relatorio_Resumo.csv` e `Relatorio_Resumo.html` |

> **Versões do teste:** `Versao_Teste = 2.1` usa a planilha R2 (100.000 fórmulas; cerca de 18 s de CPU no cálculo numa máquina de 12 threads). A `2.0` usava uma planilha de 25.000 fórmulas simples (cerca de 2 s de CPU). Os tempos e o consumo das duas versões **não se comparam**: compare `ImagemLimpa` e `ComAgentes` sempre com a mesma versão.

### 5.5 Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| Todos os 5 ciclos completados sem erro | **PASS** (exit code 0) |
| Qualquer ciclo falha, crash ou timeout | **FAIL** (exit code 1) |

### 5.6 O que um FAIL Significa `[Gestão]`

Uma falha neste teste indica que o processador ou a memória da máquina não conseguiram sustentar carga contínua por 5 ciclos de estresse. Possíveis causas:

- **Superaquecimento** — o processador ativou proteção térmica (thermal throttling)
- **Instabilidade de memória** — erros de memória causaram crash no processo
- **Driver ou firmware** — incompatibilidades de software afetando a performance
- **Recurso insuficiente** — memória RAM insuficiente para a carga aplicada

**Ação recomendada:** Investigar logs detalhados em `Execucoes/<cenário>/Logs/run_*.log` e verificar se o hardware apresenta defeitos.

### 5.7 Interrupção Segura

O operador pode interromper o teste a qualquer momento pressionando `Ctrl+Q`. O teste é encerrado de forma controlada: a captura WPR em andamento é cancelada, o log registra a interrupção e o resultado é **FAIL** (exit code 1).

### 5.8 Variante DLP/USB `[Técnico]`

O script `1-1_automacao_performance_dlp.py` mede o custo de CPU e memória do **agente de DLP** ao inspecionar cópias para um pendrive. Ele aparece no menu na mesma seção do Módulo 1 (**Cpu Memo**) e exige um pendrive montado em `E:\` (configurável em `USB_DRIVE`, no topo do script).

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Gera, na pasta do script, um arquivo de 100 MB com nome e extensão que acionam o DLP (`relatorio_financeiro_confidencial.xlsx`) | uma vez |
| 2 | Estabilização | 15 segundos |
| 3 | **Captura WPR** (`Power.light` + `VirtualAllocation.light`) enquanto o arquivo é copiado repetidamente para o pendrive | 60 segundos |
| 4 | Exportação WPA com o perfil `Agentes_SI_Profile.wpaProfile` | ~30s |
| 5 | Cooldown inteligente (aguarda a CPU cair abaixo de 15%) | até 300 segundos |
| 6 | Repetição dos passos 2–5 por **5 ciclos**, seguida da consolidação | — |

Um bloqueio do DLP durante a cópia fica registrado como aviso no log e não interrompe o ciclo.

**Evidências:** subpasta `1_cpu_memo/dlp_usb/`, separada das do Módulo 1, com os traces `Trace_DLP_*.etl`, os CSVs exportados, `Resultados_Consolidados/` e `cpu_memoria_dlp.csv`.

| Condição | Resultado |
|----------|-----------|
| Os 5 ciclos completados e consolidados sem erro | **PASS** (exit code 0) |
| Falha ao iniciar ou salvar a captura WPR, interrupção (`Ctrl+Q`) ou erro inesperado | **FAIL** (exit code 1) |

---

## 6. Módulo 2 — Disco

### 6.1 Objetivo

Medir a velocidade de leitura e escrita sustentada do disco principal, avaliando o desempenho de I/O sob operações sequenciais com blocos grandes.

### 6.2 Ferramenta Utilizada

- **Microsoft DiskSPD** (`diskspd.exe`) — ferramenta oficial da Microsoft para benchmarking de disco
- **psutil** — para identificação do disco principal

### 6.3 Procedimento

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

### 6.4 Métricas Coletadas

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

### 6.5 Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| Todas as 10 baterias completadas e CSV gerado | **PASS** (exit code 0) |
| Falha em qualquer bateria ou CSV não gerado | **FAIL** (exit code 1) |

### 6.6 Como Interpretar os Valores `[Gestão]`

Os valores de velocidade dependem do tipo de disco:

| Tipo de disco | Leitura esperada | Escrita esperada |
|---------------|------------------|------------------|
| HDD (7200 RPM) | 100–200 MB/s | 80–160 MB/s |
| SSD SATA | 400–550 MB/s | 300–520 MB/s |
| SSD NVMe | 1500–7000 MB/s | 1000–5000 MB/s |

Valores **significativamente abaixo** do esperado para o tipo de disco podem indicar: disco com defeito, driver desatualizado, superaquecimento, ou fragmentação excessiva (HDD).

### 6.7 Variante DLP/USB `[Técnico]`

O script `2-1_teste_disco_dlp.py` mede a velocidade de escrita e leitura num pendrive com o **agente de DLP** ativo, usando cópia nativa de arquivos (sem o DiskSPD). Ele aparece no menu na seção **Disco** e exige um pendrive montado em `E:\` (configurável em `USB_DRIVE`, no topo do script).

| Etapa | Descrição |
|-------|-----------|
| 1 | Gera, na pasta do script, um arquivo de 2 GB (`planilha_teste_carga.xlsx`) |
| 2 | **Escrita:** copia o arquivo do PC para o pendrive e mede a velocidade em MB/s |
| 3 | **Leitura:** copia o arquivo de volta do pendrive para o PC e mede a velocidade em MB/s |
| 4 | Intervalo de 30 segundos entre baterias |
| 5 | Repetição dos passos 2–4 por **5 baterias** e geração dos CSVs |

Se o DLP bloquear a escrita, apagar o arquivo do pendrive ou negar a leitura, a bateria registra 0,0 MB/s na operação afetada, e o log descreve o bloqueio.

**Evidências:** `2_disco/` com `resultado_validacao_usb_*.csv`, `teste_usb_nativo_*.log` e `disco_usb.csv`.

| Condição | Resultado |
|----------|-----------|
| As 5 baterias completadas e os CSVs gerados | **PASS** (exit code 0) |
| Pendrive não encontrado, interrupção (`Ctrl+Q`) ou erro inesperado | **FAIL** (exit code 1) |

---

## 7. Módulo 3 — Rede

### 7.1 Objetivo

Aferir a velocidade da conexão de rede da máquina por **dois caminhos**, nas mesmas condições:

- **Interno:** o speedtest interno (OpenSpeedTest) do laboratório. Mede a rede corporativa até um servidor controlado e é a referência mais estável para comparar máquinas.
- **Internet:** o fast.com (Netflix), pelo mesmo caminho do tráfego real do usuário. Em máquinas com agente **zero trust**, o tráfego para destinos internos pode não passar pelo agente (bypass ou túnel distinto), enquanto o tráfego para a internet passa pelo proxy/túnel e pela inspeção SSL. Esta fonte captura o impacto do agente na navegação.

As duas fontes são medidas no mesmo teste, em **rodadas intercaladas**, para que uma mudança de condição da rede ao longo da execução afete as duas por igual. O script é `Testes/3_rede/3_teste_rede.py`. Os cálculos ficam em `Testes/_lib/rede_calc.py`.

### 7.2 Ferramenta Utilizada

- **Microsoft Edge** via Selenium WebDriver, com o driver obtido automaticamente pelo Selenium Manager. Cada fonte usa o **próprio Edge com perfil temporário** (sem cache, extensões nem sincronização), apagado no fim.
- **Servidor de speedtest interno** (URL em `config.local.json` → `SpeedtestUrl`, ou `HUB_SPEEDTEST_URL`, não versionada). Só nesta fonte os erros de certificado são ignorados, porque o servidor é acessado por IP via HTTPS.
- **fast.com** (Netflix): speedtest público, sem anúncios, que usa servidores de borda próximos ao cliente. Os erros de certificado **não** são ignorados: a inspeção SSL do agente atua como atuaria para o usuário. O teste grava no painel de configurações do site uma **duração fixa** (mínima = máxima, padrão 20 s) e um **número fixo de conexões paralelas** (padrão 8), no lugar do modo automático, que encurta ou alonga a medição conforme a rede.
- **`ping.exe`** para a latência ICMP até o servidor interno, independente do navegador.
- **`psutil`**, `Get-NetAdapter` e `netsh wlan` para o tráfego de fundo e a conexão de cada rodada.

> **Nota:** o `speed.cloudflare.com` foi avaliado e descartado porque exige verificação antirrobô antes de iniciar a medição, o que impede a execução desassistida.

### 7.3 Procedimento

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Abre um Edge por fonte. No da internet, grava a configuração fixa do fast.com | ~15 s |
| 2 | Aguarda a rede acalmar: até 30 s com o tráfego de fundo abaixo do limite (o Edge recém-aberto baixa componentes) | 5–30 s |
| 3 | **Rodadas intercaladas:** aquecimento interno, aquecimento internet, interno 1, internet 1, interno 2… até 10 de cada | ~18 min |
| 4 | Gera o `resultado_afericoes.csv` e o `rede.csv` (regravados a cada rodada) | ~1 s |

Cada rodada segue os passos abaixo:

1. Lê a conexão ativa: interface, cabo ou Wi-Fi, velocidade do link e, no Wi-Fi, banda, canal, sinal e BSSID.
2. Mede o **tráfego de fundo** da interface por 5 s, com nada rodando. Acima de 1000 kbps, a rodada fica marcada como **contaminada**.
3. **Interno:** faz 10 pings ICMP ao servidor (se ele não responder a ping, o ICMP é desligado no restante da execução), abre o speedtest, inicia e espera o sinal de fim da própria página ("All done"), sem tempo fixo. O limite é de 120 s.
4. **Internet:** abre o fast.com, que inicia sozinho, e espera download, latência e upload concluírem. O limite é de 120 s.
5. Lê as métricas na página, salva o screenshot e deixa o Edge daquela fonte em página em branco, para ele não gerar tráfego durante a rodada da outra.

A 1ª rodada de cada fonte é **aquecimento**: fica registrada, mas não entra nas estatísticas. Nas execuções de 24/11/2026, a 1ª rodada do fast.com tinha upload 1,7 vez maior que as demais.

### 7.4 Métricas Coletadas

| Métrica | Fonte | Unidade | Descrição |
|---------|-------|---------|-----------|
| Download | as duas | Mbps | Velocidade de download |
| Upload | as duas | Mbps | Velocidade de upload |
| Ping | as duas | ms | Latência sem carga (no fast.com, "Não carregados") |
| Jitter | interno | ms | Variação da latência medida pelo speedtest |
| Ping ICMP / Jitter ICMP | interno | ms | Mediana e variação (média das diferenças sucessivas) de 10 pings. N/A se o servidor não responde a ICMP |
| Latência sob carga | internet | ms | Latência durante a transferência ("Carregada"); indica fila (bufferbloat). **Só informativa:** varia demais para comparar |
| Tráfego de fundo | as duas | kbps | Tráfego da interface nos 5 s antes da rodada |
| Conexão | as duas | texto | Interface, cabo/Wi-Fi, link (Mbps); no Wi-Fi, banda, canal, sinal e BSSID |
| Local do cliente, IP de saída, servidores | internet | texto | Por onde o tráfego saiu e quais servidores mediram |

**Estatística por fonte**, só com as rodadas medidas (sem aquecimento), válidas e não contaminadas:

- **mediana** (o número principal, robusto a uma rodada fora da curva);
- média, **P25 e P75** (quartis), **CV %** (desvio-padrão amostral ÷ média), mínimo e máximo;
- **`Estavel`** = `sim` quando o CV do download e o do upload ficam no máximo em 10%.

> **Nota:** no Windows 11, o `netsh wlan` exige a permissão de **Localização** (e às vezes elevação) para informar banda, canal, sinal e BSSID. Sem ela, esses campos ficam N/A, e o tipo (Wi-Fi ou cabo) continua vindo do `Get-NetAdapter`.

### 7.5 Evidências Geradas

Na pasta `3_rede/` do cenário:

- `teste_rede_<data_hora>.log`: log completo da execução.
- `resultado_afericoes.csv`: uma linha por rodada (separador `;`, decimal com vírgula). A coluna `Rodada` mostra `A1` para o aquecimento e `1`…`10` para as medidas. Colunas: `Fonte;Rodada;Aquecimento;Status;Motivo;Data_Hora;Duracao_s;Download;Upload;Ping;Jitter;Latencia_Carga;Ping_ICMP;Jitter_ICMP;Trafego_Fundo_Kbps;Contaminada;Interface;Conexao_Tipo;Link_Mbps;Wifi_Banda;Wifi_Canal;Wifi_Sinal;Wifi_BSSID;Local_Cliente;IP_Saida;Servidores;Config_Fast;Print`.
- `rede.csv`: CSV temático (`Metrica,Valor,Unidade`, decimal com ponto):
  - linhas gerais: `Versao_Teste` (2.0), `Rodadas_Configuradas`, `Aquecimento_Por_Fonte`, `Conexao_Tipo` (`cabo`, `wifi` ou `misto`) e `Roaming`;
  - um bloco por fonte (`Interno_*` e `Internet_*`) com `Status`, `Motivo`, `Rodadas_Executadas`, `Rodadas_Validas`, `Rodadas_Contaminadas` e `Estavel`, e para cada métrica `<Metrica>_Mediana`, `_Media`, `_P25`, `_P75`, `_CV`, `_Min` e `_Max` (ex.: `Interno_Download_Mediana`);
  - na internet, também `Internet_Config_Fast`, `Internet_Local_Cliente`, `Internet_IP_Saida` e `Internet_Servidores` (o valor mais frequente).
- `Evidencia_Rede_Interno_<A1|01..10>_<data_hora>.png` e `Evidencia_Rede_Internet_<A1|01..10>_<data_hora>.png`: screenshot de cada rodada.
- `Evidencia_Rede_Internet_Bloqueio_<data_hora>.png` e `Evidencia_Rede_Interno_Falha_<data_hora>.png`: só quando a página não carregou.

### 7.6 Critério de Aprovação

Cada fonte termina com um status:

| Status | Condição |
|--------|----------|
| **ok** | Pelo menos 8 rodadas válidas de 10 (`MinValidas`) |
| **parcial** | Alguma rodada válida, mas menos que o mínimo |
| **off** | Nenhuma rodada válida. O motivo fica registrado: URL não configurada, site bloqueado, 3 falhas seguidas ou rodadas contaminadas |

| Condição | Resultado |
|----------|-----------|
| Pelo menos uma fonte terminou **ok** | **PASS** (exit code 0) |
| Nenhuma fonte terminou ok | **FAIL** (exit code 1) |

Uma fonte **parcial** ou **off**, uma fonte **instável** (`Estavel=nao`), medição no **Wi-Fi** e **troca de AP** durante o teste viram avisos na seção "Avisos da rodada" do `_relatorio`, sem reprovar o teste.

- O fast.com bloqueado (página não carrega ou o site acusa erro) para de ser medido na hora, com screenshot da tela exibida. O interno segue sozinho.
- Um erro isolado numa rodada conta só aquela rodada como falha. Depois de 3 falhas seguidas, a fonte vira off.

A checagem antes da fila acusa:
- **Atenção** quando falta a URL interna (só a internet será medida) ou não há internet (só o interno será medido);
- **Impede** quando faltam as duas.

### 7.7 Referência de Valores Aceitáveis `[Gestão]`

> **Nota:** a tabela abaixo deve ser preenchida pela equipe conforme os padrões da organização. Use as **medianas** do speedtest interno.

| Métrica | Mínimo aceitável | Ideal |
|---------|-------------------|-------|
| Download | ___ Mbps | ___ Mbps |
| Upload | ___ Mbps | ___ Mbps |
| Ping | ___ ms (máximo) | ___ ms |
| Jitter | ___ ms (máximo) | ___ ms |

### 7.8 Como Analisar `[Gestão]`

A rede é a métrica que mais varia entre execuções. Em 24/11/2026, o fast.com mediu 532 Mbps às 19:31 e 80 Mbps às 23:17 na mesma máquina: o horário e os servidores escolhidos pelo site mudaram. Para que a diferença medida seja da máquina ou do agente, e não da internet:

- **Use a mediana.** A média de poucas rodadas é arrastada por uma rodada fora da curva.
- **Só compare execuções com `Estavel=sim`** nas duas pontas. Com `nao`, repita o teste antes de concluir.
- **Use cabo para comparar hardware.** O Wi-Fi é a maior fonte de variação. Se precisar ser Wi-Fi, use o mesmo AP, a mesma banda e a mesma posição. Confira `Wifi_Banda`, `Wifi_Canal` e `Wifi_Sinal` no `resultado_afericoes.csv`, e descarte execuções com `Roaming=sim`.
- **O interno é a referência.** O fast.com escolhe o servidor sozinho. Só compare execuções do fast.com com os **mesmos servidores** (`Internet_Servidores`) e na **mesma janela de horário**; de preferência, alterne baseline e candidata no mesmo período.
- **Rodadas contaminadas** (`Rodadas_Contaminadas` > 0) indicam tráfego em segundo plano: confira o Setup 6 e processos de atualização antes de repetir.
- **A latência sob carga é só informativa.** Nas medições de referência, ela variou com CV de 51%.
- **Agente zero trust:** compare o `Internet_*` do cenário baseline com o do cenário com agente. O **local do cliente** e o **IP de saída** mostram por onde o tráfego saiu: com o agente ativo, espera-se o nó de saída do provedor do agente. Se continuarem iguais aos do baseline, o tráfego provavelmente não passou pelo agente.
- O fast.com mede até a borda de conteúdo da Netflix mais próxima, muitas vezes dentro do próprio provedor de internet. O resultado representa a navegação cotidiana, não o trânsito internacional.

### 7.9 Configuração `[Técnico]`

Bloco `Rede` do `config.json`. `HUB_REDE_RODADAS` sobrescreve `Rodadas`, para testes rápidos.

| Chave | Padrão | Uso |
|-------|--------|-----|
| `Rodadas` | 10 | Rodadas medidas por fonte |
| `Aquecimento` | 1 | Rodadas de aquecimento por fonte (fora da estatística) |
| `MinValidas` | 8 | Rodadas válidas para a fonte ficar ok (no máximo `Rodadas`) |
| `LimiteCV` | 10 | CV máximo (%) do download e do upload para `Estavel=sim` |
| `MaxFalhasSeguidas` | 3 | Falhas seguidas até a fonte virar off |
| `TimeoutInternoSeg`, `TimeoutInternetSeg` | 120 | Limite de cada rodada |
| `FastDuracaoSeg`, `FastConexoes` | 20, 8 | Configuração fixa do fast.com |
| `PingsICMP` | 10 | Pings ao servidor interno por rodada (0 desliga) |
| `JanelaFundoSeg`, `LimiteTrafegoFundoKbps` | 5, 1000 | Janela e limite do tráfego de fundo |

---

## 8. Módulo 4 — Boot e Shutdown

### 8.1 Objetivo

Avaliar o tempo de inicialização e desligamento do Windows através de múltiplos ciclos de reinicialização, identificando degradações e gargalos no processo de boot.

### 8.2 Ferramenta Utilizada

- **Agendador de Tarefas do Windows** (Task Scheduler) — para automatizar reinicializações
- **Event Log de Diagnósticos do Windows** (`Microsoft-Windows-Diagnostics-Performance/Operational`) — fonte de métricas de boot/shutdown
- **PowerShell** (`boot_shutdown_duration.ps1`) — para análise dos eventos

### 8.3 Procedimento

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

### 8.4 Métricas Coletadas

| Métrica | Unidade | Descrição |
|---------|---------|-----------|
| MainPathBootTime | milissegundos | Tempo do caminho principal de boot |
| BootPostBootTime | milissegundos | Tempo de atividades pós-boot |
| ShutdownDuration | milissegundos | Tempo total de desligamento |
| Eventos de degradação | texto | Detalhamento de causas de lentidão |

### 8.5 Critérios de Avaliação

O teste utiliza **limiares progressivos**:

| Métrica | Normal | Aviso (Warning) | Crítico |
|---------|--------|-----------------|---------|
| Tempo de boot | < 30s | 30s – 60s | > 60s |
| Tempo de shutdown | < 20s | 20s – 60s | > 60s |

### 8.6 Critério de Aprovação

| Condição | Resultado |
|----------|-----------|
| Nenhum evento **crítico** nos boots do dia atual | **PASS** (exit code 0) |
| Pelo menos um evento crítico encontrado | **FAIL** (exit code 1) |

> **Nota:** Eventos de "aviso" (warning) são registrados no relatório mas **não causam FAIL**. Apenas eventos críticos reprovam o teste.

### 8.7 Impacto de Degradação de Boot `[Gestão]`

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

## 9. Módulo 5 — Bateria

### 9.1 Objetivo

Medir o consumo de energia e o **tempo real de bateria** do notebook em duas fases padronizadas — **60 minutos ociosa**, com a tela ligada, e uma **fase ativa de escritório no LibreOffice (Writer + Calc) que roda até a bateria chegar a 10%**, sem teto de tempo — para comparar o cenário **baseline** (sem agente) com o cenário **com agente de segurança** na mesma máquina. Antes de medir, o teste padroniza a máquina sozinho (**pré-voo**), relê cada ajuste e registra o valor antes e depois como evidência.

O script é `Testes/5_bateria/5_teste_bateria.py` (versão **2.0**). Ele aparece no menu do hub na seção **Escritório**, logo após **Boot Shutdown**, e precisa de um operador para desconectar o carregador. A carga de escritório roda 100% local — sem Edge, sem conta Google e sem login — e reaproveita a planilha **R2** do Módulo 1 pelo módulo compartilhado `Testes/_lib/libreoffice_workload.py`.

> **Versão 2.0 não é comparável com a 1.0.** A 1.0 rodava 60 + 60 min no Edge (Google Docs/Sheets/PDF), no modo **Melhor desempenho**, e só projetava a autonomia por extrapolação; a 2.0 usa o LibreOffice, o modo **Equilibrado** e mede a descarga real até 10%. Compare apenas execuções com o mesmo `Versao_Teste`. Os resultados também não são comparáveis com as medições antigas de 60% de CPU por 120 minutos (`cpu_stress_controller_pro.exe`).

### 9.2 Ferramentas Utilizadas

- **WMI de bateria** (`root\wmi`): `BatteryStatus` (energia restante em mWh, taxa de descarga, tensão), `BatteryFullChargedCapacity` e `BatteryCycleCount`, lidos por um único processo PowerShell que fica aberto durante o teste — a leitura custa poucos milissegundos por amostra e não pesa na fase ociosa
- **API do Windows**: `GetSystemPowerStatus` (fonte de alimentação, % de carga e estado da Economia de energia) e `powrprof` (modo de energia)
- **powercfg**: plano e configurações de energia da bateria, relatório de bateria (`/batteryreport`, antes e depois), SRUM (`/srumutil`) e relatório de energia (`/energy`)
- **Windows Performance Recorder** (`wpr.exe`, perfil `Power.light`) — um trace da fase ociosa e um da **1ª hora** da fase ativa — e **WPA Exporter** (`wpaexporter.exe`) com o perfil `Agentes_SI_Bateria_Profile.wpaProfile`
- **LibreOffice** (`soffice.exe`, instalado pelo setup `3_softwares_msStore.ps1`) — Writer com um documento `.odt` e Calc com a planilha R2 (5.000 linhas, 100.000 fórmulas), cada um num subperfil isolado `wintesthub_lo_profile_*`; o LibreOffice do usuário não é tocado
- **pyautogui/pyperclip** — digitação e edição simuladas; **psutil** — top 10 processos por CPU

### 9.3 Pré-voo de Padronização

O pré-voo roda **na tomada**, antes de pedir a desconexão do carregador. Cada item vira uma linha do `bateria_preflight.csv` com `Esperado`, `Antes`, `Acao`, `Depois`, `Situacao` (`ok`, `ajustado`, `não aplicável` ou `falhou`) e `Observacao`.

| Grupo | Item | Esperado | Como é tratado |
|-------|------|----------|----------------|
| Conferidos | Bateria presente | sim | Sem bateria (desktop ou bateria não reconhecida): falha em segundos, sem alterar nada |
| Conferidos | Carga inicial | ≥ 95% | Abaixo do mínimo: informa a carga atual e pede para carregar (aceita notebooks com limite de carga em 95–99%) |
| Conferidos | Ferramentas de captura | `wpr.exe` e `wpaexporter.exe` no PATH | Perfil WPA ausente gera só aviso (a exportação CSV é ignorada) |
| Conferidos | LibreOffice | `soffice.exe` encontrado | Ausente: falha em segundos, sem alterar nada, pedindo o Setup `3_softwares_msStore`. Aceita `HUB_LIBREOFFICE_PATH` |
| Conferidos | Conexão de rede | com acesso à internet | Mantém o rádio Wi-Fi ativo e a telemetria real dos agentes de SI. Registra `tipo \| rede \| sinal`; SSID ou sinal indisponíveis não reprovam |
| Conferidos | Monitor externo | nenhum | Também pega a tampa fechada com monitor externo |
| Ajustados | Plano de energia | Equilibrado | O mesmo plano do setup `2_opcoes_energia` |
| Ajustados | Modo de energia na bateria | **Equilibrado** | Padrão real do Windows na bateria. Sem a API do modo na bateria (Windows antigo): aplicado e conferido já na bateria |
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
| Na bateria | Modo de energia efetivo | Equilibrado | Conferido na estabilização |
| Na bateria | Economia de energia efetiva | desligada | Conferida na estabilização |

Regras:

- Os itens **ajustados** são aplicados, relidos e registrados; todo ajuste é **restaurado** ao final, por qualquer caminho de saída.
- O teste **não contorna política corporativa**: item bloqueado por GPO ou pelo sistema fica `falhou` com "bloqueado por política".
- Algum item `falhou`: o teste **não mede**, restaura o que já tinha alterado, lista os pendentes numa janela e sai com exit 1.
- Recurso inexistente na máquina (sem Bluetooth, sem sensor de luz, configuração ausente no plano) é `não aplicável` e não reprova.

### 9.4 Procedimento

| Etapa | Descrição | Duração |
|-------|-----------|---------|
| 1 | Checagens rápidas: bateria, carga, ferramentas, perfil WPA e LibreOffice | segundos |
| 2 | Rede com internet e ausência de monitor externo | ~5 s |
| 3 | Ajustes de energia (modo **Equilibrado**), brilho e Bluetooth; grava `bateria_preflight.csv` | ~15 s |
| 4 | Relatório de bateria "antes" (HTML e XML) e coletor WMI | ~5 s |
| 5 | **Aviso único**: desconectar o carregador e confirmar o checklist físico | até 10 min |
| 6 | **Estabilização** na bateria, fora da medição, com a conferência de brilho, modo e Economia | 5 min |
| 7 | **Fase ociosa**: tela ligada, nenhum aplicativo aberto pelo teste, nenhuma entrada simulada; trace WPR | 60 min fixos |
| 8 | Transição: salva o trace da ociosa, confere se a sessão está bloqueada, gera `workload_doc.odt` e `workload_calc_r2.xlsx`, abre o Writer e o Calc e espera o recálculo inicial da R2 | ~1–5 min |
| 9 | **Fase ativa — bloco 1** (primeiros 60 min): LibreOffice Writer + Calc com trace WPR | 60 min |
| 10 | Marca de 60 min: amostra-marco `fim_wpr_escritorio` e o trace `Trace_Bateria_Escritorio_*` é salvo — a fase ativa **continua** | ~1–5 min |
| 11 | **Fase ativa — bloco 2** (sem WPR): o mesmo ritmo de escritório até a bateria chegar a **10%** | até 10% (sem teto) |
| 12 | **Encerramento imediato em 10%**: fecha o LibreOffice, amostra final, relatório de bateria "depois", **grava `bateria.csv`** e **restaura todas as configurações** (inclusive tela/suspensão) | ~15 s |
| 13 | Janela de reconexão: espera o carregador (sondado a cada 2 s) ou os botões **Continuar na bateria** / **Pular exportação e finalizar** | até o operador |
| 14 | Pós-medição pesada: exportação WPA dos traces, SRUM e relatório de energia (60 s de observação) | ~5–30 min |

**Tempo total:** variável — depende da autonomia real. Conte com ~1h10 de preparação, estabilização e fase ociosa, mais o tempo de descarga da fase ativa até 10% (tipicamente 3–12 h).

Na fase ativa, o teste alterna turnos entre os dois aplicativos, com pausas realistas de 4–10 s:

- **Writer**: digita um parágrafo (via área de transferência), formata em ~30% dos turnos, rola o texto como leitura e salva (`Ctrl+S`). A cada **60 parágrafos** o texto é reiniciado para o `.odt` não crescer sem limite.
- **Calc**: preenche 2 linhas na aba `Trigger` (linhas cíclicas 1–25) e salva. A cada **~5 min** dispara o recálculo completo das 100.000 fórmulas da R2 (`Ctrl+Shift+F9`) e espera o Calc ficar ocioso — carga realista de escritório, não stress sintético contínuo.
- Perda de foco ou erro pontual: `Escape` e nova tentativa; se o Writer ou o Calc fechar sozinho, só ele é relançado (subperfil novo) e a descarga continua.

Durante toda a medição:

- A tela fica ligada e a sessão não é bloqueada por inatividade, sem simular teclado ou mouse (`SetThreadExecutionState`).
- Uma **amostra** da bateria é gravada a cada 60 s (com flush) e o **top 10 processos** a cada 5 min. A cada amostra e marco, o estado é gravado de forma atômica em `bateria_checkpoint.json` — se a bateria apagar antes de 10%, os dados ficam preservados até o último minuto.
- Uma **vigia** a cada 5 s encerra a medição de forma controlada se o carregador for reconectado, se a carga chegar a **10%** (proteção de bateria), se o operador pressionar Ctrl+Q ou se o relógio saltar mais de 120 s entre dois tiques (`hibernacao_inesperada`: a máquina suspendeu ou hibernou).
- O overlay mostra fase e carga; na fase ativa, também o tempo decorrido e se o WPR está ativo ou já salvo. Na fase ociosa ele só muda a cada amostra, para não gerar atividade de tela.

### 9.5 Métricas Coletadas

As métricas saem das amostras-marco tiradas nos limites exatos das fases (`inicio_fase`, `fim_wpr_escritorio` e `fim_fase`). A **energia em mWh é a medida principal**; o percentual de carga é complementar.

| Métrica (`bateria.csv`) | Unidade | Como é calculada |
|-------------------------|---------|------------------|
| `Protecao_Bateria_Limite` | % | Carga em que a descarga real termina (`10`) |
| `Tempo_Total_Bateria_Real_min` / `_h` | min / h | Tempo real na bateria, do início da fase ociosa ao fim da fase ativa |
| `Energia_Total_Consumida` | mWh | Energia restante no início da ociosa − energia restante no fim da fase ativa |
| `Taxa_Media_Global` | W | Energia total ÷ tempo total |
| `Autonomia_Real_Equivalente_100pct` | h | Tempo total × (capacidade de carga cheia ÷ energia total): autonomia **normalizada para 100% → 0%**, comparável entre execuções que começaram em 95–100%. Sem capacidade: tempo total × 100 ÷ queda de carga |
| `Ociosa_Duracao_Medida` / `Escritorio_Duracao_Medida` | min | Tempo entre os dois marcos da fase (`Escritorio_Duracao_Medida_h` em horas) |
| `Ociosa_Energia_Consumida` / `Escritorio_Energia_Consumida` | mWh | Energia restante no início − energia restante no fim |
| `Ociosa_Taxa_Media_Descarga` / `Escritorio_Taxa_Media_Descarga` | W | Energia consumida ÷ duração |
| `Escritorio_1h_Taxa_Media_Descarga` | W | Taxa média da **1ª hora** da fase ativa (o mesmo intervalo do trace WPR). `N/A` se a bateria chegou a 10% antes de 60 min |
| `Ociosa_Queda_Carga` / `Escritorio_Queda_Carga` | pp | % de carga no início − % no fim |
| `Ociosa_Queda_Carga_Hora` / `Escritorio_Queda_Carga_Hora` | pp/h | Queda de carga ÷ duração |
| `Ociosa_Autonomia_Projetada` / `Escritorio_Autonomia_Projetada` | h | Capacidade de carga cheia ÷ taxa média de descarga da fase (extrapolação) |
| `Tempo_Abertura_Writer` / `Tempo_Abertura_Calc` | s | Do lançamento à janela visível (o Calc inclui o recálculo inicial da R2 até a janela) |
| `Paragrafos_Digitados_Writer`, `Linhas_Editadas_Calc`, `Recalculos_Calc_R2` | un | Contadores da carga de escritório |
| `Energia_Estimada` | texto | `sim` quando a bateria não informa mWh (ou informa capacidade em unidade relativa): a energia é estimada pela queda de % × capacidade de carga cheia |
| `Carga_Bateria_Inicial` / `Carga_Bateria_Final` | % | Carga no início da fase ociosa e na amostra final |
| `Capacidade_Carga_Cheia` / `Capacidade_Projeto` | mWh | WMI de bateria; a capacidade de projeto vem do relatório de bateria quando o WMI não a informa |
| `Ciclos_Carga` | un | Ciclos de carga informados pela bateria |
| `Plano_Energia` | texto | Plano após o pré-voo |
| `Modo_Energia` / `Brilho` | texto / % | Valor predominante nas amostras das fases medidas (`Equilibrado`, 50%) |
| `Bluetooth` | texto | `desligado` ou `ausente` |
| `Desvios_Padronizacao` | un | Amostras das fases medidas com brilho ≠ 50%, modo ≠ Equilibrado ou Economia ligada |
| `Versao_Teste`, `Coleta_Valida`, `Motivo_Encerramento` | texto | Versão do teste (`2.0`), `sim`/`nao` e o motivo do fim da medição |

`Motivo_Encerramento`: `protecao_bateria`, `carregador_reconectado`, `parada_segura`, `sessao_bloqueada`, `hibernacao_inesperada`, `padronizacao_na_bateria` ou `erro`. Fase sem dados = `N/A`. Formato: separador `,`, decimal com ponto e 2 casas.

### 9.6 Evidências Geradas

Na pasta `5_bateria/` do cenário:

- `teste_bateria_<data_hora>.log` — log completo da execução
- `bateria_preflight.csv` — uma linha por item do pré-voo (separador `;`): `Item;Esperado;Antes;Acao;Depois;Situacao;Observacao`. A coluna `Antes` permite restaurar a máquina à mão se o processo for encerrado à força
- `bateria_relatorio_antes.html` / `bateria_relatorio_antes.xml` e `bateria_relatorio_depois.html` — relatório de bateria do Windows antes e depois da medição
- `bateria_amostras.csv` — uma amostra a cada 60 s e os marcos de cada fase (separador `;`, decimal com vírgula): `Data_Hora;Fase;Tipo;Decorrido_Fase_s;Carga_Pct;Energia_Restante_mWh;Taxa_Descarga_mW;Tensao_mV;Fonte;Brilho_Pct;Modo_Energia;Economia_Energia;Desvio`. `Fase` = `estabilizacao`, `ociosa`, `transicao`, `escritorio` ou `encerramento`; `Tipo` = `periodica`, `inicio_fase`, `fim_wpr_escritorio` ou `fim_fase`
- `bateria_checkpoint.json` — estado da medição (fase, motivo, última amostra, marcos, contadores do LibreOffice, desvios), regravado de forma atômica a cada amostra e marco
- `bateria_top_processos.csv` — top 10 processos por CPU a cada 5 min: `Data_Hora;Fase;Posicao;Processo;PID;CPU_Pct;Memoria_MB`. `CPU_Pct` é a média do processo na janela de 5 min, em % da máquina
- `Trace_Bateria_Ociosa_<data_hora>.etl` e `Trace_Bateria_Escritorio_<data_hora>.etl` — trace de energia da fase ociosa e da 1ª hora da fase ativa (parcial, se a fase encerrou antes)
- `CSV_Ociosa_<data_hora>/` e `CSV_Escritorio_<data_hora>/` — exportação dos traces pelo perfil WPA de bateria (só se a exportação não foi pulada)
- `bateria_srum.csv` — relatório SRUM (`powercfg /srumutil`)
- `bateria_relatorio_energia.html` — relatório de energia (`powercfg /energy`, 60 s)
- `bateria.csv` — CSV temático (`Metrica,Valor,Unidade`). É gravado sempre que a medição começou, inclusive em encerramento antecipado, e **antes** da pós-medição pesada

Nada é gravado em `C:\BATERIA`, em `C:\Traces` nem na raiz do projeto. Os arquivos do LibreOffice ficam numa pasta temporária (`wintesthub_lo_bateria_*`), removida no encerramento.

### 9.7 Critério de Aprovação

O PASS/FAIL decide se a **coleta é válida**; não há limiar de autonomia ou consumo.

| Condição | Resultado |
|----------|-----------|
| Pré-voo e conferência na bateria ok, fase ociosa completa, fase ativa iniciada e drenada até a proteção de bateria (**10%**, qualquer duração), leitura de energia (medida ou estimada) nas duas fases, `bateria.csv` e `bateria_amostras.csv` gravados | **PASS** (exit code 0) |
| Sem bateria, carga abaixo de 95%, ferramentas ou LibreOffice ausentes, item fora do padrão ou bloqueado por política, sem internet, monitor externo — antes de pedir a desconexão | **FAIL** (exit code 1) |
| Carregador não desconectado em 10 minutos | **FAIL** (exit code 1) |
| Brilho, modo ou Economia fora do padrão já na bateria (`padronizacao_na_bateria`) | **FAIL** (exit code 1) |
| Carregador reconectado durante a estabilização ou a medição | **FAIL** (exit code 1) |
| Proteção de bateria (10%) ainda na fase ociosa ou na transição | **FAIL** (exit code 1) |
| Sessão bloqueada no início da fase ativa | **FAIL** (exit code 1) |
| Suspensão ou hibernação no meio da medição (`hibernacao_inesperada`) | **FAIL** (exit code 1) |
| Sem leitura de energia numa das fases (bateria sem mWh e sem capacidade de carga cheia) | **FAIL** (exit code 1) |
| Parada segura (Ctrl+Q) ou erro inesperado | **FAIL** (exit code 1) |

> **Nota:** não há mínimo de duração para a fase ativa: um notebook com bateria degradada que chega a 10% com 12 min de fase ativa também produz uma medição real válida. Desvios de padronização durante a medição e falhas nas evidências complementares (exportação CSV, SRUM, relatório de energia — inclusive quando a exportação é pulada) **não reprovam**: ficam como aviso no log e, no caso dos desvios, em `Desvios_Padronizacao`.

### 9.8 Como Interpretar `[Gestão]`

- Compare o `bateria.csv` do cenário **baseline** com o do cenário **com agente**, executados na **mesma máquina**, na **mesma rede** e com a **mesma versão do teste** (`Versao_Teste = 2.0`).
- A **fase ociosa** mostra o custo de fundo do agente — é onde 1–2 W de diferença aparecem com mais clareza. A **fase ativa** representa o uso real de escritório.
- Para o tempo de bateria, use `Autonomia_Real_Equivalente_100pct`: ela normaliza execuções que começaram em 95% ou 100%. `Tempo_Total_Bateria_Real_*` é o tempo bruto medido (de ~95–100% até 10%).
- Use a **taxa média de descarga (W)** e a **energia consumida (mWh)** como medidas de consumo; a queda em % tem resolução de 1 ponto e é complementar. `Escritorio_1h_Taxa_Media_Descarga` é o intervalo que tem trace WPR para atribuição por processo.
- Só compare execuções com `Coleta_Valida = sim` e `Desvios_Padronizacao = 0`. `Energia_Estimada = sim` indica menor precisão.
- A **autonomia projetada** por fase continua sendo uma extrapolação linear; o tempo real vem das métricas `Tempo_Total_*` e `Autonomia_Real_*`.
- O `bateria_top_processos.csv` e os traces `.etl` (no WPA) ajudam a atribuir a diferença de consumo a processos específicos.

### 9.9 Interrupção Segura

Assim como no Módulo 1, o teste pode ser interrompido com **Ctrl+Q**. Fechar a janela do monitor do teste (pela barra de tarefas ou Alt+F4) e um Ctrl+C recebido pelo teste têm o mesmo efeito. A parada segura salva o trace parcial, fecha o LibreOffice do teste, grava o que já foi medido (`bateria.csv` com `Coleta_Valida = nao`), restaura as configurações alteradas e sai com exit code 1, sem rodar a exportação pesada.

Se o processo for encerrado à força (por exemplo, fechando a janela do hub), a restauração automática não roda: use a coluna `Antes` do `bateria_preflight.csv` para voltar brilho, Bluetooth e configurações de energia aos valores anteriores. O `bateria_checkpoint.json` e o `bateria_amostras.csv` preservam o que foi medido até ali.

---

## 10. Módulo 6 — Wi-Fi Fast Transition (802.11r)

### 10.1 Objetivo

Verificar se a máquina (adaptador Wi-Fi + driver + firmware/BIOS + Windows) faz **roaming com Fast BSS Transition (802.11r)** ao trocar de AP dentro da mesma rede. Sem FT, cada troca de AP passa por uma reautenticação completa (4-way handshake e, em redes 802.1X, o RADIUS), o que gera interrupções perceptíveis em chamadas de voz/vídeo e VPN. O teste também coleta tudo o que interfere nessa compatibilidade, para explicar um FAIL.

### 10.2 Ferramentas Utilizadas

- **API nativa de WLAN do Windows (`wlanapi.dll`)**, lida pelo script: BSSID, RSSI e qualidade a cada 250 ms; notificações de associação/roaming; cache de varredura com os *Information Elements* de cada AP.
- **`netsh wlan show interfaces`**: AKM da associação atual (`akm = 00-0f-ac:NN`), relida a cada 2 s e logo após cada troca de AP.
- **`netsh wlan show drivers` / `wirelesscapabilities`**: capacidades declaradas pelo driver (Transição Rápida, 802.11k, 802.11v, SAE, MFP).
- **Ping ICMP (`IcmpSendEcho`)** a cada 200 ms para o gateway e para a internet (`8.8.8.8`).
- **Painel ao vivo** no navegador (servidor local em `127.0.0.1`), sem dependência de internet.

O teste **não altera nenhuma configuração** do sistema, do adaptador ou da rede, e não força varreduras Wi-Fi.

### 10.3 Procedimento

1. **Pré-voo:** exige o Wi-Fi conectado — a rede conectada é a rede testada. Registra SSID, BSSID inicial, autenticação, cifra, AKM, banda, canal, RSSI e gateway.
2. **Coleta de compatibilidade:** adaptador e propriedades avançadas (Roaming Aggressiveness, banda preferida, MIMO Power Save...), driver (versão, data, fornecedor, INF), capacidades sem fio, BIOS, modelo, SO/build, plano e economia de energia do adaptador sem fio, adaptadores virtuais/VPN ativos e perfil WLAN (**sem a senha**).
3. **Inventário de APs:** para cada BSSID do SSID no cache de varredura, AKMs anunciadas (RSN IE), Mobility Domain/MDID (802.11r), 802.11k (RM) e 802.11v (BSS Transition).
4. **Caminhada (5 min):** o painel abre no navegador; o operador clica em **Iniciar caminhada** (ou o início é automático após 60 s) e anda pelo escritório passando por áreas de APs diferentes. O painel mostra AP atual, RSSI, gráficos de RSSI e latência, e destaca cada troca com a classificação.
5. **Pós-processamento:** exportação do log `WLAN-AutoConfig/Operational` do período, relatório WLAN do Windows (`wlanreport`), classificação de cada troca, CSVs e relatório HTML.

### 10.4 Classificação de Cada Troca de AP

| Classificação | Regra |
|---------------|-------|
| **FT** | Após a troca, a AKM conectada é de Fast Transition — FT-802.1X (`00-0f-ac:03`), FT-PSK (`:04`), FT-SAE (`:09`), FT-802.1X-SHA384 (`:0d`), FT-FILS (`:10`/`:11`), FT-PSK-SHA384 (`:13`), FT-SAE-EXT-KEY (`:19`) — **e não houve desconexão** |
| **Não FT** | A AKM após a troca não é de FT (ex.: PSK, 802.1X, SAE), ou a troca passou por desconexão (reconexão completa) |
| **Indeterminado** | A AKM após a troca não pôde ser lida (driver não informa) |

O tempo de troca vem das notificações WLAN do Windows, quando disponíveis, e é dividido em duas fases:

- **Reassociação:** início do roaming → autenticação no AP novo. É a troca pelo ar (autenticação FT e reassociação) e a parte comparável ao tempo de roaming mostrado pela controladora (WLC).
- **Conclusão no Windows:** autenticação → roaming concluído (instalação de chaves, liberação da porta e aviso aos programas). A WLC não enxerga essa fase.

Sem notificações, só o total pela amostragem (resolução de 250 ms). O início é procurado desde o fim do roaming anterior, porque tentativas demoradas começam segundos antes de o BSSID mudar; trocas acima de 1 s são sinalizadas como **demoradas**. Os carimbos usam relógio de alta resolução (< 1 ms). A interrupção é o maior intervalo sem resposta do gateway em torno da troca.

### 10.5 Métricas Coletadas

O `wifi_ft.csv` (formato `Metrica,Valor,Unidade`) traz: SSID, autenticação, cifra, AKM conectada, adaptador, versão/data/fornecedor do driver, firmware, BIOS, build do SO, suporte declarado a FT/802.11k/802.11v, APs vistos/com FT anunciado/utilizados, duração da caminhada, roamings (total, FT, não FT, indeterminados, com desconexão, demorados), tempo de troca total, de reassociação e de conclusão no Windows (média, mediana e máximo), interrupção média/máxima (gateway e internet), perda e latência média/p95 (gateway e internet), RSSI mínimo/médio/máximo e resultado.

### 10.6 Evidências Geradas

| Arquivo | Conteúdo |
|---------|----------|
| `wifi_ft_relatorio.html` | Relatório com gráficos (RSSI × tempo com marcadores de roaming, linha do tempo de APs, latência/perda, tempo de troca e interrupção por roaming), tabelas de roamings, achados de compatibilidade, APs e informações técnicas. Abre sem internet |
| `wifi_ft.csv` | CSV temático |
| `wifi_ft_roamings.csv` | Uma linha por troca de AP |
| `wifi_ft_amostras.csv` | Série de 250 ms: BSSID, RSSI, qualidade, canal, taxas |
| `wifi_ft_pings.csv` | Todos os pings (gateway e internet) |
| `wifi_ft_eventos_wlan.csv` | Notificações WLAN (associação, roaming, desconexão) |
| `wifi_ft_compatibilidade.json` | Toda a coleta de compatibilidade e os achados |
| `brutos/` | Saídas de `netsh`/PowerShell/`powercfg`, log `WLAN-AutoConfig` (`.evtx` e `.txt`) e `wlan-report.html` |

### 10.7 Critério de Aprovação

| Resultado | Condição |
|-----------|----------|
| **PASS** | Pelo menos **1** troca de AP classificada como **FT** |
| **FAIL** | Wi-Fi desconectado no início; nenhuma troca de AP; apenas trocas Não FT; ou apenas trocas indeterminadas |

Tempo de troca e perda de pacotes são registrados, mas não reprovam. Ping para a internet bloqueado vira `N/A` e não reprova.

### 10.8 Como Interpretar `[Gestão]`

- **FAIL "nenhuma troca de AP":** o operador não se afastou o suficiente do AP inicial, ou só há 1 AP do SSID no percurso. Não indica problema da máquina.
- **FAIL "nenhum com Fast Transition" com o achado "a rede usa PSK/802.1X/SAE":** o 802.11r não está habilitado no SSID (configuração da controladora/AP), não é problema da máquina.
- **FAIL com a rede anunciando FT, mas a máquina conectando sem FT:** suspeite do driver/adaptador (veja "Transição Rápida" nas capacidades e a idade do driver) ou de política do Windows.
- **Interrupções altas mesmo com FT:** verifique economia de energia do adaptador, Roaming Aggressiveness, adaptadores virtuais/VPN e RSSI muito baixo antes da troca (o cliente esperou demais para trocar).

---

## 11. Módulos 7 a 11 — Cargas de Desenvolvimento

### 11.1 Objetivo

Medir quanto tempo um desenvolvedor espera nas tarefas reais do dia a dia (compilar, rodar testes, instalar dependências, subir containers, operar o git) e, com isso, o impacto combinado do hardware e da imagem corporativa (EDR, DLP, antivírus) sobre o trabalho de desenvolvimento. As cargas vêm do processo de homologação de notebooks para desenvolvimento e usam **repositórios open source fixados por tag**, para que qualquer máquina meça exatamente o mesmo código.

Os cinco módulos são independentes (um por linguagem ou ferramenta) e podem ser escolhidos separadamente no menu:

| Módulo | Pasta | Cargas | Repositório (tag fixa) |
|--------|-------|--------|------------------------|
| 7 — .NET | `7_dev_dotnet` | A4a build limpo, A4b build incremental (1 arquivo alterado no Domain), A4c testes de unidade | `jasontaylordev/CleanArchitecture` `v11.0.0` (.NET 10, 13 projetos) |
| 8 — Go | `8_dev_go` | A5a `go build` com cache limpo, A5c `go test` de todos os pacotes | `gohugoio/hugo` `v0.169.0` (toolchain `go1.27.0` fixada por `GOTOOLCHAIN`) |
| 9 — Python | `9_dev_python` | A6a `pip install` de dependências travadas num venv novo, A6b `pytest -n auto` | `pydantic/pydantic` `v2.14.4` (CPython 3.12 gerenciado pelo `uv`) |
| 10 — Containers | `10_dev_containers` | A7a `podman build --no-cache` multi-stage, A7b `podman compose up` até `healthy` | Dockerfile do Hugo `v0.169.0`; stack pública SQL Server + RabbitMQ + Redis |
| 11 — Git e arquivos | `11_dev_git_arquivos` | B1 criar/ler/apagar 20 mil arquivos de 4 KB, B3 `git clone --local` + `git status` | `home-assistant/core` `2026.11.2` (~31 mil arquivos) |

### 11.2 Ferramentas Utilizadas

- **Biblioteca comum `Testes/_lib/dev_cargas.py`**: executa as cargas descritas no `cargas.json` de cada módulo, cronometra só o comando medido (`time.perf_counter`), aplica o limite de tempo, monitora tomada e Ctrl+Q e grava as evidências. Não aparece no menu.
- **Ferramentas de desenvolvimento** instaladas pelos setups `7_install_devtools_dev` (Git, .NET SDK 10, Go, uv, docker-compose) e `10_preparar_podman` (WSL2, Podman CLI e `podman machine` rootful).
- **`psutil`** para ler a tomada e encerrar a árvore de processos de uma carga (msbuild, go, podman).

### 11.3 Procedimento

1. **Pré-checagem:** o módulo exige a máquina **na tomada** (na bateria, não mede nada e reprova) e confere cada ferramenta do módulo e a versão mínima. Ferramenta ausente reprova o módulo antes de qualquer medição.
2. **Repositórios:** clona (ou reaproveita) cada repositório na pasta de trabalho (`%USERPROFILE%\wintestehub-dev-work`, configurável por `DevWorkDir` no `config.local.json`), faz checkout da tag fixa e limpa a árvore (`git reset --hard` + `git clean -fdx`). Fora da medição.
3. **Preparo (1x por carga):** downloads e builds de aquecimento que a carga pressupõe (ex.: `go mod download`, pull das imagens). Fora da medição.
4. **Execuções (3 por carga):** `setup` → **`command` cronometrado** → `cleanup`. O `setup` deixa o estado inicial igual em toda execução (ex.: apaga `bin/obj`, limpa o cache do Go, recria o venv); o `cleanup` desfaz o que a carga criou.
5. **Monitoramento contínuo:** a cada 0,5 s o módulo confere o limite de tempo e o Ctrl+Q; a cada 2 s, a tomada. Desconectar a tomada ou apertar Ctrl+Q interrompe a carga em curso, roda o `cleanup` e encerra o módulo com FAIL. O Ctrl+Q também para a fila do hub: os módulos seguintes não rodam. Já a tomada desconectada só encerra o módulo atual.
6. **Registro:** versões das ferramentas, plano de energia, tomada, commit dos repositórios e digests das imagens de container entram no JSON do módulo.

### 11.4 Referência e Limite de Tempo

O limite de cada carga é **10 vezes o tempo medido no notebook de referência** (o notebook atual da frota), comparando frio com frio: a 1ª execução (caches do sistema vazios) é limitada a 10x a execução fria da referência, e as seguintes a 10x a mediana. Sem essa separação, cargas com aquecimento grande (ex.: A4c, cuja execução fria é 7x a mediana) reprovariam indevidamente em máquinas só um pouco mais lentas. A referência é gerada uma vez, rodando cada módulo avulso com `--calibrar` no notebook de referência, e fica versionada no `referencia.json` do módulo (mediana, fria e os dois limites por carga, modelo de CPU, RAM, data e versões das ferramentas; sem hostname).

- A carga que passa do limite é **encerrada** (processo e todos os filhos) e fica como `TEMPO_EXCEDIDO`.
- Módulo sem `referencia.json`, ou carga sem entrada nele (ex.: cargas internas do `workloads.local.json`): roda sem limite, com aviso no log e no JSON.

### 11.5 Métricas Coletadas

| Métrica | Descrição |
|---------|-----------|
| `mediana_s` | Mediana das 3 execuções do comando medido, em segundos |
| `fria_s` | Tempo da 1ª execução (caches de disco do SO ainda frios) |
| `execucoes_s` | Todos os tempos medidos |
| `limite_s` | Limite das execuções 2 e 3 (10x a mediana da referência) ou vazio; o da 1ª execução (10x a fria da referência) fica no JSON (`limite_fria_s`) |
| Parciais do B1 | Tempos de criar, ler e apagar (linhas `B1-arquivos-pequenos:criar` etc.) |
| `sensivel_rede` | `sim` nas cargas que dependem de rede durante a medição (A6a, A7a) |

### 11.6 Evidências Geradas

| Arquivo | Conteúdo |
|---------|----------|
| `dev_<modulo>.csv` | CSV temático: `carga;status;mediana_s;fria_s;limite_s;execucoes_s;sensivel_rede;motivo` |
| `dev_<modulo>.json` | Contexto completo: host, data, CPU, RAM, plano de energia, tomada, versões, referência usada, registros (commits, digests), resultado por carga com todas as execuções e o motivo de cada falha |
| `logs/<carga>.log` | Saída de cada fase (`preparo`, `setup run N`, `command run N`, `cleanup run N`) e o tempo de cada execução |
| `logs/_repos.log` | Clone e checkout dos repositórios |

### 11.7 Critério de Aprovação

| Resultado | Condição |
|-----------|----------|
| **PASS** | Todas as cargas habilitadas do módulo terminam `OK` |
| **FAIL** | Máquina na bateria; ferramenta ausente ou abaixo da versão mínima; falha ao preparar um repositório; alguma carga `FALHOU` (processo caiu ou saiu com código ≠ 0), `TEMPO_EXCEDIDO` (acima de 10x a referência) ou `INTERROMPIDO` (Ctrl+Q ou tomada desconectada) |

Uma carga que falha não impede as próximas do mesmo módulo (o resultado parcial fica registrado); interrupções param o módulo.

### 11.8 Ressalvas `[Técnico]`

- **Rede:** A6a (`pip install` do PyPI) e A7a (`go mod download` dentro do build do container) dependem de rede durante a medição. Compare máquinas na mesma rede.
- **Tags móveis de imagens** (`mssql/server:2022-latest`, `golang:1.27-alpine3.24`): puxe no mesmo dia nas máquinas comparadas; os digests ficam no JSON.
- **Cache de build do container:** o Dockerfile do Hugo usa `RUN --mount=type=cache`, que o `--no-cache` não limpa; o `setup` da A7a apaga esses caches dentro da VM do Podman.
- **pydantic-core:** a A6a instala a wheel publicada do `pydantic-core` (Rust) na versão exigida pela tag, em vez de compilá-la.
- **Recursos da VM do Podman:** a VM WSL2 usa o padrão do WSL (50% da RAM, todas as threads). Não use `.wslconfig` diferente entre as máquinas comparadas.
- **Cargas internas:** podem ser acrescentadas no `workloads.local.json` (fora do git, exemplo em `workloads.local.example.json`); não entram no `referencia.json`.

### 11.9 Como Interpretar `[Gestão]`

- O número que importa é a **mediana** de cada carga comparada com a do notebook de referência: uma razão de 1,3 significa que o desenvolvedor espera 30% mais naquela tarefa.
- **B1 alto com o restante normal** aponta para overhead de EDR/antivírus em arquivos pequenos (padrão de `node_modules`, `obj/`, `.git`), não para o disco.
- **FAIL por TEMPO_EXCEDIDO** significa uma tarefa pelo menos 10 vezes mais lenta que na referência: inviável para uso de desenvolvimento.
- **FAIL por ferramenta ausente ou na bateria** é de preparação, não do hardware: rode os setups 7 e 10 e repita na tomada.

---

## 12. Rastreabilidade e Evidências

### 12.1 Estrutura de Armazenamento

Toda execução gera evidências organizadas por cenário, em duas pastas: `Execucoes/` (logs, evidências completas e estado) e `Exportar/` (cópia de `Traces/` sem `.etl`, logs e pastas vazias, pronta para o Drive).

```
Execucoes/
└── ImagemLimpa_DESKTOP-ABC_2026-04-15/     ← cenário
    ├── Logs/                                ← uma entrada por run
    │   ├── run_20260415_093000.log          ← saída completa de cada script
    │   └── run_20260415_093000.{html,csv,json}
    └── Traces/
        ├── _state.json                          ← estado e histórico
        ├── _relatorio.html                      ← relatório consolidado
        ├── _relatorio.csv
        ├── _relatorio.json
        ├── informacoes_maquina.csv              ← inventário do setup 1
        ├── maquina.csv                          ← inventário do hub + modelo/patrimônio informados
        ├── <módulo>/frequencia_cpu.csv          ← frequência da CPU durante o teste (gerado pelo hub; exceto 0 e 5)
        ├── 0_consumo_basal/                     ← evidências do teste de consumo basal
        │   ├── consumo_basal_*.log
        │   ├── Trace_Basal_*_Run1.etl … Trace_Basal_*_Run3.etl
        │   ├── CSV_*_Run1/ … CSV_*_Run3/        ← exportação WPA de cada ciclo
        │   ├── Resultados_Consolidados/         ← Relatorio_Resumo.csv e .html
        │   ├── consumo_basal.csv
        │   ├── ciclos_basal.csv
        │   └── top_processos_basal.csv
        ├── 1_cpu_memo/                          ← evidências do teste de CPU
        │   ├── automacao_*.log
        │   ├── Trace_*_Run1.etl … Trace_*_Run5.etl
        │   ├── CSV_*_Run1/ … CSV_*_Run5/        ← exportação WPA de cada ciclo
        │   ├── Resultados_Consolidados/         ← Relatorio_Resumo.csv e .html
        │   ├── cpu_memoria.csv
        │   ├── ciclos_libreoffice.csv
        │   └── dlp_usb/                         ← variante 1-1 (mesma estrutura, com cpu_memoria_dlp.csv)
        ├── 2_disco/                             ← evidências do teste de disco
        │   ├── resultado_validacao_disco_*.csv
        │   ├── disco.csv
        │   └── resultado_validacao_usb_*.csv, teste_usb_nativo_*.log, disco_usb.csv  ← variante 2-1
        ├── 3_rede/                              ← evidências do teste de rede (interno + internet)
        │   ├── teste_rede_*.log
        │   ├── resultado_afericoes.csv              (uma linha por rodada, das duas fontes)
        │   ├── rede.csv                             (blocos Interno_* e Internet_*)
        │   ├── Evidencia_Rede_Interno_A1_*.png
        │   ├── Evidencia_Rede_Internet_A1_*.png
        │   ├── ...
        │   └── Evidencia_Rede_Internet_10_*.png
        ├── 4_boot_shutdown/                     ← evidências do teste de boot
        │   ├── BootShutdown_<data>.csv
        │   └── boot_shutdown.csv
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
        ├── 7_dev_dotnet/ … 11_dev_git_arquivos/  ← evidências das cargas de dev
        │   ├── dev_<modulo>.csv
        │   ├── dev_<modulo>.json
        │   └── logs/                            ← <carga>.log e _repos.log
        └── <pasta do teste>/_anterior/           ← evidências substituídas em reexecuções
            ├── run1_2026-04-15T09-30-00/
            └── run2_2026-04-15T14-00-00/

Exportar/
└── ImagemLimpa/                             ← nome do cenário
    ├── 3440 - 050221/                       ← {modelo} - {patrimônio}: cópia de Traces/
    │                                           sem *.etl, *.log, pastas logs/ e pastas vazias
    └── 3440 - 050221.zip                    ← opcional
```

A pasta de exportação é regerada ao fim de cada execução (e pela opção `[E]` do menu). `Traces/` não é alterada: os `.etl` continuam disponíveis em `Execucoes/` para análise no WPA. Os dados de análise de cada módulo ficam em CSV, JSON ou HTML, então nada que sustente um resultado se perde na exportação.

> ![Estrutura de Pastas](img/placeholder-estrutura-traces.png)  
> *Insira aqui: screenshot do Windows Explorer mostrando a estrutura de pastas de um cenário real*

### 12.2 Ciclo de Vida das Evidências

1. **Primeira execução:** Evidências são salvas diretamente nas subpastas do cenário
2. **Re-execução:** Evidências anteriores são movidas para `<pasta do teste>/_anterior/run{N}_{data-hora}/` e novas evidências são geradas
3. **Consolidação:** O relatório `_relatorio.*` é atualizado com os resultados de todas as runs

**Nenhuma evidência é apagada.** O histórico completo de todas as tentativas é preservado.

> **Nota:** a pasta de evidências é a da categoria, compartilhada pelos scripts da mesma pasta. Reexecutar um teste também move para `_anterior/` as evidências atuais dos outros testes da mesma pasta (por exemplo, o Módulo 1 e a variante 1-1).

### 12.3 O Arquivo _state.json `[Técnico]`

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
          "duration": 1842.5
        }
      ]
    }
  ]
}
```

### 12.4 Cadeia de Custódia `[Gestão]`

Para auditar uma execução e validar a integridade dos resultados:

| Etapa de auditoria | O que verificar | Onde encontrar |
|---------------------|----------------|----------------|
| **1. Identificação** | Máquina, data, operador | `_state.json` → `machine`, `modelo`, `patrimonio`, `createdAt` |
| **2. Escopo** | Quais testes foram executados | `_state.json` → `runs[].tests[]` |
| **3. Resultados** | PASS/FAIL de cada teste | `_relatorio.html` ou `_state.json` |
| **4. Evidências** | Dados brutos que suportam o resultado | Subpastas do cenário (CSVs, screenshots, logs) |
| **5. Histórico** | Re-execuções e tentativas anteriores | `_anterior/` e múltiplas entries em `runs[]` |
| **6. Ambiente** | Configuração da máquina no momento do teste | `Traces/informacoes_maquina.csv` (gerado pelo setup 1) e `Traces/maquina.csv` (gerado pelo hub) |

---

## 13. Formatos de Relatório

### 13.1 Relatório HTML

Relatório visual com tabela formatada, badges de status coloridos e resumo estatístico. Ideal para apresentação e compartilhamento. Há dois:

- **`Traces/_relatorio.html` (consolidado do cenário):** nome do cenário, máquina, datas de criação e da última execução, total de runs e estatísticas (PASS, FAIL, ERROR). Tabela com o último resultado de cada teste: nome, status, duração, run e pasta de evidências.
- **`Logs/run_*.html` (uma execução):** máquina, usuário, início e tempo total. Tabela com cada script da run: fase, nome, tipo, status, duração e número de evidências. Para os que não passaram, mostra as últimas linhas de erro.

> ![Exemplo Relatório HTML](img/placeholder-relatorio-html-exemplo.png)  
> *Insira aqui: screenshot de um relatório HTML real*

### 13.2 Relatório CSV

Dados tabulares com uma linha por teste. Ideal para importação em Excel ou ferramentas de BI.

**Colunas do `Logs/run_*.csv`:**

| Coluna | Descrição |
|--------|-----------|
| Timestamp | Data e hora da execução |
| Kind | `setup` ou `test` |
| Name | Nome do script |
| Type | Extensão, sem o ponto (`ps1` ou `py`) |
| Status | `PASS`, `FAIL` ou `ERROR` |
| Duration_s | Duração em segundos |
| ExitCode | Código de saída do processo |
| TraceCount | Quantidade de arquivos de evidência |
| TraceDir | Caminho da pasta de evidências |

O consolidado `Traces/_relatorio.csv` tem as colunas `Nome`, `Status`, `Duracao_s`, `Run`, `Reexecucao` e `Pasta`, com o último resultado de cada teste. O `_relatorio.json` traz o mesmo status com o nome do cenário, o hostname, o modelo e o patrimônio; a data de cada run está no `_state.json`. O `Traces/maquina.csv` traz o inventário da máquina.

### 13.3 Relatório JSON

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

### 13.4 Qual Relatório Usar `[Gestão]`

| Necessidade | Formato recomendado |
|-------------|---------------------|
| Apresentar resultado a stakeholders | **HTML** (`_relatorio.html`) |
| Alimentar planilha de acompanhamento | **CSV** (`_relatorio.csv`) |
| Integrar com sistema de gestão de ativos | **JSON** (`_relatorio.json`) |
| Alimentar BI com métricas de cada módulo | **CSV** (CSVs temáticos em `Traces/<módulo>/`, também em `Exportar/`) |
| Investigar causa de falha | **LOG** (`Logs/run_*.log`) |
| Auditoria de processo | **JSON** (`_state.json`) + evidências |

---

## 14. Glossário

| Termo | Definição |
|-------|-----------|
| **Aferição** | Uma medição individual dentro de um teste. Ex: cada uma das rodadas de velocidade de rede |
| **Autonomia projetada** | Tempo que a bateria cheia duraria no ritmo de consumo medido numa fase: capacidade de carga cheia ÷ taxa média de descarga. É uma extrapolação linear; o tempo real medido até 10% está em `Tempo_Total_Bateria_Real_*` e `Autonomia_Real_Equivalente_100pct` |
| **Bateria (teste de disco)** | Um ciclo completo de operações dentro de um teste. Ex: cada uma das 10 baterias de leitura/escrita do teste de disco |
| **Bateria (Módulo 5)** | O teste de consumo de energia na bateria do notebook (seção 9) |
| **Cenário** | Sessão de testes associada a uma máquina e data, agrupando runs e evidências |
| **Cooldown** | Período de espera entre ciclos de estresse para a CPU retornar ao estado ocioso |
| **DiskSPD** | Ferramenta de benchmarking de disco da Microsoft |
| **Economia de energia** | Recurso do Windows (antes "Economia de bateria") que reduz brilho e atividade em segundo plano; liga sozinho abaixo de um limite de carga. O teste o deixa desligado e sem acionamento automático |
| **Evidência** | Arquivo gerado por um teste que comprova o resultado (CSV, screenshot, log) |
| **Exit Code** | Código numérico retornado por um processo ao encerrar. `0` = sucesso, `≠ 0` = falha |
| **Fase de escritório** | Fase ativa do teste de bateria (v2.0): uso de escritório contínuo no LibreOffice Writer e Calc (planilha R2) até a bateria chegar a 10%, com trace WPR só na 1ª hora |
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
