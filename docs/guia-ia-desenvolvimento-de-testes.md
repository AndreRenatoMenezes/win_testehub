# Guia para IA: desenvolvimento de testes Python para o WinTestHub

> **Para quem é este documento:** um assistente de IA que vai escrever ou revisar módulos de teste em Python para o WinTestHub. Ele descreve o contrato **real** entre os scripts e o orquestrador (`hub.ps1`), as armadilhas já encontradas no projeto, um modelo de script pronto e o que entregar junto com o código.
>
> Leia tudo antes de gerar código. As seções 2 e 3 são regras obrigatórias. O resto explica o porquê e traz o modelo.

---

## 1. Contexto

O **WinTestHub** homologa notebooks e desktops Windows 10/11. O operador dá dois cliques em `hub.bat`, que eleva para administrador e executa o `hub.ps1` (Windows PowerShell 5.1). O hub:

1. pede um **cenário** (ex.: `ImagemLimpa`, `ComAgentes`) e cria `Execucoes/<cenário>_<host>_<data>/`;
2. **Fase 1 (preparação):** executa os scripts de `Setup/` (energia, Python 3.12, `.venv`, dependências…);
3. **Fase 2 (testes):** procura recursivamente todo `*.py` e `*.ps1` em `Testes/`, mostra um menu de seleção e executa os escolhidos, **um por vez**;
4. grava o status de cada teste em `Traces/_state.json`, gera relatórios (HTML, CSV, JSON, log) e copia os CSVs-resumo para `Resultados/<cenário>/`.

Módulos existentes, que servem de referência:

| Pasta | Script | Padrões que vale copiar |
|-------|--------|-------------------------|
| `Testes/2_disco/` | `2_teste_disco.py` | O mais simples: overlay, thread de trabalho, `_exit_code`, CSV temático, binário ao lado do script |
| `Testes/3_rede/` | `3_teste_rede.py` | Logging em arquivo + console, URL interna via `config.local.json`, `raise` na thread |
| `Testes/1_cpu_memo/` | `1-1_automacao_performance_dlp.py` | Variante numa subpasta própria, `Ctrl+Q` com `pynput`, limpeza (WPR) no `except` |
| `Testes/4_boot_shutdown/` | `4_boot_shutdown_auto.py` | Teste que reinicia a máquina (caso avançado; evite se puder) |
| `Testes/5_bateria/`, `Testes/6_wifi_fast_transition/` | | Interação com o operador por janela Tkinter |

---

## 2. Contrato obrigatório

### 2.1 Exit code é o resultado

| Exit code do processo | Status no hub |
|-----------------------|---------------|
| `0` | **PASS** |
| qualquer outro | **FAIL** |
| exceção dentro do próprio hub | ERROR |

- Saia com `0` **somente** se o critério de aprovação foi verificado e atendido. "Rodou sem exceção" não é PASS se o critério exige, por exemplo, 5 aferições válidas.
- **`sys.exit()` dentro de uma `threading.Thread` só encerra a thread.** O processo termina com `0` e o hub registra PASS. Na thread de trabalho, faça `raise` ou ajuste a variável global `_exit_code`; chame `sys.exit(_exit_code)` **apenas na thread principal**, depois do `mainloop()`.
- `KeyboardInterrupt` **não** é subclasse de `Exception`. Um `except Exception` não o captura, e a thread morre deixando `_exit_code = 0`. Esse bug já aconteceu no módulo 1-1. Use uma exceção própria para a parada segura (veja o modelo).

### 2.2 Evidências vão para `HUB_EVIDENCE_DIR`

O hub define, antes de cada script, e limpa depois:

| Variável | Valor |
|----------|-------|
| `HUB_EVIDENCE_DIR` | `Execucoes/<cenário>/Traces/<nome-da-pasta-do-teste>` (já existe) |
| `HUB_TRACE_DIR` | Igual a `HUB_EVIDENCE_DIR` |
| `HUB_TRACE_ROOT` | `Execucoes/<cenário>/Traces` |

Regras:

