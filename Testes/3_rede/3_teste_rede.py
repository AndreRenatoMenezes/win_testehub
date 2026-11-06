import os
import sys
import time
import csv
import re
import json
import shutil
import logging
import tkinter as tk
import threading
from datetime import datetime
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# =============================================================================
# CONFIGURACOES DO TESTE
# =============================================================================
QTD_AFERICOES = 5
ARQUIVO_CSV = "resultado_afericoes.csv"

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))


def carregar_url_teste():
    """URL do speedtest interno, mantida fora do repositorio.

    Ordem: variavel de ambiente HUB_SPEEDTEST_URL; depois a chave
    "SpeedtestUrl" do config.local.json na raiz do hub (nao versionado,
    veja config.local.example.json). Retorna "" se nenhuma estiver definida.
    """
    url = os.environ.get("HUB_SPEEDTEST_URL", "").strip()
    if url:
        return url
    caminho = os.path.join(DIRETORIO_ATUAL, "..", "..", "config.local.json")
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return str(json.load(f).get("SpeedtestUrl", "")).strip()
    except (OSError, ValueError, AttributeError):
        return ""


URL_TESTE = carregar_url_teste()
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')

# --- INTEGRACAO COM O HARDWARE TEST HUB ---
HUB_EVIDENCE_DIR = os.environ.get("HUB_EVIDENCE_DIR")
DIRETORIO_SAIDA = HUB_EVIDENCE_DIR if HUB_EVIDENCE_DIR else DIRETORIO_ATUAL
os.makedirs(DIRETORIO_SAIDA, exist_ok=True)
CAMINHO_CSV = os.path.join(DIRETORIO_SAIDA, ARQUIVO_CSV)

# =============================================================================
# LOGGING ESTRUTURADO
# =============================================================================
LOG_FILE = os.path.join(DIRETORIO_SAIDA, f"teste_rede_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("TesteRede")
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter(
    "[%(asctime)s] [%(levelname)-7s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)

_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(_fmt)

logger.addHandler(_fh)
logger.addHandler(_ch)


# =============================================================================
# DETECCAO DO EDGE
# =============================================================================
def encontrar_edge():
    """Localiza o binario do Microsoft Edge em caminhos conhecidos.

    Verificacao leve, usada apenas para emitir mensagem de erro clara quando o
    Edge nao existe. A inicializacao do driver NAO depende deste caminho: o
    Selenium Manager localiza o Edge padrao do Windows e obtem o msedgedriver.
    """
    candidatos = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        shutil.which("msedge"),
    ]
    for caminho in candidatos:
        if caminho and os.path.isfile(caminho):
            logger.debug(f"Edge encontrado em: {caminho}")
            return caminho

    logger.debug("Edge nao encontrado em nenhum caminho conhecido.")
    return None


CAMINHO_EDGE = encontrar_edge()


# =============================================================================
# OVERLAY VISUAL (FEEDBACK FLUTUANTE CLICK-THROUGH)
# =============================================================================
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Rede")

        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"340x120+{largura_tela - 370}+30")
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#1e1e1e")

        self.root.update_idletasks()
        self._set_click_through()

        self.lbl_ciclo = tk.Label(
            self.root, text="Preparando...",
            fg="#00ff00", bg="#1e1e1e", font=("Segoe UI", 12, "bold")
        )
        self.lbl_ciclo.pack(pady=(10, 5))

        self.lbl_status = tk.Label(
            self.root, text="Iniciando teste de rede...",
            fg="white", bg="#1e1e1e", font=("Segoe UI", 10)
        )
        self.lbl_status.pack(pady=0)

        self.lbl_tempo = tk.Label(
            self.root, text="Aguarde...",
            fg="#00d2ff", bg="#1e1e1e", font=("Consolas", 11)
        )
        self.lbl_tempo.pack(pady=5)

    def _set_click_through(self):
        """Torna a janela transparente a cliques no Windows usando ctypes."""
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            LWA_ALPHA = 0x00000002

            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 230, LWA_ALPHA)
        except Exception:
            pass

    def atualizar(self, ciclo, total_ciclos, status, tempo="--"):
        texto_ciclo = (
            f"Aferição {ciclo} de {total_ciclos}" if ciclo > 0 else "Finalizando..."
        )
        self.root.after(0, lambda: self.lbl_ciclo.config(text=texto_ciclo))
        self.root.after(0, lambda: self.lbl_status.config(text=status))
        if tempo != "--":
            self.root.after(
                0, lambda: self.lbl_tempo.config(text=f"Tempo restante: {tempo}s")
            )
        else:
            self.root.after(0, lambda: self.lbl_tempo.config(text="Aguarde..."))

    def fechar(self):
        self.root.after(0, self.root.destroy)


