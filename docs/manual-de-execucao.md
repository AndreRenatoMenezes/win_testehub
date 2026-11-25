# Manual de Execução — Hardware Test Hub

**Versão:** 1.2  
**Data:** 2026-11-23  
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

O **WinTestHub** (Hardware Test Hub) é um framework Windows para validação de hardware que automatiza a preparação do ambiente, execução de testes de diagnóstico (CPU, memória, disco, rede, boot/shutdown, bateria, Wi-Fi e cargas reais de desenvolvimento) e geração de relatórios. Através de um menu interativo no console, o operador seleciona quais testes executar e acompanha o progresso em tempo real. Os resultados são persistidos em múltiplos formatos (HTML, CSV, JSON) com rastreabilidade completa por cenário.

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
| Cargas de dev (Módulos 7 a 11) | Notebook **na tomada**; ~20 GB livres na pasta de trabalho (repositórios, caches e imagens); virtualização habilitada na BIOS para o módulo 10 (Podman/WSL2) |
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

Para as **cargas de desenvolvimento (Módulos 7 a 11)**, os setups `7_install_devtools_dev` e `10_preparar_podman` instalam Git, .NET SDK 10, Go, uv, docker-compose, WSL2 e Podman (veja a seção 4.8).

### 2.3 Rede `[Técnico]`

O teste de rede (`3_teste_rede.py`, ~20 min) mede **duas fontes em rodadas intercaladas**, 10 de cada mais 1 de aquecimento:

- **Speedtest interno:** a URL fica fora do repositório, na chave `SpeedtestUrl` do `config.local.json` na raiz do hub (modelo em `config.local.example.json`) ou na variável de ambiente `HUB_SPEEDTEST_URL`. Verifique se a máquina tem acesso a essa URL.
- **Internet (`https://fast.com/`, Netflix):** os domínios `fast.com`, `api.fast.com` e `*.oca.nflxvideo.net`, ou a categoria "speedtest", precisam estar liberados na política do agente zero trust/proxy. O teste registra o **IP público de saída** e a localização vistos pelo fast.com, como evidência do caminho do tráfego (com o agente ativo, devem ser os do nó de saída do agente).
- **Uma fonte fora do ar vira só aviso:** o teste passa quando pelo menos uma das duas mede ok, e o motivo da outra aparece nos avisos da rodada.
- **Para comparar hardware, use cabo.** No Wi-Fi o teste registra banda, canal, sinal e AP de cada rodada e avisa no relatório. No Windows 11, o `netsh` só informa esses campos com a permissão de **Localização** ligada.
- Para um teste rápido (ex.: conferir o acesso), defina `HUB_REDE_RODADAS=2` antes de abrir o hub.

### 2.4 Estrutura de Pastas Esperada `[Técnico]`

```
C:\TesteHub\
├── hub.bat              # Ponto de entrada
├── hub.ps1              # Orquestrador principal
├── config.json          # Configurações
├── config.local.json    # Valores internos, como a URL do speedtest (não versionado)
├── Setup\environment\   # Scripts de setup (13 scripts)
├── Testes\              # Módulos de teste (11 módulos + 2 variantes DLP/USB; _lib\ = biblioteca dos módulos 7 a 11)
├── Execucoes\           # Logs, evidências e estado de cada cenário (criada pelo hub)
└── Exportar\            # Traces de cada cenário prontos para o Drive, sem .etl nem logs (criada pelo hub)
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
| `7_install_devtools_dev` | Instala Git, .NET SDK 10, Go, uv e docker-compose (módulos 7 a 11) |
| `8_enable_diagnostics` | Habilita os diagnósticos de boot/shutdown do Windows |
| `9_AdicionarTecladoUSInt` | Adiciona o layout de teclado EUA-Internacional |
| `10_preparar_podman` | Ativa o WSL2, instala o Podman e liga a `podman machine` (módulo 10; pode pedir reinício) |
| `11_ca_corporativa_dev` | Opcional: CA corporativa para redes com inspeção TLS (sem inspeção, não altera nada) |
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

- **`[N]`** — Criar um novo cenário. O hub pergunta:
    1. o **nome do cenário** (ex.: `SDWAN 108.11.4.734 - Stack`; Enter = `Execucao`);
    2. o **modelo** da máquina (ex.: `3440`);
    3. o **patrimônio/serial** (ex.: `050221`).

    O modelo e o patrimônio são obrigatórios e nomeiam a pasta de exportação (`3440 - 050221`). Caracteres inválidos em nome de pasta (`\ / : * ? " < > |`, além de `[` e `]`) são removidos.