- **Todo** arquivo gerado (CSV, log, JSON, prints de tela, traces ETL) vai para `HUB_EVIDENCE_DIR` ou uma subpasta dele. Nunca grave na raiz do projeto, na pasta do script (quando rodando no hub), no Desktop ou em `%TEMP%` como destino final.
- Para rodar fora do hub, use a pasta do próprio script como fallback. Trate string vazia como ausente:

  ```python
  BASE_DIR = os.path.dirname(os.path.abspath(__file__))
  OUTPUT_DIR = os.environ.get("HUB_EVIDENCE_DIR") or BASE_DIR
  os.makedirs(OUTPUT_DIR, exist_ok=True)
  ```

- O hub conta os arquivos dessa pasta como "Traces gerados" no relatório.
- Numa reexecução, o hub move as evidências antigas para `HUB_EVIDENCE_DIR/_anterior/run<N>_<timestamp>/` **antes** de chamar o script. O script **não** deve apagar nada em `HUB_EVIDENCE_DIR`, nem ler ou incluir `_anterior/` em globs (use globs não recursivos ou filtre `_anterior`).

### 2.3 Variantes na mesma pasta

O hub dá a **todos** os scripts de uma pasta o mesmo `HUB_EVIDENCE_DIR`. Uma variante (ex.: `7-1_...py` dentro de `7_categoria/`) deve gravar numa **subpasta própria** (`os.path.join(HUB_EVIDENCE_DIR, "nome_variante")`) e ter um CSV temático com nome próprio. Caso contrário, um teste sobrescreve o outro e globs como `CSV_*` misturam os resultados.

### 2.4 Nenhuma interação pelo console

- Na Fase 2 o hub executa o script em modo silencioso: **o stdout é capturado para o log e não aparece para o operador**. O console mostra só o painel de progresso do hub.
- Portanto **nunca use `input()`, `getpass`, `msvcrt.getch` ou "pressione Enter"**. O script trava esperando uma entrada que ninguém vê, e o hub não tem timeout.
- Para informar o operador, use um **overlay Tkinter click-through** (seção 4.3). Para pedir uma ação (desconectar o carregador, andar com o notebook), use uma **janela Tkinter própria** com botão, como os módulos 5 e 6.

### 2.5 O hub não tem timeout

Se o script travar, o hub trava junto. Toda espera precisa de limite: `timeout=` em `subprocess.run`, `requests` e `WebDriverWait`; laços de polling com prazo máximo; nada de `while True` sem saída.

### 2.6 Descoberta, nome e ordem no menu

- Estrutura: `Testes/N_categoria/N_nome_do_teste.py`. Ex.: `Testes/7_gpu/7_teste_gpu.py`. Variante: `Testes/7_gpu/7-1_teste_gpu_variante.py`.
- O rótulo do grupo no menu vem do nome da pasta sem o prefixo numérico: `7_gpu` → **Gpu**; `6_wifi_fast_transition` → **Wifi Fast Transition**.
- O menu é ordenado pelo **nome do arquivo** (não da pasta) e cria um separador sempre que a pasta muda. Por isso o prefixo numérico do arquivo deve ser igual ao da pasta, senão o grupo aparece partido.
- **Todo** `.py`/`.ps1` dentro de `Testes/` vira item do menu, inclusive módulos auxiliares (`utils.py`, `helpers.py`). Prefira um script **autocontido**. Se um auxiliar for inevitável, ele precisa entrar no `-Exclude` da função `Get-Scripts` do `hub.ps1` (como `boot_shutdown_duration.ps1`).
- Arquivos não-script (binários, HTML, JSON de configuração) podem ficar na pasta do teste ou em `assets/`.

### 2.7 Ambiente de execução