def realizar_afericoes(ui):
    logger.info("Verificando pre-requisitos...")
    logger.info(f"  Edge         : {CAMINHO_EDGE or 'NAO ENCONTRADO'}")
    logger.info(f"  URL Teste    : {URL_TESTE}")
    logger.info(f"  Afericoes    : {QTD_AFERICOES}")
    logger.info(f"  Saida        : {DIRETORIO_SAIDA}")

    # Esta funcao roda dentro do worker_thread: falhas de pre-requisito usam
    # raise (nunca sys.exit, que so encerra a thread e deixaria o exit code 0).
    if not URL_TESTE:
        raise RuntimeError(
            "URL do speedtest interno nao configurada. Defina HUB_SPEEDTEST_URL "
            "ou crie config.local.json na raiz do hub (modelo: config.local.example.json)."
        )

    if not CAMINHO_EDGE:
        raise RuntimeError(
            "Microsoft Edge nao foi encontrado no sistema. O Edge e nativo do "
            "Windows 10/11; verifique se nao foi removido da maquina."
        )

    logger.info("Pre-requisitos verificados com sucesso.")

    options = EdgeOptions()
    # Mantido do procedimento original: o speedtest interno e acessado por IP via HTTPS.
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--start-maximized')

    logger.info("Iniciando Microsoft Edge via Selenium...")
    ui.atualizar(0, QTD_AFERICOES, "Iniciando Edge e acessando URL...")
    try:
        driver = webdriver.Edge(options=options)
    except WebDriverException as e:
        raise RuntimeError(
            "Falha ao iniciar o Microsoft Edge via Selenium. Verifique se o "
            "Selenium Manager conseguiu obter o msedgedriver (acesso ao CDN de drivers)."
        ) from e
    wait = WebDriverWait(driver, 15)
    logger.info("Edge iniciado com sucesso.")

    resultados_csv = []

    try:
        logger.info(f"Acessando {URL_TESTE}...")
        driver.get(URL_TESTE)
        time.sleep(5)

        janela_principal = driver.current_window_handle

        for i in range(1, QTD_AFERICOES + 1):
            logger.info(f"--- Afericao {i}/{QTD_AFERICOES} ---")
            ui.atualizar(i, QTD_AFERICOES, "Iniciando aferição...")

            # 1. Clicar no botao Start
            btn_start = wait.until(EC.presence_of_element_located((By.ID, "startButtonDesk")))
            driver.execute_script("arguments[0].dispatchEvent(new Event('click', {bubbles: true}));", btn_start)
            logger.info("Teste de rede iniciado. Aguardando 60s para finalizacao...")

            # 2. Aguardar o teste finalizar com countdown visual
            for seg in range(60, 0, -1):
                ui.atualizar(i, QTD_AFERICOES, "Aferindo velocidade...", seg)
                time.sleep(1)
            logger.info("Tempo de espera concluido. Acessando pagina de resultados...")

            # 3. Localizar o link e clicar para abrir a nova aba
            link_resultados = driver.find_element(By.ID, "resultsData")
            driver.execute_script("arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));", link_resultados)

            # 4. Mudar o foco para a nova aba
            wait.until(EC.number_of_windows_to_be(2))
            for window_handle in driver.window_handles:
                if window_handle != janela_principal:
                    driver.switch_to.window(window_handle)
                    break

            # 5. Esperar o Sumario carregar e extrair os dados via Regex
            summary_element = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "network-analysis-text")))
            texto_sumario = summary_element.text
            logger.debug(f"Texto do sumario: {texto_sumario}")

            match_down = re.search(r"download speed of ([\d\.]+)", texto_sumario)
            match_up = re.search(r"upload speed of ([\d\.]+)", texto_sumario)
            match_ping = re.search(r"ping of ([\d\.]+)", texto_sumario)
            match_jitter = re.search(r"jitter of ([\d\.]+)", texto_sumario)

            download_val = match_down.group(1).replace(".", ",") if match_down else "N/A"
            upload_val = match_up.group(1).replace(".", ",") if match_up else "N/A"
            ping_val = match_ping.group(1).replace(".", ",") if match_ping else "N/A"
            jitter_val = match_jitter.group(1).replace(".", ",") if match_jitter else "N/A"

            logger.info(f"Resultados: Download={download_val} Mbps | Upload={upload_val} Mbps | Ping={ping_val} ms | Jitter={jitter_val} ms")

            if "N/A" in (download_val, upload_val, ping_val, jitter_val):
                logger.warning("Alguns valores nao foram capturados (N/A). Verifique a pagina de resultados.")

            # 6. Screenshot da evidencia
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome_print = f"Evidencia_Afericao_{i}_{timestamp}.png"
            caminho_print = os.path.join(DIRETORIO_SAIDA, nome_print)
            driver.save_screenshot(caminho_print)
            logger.info(f"Screenshot salvo: {caminho_print}")

            resultados_csv.append({
                "Afericao": i,
                "Data_Hora": timestamp,
                "Download": download_val,
                "Upload": upload_val,
                "Ping": ping_val,
                "Jitter": jitter_val,
                "Print": nome_print
            })

            # 7. Fechar a aba de resultados e voltar
            driver.close()
            driver.switch_to.window(janela_principal)
            logger.info(f"Afericao {i}/{QTD_AFERICOES} concluida.")
            ui.atualizar(i, QTD_AFERICOES, f"Aferição {i} concluída")

            # Atualiza a pagina original para repor a barra de progresso
            driver.refresh()
            time.sleep(3)

    except Exception as e:
        logger.error(f"Erro durante as afericoes: {e}", exc_info=True)

    finally:
        logger.info("Encerrando Edge...")
        driver.quit()

    return resultados_csv


