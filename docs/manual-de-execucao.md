# Manual de Execução — Hardware Test Hub

**Versão:** 1.1  
**Data:** 2026-11-06  
**Público-alvo:** Operadores de campo, equipe técnica, gestores

---

## Sumário

1. [Visão Geral](#1-visão-geral)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Instalação e Primeiro Uso](#3-instalação-e-primeiro-uso)
4. [Operação Passo a Passo](#4-operação-passo-a-passo)
5. [Cenários e Re-execução](#5-cenários-e-re-execução)
6. [Saídas e Relatórios](#6-saídas-e-relatórios)
7. [Troubleshooting](#7-troubleshooting)
8. [Referência Rápida](#8-referência-rápida)

---

## 1. Visão Geral

O **Hardware Test Hub** é um framework Windows para validação de hardware que automatiza a preparação do ambiente, execução de testes de diagnóstico (CPU, memória, disco, rede, boot/shutdown e bateria) e geração de relatórios. Através de um menu interativo no console, o operador seleciona quais testes executar e acompanha o progresso em tempo real. Os resultados são persistidos em múltiplos formatos (HTML, CSV, JSON) com rastreabilidade completa por cenário.

---

## 2. Pré-requisitos

### 2.1 Hardware e Sistema Operacional

| Requisito | Especificação |
|-----------|---------------|
| Sistema Operacional | Windows 10 ou Windows 11 |
| Privilégios | Acesso de Administrador local |
| Conexão de rede | Necessária para testes de rede e instalação de dependências |
| Espaço em disco | Mínimo 10 GB livres (o teste de disco cria arquivo temporário de 8 GB) |
| Bateria (Módulo 5) | Notebook com bateria reconhecida pelo Windows, carregada a pelo menos **95%** no início. Desative durante a homologação o limite de carga do fabricante (ex.: Dell "Primarily AC" ou carga adaptativa), que impede chegar a 95% |
| Wi-Fi Fast Transition (Módulo 6) | Notebook com Wi-Fi **conectado à rede a testar** antes de iniciar; rede com 2 ou mais APs do mesmo SSID no percurso da caminhada |

### 2.2 Software

Os itens abaixo são instalados automaticamente pela **Fase de Setup** do hub. Não é necessário instalá-los manualmente antes da primeira execução:

- Python 3.x (com ambiente virtual `.venv`)
- Microsoft Edge (nativo do Windows 10/11 — usado no teste de rede)
- Dependências Python: `psutil`, `speedtest-cli`, `requests`, `selenium`, `pandas`, `pyautogui`, `pyperclip`, `pynput`

Para o **teste de bateria (Módulo 5)**, além disso:

- **Windows Performance Toolkit** (`wpr.exe` e `wpaexporter.exe`) no PATH — o mesmo pré-requisito do Módulo 1
- **Microsoft Edge com a conta Google já logada** (Google Docs e Sheets), como no Módulo 1
- **Feche o Edge antes de iniciar**: o teste encerra o Edge e reabre só com as páginas dele

### 2.3 Rede `[Técnico]`

- O teste de rede acessa o servidor de speedtest interno, cuja URL fica fora do repositório: chave `SpeedtestUrl` do `config.local.json` na raiz do hub (modelo em `config.local.example.json`) ou variável de ambiente `HUB_SPEEDTEST_URL`. Verifique se a máquina tem acesso a essa URL antes de executar o módulo de rede.
- O teste complementar de rede na internet (`3-1_teste_rede_internet.py`) acessa `https://fast.com/` (Netflix). Os domínios `fast.com`, `api.fast.com` e `*.oca.nflxvideo.net` — ou a categoria "speedtest" — precisam estar liberados na política do agente zero trust/proxy; caso contrário, o teste falha com "site inacessível ou bloqueado".
- Esse teste registra no CSV o **IP público de saída** e a localização vistos pelo fast.com, como evidência do caminho percorrido pelo tráfego (com o agente ativo, devem ser os do nó de saída do agente).

### 2.4 Estrutura de Pastas Esperada `[Técnico]`

```
C:\TesteHub\
├── hub.bat              # Ponto de entrada
├── hub.ps1              # Orquestrador principal
├── config.json          # Configurações
├── config.local.json    # Valores internos, como a URL do speedtest (não versionado)
├── Setup\environment\   # Scripts de setup (10 scripts)
├── Testes\              # Módulos de teste (6 módulos + 2 variantes DLP/USB)
├── Execucoes\           # Logs, evidências e estado de cada cenário (criada pelo hub)
└── Resultados\          # CSVs estruturados de cada cenário (criada pelo hub)
```

> **Importante:** O hub espera estar em `C:\TesteHub`. Caso utilize outro caminho, ajuste a referência no `hub.bat`.

---

## 3. Instalação e Primeiro Uso

### 3.1 Copiar o Repositório

Copie toda a pasta do projeto para `C:\TesteHub` na máquina de teste.

Confira se a cópia inclui os arquivos internos que **não estão no repositório do GitHub**: o `config.local.json` (URL do speedtest interno) e os perfis `Agentes_SI_Profile.wpaProfile` (em `Testes\1_cpu_memo\`) e `Agentes_SI_Bateria_Profile.wpaProfile` (em `Testes\5_bateria\`). Sem os perfis, os módulos 1 e 5 rodam, mas pulam a exportação CSV dos traces.

### 3.2 Primeira Execução

1. Clique duas vezes em `hub.bat`
2. Se solicitado pelo UAC (Controle de Conta de Usuário), clique em **Sim** para conceder privilégios de administrador

> ![Tela UAC](img/placeholder-uac.png)  
> *Insira aqui: screenshot da tela de elevação UAC ao executar hub.bat*

3. O hub iniciará no console PowerShell

### 3.3 Fase de Setup (Primeira Vez)

Na primeira execução, a **Fase de Setup** será apresentada automaticamente. Ela prepara o ambiente da máquina:

| Script | O que faz |
|--------|-----------|
| `1_captura_infos_pc` | Coleta informações do sistema (CPU, RAM, disco, bateria, SO) |
| `2_opcoes_energia` | Configura o plano de energia (evita suspensão durante os testes) |
| `3_softwares_msStore` | Instala via winget o Windows ADK, o CrystalDiskMark e o CrystalDiskInfo |
| `4_install_python` | Instala o Python 3.12 |
| `5_install_py_dependencies` | Cria o ambiente virtual e instala os pacotes Python |
| `6_pausa_WinUpdate` | Pausa o Windows Update por 35 dias (evita interferência nos testes) |
| `8_enable_diagnostics` | Habilita os diagnósticos de boot/shutdown do Windows |
| `9_AdicionarTecladoUSInt` | Adiciona o layout de teclado EUA-Internacional |
| `12_remover_appx_bloatware` | Remove aplicativos pré-instalados (Xbox, Copilot, Teams, Notícias e outros) |
| `13_remover_onedrive` | Desinstala o OneDrive e bloqueia a reinstalação |

**Recomendação:** Na primeira execução, selecione **todos** os scripts de setup (tecla `A`). Em execuções subsequentes, o setup pode ser ignorado (veja a seção 3.4).

> ![Menu de Setup](img/placeholder-menu-setup.png)  
> *Insira aqui: screenshot do menu checkbox da Fase de Setup*

### 3.4 Pular o Setup em Execuções Futuras `[Técnico]`

Edite o arquivo `config.json` e altere:

```json
{
    "SkipSetup": true
}
```

Isso faz o hub pular direto para a Fase de Testes nas próximas execuções.

---

## 4. Operação Passo a Passo

### 4.1 Selecionar ou Criar um Cenário

Ao iniciar, o hub exibe os 5 cenários mais recentes (se houver) e oferece três opções:

- **`[N]`** — Criar um novo cenário (será solicitado um nome, ex: `ImagemLimpa`)
- **`[1-5]`** — Continuar um cenário existente
- **`[E]`** — Exportar um cenário para ZIP: o hub compacta a pasta do cenário, confere se o ZIP tem o mesmo número de arquivos e só então remove a pasta original. Ao final de cada execução, o hub também pergunta se deseja exportar o cenário.

O nome do cenário é combinado com o hostname e a data, resultando em algo como: `ImagemLimpa_DESKTOP-ABC_2026-04-15`

> ![Seleção de Cenário](img/placeholder-selecao-cenario.png)  
> *Insira aqui: screenshot da tela de seleção/criação de cenário*

### 4.2 Navegar o Menu de Testes

Após selecionar o cenário, o menu de testes é exibido. Os testes são agrupados pelo nome da pasta, sem o prefixo numérico, e os que nunca rodaram no cenário (**pendentes**) já vêm marcados:

```
-- Cpu Memo --------------------------------
[X] 1_automacao_performance        [PY]   pendente
[X] 1-1_automacao_performance_dlp  [PY]   pendente
-- Disco -----------------------------------
[X] 2_teste_disco                  [PY]   pendente
[X] 2-1_teste_disco_dlp            [PY]   pendente
-- Rede ------------------------------------
[X] 3_teste_rede                   [PY]   pendente
-- Rede Internet ---------------------------
[X] 3-1_teste_rede_internet        [PY]   pendente
-- Boot Shutdown ---------------------------
[X] 4_boot_shutdown_auto           [PY]   pendente
-- Bateria ---------------------------------
[X] 5_teste_bateria                [PY]   pendente
-- Wifi Fast Transition --------------------
[X] 6_teste_fast_transition        [PY]   pendente
```

Desmarque com `Espaço` o que não for executar agora. Os módulos 5 e 6 exigem o operador presente e convém executá-los sozinhos (seções 4.6 e 4.7), e as variantes DLP/USB (`1-1` e `2-1`) só fazem sentido com um pendrive em `E:\`.

Num cenário com execuções anteriores, o menu mostra o último resultado e a duração de cada teste. Só os pendentes vêm marcados:

```
[ ] 1_automacao_performance        [PY]   PASS  (361.5s)
[ ] 2_teste_disco                  [PY]   FAIL  (12.3s)
[X] 3_teste_rede                   [PY]   pendente
[X] 3-1_teste_rede_internet        [PY]   pendente
```

> ![Menu de Testes](img/placeholder-menu-testes.png)  
> *Insira aqui: screenshot do menu checkbox com testes e status*

### 4.3 Controles do Menu

| Tecla | Ação |
|-------|------|
| `↑` `↓` | Navegar entre os itens |
| `Espaço` | Marcar/desmarcar o item atual |
| `A` | Selecionar/desselecionar **todos** |
| `P` | Selecionar apenas os **pendentes** (nunca executados no cenário) |
| `Enter` | Confirmar seleção e iniciar execução |
| `Esc` | Cancelar e sair |

**Dica:** `P` não marca os testes que falharam. Para reexecutar um FAIL, marque-o com `Espaço`.

### 4.4 Acompanhar a Execução

Após confirmar, o hub mostra um resumo dos testes selecionados e inicia a execução sequencial. Durante a execução:

- O console exibe o progresso em tempo real (nome do teste, tempo decorrido)
- Testes com interface visual (CPU, Disco, Rede, Bateria) exibem um **overlay transparente** na tela com informações de progresso
- O overlay é "click-through" — não interfere no uso da máquina

> ![Execução em Progresso](img/placeholder-execucao-progresso.png)  
> *Insira aqui: screenshot da execução com overlay de progresso visível*

### 4.5 Interpretar Resultados na Tela

Ao final de cada teste, o resultado é exibido:

| Indicador | Significado |
|-----------|-------------|
| **PASS** (verde) | Teste concluído com sucesso (exit code 0) |
| **FAIL** (vermelho) | Teste falhou (exit code diferente de 0) |
| **ERR** (amarelo) | Erro inesperado na execução |

Ao final de todos os testes, um resumo geral é apresentado com contagem de PASS/FAIL/ERROR.

> ![Resultados Finais](img/placeholder-resultados-finais.png)  
> *Insira aqui: screenshot do resumo final no console*

### 4.6 Teste de Bateria (Módulo 5) — Passo a Passo do Operador

O teste de bateria leva **~2h20–2h40** e precisa do operador no começo (para desconectar o carregador) e no fim (para reconectar). Prefira executá-lo **sozinho**, sem outros testes na mesma seleção.

**1. Prepare a máquina, ainda na tomada**

- Carregue a bateria até pelo menos **95%** (desative o limite de carga do fabricante, se houver).
- Feche o Edge e os demais aplicativos. Deixe a conta Google logada no Edge.
- Conecte a rede com acesso à internet e desconecte monitor externo e dock.
- Se a política da máquina bloqueia a tela por inatividade, desative o bloqueio durante o teste (o teste mantém a tela ligada sem simular teclado ou mouse, mas não contorna política).

**2. Selecione o teste**

No menu de testes, marque `5_teste_bateria.py` (seção **Bateria**) e confirme com `Enter`.

**3. Aguarde o pré-voo (~1 min)**

O teste confere a bateria, a carga, as ferramentas de captura, a rede e o monitor; abre e fecha o Edge para conferir a conta Google; e ajusta plano e modo de energia, Economia de energia, brilho, Bluetooth e suspensão. Se aparecer a janela **"Ação Necessária — Login no Google"** (ou "no Edge"), faça o login no Edge e clique em **OK**.

Se algum item não puder ser ajustado, a janela **"Teste de bateria não iniciado"** lista os pendentes; nada é medido e as configurações já voltam ao que eram (veja a seção 7.1).

**4. Desconecte o carregador e confirme o checklist**

Na janela **"Teste de bateria — desconecte o carregador"**:

1. Desconecte periféricos (mouse, teclado, pendrive, fone) e o dock/hub USB, e apague a luz do teclado.
2. Marque as três caixas e clique em **Confirmo o checklist**.
3. Desconecte o carregador da tomada — a janela mostra "Carregador: DESCONECTADO" e a medição começa sozinha.

O limite para isso é de **10 minutos**; depois disso o teste encerra sem medir (FAIL) e restaura a máquina. **Cancelar teste** ou `Ctrl+Q` interrompem com segurança.

**5. Não use a máquina (~2h10)**

O overlay mostra a fase, a carga e os minutos restantes:

| Fase no overlay | O que acontece | Duração |
|-----------------|----------------|---------|
| Estabilização | Confere brilho, modo e Economia já na bateria (fora da medição) | 5 min |
| Fase ociosa | Tela ligada, nada aberto pelo teste | 60 min |
| Transição | Salva o trace e abre o Edge com documento, planilha e PDF | ~1–5 min |
| Fase de escritório | O teste digita e navega no Edge sozinho | 60 min |

Não toque no mouse nem no teclado — na fase de escritório o teste está usando os dois. Levar o mouse a um canto da tela aciona a parada segura. **Não reconecte o carregador** antes do aviso: isso invalida a medição.

**6. Reconecte quando o aviso pedir**

A janela **"Teste de bateria — medição encerrada"** (e o overlay "O carregador já pode ser reconectado") indica o fim da medição. Reconecte o carregador. O teste ainda converte os traces e gera o SRUM e o relatório de energia (~5–20 min), restaura as configurações e devolve o resultado ao hub.

O resultado detalhado fica em `5_bateria/bateria.csv` (copiado para `Resultados/`): `Coleta_Valida = sim` indica uma execução que serve para comparar baseline × agente.

### 4.7 Teste de Wi-Fi Fast Transition (Módulo 6) — Passo a Passo do Operador

O teste leva **~7 min** (1 min de coleta + 5 min de caminhada + 1 min de processamento) e precisa do operador **andando com o notebook** durante a caminhada. Execute-o **sozinho** na seleção, numa máquina que você possa levar pelo escritório.

**1. Prepare a máquina**

- Conecte o Wi-Fi na rede que será testada (a rede corporativa com 802.11r). O teste usa a rede **já conectada**: não pede SSID nem senha.
- Deixe a tampa aberta e o carregador desconectado (ou leve-o junto), para poder andar.
- Planeje um percurso que passe por áreas de **APs diferentes** do mesmo SSID (ex.: de uma ponta à outra do andar).

**2. Selecione o teste**

No menu de testes, marque `6_teste_fast_transition.py` (seção **Wifi Fast Transition**) e confirme com `Enter`.

**3. Aguarde a coleta (~15–30 s)**

O teste confere a conexão e coleta adaptador, driver, BIOS, energia e os APs visíveis. Em seguida, o **painel ao vivo** abre sozinho numa janela do Edge.

**4. Inicie a caminhada**

Clique em **Iniciar caminhada** (se ninguém clicar, ela começa sozinha em 60 s). Durante os 5 minutos, ande pelo percurso. O painel mostra:

| Área do painel | O que mostra |
|----------------|--------------|
| AP atual | AP em uso (AP1, AP2... com cor fixa), BSSID, canal, banda e AKM |
| Sinal (RSSI) | Intensidade do sinal em dBm (≥ -60 bom, -60 a -70 razoável, < -70 fraco) |
| Roamings | Contadores ✓ FT, ✕ Não FT e ? Indeterminado |
| Gráficos | RSSI e latência dos últimos 90 s; linhas verticais marcam cada troca de AP |
| Trocas de AP | Lista das trocas com classificação, tempo de troca e interrupção |

A cada troca de AP aparece um destaque grande na tela (verde = FT, vermelho = Não FT, amarelo = lendo a AKM). **Encerrar agora** termina antes do tempo e ainda gera o relatório. Fechar o painel não interrompe o teste.

**5. Veja o resultado**

Ao fim, o painel mostra PASS/FAIL e abre o relatório `6_wifi_fast_transition/wifi_ft_relatorio.html`, com gráficos e informações técnicas. O `wifi_ft.csv` é copiado para `Resultados/`.

---

## 5. Cenários e Re-execução

### 5.1 O que é um Cenário

Um **cenário** é uma sessão de testes associada a uma máquina e data. Ele agrupa todas as execuções (runs) e suas evidências em uma única pasta dentro de `Execucoes/`, com os resultados estruturados numa pasta de mesmo nome em `Resultados/`. Isso permite:

- Executar testes em diferentes momentos (dias) e consolidar resultados
- Re-executar apenas os testes que falharam
- Manter histórico completo de todas as tentativas

### 5.2 Continuar um Cenário Existente

Ao iniciar o hub, selecione o número do cenário que deseja continuar. O menu de testes mostrará o status da última execução de cada teste; os pendentes já vêm marcados, e os que falharam podem ser marcados com `Espaço`.

### 5.3 Re-execução de Testes

Ao re-executar um teste que já foi rodado anteriormente:

1. As evidências da execução anterior são **automaticamente movidas** para a subpasta `_anterior/` dentro da pasta do teste (ex.: `Traces/2_disco/_anterior/run1_<data-hora>/`)
2. O teste roda novamente e gera novas evidências
3. O `_state.json` é atualizado com a nova run

**Nenhuma evidência é perdida.** O histórico completo fica preservado em `_anterior/`.

> **Nota:** a pasta de evidências é a da categoria, compartilhada pelos scripts da mesma pasta. Reexecutar o `1_automacao_performance` também move para `_anterior/` as evidências atuais do `1-1_automacao_performance_dlp`, e vice-versa. Nada se perde, mas as evidências "atuais" passam a ser só as do teste reexecutado.

### 5.4 Estrutura de um Cenário `[Técnico]`

```
Execucoes/
└── ImagemLimpa_DESKTOP-ABC_2026-04-15/      # {cenário}_{hostname}_{data}
    ├── Logs/
    │   ├── run_20260415_093000.log          # Saída completa de cada script
    │   └── run_20260415_093000.{html,csv,json}
    └── Traces/
        ├── _state.json                      # Estado e histórico de todas as runs
        ├── _relatorio.{html,csv,json}       # Relatório consolidado
        ├── informacoes_maquina.csv          # Inventário gerado pelo setup 1
        ├── 1_cpu_memo/                      # Evidências do Módulo 1
        │   └── dlp_usb/                     # Evidências da variante 1-1
        ├── 2_disco/                         # Evidências do Módulo 2 e da variante 2-1
        ├── 3_rede/
        ├── 3_rede_internet/
        ├── 4_boot_shutdown/
        ├── 5_bateria/                       # Pré-voo, amostras, traces, bateria.csv
        ├── 6_wifi_fast_transition/
        └── <pasta do teste>/_anterior/      # Evidências de execuções anteriores
            ├── run1_2026-04-15T09-30-00/
            └── run2_2026-04-15T14-00-00/

Resultados/
└── ImagemLimpa_DESKTOP-ABC_2026-04-15/
    ├── maquina.csv                          # Modelo, série, CPU, RAM, disco, SO
    ├── cenario.csv                          # Status consolidado de cada teste
    └── cpu_memoria.csv, disco.csv, ...      # CSVs temáticos de cada módulo
```

---

## 6. Saídas e Relatórios

### 6.1 Onde Encontrar os Resultados

| Local | Conteúdo | Quando usar |
|-------|----------|-------------|
| `Execucoes/{cenário}/Logs/` | Resultados **por execução** (run) | Consultar uma execução específica |
| `Execucoes/{cenário}/Traces/` | Evidências e relatório **consolidado** do cenário | Visão completa de um ciclo de testes |
| `Resultados/{cenário}/` | Inventário da máquina, status do cenário e CSVs temáticos de cada módulo (`cpu_memoria.csv`, `disco.csv`, `rede.csv`, `rede_internet.csv`, `boot_shutdown.csv`, `bateria.csv`, `wifi_ft.csv` e, quando executadas, `cpu_memoria_dlp.csv` e `disco_usb.csv`) | Planilhas e BI |

### 6.2 Formatos Disponíveis

| Formato | Arquivo | Melhor para |
|---------|---------|-------------|
| **HTML** | `run_*.html` / `_relatorio.html` | Visualização e apresentação |
| **CSV** | `run_*.csv` / `_relatorio.csv` | Análise em Excel ou ferramentas de BI |
| **JSON** | `run_*.json` / `_relatorio.json` | Integração com sistemas externos |
| **LOG** | `run_*.log` | Diagnóstico de problemas (saída completa dos scripts) |

### 6.3 Interpretar o Relatório HTML

Há dois relatórios HTML:

- **`_relatorio.html` (consolidado do cenário):** nome do cenário, máquina, datas de criação e da última execução, total de runs e estatísticas (PASS, FAIL, ERROR). A tabela traz o **último resultado** de cada teste, com status colorido, duração, run em que foi obtido e pasta de evidências.
- **`run_*.html` (uma execução):** máquina, usuário, início e tempo total. A tabela traz cada script executado naquela run, com fase (setup/teste), status, duração e número de evidências. Para testes que não passaram, mostra logo abaixo as últimas linhas de erro.

> ![Relatório HTML](img/placeholder-relatorio-html.png)  
> *Insira aqui: screenshot do relatório HTML aberto no navegador*

### 6.4 Qual Relatório Usar `[Gestão]`

| Necessidade | Relatório recomendado |
|-------------|----------------------|
| Apresentar resultado a stakeholders | `_relatorio.html` (cenário consolidado) |
| Alimentar planilha de acompanhamento | `_relatorio.csv` |
| Auditar uma execução específica | `run_*.json` (dados estruturados com timestamps) |
| Investigar falha em um teste | `run_*.log` (saída completa do script) |

---

## 7. Troubleshooting

### 7.1 Erros Comuns

| Problema | Causa provável | Solução |
|----------|---------------|---------|
| Hub não inicia / fecha imediatamente | Falta de privilégio de admin | Execute `hub.bat` como Administrador (clique direito → Executar como administrador) |
| "Python não encontrado" | Python não instalado ou `.venv` ausente | Re-execute o setup selecionando scripts 4 e 5 |
| Teste de rede falha com "Edge não encontrado" | Microsoft Edge ausente/removido da máquina | O Edge é nativo do Windows 10/11 — reinstale/repare o Microsoft Edge pelo site oficial da Microsoft |
| Teste de rede falha com "URL do speedtest interno não configurada" | `config.local.json` ausente ou sem a chave `SpeedtestUrl` | Crie o `config.local.json` a partir do `config.local.example.json` (veja a seção 7.3) |
| Teste de rede falha com "Falha ao iniciar o Microsoft Edge via Selenium" | O Selenium Manager não conseguiu baixar o `msedgedriver` | Verifique o acesso da máquina ao CDN de drivers do Edge, ou coloque um `msedgedriver.exe` compatível no `PATH` |
| Teste de rede internet falha com "site inacessível ou bloqueado" | Política do agente zero trust/proxy bloqueando o fast.com (ou a categoria speedtest), ou máquina sem acesso à internet | Libere `fast.com`, `api.fast.com` e `*.oca.nflxvideo.net` na política; confira a tela capturada em `Evidencia_Internet_Bloqueio_*.png` e o log `teste_rede_internet_*.log` |
| Teste de rede internet com menos de 5 aferições válidas | Rede instável ou medição sem concluir em 120 s | Verifique a conexão e o log; os valores ausentes aparecem como `N/A` em `resultado_afericoes_internet.csv` |
| Teste de disco falha rapidamente | Espaço insuficiente em disco | Libere pelo menos 10 GB no disco principal |
| Overlay visual não aparece | Problema com `tkinter` | Verifique se o Python foi instalado com suporte a tkinter (padrão na instalação oficial) |
| Wi-Fi FT: "O Wi-Fi não está conectado" | Máquina no cabo, Wi-Fi desligado ou desconectado | Conecte o Wi-Fi na rede a testar e execute de novo |
| Wi-Fi FT: FAIL "Nenhuma troca de AP aconteceu" | O operador não se afastou do AP inicial, ou só há 1 AP do SSID no percurso | Refaça a caminhada indo até áreas de outros APs (confira o inventário de APs no relatório) |
| Wi-Fi FT: FAIL "nenhum com Fast Transition" e achado "a rede usa PSK/802.1X/SAE" | O 802.11r não está habilitado no SSID | Habilite o 802.11r (FT) no SSID da controladora/AP; não é problema da máquina |
| Wi-Fi FT: rede anuncia FT, mas as trocas saem "Não FT" | Driver/adaptador sem suporte, driver antigo ou política do Windows | Veja "Transição Rápida" nas capacidades e a data do driver no relatório; atualize o driver Wi-Fi |
| Wi-Fi FT: trocas "Indeterminado" | O driver não informa a AKM no `netsh wlan show interfaces` | Atualize o driver; a evidência bruta fica em `brutos/netsh_interfaces*.txt` |
| Wi-Fi FT: painel não abriu | Edge bloqueado por política | Abra no navegador a URL "Painel ao vivo" registrada no log `teste_wifi_ft_*.log`; o teste roda mesmo sem o painel |
| Wi-Fi FT: métricas de internet `N/A` | Ping para `8.8.8.8` bloqueado pelo firewall | Esperado em redes corporativas; não reprova |
| Teste de boot/shutdown não completa os 5 ciclos | Task Scheduler falhou ou máquina não reiniciou | Verifique se a tarefa agendada `HardwareTestHub_Reiniciador` existe no Agendador de Tarefas |
| Bateria: "Este teste exige um notebook com bateria reconhecida pelo Windows" | Desktop ou bateria não reconhecida | O teste só roda em notebook; confira a bateria no Gerenciador de Dispositivos. Nada foi alterado na máquina |
| Bateria: "Carga da bateria em X%; o mínimo para iniciar é 95%" | Bateria não carregada ou limite de carga do fabricante ativo | Carregue a bateria na tomada; desative o limite de carga do fabricante (app ou BIOS) e execute de novo |
| Bateria: "Ferramentas de captura não encontradas no PATH" | Windows Performance Toolkit ausente | Instale o WPT (o mesmo do Módulo 1) e inclua a pasta dele no PATH |
| Bateria: janela "Teste de bateria não iniciado" | Item do pré-voo fora do padrão ou "bloqueado por política" | A janela e o `bateria_preflight.csv` listam os itens pendentes; ajuste-os (ou peça exceção da política) e execute de novo. O teste já restaurou o que tinha alterado |
| Bateria: "sem acesso à internet" ou "monitor externo conectado" no pré-voo | Rede sem internet ou monitor externo/dock ligado | Conecte a rede com internet e desconecte o monitor externo antes de iniciar |
| Bateria: "O carregador não foi desconectado em 10 min" (`carregador_nao_desconectado`) | Operador ausente na hora do aviso | Execute de novo com o operador presente |
| Bateria: FAIL com motivo `carregador_reconectado` | Carregador reconectado antes do aviso de fim da medição | Execute de novo e só reconecte quando a janela "medição encerrada" pedir |
| Bateria: FAIL com motivo `protecao_bateria` | A carga chegou a 7% na fase ociosa ou antes de 30 min da fase de escritório | A bateria não sustenta as duas fases: comece com 100% de carga; se persistir, registre a autonomia baixa |
| Bateria: FAIL com motivo `sessao_bloqueada` | A política de bloqueio por inatividade bloqueou a sessão | Desative o bloqueio automático de tela durante o teste (ou peça exceção da política) e execute de novo |
| Bateria: FAIL com motivo `login_exigido` | O Google pediu login quando o Edge abriu já na bateria | Faça o login no Edge na tomada e execute de novo |
| Bateria: FAIL com motivo `padronizacao_na_bateria` | Brilho, modo de energia ou Economia de energia não ficaram no padrão depois de desconectar | Veja as linhas "efetivo" no `bateria_preflight.csv`; confira o software de energia do fabricante |
| Bateria: máquina ficou com brilho 50%, Bluetooth desligado ou energia alterada | O processo foi encerrado à força (ex.: janela do hub fechada) e a restauração automática não rodou | Use a coluna `Antes` do `bateria_preflight.csv`: brilho e Bluetooth pelas Configurações; para os itens de energia, `powercfg /setdcvalueindex SCHEME_CURRENT <subgrupo> <configuração> <valor>` seguido de `powercfg /setactive SCHEME_CURRENT` |

### 7.2 Re-executar um Setup Individual

Se um setup específico falhou, não é necessário re-executar todos:

1. Abra `hub.bat`
2. Na Fase de Setup, marque **apenas** o script que precisa ser re-executado
3. Confirme com `Enter`

### 7.3 Variáveis de Ambiente e config.json `[Técnico]`

O hub injeta as seguintes variáveis de ambiente para cada teste:

| Variável | Descrição |
|----------|-----------|
| `HUB_EVIDENCE_DIR` | Pasta onde o teste deve salvar suas evidências |
| `HUB_TRACE_DIR` | Igual a `HUB_EVIDENCE_DIR` |
| `HUB_TRACE_ROOT` | Pasta `Traces` do cenário atual |

Configurações em `config.json`:

```json
{
    "SkipSetup": false,
    "Paths": {
        "SetupRoot": "Setup",
        "TestsRoot": "Testes",
        "ResultadosDir": "Resultados",
        "ExecucoesDir": "Execucoes"
    },
    "Settings": {
        "PythonVenvName": ".venv",
        "HtmlReportTitle": "Hardware Test Hub - Relatório Final"
    }
}
```

Valores internos ficam em `config.local.json`, na raiz do hub. Esse arquivo não vai para o repositório; o modelo é o `config.local.example.json`:

| Chave | Variável de ambiente equivalente | Uso |
|-------|----------------------------------|-----|
| `SpeedtestUrl` | `HUB_SPEEDTEST_URL` (tem prioridade) | URL do speedtest interno do Módulo 3 |

---

## 8. Referência Rápida

### Controles do Menu

| Tecla | Ação |
|-------|------|
| `↑` `↓` | Navegar |
| `Espaço` | Marcar/desmarcar item |
| `A` | Selecionar/desselecionar todos |
| `P` | Selecionar apenas pendentes |
| `Enter` | Confirmar e executar |
| `Esc` | Cancelar |

### Exit Codes dos Testes

| Código | Status | Significado |
|--------|--------|-------------|
| `0` | PASS | Teste concluído com sucesso |
| `≠ 0` | FAIL | Teste falhou ou encontrou erro |

### Comandos de Execução

```bat
REM Iniciar o hub (com elevação UAC automática)
hub.bat

REM Iniciar diretamente via PowerShell (já como Admin)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File hub.ps1
```

### Atalhos de Teclado nos Testes Visuais

| Atalho | Teste | Ação |
|--------|-------|------|
| `Ctrl+Q` | CPU & Memória, Bateria | Interromper teste de forma segura |

---

> **Nota sobre imagens:** Os placeholders `img/placeholder-*.png` devem ser substituídos por screenshots reais capturados durante a execução do hub. Crie a pasta `docs/img/` e salve as imagens com os nomes indicados.