| Item | Valor |
|------|-------|
| Interpretador | `.venv\Scripts\python.exe` na raiz do hub (fallback: `python3`/`python` do PATH), chamado como `python -u <caminho>` |
| Versão | Python 3.12 |
| Privilégio | Administrador (o `hub.bat` já elevou; não tente se autoelevar) |
| Diretório atual | **Não confie nele.** Resolva caminhos a partir de `__file__` |
| stderr | Mesclado ao stdout e capturado no log (tracebacks aparecem no log) |
| Pacotes disponíveis | Biblioteca padrão + `psutil`, `speedtest-cli`, `requests`, `selenium`, `pandas`, `pyautogui`, `pyperclip`, `pynput` |

Pacote novo? Adicione-o à lista `$Pacotes` de `Setup/environment/5_install_py_dependencies.ps1` e cite isso na entrega.

### 2.8 Saída de console e encoding

- O stdout do Python, quando vai para um pipe no Windows, usa a codificação local (cp1252). Um `print` com caractere fora dela (`→`, `✓`, emoji) lança `UnicodeEncodeError` e o teste vira FAIL por um motivo bobo. Logo no início do script, faça:

  ```python
  for _s in (sys.stdout, sys.stderr):
      try:
          _s.reconfigure(errors="replace")
      except AttributeError:
          pass
  ```

- Mesmo assim, o PowerShell decodifica a saída com outra página de código, e acentos chegam corrompidos ao log do hub. **Escreva as mensagens de console em ASCII, sem acentos** (`"Afericao concluida"`), como fazem os módulos existentes. Arquivos (CSV, log próprio, JSON) devem ser gravados em `encoding="utf-8"` e podem ter acentos.

### 2.9 Mensagem de falha que o hub consegue mostrar

Quando o teste falha, o hub procura nas linhas da saída as palavras `erro`, `fail`, `falha`, `exception`, `critical`, `traceback`, `error` ou `[ERRO]`, pega a **última** linha encontrada e a mostra no painel (cortada em ~57 caracteres). Então:

- Antes de sair com FAIL, imprima **uma última linha curta e específica** com a causa: `[ERRO] Pendrive E:\ nao encontrado`, `[FALHA] 2/5 afericoes validas (minimo 5)`.
- Evite deixar como última linha um traceback genérico ou uma mensagem longa.

### 2.10 Dados sensíveis (o repositório é público)

- Nunca coloque no código IPs, URLs ou hostnames internos, credenciais, tokens, números de série ou logs reais. O CI bloqueia qualquer IPv4 fixo além de `127.0.0.1`, `0.0.0.0` e `8.8.8.8`.
- Valores internos ficam no `config.local.json` (não versionado) e numa variável de ambiente `HUB_*` equivalente, que tem prioridade. Siga o padrão do módulo 3 (seção 4.5) e acrescente a chave nova ao `config.local.example.json` com um valor fictício.
- Binários de terceiros só podem ser versionados se a licença permitir redistribuição (como o `diskspd.exe`, MIT). Caso contrário, documente como "arquivo não versionado" e falhe com mensagem clara quando ele faltar.

---

## 3. Requisitos de qualidade

1. **Limpeza garantida.** Tudo o que o teste inicia ou cria precisa ser desfeito num `finally` ou no `except`: processos (`wpr -cancel`, `driver.quit()`), arquivos temporários grandes, tarefas agendadas, configurações do Windows alteradas, serviços parados.
2. **Parada segura com `Ctrl+Q`** em testes com mais de ~2 minutos. Parar **é FAIL** (`_exit_code = 1`), faz a limpeza e grava o que já foi coletado.
3. **Pré-requisitos verificados no início** (arquivo, unidade, rede, binário, carga de bateria…), com mensagem `[ERRO]` clara e FAIL imediato, antes de gastar minutos de teste.
4. **Critério de aprovação explícito e mensurável** no topo do script, numa constante, e o mesmo texto na metodologia.
5. **Log próprio** em `OUTPUT_DIR` (`logging` com `FileHandler` em UTF-8, nível DEBUG) além do console (nível INFO). Comece registrando host, usuário, parâmetros e pasta de saída.
6. **Sem efeitos colaterais fora do teste.** Não altere configurações globais da máquina sem restaurá-las. Se a alteração for intencional e permanente, ela pertence a um script de `Setup/`, não a `Testes/`.
7. **Script autocontido**, executável sozinho (`python 7_teste_gpu.py`) e dentro do hub, sem alterações.