- **`[1-5]`** — Continuar um cenário existente. Se o cenário foi criado antes desta versão e não tem modelo e patrimônio, o hub pergunta os dois uma única vez.

- **`[E]`** — Exportar um cenário existente: o hub regera a pasta `Exportar/` desse cenário (ver [6.5](#65-pasta-de-exportação)) e pergunta se deseja compactá-la em ZIP.

O nome do cenário é combinado com o hostname e a data na pasta de execução, resultando em algo como: `ImagemLimpa_DESKTOP-ABC_2026-04-15`

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
-- Boot Shutdown ---------------------------
[X] 4_boot_shutdown_auto           [PY]   pendente
-- Bateria ---------------------------------
[X] 5_teste_bateria                [PY]   pendente
-- Wifi Fast Transition --------------------
[X] 6_teste_fast_transition        [PY]   pendente
-- Dev Dotnet ------------------------------
[X] 7_dev_dotnet                   [PY]   pendente
-- Dev Go ----------------------------------
[X] 8_dev_go                       [PY]   pendente
-- Dev Python ------------------------------
[X] 9_dev_python                   [PY]   pendente
-- Dev Containers --------------------------
[X] 10_dev_containers              [PY]   pendente
-- Dev Git Arquivos ------------------------
[X] 11_dev_git_arquivos            [PY]   pendente
```

Desmarque com `Espaço` o que não for executar agora. Os módulos 5 e 6 exigem o operador presente e convém executá-los sozinhos (seções 4.6 e 4.7), os módulos 7 a 11 exigem a máquina na tomada e os setups de ferramentas (seção 4.8), e as variantes DLP/USB (`1-1` e `2-1`) só fazem sentido com um pendrive em `E:\`.

Num cenário com execuções anteriores, o menu mostra o último resultado e a duração de cada teste. Só os pendentes vêm marcados:

```
[ ] 1_automacao_performance        [PY]   PASS  (361.5s)
[ ] 2_teste_disco                  [PY]   FAIL  (12.3s)
[X] 3_teste_rede                   [PY]   pendente
[X] 4_boot_shutdown_auto           [PY]   pendente
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

Após confirmar, o hub faz a checagem antes da fila (seção 4.9), mostra o resumo dos testes selecionados e inicia a execução sequencial. Durante a execução:

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

O resultado detalhado fica em `5_bateria/bateria.csv`: `Coleta_Valida = sim` indica uma execução que serve para comparar baseline × agente.

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

Ao fim, o painel mostra PASS/FAIL e abre o relatório `6_wifi_fast_transition/wifi_ft_relatorio.html`, com gráficos e informações técnicas. O `wifi_ft.csv` fica na mesma pasta e segue na exportação.

### 4.8 Cargas de Desenvolvimento (Módulos 7 a 11) — Passo a Passo do Operador

Os módulos 7 a 11 cronometram tarefas reais de desenvolvimento (build, testes, `pip install`, containers, git). Cada um leva de 3 a 30 min (o 11 é o mais curto; o 8 e o 10, os mais longos), conforme a máquina e o primeiro download dos repositórios e imagens. A metodologia completa está na seção 10 da *Metodologia de Testes*.

**1. Prepare a máquina (uma vez)**

Na Fase de Setup, rode:

| Setup | Quando |
|-------|--------|
| `7_install_devtools_dev` | Sempre (Git, .NET SDK 10, Go, uv e docker-compose) |
| `10_preparar_podman` | Para o módulo 10. Se ele pedir para **reiniciar** (ativação do WSL2), o hub mostra `REINICIAR` e pergunta "Reiniciar agora? (S/N)". Com **S**, o Windows reinicia em 15 s e, depois do logon, o hub abre sozinho e continua a fila de setups no mesmo cenário. Com **N**, a fila segue e o 10 fica para rodar de novo depois que você reiniciar. Se cancelar o reinício com `shutdown /a`, a retomada continua agendada: o hub abre sozinho no próximo logon (se você abrir o hub à mão antes disso, o agendamento é removido) |
| `11_ca_corporativa_dev` | Só em rede com inspeção TLS. Na rede do laboratório ele confere e sai sem alterar nada |

O hub relê o PATH antes de cada script: o que um setup instala já vale para os setups e testes seguintes, sem reabrir o hub.

**2. Siga as regras de comparação**

- Notebook **na tomada** (na bateria o módulo reprova sem medir) e plano de energia no padrão do hub (setup `2_opcoes_energia`, **Equilibrado**), o mesmo da calibração da referência. O plano em uso fica registrado no JSON do módulo.
- Reinicie, espere 10 min ocioso e confira que Windows Update e varreduras de antivírus não estão rodando.
- Use a mesma rede nas máquinas comparadas: A6a (`pip install`) e A7a (build do container) baixam pacotes durante a medição.

**3. Selecione os módulos**

No menu, marque os módulos desejados (seções **Dev Dotnet**, **Dev Go**, **Dev Python**, **Dev Containers** e **Dev Git Arquivos**). Uma janela flutuante mostra a carga atual, a execução (1 a 3) e o limite. O cronômetro fica em azul ("medindo") durante a medição. Em amarelo, ele mostra as fases fora da medição: download do repositório, preparo, setup e cleanup. O preparo pode levar mais de 10 minutos na primeira vez, por exemplo para compilar os testes do Hugo. A última linha da janela mostra o uso de CPU da máquina e a última saída do comando em curso, com há quantos segundos ela apareceu. Se o cronômetro anda e a CPU está alta, o teste está trabalhando. Alguns comandos ficam vários minutos sem escrever nada, como o `podman build`. **Ctrl+Q** interrompe com segurança: a carga é encerrada, o `cleanup` roda, o módulo termina com FAIL e o hub para a fila.

**4. Veja o resultado**

Cada módulo grava em `Traces/<módulo>/` o `dev_<módulo>.csv`, o `dev_<módulo>.json` e os logs em `logs/` (que não vão para a pasta de exportação). O módulo dá **PASS** quando todas as cargas terminam OK; dá **FAIL** se alguma quebrar, passar de **10x o tempo da referência**, se faltar ferramenta ou se a máquina estiver na bateria.

**Calibração da referência `[Técnico]`**

O limite de 10x vem do `referencia.json` de cada módulo, gerado no **notebook de referência** (o atual da frota). Para gerar ou atualizar, nessa máquina, com o `.venv` do hub:

```bat
cd C:\TesteHub
.venv\Scripts\python Testes\7_dev_dotnet\7_dev_dotnet.py --calibrar
.venv\Scripts\python Testes\8_dev_go\8_dev_go.py --calibrar
.venv\Scripts\python Testes\9_dev_python\9_dev_python.py --calibrar
.venv\Scripts\python Testes\10_dev_containers\10_dev_containers.py --calibrar
.venv\Scripts\python Testes\11_dev_git_arquivos\11_dev_git_arquivos.py --calibrar
```

A calibração só grava o arquivo se todas as cargas terminarem OK. Versione os `referencia.json` gerados (não contêm hostname). Sem o arquivo, o módulo roda sem limite de tempo e avisa no log.

Outras opções da execução avulsa: `--runs N` (padrão 3), `--only A4a,A4c` (só as cargas com esses prefixos; com `--calibrar`, atualiza só a referência dessas cargas e mantém as demais) e `--sem-overlay`. Fora do hub, as evidências vão para `_saida/` dentro da pasta do módulo.

**Cargas internas `[Técnico]`**

Para medir também repositórios internos, copie `workloads.local.example.json` para `workloads.local.json` (raiz do hub, fora do git) e descreva as cargas no mesmo formato do `cargas.json` do módulo. Elas rodam junto com as públicas, sem limite de tempo. Nunca coloque credenciais no arquivo: o clone usa o gerenciador de credenciais do git.

---

### 4.9 Checagem Antes da Fila e Sobras de Teste

Depois que você escolhe os testes, e antes do resumo pré-execução, o hub confere **só o que os testes selecionados precisam**. Leva alguns segundos e evita descobrir horas depois que um módulo saiu vazio ou com FAIL.

Cada achado aparece no resumo com um nível e com o que fazer:

- **`[X]` Impede:** o teste vai falhar com certeza.
    - Falta o `Agentes_SI_Profile.wpaProfile` (módulo 1) ou o `Agentes_SI_Bateria_Profile.wpaProfile` (módulo 5) na pasta do teste. Esses arquivos não são versionados.
    - Falta o `wpr.exe` ou o `wpaexporter.exe` (módulos 1 e 5).
    - A URL do speedtest interno não está configurada **e** não há internet (módulo 3: nenhuma das duas fontes pode ser medida).
    - Falta uma ferramenta de dev, ou ela está abaixo da versão mínima do `cargas.json` (módulos 7 a 11). A ação manda rodar o Setup 7 ou o Setup 10.
    - A `podman machine` está desligada (módulo 10).
    - O notebook está na bateria (módulos 7 a 11, que dão FAIL fora da tomada).
- **`[!]` Atenção:** o teste roda, mas a medição pode sair comprometida.
    - Notebook na bateria (demais testes; o teste 5 é o único que deve rodar na bateria).
    - Sem internet (módulos 3 e 7 a 11). No módulo 3, só o speedtest interno será medido.
    - A URL do speedtest interno não está configurada (módulo 3: só a internet será medida).
    - Pouco espaço livre no disco do hub (padrão: menos de 20 GB).
    - **Sobra de teste:** um processo que um teste abriu e não fechou direito, consumindo recursos.
    - Processo qualquer usando muita CPU (os 5 maiores acima de 10% de um núcleo). Só aviso: o hub **nunca** encerra processos que não são de teste.

Teclas do resumo pré-execução:

| Tecla | Ação |
|-------|------|
| `Enter` | Iniciar (só quando não há `[X]`) |
| `R` | Tirar da fila os testes com `[X]` e refazer a checagem (só com `[X]`) |
| `C` | Continuar mesmo assim: os testes com `[X]` rodam e o fato fica registrado (só com `[X]`) |
| `F` | Encerrar as sobras de teste (pede confirmação `S/N`) e refazer a checagem (só com sobra) |
| `Esc` | Voltar ao menu de testes |

Com algum `[X]` na tela, o `Enter` não inicia a fila: escolha `R`, `C` ou `Esc`. Os achados e a escolha feita vão para o log da run. Quando a fila inicia (`Enter` ou `C`), os achados também entram nos avisos da rodada (seção 6.6); com `Esc`, ou recusando o `F`, ficam só no log.

**Sobras que o hub reconhece.** O Edge e o Python são reconhecidos pela linha de comando ou pela flag de automação. `wpaexporter.exe` e `diskspd.exe` são reconhecidos pelo nome, porque só existem por causa dos testes do hub.

| Sobra | Como o hub encerra |
|-------|--------------------|
| Sessão do WPR gravando | `wpr -cancel` |
| `wpaexporter.exe`, `diskspd.exe` | encerra a árvore do processo |
| Edge da automação (`msedgedriver` e o Edge aberto por ele ou com `--enable-automation`) | encerra a árvore do processo |
| Python rodando um script de `Testes\` | encerra a árvore do processo |
| Build servers do .NET (`MSBuild /nodeReuse`, `VBCSCompiler`) | só entre testes: encerra os processos que o teste abriu (antes da fila, só aviso, sem `F`: podem ser do Visual Studio do usuário) |
| Stack do módulo 10 (containers `wintestehub-*`) | `podman compose down -v` |
| `podman machine` ligada sem o módulo 10 na fila | `podman machine stop` |

O Edge e o Python do usuário ficam: um Edge comum (mesmo aberto para depuração pelo VS Code) e um Python fora de `Testes\` não são sobra.

**Entre um teste e outro**, o hub repete a busca só com as sobras do teste que acabou e as encerra sem perguntar, porque a fila é desassistida. Entre os processos, ele só encerra os que **o próprio teste abriu**: o que já existia antes do teste começar (ex.: o Visual Studio do usuário) fica. A sessão do WPR, a stack do módulo 10 e a `podman machine` não são processos; elas seguem a pasta do teste que acabou de rodar. A `podman machine` só é desligada quando nenhum teste do módulo 10 vem depois. Cada encerramento vai para o log e para os avisos da rodada.

## 5. Cenários e Re-execução

### 5.1 O que é um Cenário

Um **cenário** é uma sessão de testes associada a uma máquina e data. Ele agrupa todas as execuções (runs) e suas evidências em uma única pasta dentro de `Execucoes/`. Ao fim de cada execução, uma cópia enxuta das evidências é gerada em `Exportar/<cenário>/<modelo> - <patrimônio>/`. Isso permite:

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
        ├── maquina.csv                      # Modelo, série, CPU, RAM, disco, SO + modelo/patrimônio informados
        ├── 1_cpu_memo/                      # Evidências do Módulo 1
        │   └── dlp_usb/                     # Evidências da variante 1-1
        ├── 2_disco/                         # Evidências do Módulo 2 e da variante 2-1
        ├── 3_rede/                          # Speedtest interno + fast.com (rede.csv)
        ├── 4_boot_shutdown/
        ├── 5_bateria/                       # Pré-voo, amostras, traces, bateria.csv
        ├── 6_wifi_fast_transition/
        └── <pasta do teste>/_anterior/      # Evidências de execuções anteriores
            ├── run1_2026-04-15T09-30-00/
            └── run2_2026-04-15T14-00-00/

Exportar/
└── ImagemLimpa/                             # Nome do cenário
    ├── 3440 - 050221/                       # {modelo} - {patrimônio}: cópia de Traces/ sem .etl, logs e pastas vazias
    └── 3440 - 050221.zip                    # Opcional
```

---

## 6. Saídas e Relatórios

### 6.1 Onde Encontrar os Resultados

| Local | Conteúdo | Quando usar |
|-------|----------|-------------|
| `Execucoes/{cenário}/Logs/` | Resultados **por execução** (run) | Consultar uma execução específica |
| `Execucoes/{cenário}/Traces/` | Evidências e relatório **consolidado** do cenário | Visão completa de um ciclo de testes |
| `Exportar/{cenário}/{modelo} - {patrimônio}/` | Cópia de `Traces/` sem `.etl`, logs e pastas vazias, com o inventário (`maquina.csv`), o relatório consolidado e os CSVs temáticos de cada módulo | Subir para o Drive, planilhas e BI |

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
| Subir as evidências para o Drive | `Exportar/<cenário>/<modelo> - <patrimônio>/` |

### 6.5 Pasta de Exportação

Ao fim de cada execução, o hub regera `Exportar/<cenário>/<modelo> - <patrimônio>/`, uma cópia de `Traces/` pronta para arrastar para a pasta do projeto no Drive (ex.: `Netskope SD-WAN 108.11.4.734/Windows/SDWAN 108.11.4.734 - Stack/`).

| Fica de fora | Motivo |
|--------------|--------|
| Arquivos `.etl` (traces do WPR, 200 a 400 MB cada) | Os CSVs exportados pelo WPA ficam |
| Arquivos `.log` e pastas `logs/` | Não são usados na análise nem na conferência |
| Pastas que ficam vazias | Ruído |

Todo o resto vai: relatórios `_relatorio.*`, `_state.json`, `maquina.csv`, `informacoes_maquina.csv`, CSVs temáticos, CSVs do WPA, evidências PNG/HTML/XML e as pastas `_anterior/` (já filtradas).

- **`Traces/` não é alterada.** Os `.etl` e logs originais continuam em `Execucoes/` para abrir no WPA ou investigar falhas.
- **A pasta é recriada a cada execução** e reflete o estado atual do cenário. Arquivos colocados à mão nela são perdidos, e um ZIP anterior dela é removido por estar desatualizado.
- Ao final, o hub mostra quantos arquivos e MB foram exportados e quanto ficou de fora (ex.: `12 .etl, 3600 MB`).
- Se um módulo tinha só `.etl` e logs, o hub avisa com `[!] <módulo> sem evidencias do teste na exportacao` (o `frequencia_cpu.csv`, gerado pelo próprio hub, não conta como evidência). Isso costuma indicar que o teste não gerou os CSVs: por exemplo, falta o `.wpaProfile` dos módulos 1 e 5, e o WPA não exporta. As evidências continuam só em `Execucoes/`. Corrija a causa e reexecute o teste, ou gere os CSVs a partir dos `.etl`.
- Em seguida, pergunta se deseja **compactar em ZIP**. O ZIP fica ao lado da pasta (`3440 - 050221.zip`), contém a pasta como raiz e é validado pela contagem de arquivos. Nenhuma pasta é apagada.
- A opção **`[E]`** do menu inicial faz o mesmo para um cenário existente, sem rodar testes.

### 6.6 Avisos da Rodada e Frequência da CPU

O `_relatorio.html` e o `_relatorio.json` (em `Traces/`, e portanto também na exportação) têm duas seções a mais:

**Avisos da rodada**, com a run, a fonte e o texto de cada aviso:

| Fonte | Quando aparece |
|-------|----------------|
| `checagem` | Achados da checagem antes da fila, o teste tirado com `R` (com o motivo) ou a escolha `C` |
| `sobra` | Sobra de teste encerrada antes da fila (`F`) ou entre testes |
| `modulo_vazio` | Módulo executado que ficaria só com `.etl`/logs na exportação |
| `csv_faltando` | Teste executado que não gerou o CSV temático |
| `carga_dev` | Carga dos módulos 7 a 11 com status diferente de `OK`, com o motivo |
| `rede` | Carga de dev sensível à internet do lab (ex.: `pip install`, `podman build`) |
| `throttling` | Queda do clock sob carga acima do limite (padrão 20%) |

Os avisos ficam guardados no `_state.json` e se acumulam: os de uma run anterior continuam no relatório, identificados pelo número da run. Quem abre a pasta no Drive vê as ressalvas da rodada sem abrir os CSVs.

**Frequência da CPU por módulo.** Enquanto cada teste roda, o hub grava `<módulo>/frequencia_cpu.csv` com uma amostra a cada 5 s: uso da CPU, desempenho em % (acima de 100 = turbo), MHz efetivo e a maior temperatura das zonas térmicas ACPI, quando o firmware expõe. O relatório mostra o MHz médio, o MHz no começo e no fim e a queda. A queda (aviso a partir de 20%) compara a mediana do 1º e do último minuto **com a CPU sob carga** (uso de pelo menos 50%), porque em ocioso o clock cai sem ser throttling. Testes curtos ou ociosos aparecem sem queda (`-`).

O amostrador não roda nos setups nem no teste 5 (bateria), para não acordar a CPU a cada poucos segundos durante horas. No teste 4, a máquina reinicia e o CSV fica parcial; com menos de 3 amostras, ele é ignorado.

---

## 7. Troubleshooting

### 7.1 Erros Comuns

| Problema | Causa provável | Solução |
|----------|---------------|---------|
| Hub não inicia / fecha imediatamente | Falta de privilégio de admin | Execute `hub.bat` como Administrador (clique direito → Executar como administrador) |
| "Python não encontrado" | Python não instalado ou `.venv` ausente | Re-execute o setup selecionando scripts 4 e 5 |
| Teste de rede falha com "Edge não encontrado" | Microsoft Edge ausente/removido da máquina | O Edge é nativo do Windows 10/11 — reinstale/repare o Microsoft Edge pelo site oficial da Microsoft |
| Teste de rede com aviso "speedtest interno off -- URL do speedtest interno nao configurada" | `config.local.json` ausente ou sem a chave `SpeedtestUrl` | Crie o `config.local.json` a partir do `config.local.example.json` (veja a seção 7.3). Só a internet foi medida |
| Teste de rede falha com "Falha ao iniciar o Microsoft Edge via Selenium" | O Selenium Manager não conseguiu baixar o `msedgedriver` | Verifique o acesso da máquina ao CDN de drivers do Edge, ou coloque um `msedgedriver.exe` compatível no `PATH` |
| Teste de rede com aviso "internet (fast.com) off -- fast.com bloqueado" | Política do agente zero trust/proxy bloqueando o fast.com (ou a categoria speedtest), ou máquina sem acesso à internet | Libere `fast.com`, `api.fast.com` e `*.oca.nflxvideo.net` na política; confira a tela capturada em `Evidencia_Rede_Internet_Bloqueio_*.png` e o log `teste_rede_*.log`. O speedtest interno continua sendo medido |
| Teste de rede com aviso de fonte "parcial" ou "instavel" | Rodadas que falharam, passaram de 120 s ou foram contaminadas por tráfego de fundo; ou CV acima de 10% | Veja as colunas `Status`, `Motivo` e `Contaminada` no `resultado_afericoes.csv`. Prefira cabo, feche o que estiver baixando (atualizações) e repita |
| Teste de rede FAIL | Nenhuma das duas fontes terminou ok | Confira os motivos no `rede.csv` (`Interno_Motivo`, `Internet_Motivo`) e no log |
| Teste de disco falha rapidamente | Espaço insuficiente em disco | Libere pelo menos 10 GB no disco principal |
| Overlay visual não aparece | Problema com `tkinter` | Verifique se o Python foi instalado com suporte a tkinter (padrão na instalação oficial) |
| Wi-Fi FT: "O Wi-Fi não está conectado" | Máquina no cabo, Wi-Fi desligado ou desconectado | Conecte o Wi-Fi na rede a testar e execute de novo |
| Wi-Fi FT: FAIL "Nenhuma troca de AP aconteceu" | O operador não se afastou do AP inicial, ou só há 1 AP do SSID no percurso | Refaça a caminhada indo até áreas de outros APs (confira o inventário de APs no relatório) |
| Wi-Fi FT: FAIL "nenhum com Fast Transition" e achado "a rede usa PSK/802.1X/SAE" | O 802.11r não está habilitado no SSID | Habilite o 802.11r (FT) no SSID da controladora/AP; não é problema da máquina |
| Wi-Fi FT: rede anuncia FT, mas as trocas saem "Não FT" | Driver/adaptador sem suporte, driver antigo ou política do Windows | Veja "Transição Rápida" nas capacidades e a data do driver no relatório; atualize o driver Wi-Fi |
| Wi-Fi FT: trocas "Indeterminado" | O driver não informa a AKM no `netsh wlan show interfaces` | Atualize o driver; a evidência bruta fica em `brutos/netsh_interfaces*.txt` |
| Wi-Fi FT: painel não abriu | Edge bloqueado por política | Abra no navegador a URL "Painel ao vivo" registrada no log `teste_wifi_ft_*.log`; o teste roda mesmo sem o painel |
| Wi-Fi FT: métricas de internet `N/A` | Ping para `8.8.8.8` bloqueado pelo firewall | Esperado em redes corporativas; não reprova |
| Cargas dev: FAIL "Notebook na bateria" | Carregador desconectado | Conecte o carregador e execute de novo; o módulo não mede na bateria |
| Cargas dev: FAIL "'go'/'dotnet'/'uv'/'podman' nao encontrado no PATH" | Setup de ferramentas não rodou | Rode o setup `7_install_devtools_dev` (e o `10_preparar_podman` para containers) |
| Cargas dev: carga `TEMPO_EXCEDIDO` | A tarefa levou mais de 10x o tempo do notebook de referência | Confira no log da carga se houve espera de rede; se não, a máquina é inadequada para essa tarefa de desenvolvimento |
| Cargas dev: carga `FALHOU` | Build/teste quebrou, rede caiu no `setup` ou a VM do Podman parou | Veja o motivo no CSV e a saída completa em `Traces/<módulo>/logs/<carga>.log` |
| Cargas dev: aviso "sem referencia.json" | Módulo ainda não calibrado | Rode a calibração no notebook de referência (seção 4.8); até lá o módulo só reprova por falha |
| Podman: setup fica `REINICIAR` | O WSL2 acabou de ser ativado | Responda **S** na pergunta do hub (reinicia e retoma sozinho) ou reinicie depois e rode o `10_preparar_podman` de novo. Na 3ª vez seguida ele vira FAIL: confira a virtualização e o WSL |
| Podman: "Habilite a virtualização" | VT-x/AMD-V desligado na BIOS | Habilite a virtualização na BIOS/UEFI |
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
        "ExportarDir": "Exportar",
        "ExecucoesDir": "Execucoes"
    },
    "Settings": {
        "PythonVenvName": ".venv",
        "HtmlReportTitle": "WinTestHub - Relatório Final"
    },
    "Preflight": {
        "MinFreeGB": 20,
        "CpuAlertPct": 10,
        "InternetHost": "www.msftconnecttest.com"
    },
    "CpuSampler": {
        "Enabled": true,
        "IntervalSec": 5,
        "ThrottleAlertPct": 20,
        "LoadMinPct": 50,
        "SkipFolders": ["5_bateria"]
    }
}
```

As seções `Preflight` e `CpuSampler` são opcionais: um `config.json` antigo, sem elas, usa os valores acima.

| Chave | Uso |
|-------|-----|
| `Preflight.MinFreeGB` | Espaço livre mínimo no disco do hub antes de avisar |
| `Preflight.CpuAlertPct` | % de um núcleo a partir da qual um processo aparece como "usando CPU" |
| `Preflight.InternetHost` | Host testado na porta 443 para a checagem de internet |
| `CpuSampler.Enabled` | Liga/desliga o `frequencia_cpu.csv` (`false` sem aspas) |
| `CpuSampler.IntervalSec` | Intervalo entre amostras, em segundos (mínimo 1) |
| `CpuSampler.ThrottleAlertPct` | Queda do clock sob carga que vira aviso de throttling |
| `CpuSampler.LoadMinPct` | Uso de CPU a partir do qual a amostra conta como "sob carga" |
| `CpuSampler.SkipFolders` | Pastas de teste em que o amostrador não roda |

Valores internos ficam em `config.local.json`, na raiz do hub. Esse arquivo não vai para o repositório; o modelo é o `config.local.example.json`:

| Chave | Variável de ambiente equivalente | Uso |
|-------|----------------------------------|-----|
| `SpeedtestUrl` | `HUB_SPEEDTEST_URL` (tem prioridade) | URL do speedtest interno do Módulo 3 |
| `DevWorkDir` | — | Pasta de trabalho dos módulos 7 a 11 (padrão `%USERPROFILE%\wintestehub-dev-work`) |

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

### Resumo Pré-execução (Checagem)

| Tecla | Ação |
|-------|------|
| `Enter` | Iniciar (sem itens `[X]`) |
| `R` | Tirar da fila os testes com `[X]` (só com `[X]`) |
| `C` | Continuar mesmo assim (só com `[X]`) |
| `F` | Encerrar as sobras de teste (só com sobra) |
| `Esc` | Voltar ao menu |

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
| `Ctrl+Q` | CPU & Memória, Bateria, Cargas dev (7 a 11) | Interromper o teste de forma segura e **parar a fila**: os testes seguintes ficam como *cancelado* e o hub gera o relatório com o que já rodou |

O Ctrl+Q vale para a execução inteira, não só para o teste em andamento. Para pular só um teste com falha, não use o Ctrl+Q: espere a pergunta "Teste falhou. Deseja continuar?" e responda `S`. Teclas apertadas durante o teste são descartadas antes dessa pergunta, então elas não respondem por você.

---

> **Nota sobre imagens:** Os placeholders `img/placeholder-*.png` devem ser substituídos por screenshots reais capturados durante a execução do hub. Crie a pasta `docs/img/` e salve as imagens com os nomes indicados.