def salvar_csv(dados):
    if not dados:
        logger.warning("Nenhum dado coletado para salvar no CSV.")
        return

    colunas = ["Afericao", "Data_Hora", "Download", "Upload", "Ping", "Jitter", "Print"]

    with open(CAMINHO_CSV, mode='w', newline='', encoding='utf-8') as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=';')
        writer.writeheader()
        for linha in dados:
            writer.writerow(linha)
    logger.info(f"Dados salvos com sucesso em: {CAMINHO_CSV}")

    # --- CSV tematico para o Hub (rede.csv) ---
    rede_csv_path = os.path.join(DIRETORIO_SAIDA, "rede.csv")

    def parse_br(val):
        try:
            return float(val.replace(",", "."))
        except (ValueError, AttributeError):
            return 0.0

    downloads = [parse_br(d["Download"]) for d in dados if d["Download"] != "N/A"]
    uploads = [parse_br(d["Upload"]) for d in dados if d["Upload"] != "N/A"]
    pings = [parse_br(d["Ping"]) for d in dados if d["Ping"] != "N/A"]
    jitters = [parse_br(d["Jitter"]) for d in dados if d["Jitter"] != "N/A"]

    with open(rede_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Metrica", "Valor", "Unidade"])
        writer.writerow(["Afericoes_Executadas", len(dados), "un"])
        writer.writerow(["Download_Media", f"{sum(downloads)/len(downloads):.2f}" if downloads else "N/A", "Mbps"])
        writer.writerow(["Upload_Media", f"{sum(uploads)/len(uploads):.2f}" if uploads else "N/A", "Mbps"])
        writer.writerow(["Ping_Media", f"{sum(pings)/len(pings):.2f}" if pings else "N/A", "ms"])
        writer.writerow(["Jitter_Media", f"{sum(jitters)/len(jitters):.2f}" if jitters else "N/A", "ms"])
        writer.writerow(["Download_Maxima", f"{max(downloads):.2f}" if downloads else "N/A", "Mbps"])
        writer.writerow(["Download_Minima", f"{min(downloads):.2f}" if downloads else "N/A", "Mbps"])
        writer.writerow(["Upload_Maxima", f"{max(uploads):.2f}" if uploads else "N/A", "Mbps"])
        writer.writerow(["Upload_Minima", f"{min(uploads):.2f}" if uploads else "N/A", "Mbps"])
    logger.info(f"rede.csv gerado em: {rede_csv_path}")


# =============================================================================
# EXECUCAO PRINCIPAL
# =============================================================================
_exit_code = 0

def worker_thread(ui):
    global _exit_code
    _exit_code = 0
    logger.info("=" * 50)
    logger.info("INICIO: Teste de Rede (Afericoes de Velocidade)")
    logger.info("=" * 50)
    logger.info(f"Host: {os.environ.get('COMPUTERNAME', 'N/A')} | User: {os.environ.get('USERNAME', 'N/A')}")
    if HUB_EVIDENCE_DIR:
        logger.info(f"Modo Hub detectado. Evidencias em: {HUB_EVIDENCE_DIR}")
    logger.info(f"Log salvo em: {LOG_FILE}")

    try:
        dados_coletados = realizar_afericoes(ui)
        salvar_csv(dados_coletados)

        total = len(dados_coletados)
        logger.info("=" * 50)
        logger.info(f"FIM: {total}/{QTD_AFERICOES} afericoes concluidas.")
        logger.info("=" * 50)

        if total == 0:
            _exit_code = 1
    except Exception as e:
        logger.error(f"Erro fatal na thread principal: {e}", exc_info=True)
        _exit_code = 1
    finally:
        ui.fechar()


if __name__ == "__main__":
    ui = MonitorOverlay()
    threading.Thread(target=worker_thread, args=(ui,), daemon=True).start()
    ui.root.mainloop()
    sys.exit(_exit_code)