---

## 4. Padrões de implementação

### 4.1 Arquitetura do processo

```
thread principal  ── cria o overlay Tk ── mainloop() ── sys.exit(_exit_code)
        │                                     ▲
        └─ inicia ─► thread de trabalho ──────┘ (pede o fechamento ao terminar)
                       try: pré-requisitos → ciclos → CSVs → PASS/FAIL
                       except ParadaSolicitada / Exception: _exit_code = 1
                       finally: limpeza + fechar overlay
listener pynput (daemon) ── Ctrl+Q ──► threading.Event
```

O Tkinter só pode ser manipulado pela thread principal. A thread de trabalho apenas **publica** o estado numa fila, e a thread principal a lê com `root.after()` (polling). Os módulos antigos chamam `root.after()` direto da thread de trabalho; funciona na prática, mas o polling é o padrão recomendado para código novo.

### 4.2 Pausas interrompíveis

Troque `time.sleep(n)` por `_stop.wait(n)` seguido de `checar_parada()`. Assim o `Ctrl+Q` responde em até 1 s, mesmo durante um cooldown de vários minutos.

### 4.3 Overlay click-through

Janela pequena no canto superior direito, sempre por cima, semitransparente e **transparente a cliques** (`WS_EX_LAYERED | WS_EX_TRANSPARENT`), para não atrapalhar automações de mouse/teclado (Selenium, pyautogui). Mostra: ciclo atual, status e tempo restante, e a dica "Ctrl+Q para parada segura".

### 4.4 CSV temático (resumo para BI)

Se o teste tem métricas, gere em `OUTPUT_DIR` um CSV-resumo com nome curto (`gpu.csv`), neste formato fixo:

- UTF-8, separador `,`, decimal com **ponto**, cabeçalho `Metrica,Valor,Unidade`;
- uma linha por métrica, nomes em `Snake_Case` sem acento (`Leitura_Media`, `Ciclos_Executados`);
- `N/A` quando a métrica não pôde ser calculada.

Os CSVs detalhados, para leitura humana no Excel, podem usar `;` e vírgula decimal, como no módulo 2.

Depois, registre o CSV no `hub.ps1`, função `Copy-ThematicCSVs`:

```powershell
# Módulo principal: no mapa $expectedCSVs (chave = nome da pasta)
"7_gpu" = "gpu.csv"

# Variante: no mapa $variantCSVs (chave = caminho relativo a Traces)
"7_gpu/variante/gpu_variante.csv" = "gpu_variante.csv"
```

Se a variante for nova, acrescente também um caso ao `.github/scripts/Test-CopyThematicCSVs.ps1`.

### 4.5 Configuração interna (URL, host, credencial de teste)

```python
def carregar_config_local(chave, var_ambiente):
    """Variavel de ambiente tem prioridade; depois config.local.json na raiz do hub."""
    valor = os.environ.get(var_ambiente, "").strip()
    if valor:
        return valor
    caminho = os.path.join(BASE_DIR, "..", "..", "config.local.json")
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return str(json.load(f).get(chave, "")).strip()
    except (OSError, ValueError, AttributeError):
        return ""
```

Valor vazio é pré-requisito não atendido: `raise RuntimeError("... Defina HUB_X ou config.local.json")`.

### 4.6 Subprocessos e binários

- Localize binários pela pasta do script (`os.path.join(BASE_DIR, "ferramenta.exe")`) ou pelo `PATH` (`shutil.which`). Falhe com `[ERRO]` se não existirem.
- Use `subprocess.run([...], capture_output=True, text=True, timeout=...)` com **lista** de argumentos (evite `shell=True`), verifique `returncode` e grave stdout/stderr relevantes no log.
- Saída de ferramentas do Windows (`schtasks`, `netsh`, `powercfg`) costuma vir em cp850/cp1252: use `encoding="cp850", errors="replace"` ou `errors="replace"`.
- Na hora de interpretar números, não dependa do idioma do Windows (pt-BR usa vírgula decimal e mensagens traduzidas). Prefira saídas estruturadas (CSV, XML, `ConvertTo-Json` no PowerShell) a parsear texto.

---

## 5. Modelo de script

Ponto de partida para um módulo novo. Troque o que está marcado com `TODO`; a estrutura (overlay, thread, Ctrl+Q, exit code, CSV temático, limpeza) deve ser mantida.

```python
"""
Modulo 7 -- <Nome do teste>.

Executado pelo WinTestHub (hub.ps1). Contrato:
  - exit code 0 = PASS; qualquer outro = FAIL;
  - evidencias em HUB_EVIDENCE_DIR (fallback: pasta deste script);
  - sem input() no console: o hub captura o stdout e o operador nao o ve.

Criterio de aprovacao: CICLOS_TOTAIS ciclos validos, sem erro.
"""
import csv
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime

from pynput import keyboard as kb

# Um print com caractere fora do cp1252 nao pode derrubar o teste.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except AttributeError:
        pass

# =============================================================================
# CONFIGURACAO DO TESTE  (TODO)
# =============================================================================
NOME_TESTE = "Exemplo"
CICLOS_TOTAIS = 5
DURACAO_CICLO_S = 30
PAUSA_ENTRE_CICLOS_S = 10
CSV_TEMATICO = "exemplo.csv"   # registrar em $expectedCSVs do hub.ps1

# =============================================================================
# INTEGRACAO COM O HUB
# =============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSAO = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.environ.get("HUB_EVIDENCE_DIR") or BASE_DIR
# Variante na mesma pasta do modulo principal? Use uma subpasta propria:
# OUTPUT_DIR = os.path.join(OUTPUT_DIR, "variante")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =============================================================================
# LOG: arquivo (DEBUG, UTF-8) + console (INFO, capturado pelo hub)
# =============================================================================
LOG_FILE = os.path.join(OUTPUT_DIR, f"teste_exemplo_{SESSAO}.log")
logger = logging.getLogger("TesteExemplo")
logger.setLevel(logging.DEBUG)
_fmt = logging.Formatter("[%(asctime)s] [%(levelname)-7s] %(message)s", "%Y-%m-%d %H:%M:%S")
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(_fmt)
logger.addHandler(_fh)
logger.addHandler(_ch)

# =============================================================================
# PARADA SEGURA (Ctrl+Q)
# =============================================================================
class ParadaSolicitada(Exception):
    """Ctrl+Q. Subclasse de Exception (KeyboardInterrupt escaparia do except)."""


_stop = threading.Event()
_ctrl = False


def _on_press(key):
    global _ctrl
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl = True
    elif _ctrl and getattr(key, "char", None) in ("q", "Q", "\x11"):
        if not _stop.is_set():
            logger.warning("Parada segura solicitada (Ctrl+Q).")
        _stop.set()


def _on_release(key):
    global _ctrl
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl = False


def checar_parada():
    if _stop.is_set():
        raise ParadaSolicitada("Parada segura solicitada pelo operador.")


def aguardar(segundos, ui=None, ciclo=0, status=""):
    """Pausa interrompivel por Ctrl+Q, com contagem regressiva no overlay."""
    for restante in range(int(segundos), 0, -1):
        if ui:
            ui.atualizar(ciclo, status, restante)
        if _stop.wait(1):
            break
    checar_parada()

# =============================================================================
# OVERLAY (click-through; so a thread principal toca no Tk)
# =============================================================================
class Overlay:
    def __init__(self, titulo):
        self._fila = queue.Queue()
        self.root = tk.Tk()
        self.root.title(titulo)
        largura = self.root.winfo_screenwidth()
        self.root.geometry(f"340x140+{largura - 370}+30")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#1e1e1e")
        self.root.protocol("WM_DELETE_WINDOW", _stop.set)
        self.lbl_ciclo = tk.Label(self.root, text="Preparando...", fg="#61C568",
                                  bg="#1e1e1e", font=("Segoe UI", 12, "bold"))
        self.lbl_ciclo.pack(pady=(10, 4))
        self.lbl_status = tk.Label(self.root, text="Iniciando...", fg="white",
                                   bg="#1e1e1e", font=("Segoe UI", 10))
        self.lbl_status.pack()
        self.lbl_tempo = tk.Label(self.root, text="", fg="#00d2ff",
                                  bg="#1e1e1e", font=("Consolas", 11))
        self.lbl_tempo.pack(pady=4)
        tk.Label(self.root, text="Ctrl+Q para parada segura", fg="#888888",
                 bg="#1e1e1e", font=("Segoe UI", 8)).pack()
        self.root.update_idletasks()
        self._click_through()
        self.root.after(200, self._consumir_fila)

    def _click_through(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            estilo = user32.GetWindowLongW(hwnd, -20)                      # GWL_EXSTYLE
            user32.SetWindowLongW(hwnd, -20, estilo | 0x00080000 | 0x00000020)  # LAYERED | TRANSPARENT
            user32.SetLayeredWindowAttributes(hwnd, 0, 230, 0x00000002)   # LWA_ALPHA
        except Exception:
            pass

    # Chamados pela thread de trabalho: so enfileiram.
    def atualizar(self, ciclo, status, restante_s=None):
        self._fila.put(("estado", ciclo, status, restante_s))

    def fechar(self):
        self._fila.put(("fechar",))

    def _consumir_fila(self):
        try:
            while True:
                msg = self._fila.get_nowait()
                if msg[0] == "fechar":
                    self.root.destroy()
                    return
                _, ciclo, status, restante = msg
                self.lbl_ciclo.config(text=f"Ciclo {ciclo} de {CICLOS_TOTAIS}" if ciclo else NOME_TESTE)
                self.lbl_status.config(text=status)
                self.lbl_tempo.config(text=f"Restante: {restante}s" if restante else "")
        except queue.Empty:
            pass
        self.root.after(200, self._consumir_fila)


class SemOverlay:
    """Fallback quando o Tk nao abre: o teste segue sem feedback visual."""
    def atualizar(self, *args, **kwargs):
        pass

    def fechar(self):
        pass

# =============================================================================
# LOGICA DO TESTE  (TODO)
# =============================================================================
def verificar_prerequisitos():
    # TODO: checar arquivos, binarios, unidades, rede, config.local.json...
    # Falhou? raise RuntimeError("mensagem curta e especifica")
    pass


def executar_ciclo(n, ui):
    """Executa um ciclo e devolve um dict com as metricas. TODO."""
    ui.atualizar(n, "Medindo...")
    aguardar(DURACAO_CICLO_S, ui, n, "Medindo...")
    return {"ciclo": n, "valor": 0.0}


def limpar():
    """Desfaz tudo o que o teste criou/iniciou. Deve ser idempotente. TODO."""
    pass


def gravar_csvs(resultados):
    detalhado = os.path.join(OUTPUT_DIR, f"resultado_exemplo_{SESSAO}.csv")
    with open(detalhado, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ciclo", "valor"])
        w.writeheader()
        w.writerows(resultados)

    valores = [r["valor"] for r in resultados]
    with open(os.path.join(OUTPUT_DIR, CSV_TEMATICO), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Metrica", "Valor", "Unidade"])
        w.writerow(["Ciclos_Executados", len(resultados), "un"])
        w.writerow(["Valor_Medio", f"{sum(valores) / len(valores):.2f}" if valores else "N/A", "un"])
    logger.info(f"CSVs gravados em {OUTPUT_DIR}")

# =============================================================================
# EXECUCAO
# =============================================================================
_exit_code = 1   # pessimista: so vira 0 quando o criterio for verificado


def worker(ui):
    global _exit_code
    resultados = []
    try:
        logger.info(f"INICIO: {NOME_TESTE} | Host: {os.environ.get('COMPUTERNAME', 'N/A')}")
        logger.info(f"Evidencias em: {OUTPUT_DIR}")
        verificar_prerequisitos()

        for n in range(1, CICLOS_TOTAIS + 1):
            checar_parada()
            resultados.append(executar_ciclo(n, ui))
            logger.info(f"Ciclo {n}/{CICLOS_TOTAIS} concluido")
            if n < CICLOS_TOTAIS:
                aguardar(PAUSA_ENTRE_CICLOS_S, ui, n, "Pausa entre ciclos")

        gravar_csvs(resultados)
        if len(resultados) == CICLOS_TOTAIS:
            _exit_code = 0
            logger.info("RESULTADO: PASS")
        else:
            print(f"[FALHA] {len(resultados)}/{CICLOS_TOTAIS} ciclos validos")

    except ParadaSolicitada:
        logger.warning("Teste interrompido pelo operador.")
        print("[FALHA] Interrompido pelo operador (Ctrl+Q)")
    except Exception as e:
        logger.critical(f"Falha durante o teste: {e}", exc_info=True)
        print(f"[ERRO] {e}")   # ultima linha: o hub mostra esta causa no painel
    finally:
        try:
            limpar()
        except Exception as e:
            logger.error(f"Erro na limpeza: {e}", exc_info=True)
        if _exit_code != 0 and resultados:
            try:
                gravar_csvs(resultados)   # preserva o que ja foi coletado
            except Exception:
                pass
        ui.fechar()


if __name__ == "__main__":
    listener = kb.Listener(on_press=_on_press, on_release=_on_release)
    listener.daemon = True
    listener.start()
    try:
        ui = Overlay(f"Monitor - {NOME_TESTE}")
    except tk.TclError:
        ui = None

    if ui:
        threading.Thread(target=worker, args=(ui,), daemon=True).start()
        ui.root.mainloop()
    else:
        worker(SemOverlay())

    listener.stop()
    sys.exit(_exit_code)   # unico sys.exit, na thread principal
```

Observações sobre o modelo:

- `_exit_code` começa em `1`: qualquer caminho inesperado termina em FAIL, nunca num PASS falso.
- As mensagens com `[FALHA]`/`[ERRO]` são impressas por último, de propósito (seção 2.9).
- Se o teste usa Selenium, crie o driver dentro do `try` e chame `driver.quit()` em `limpar()`. Se usa WPR, chame `wpr -cancel` em `limpar()` quando a captura estiver ativa.

---

## 6. Anti-padrões (não gere)

| Não faça | Por quê | Faça |
|----------|---------|------|
| `sys.exit(1)` na thread de trabalho | Encerra só a thread; o processo sai com 0 → PASS falso | `raise` ou `_exit_code = 1` |
| `except Exception` como única proteção com `KeyboardInterrupt` para parar | `KeyboardInterrupt` escapa; PASS falso e processos órfãos | Exceção própria (`ParadaSolicitada`) |
| `input()`, "pressione Enter" | O operador não vê o console; o hub trava | Janela Tkinter |
| `time.sleep(300)` | `Ctrl+Q` não responde | `aguardar()` / `_stop.wait()` |
| `open("resultado.csv", "w")` com caminho relativo | Grava no diretório atual (raiz do hub) | `os.path.join(OUTPUT_DIR, ...)` |
| `shutil.rmtree(OUTPUT_DIR)` ou limpar a pasta no início | Apaga evidências e o `_anterior/` | Só crie arquivos novos |
| `glob("**/*.csv", recursive=True)` na pasta de evidências | Pega arquivos de `_anterior/` e de variantes | Glob não recursivo, ou filtre |
| `utils.py` ao lado do teste | Vira item do menu do hub | Script autocontido |
| URL/IP interno no código | Repositório público; CI bloqueia | `config.local.json` + `HUB_*` |
| `print("✓ OK →")` | `UnicodeEncodeError` em cp1252 → FAIL | ASCII no console |
| `subprocess.run(cmd)` sem `timeout` | O hub não tem timeout | Sempre `timeout=` |
| `sys.exit(0)` no fim sem checar o critério | PASS só porque não houve exceção | Verifique o critério explicitamente |
| Alterar plano de energia, serviço ou registro sem restaurar | Contamina os próximos testes do cenário | Restaure em `finally`, ou mova para `Setup/` |

---

## 7. Validação antes de entregar

No Windows, numa máquina de teste (o CI **não** executa os testes, só valida sintaxe):

```powershell
# 1. Sintaxe, como no CI
pip install ruff
ruff check --select E9,F63,F7,F82 --target-version py312 Testes/
python -m compileall -q Testes/

# 2. Avulso (fallback para a pasta do script)
.\.venv\Scripts\python.exe -u Testes\7_gpu\7_teste_gpu.py; "exit=$LASTEXITCODE"

# 3. Simulando o hub
$env:HUB_EVIDENCE_DIR = "C:\temp\hub_ev\7_gpu"; New-Item -ItemType Directory $env:HUB_EVIDENCE_DIR -Force | Out-Null
.\.venv\Scripts\python.exe -u Testes\7_gpu\7_teste_gpu.py 2>&1 | Out-File C:\temp\hub_ev\saida.txt; "exit=$LASTEXITCODE"
Remove-Item Env:HUB_EVIDENCE_DIR
```

Confira:

- [ ] PASS → exit 0; pré-requisito ausente → exit ≠ 0 com `[ERRO] ...` na última linha relevante;
- [ ] `Ctrl+Q` no meio do teste → exit ≠ 0, limpeza feita, nada órfão no Gerenciador de Tarefas;
- [ ] todos os arquivos em `HUB_EVIDENCE_DIR` (nada novo na raiz do projeto nem na pasta do script);
- [ ] CSV temático no formato `Metrica,Valor,Unidade`;
- [ ] a saída redirecionada (passo 3) não tem `UnicodeEncodeError`;
- [ ] pelo menos uma execução completa pelo `hub.bat`, num cenário de teste: o item aparece no grupo certo, o status e a duração entram no relatório e o CSV chega em `Resultados/`.

---

## 8. O que entregar junto com o script

Um teste novo só está completo com todos estes itens (é o checklist do `CONTRIBUTING.md`):

1. `Testes/N_categoria/N_nome.py`, seguindo o modelo.
2. Diff do `hub.ps1`: CSV temático em `$expectedCSVs` (ou em `$variantCSVs`, para variante) e, se houver script auxiliar, o `-Exclude` em `Get-Scripts`.
3. Diff de `Setup/environment/5_install_py_dependencies.ps1`, se houver pacote novo.
4. Chave nova em `config.local.example.json` (valor fictício), se houver configuração interna.
5. Seção nova em `docs/metodologia-de-testes.md` (objetivo, procedimento, métricas, **critério de aprovação**) e passo a passo do operador em `docs/manual-de-execucao.md`. Depois, `python docs/gerar_html.py` (os `.html` são gerados; nunca edite à mão).
6. Linha na tabela "Módulos de teste" do `README.md` e na estrutura do repositório.
7. Entrada no `CHANGELOG.md`, seção **Não lançado**.
8. Mensagem de commit no padrão Conventional Commits: `feat(gpu): adiciona modulo 7 de teste de GPU`.

### Antes de escrever código, pergunte ao solicitante se faltar

- O **critério de PASS** exato e mensurável (limiar, quantidade de ciclos válidos);
- a duração esperada e o número de ciclos/baterias;
- se precisa de operador presente (e o que ele faz);
- pré-requisitos de hardware/rede (pendrive em qual letra, AP, carregador…);
- se há valor interno (URL, host) que deve ir para o `config.local.json`;
- se é um módulo novo (pasta nova) ou uma variante de um existente.

### Estilo

- Python 3.12, indentação de 4 espaços, nomes e comentários em português, sem acentos nas mensagens de console.
- Constantes de configuração no topo, em MAIÚSCULAS, com comentário.
- Docstring no topo com o propósito, o contrato e o critério de aprovação.
- Se o teste também tiver uma parte em PowerShell, ela precisa ser compatível com o **Windows PowerShell 5.1** (sem `??`, `?.` nem operador ternário) e usar CRLF.
