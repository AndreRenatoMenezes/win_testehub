import os
import sys
import time
import csv
import shutil
import logging
import tkinter as tk
import threading
from collections import Counter
from datetime import datetime
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# =============================================================================
# CONFIGURACOES DO TESTE
# =============================================================================
# Teste complementar ao 3_teste_rede.py: mede a velocidade contra um speedtest
# PUBLICO da internet (fast.com, da Netflix), pelo mesmo caminho do trafego real
# do usuario -- inclusive atraves do agente zero trust (proxy/tunel/inspecao SSL).
URL_TESTE = "https://fast.com/"
QTD_AFERICOES = 5
TIMEOUT_CARREGAMENTO = 30   # s, para a interface de medicao aparecer
TIMEOUT_AFERICAO = 120      # s, por afericao (download + latencia + upload)
PAUSA_ENTRE_AFERICOES = 3   # s
ARQUIVO_CSV = "resultado_afericoes_internet.csv"
ARQUIVO_CSV_TEMATICO = "rede_internet.csv"

# IDs do DOM do fast.com (validados em 2026-10-07; independentes do idioma)
ID_DOWNLOAD = "speed-value"
ID_DOWNLOAD_UNID = "speed-units"
ID_UPLOAD = "upload-value"
ID_UPLOAD_UNID = "upload-units"
ID_LATENCIA = "latency-value"
ID_LATENCIA_UNID = "latency-units"
ID_LATENCIA_CARGA = "bufferbloat-value"
ID_LATENCIA_CARGA_UNID = "bufferbloat-units"
ID_LOCAL_CLIENTE = "user-location"
ID_IP_SAIDA = "user-ip"
ID_SERVIDORES = "server-locations"
ID_ERRO = "error-results-msg"
ID_MAIS_DETALHES = "show-more-details-link"
CLASSE_CONCLUIDO = "succeeded"

IDS_LEITURA = [
    ID_DOWNLOAD, ID_DOWNLOAD_UNID, ID_UPLOAD, ID_UPLOAD_UNID,
    ID_LATENCIA, ID_LATENCIA_UNID, ID_LATENCIA_CARGA, ID_LATENCIA_CARGA_UNID,
    ID_LOCAL_CLIENTE, ID_IP_SAIDA, ID_SERVIDORES, ID_ERRO,
]

# Le texto, classe e visibilidade de varios elementos num unico snapshot
JS_SNAPSHOT = """
const out = {};
for (const id of arguments[0]) {
    const el = document.getElementById(id);
    out[id] = el ? {
        texto: (el.textContent || '').trim(),
        classe: (el.className || '').toString(),
        visivel: el.getClientRects().length > 0
    } : null;
}
return out;
"""

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')

# --- INTEGRACAO COM O HARDWARE TEST HUB ---
HUB_EVIDENCE_DIR = os.environ.get("HUB_EVIDENCE_DIR")
DIRETORIO_SAIDA = HUB_EVIDENCE_DIR if HUB_EVIDENCE_DIR else DIRETORIO_ATUAL
os.makedirs(DIRETORIO_SAIDA, exist_ok=True)
CAMINHO_CSV = os.path.join(DIRETORIO_SAIDA, ARQUIVO_CSV)
CAMINHO_CSV_TEMATICO = os.path.join(DIRETORIO_SAIDA, ARQUIVO_CSV_TEMATICO)

# =============================================================================
# LOGGING ESTRUTURADO
# =============================================================================
LOG_FILE = os.path.join(DIRETORIO_SAIDA, f"teste_rede_internet_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("TesteRedeInternet")
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
    Selenium Manager localiza o Edge padrao do Windows sozinho.
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
# CONVERSAO DE VALORES
# =============================================================================
FATOR_MBPS = {"kbps": 0.001, "mbps": 1.0, "gbps": 1000.0}
FATOR_MS = {"ms": 1.0, "s": 1000.0}


def parse_numero(texto):
    """Converte '140', '8,5' ou '8.5' em float. Retorna None se invalido."""
    if texto is None:
        return None
    texto = str(texto).strip().replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def converter(valor, unidade, fatores, unidade_padrao):
    """Converte valor+unidade para a unidade padrao. Unidade vazia = padrao."""
    numero = parse_numero(valor)
    if numero is None:
        return None
    unidade = (unidade or unidade_padrao).strip().lower()
    fator = fatores.get(unidade)
    if fator is None:
        return None
    return numero * fator


def formatar_br(valor):
    """Float -> '140,00' (padrao do CSV por afericao); None -> 'N/A'."""
    return f"{valor:.2f}".replace(".", ",") if valor is not None else "N/A"


def formatar_ponto(valor):
    """Float -> '140.00' (padrao do CSV tematico); None -> 'N/A'."""
    return f"{valor:.2f}" if valor is not None else "N/A"


def mais_frequente(valores):
    """Valor de texto mais frequente (ignora vazios); 'N/A' se nao houver."""
    valores = [v for v in valores if v]
    return Counter(valores).most_common(1)[0][0] if valores else "N/A"


def interpretar_snapshot(snap):
    """Extrai as metricas de um snapshot do DOM do fast.com."""
    def texto(id_):
        item = snap.get(id_) or {}
        return item.get("texto", "")

    def concluido(id_):
        item = snap.get(id_) or {}
        return CLASSE_CONCLUIDO in item.get("classe", "").split()

    download = converter(texto(ID_DOWNLOAD), texto(ID_DOWNLOAD_UNID), FATOR_MBPS, "mbps") if concluido(ID_DOWNLOAD) else None
    upload = converter(texto(ID_UPLOAD), texto(ID_UPLOAD_UNID), FATOR_MBPS, "mbps") if concluido(ID_UPLOAD) else None
    ping = converter(texto(ID_LATENCIA), texto(ID_LATENCIA_UNID), FATOR_MS, "ms") if concluido(ID_LATENCIA) else None
    latencia_carga = converter(texto(ID_LATENCIA_CARGA), texto(ID_LATENCIA_CARGA_UNID), FATOR_MS, "ms")

    # Velocidade zero com status concluido nao e uma medicao valida
    if download is not None and download <= 0:
        download = None
    if upload is not None and upload <= 0:
        upload = None

    servidores = " | ".join(p.strip() for p in texto(ID_SERVIDORES).split("|") if p.strip())

    return {
        "download": download,
        "upload": upload,
        "ping": ping,
        "latencia_carga": latencia_carga,
        "local_cliente": texto(ID_LOCAL_CLIENTE),
        "ip_saida": texto(ID_IP_SAIDA),
        "servidores": servidores,
        "concluido": concluido(ID_DOWNLOAD) and concluido(ID_LATENCIA) and concluido(ID_UPLOAD),
        "erro_visivel": bool((snap.get(ID_ERRO) or {}).get("visivel")),
    }


# =============================================================================
# OVERLAY VISUAL (FEEDBACK FLUTUANTE CLICK-THROUGH)
# =============================================================================
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Rede (Internet)")

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
            self.root, text="Iniciando teste de rede (internet)...",
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

    def atualizar(self, ciclo, total_ciclos, status, decorrido=None):
        texto_ciclo = (
            f"Aferição {ciclo} de {total_ciclos}" if ciclo > 0 else "Finalizando..."
        )
        self.root.after(0, lambda: self.lbl_ciclo.config(text=texto_ciclo))
        self.root.after(0, lambda: self.lbl_status.config(text=status))
        if decorrido is not None:
            self.root.after(
                0, lambda: self.lbl_tempo.config(text=f"Tempo decorrido: {decorrido}s")
            )
        else:
            self.root.after(0, lambda: self.lbl_tempo.config(text="Aguarde..."))

    def fechar(self):
        self.root.after(0, self.root.destroy)


# =============================================================================
# AFERICOES
# =============================================================================
def salvar_screenshot(driver, prefixo):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"{prefixo}_{timestamp}.png"
    caminho = os.path.join(DIRETORIO_SAIDA, nome)
    try:
        driver.save_screenshot(caminho)
        logger.info(f"Screenshot salvo: {caminho}")
    except WebDriverException as e:
        logger.error(f"Falha ao salvar screenshot {nome}: {e}")
    return nome, timestamp


def registrar_bloqueio(driver, motivo):
    """Evidencia e log do cenario de site inacessivel/bloqueado."""
    salvar_screenshot(driver, "Evidencia_Internet_Bloqueio")
    try:
        titulo, url_atual = driver.title, driver.current_url
    except WebDriverException:
        titulo, url_atual = "N/A", "N/A"
    logger.error(f"Site inacessivel ou bloqueado pela politica de rede: {motivo}")
    logger.error(f"  Pagina exibida: titulo='{titulo}' | url='{url_atual}'")
    logger.error("  Verifique o agente zero trust/proxy: fast.com, api.fast.com e "
                 "*.oca.nflxvideo.net precisam estar liberados.")


def executar_afericao(driver, ui, i):
    """Executa uma afericao. Retorna (linha, bloqueado)."""
    ui.atualizar(i, QTD_AFERICOES, "Abrindo fast.com...")

    # 1. Carregar a pagina (o fast.com inicia a medicao sozinho)
    try:
        driver.get(URL_TESTE)
        WebDriverWait(driver, TIMEOUT_CARREGAMENTO).until(
            EC.presence_of_element_located((By.ID, ID_DOWNLOAD))
        )
    except TimeoutException:
        registrar_bloqueio(driver, f"interface de medicao nao carregou em {TIMEOUT_CARREGAMENTO}s")
        return None, True
    except WebDriverException as e:
        detalhe = (e.msg or str(e) or type(e).__name__).strip().splitlines()[0]
        registrar_bloqueio(driver, f"falha ao acessar {URL_TESTE} ({detalhe})")
        return None, True

    # 2. Exibir upload/latencias para que aparecam no screenshot
    driver.execute_script(
        "const l = document.getElementById(arguments[0]); if (l) { l.click(); }",
        ID_MAIS_DETALHES
    )
    logger.info("Medicao iniciada. Aguardando conclusao de download, latencia e upload...")

    # 3. Aguardar a conclusao consultando o DOM
    inicio = time.time()
    dados = {}
    while True:
        decorrido = int(time.time() - inicio)
        snap = driver.execute_script(JS_SNAPSHOT, IDS_LEITURA) or {}
        dados = interpretar_snapshot(snap)

        if dados["erro_visivel"]:
            texto_erro = (snap.get(ID_ERRO) or {}).get("texto", "")
            registrar_bloqueio(driver, f"o fast.com nao alcancou seus servidores de medicao ('{texto_erro}')")
            return None, True

        if dados["concluido"]:
            break

        if decorrido >= TIMEOUT_AFERICAO:
            logger.warning(f"Afericao {i} nao concluiu em {TIMEOUT_AFERICAO}s.")
            break

        parcial = (snap.get(ID_DOWNLOAD) or {}).get("texto", "-")
        unidade = (snap.get(ID_DOWNLOAD_UNID) or {}).get("texto", "")
        ui.atualizar(i, QTD_AFERICOES, f"Aferindo velocidade... {parcial} {unidade}", decorrido)
        time.sleep(1)

    logger.debug(f"Snapshot final da afericao {i}: {snap}")

    # 4. Evidencia
    nome_print, timestamp = salvar_screenshot(driver, f"Evidencia_Internet_Afericao_{i}")

    valida = all(dados[k] is not None for k in ("download", "upload", "ping"))
    linha = {
        "Afericao": i,
        "Data_Hora": timestamp,
        "Download": dados["download"],
        "Upload": dados["upload"],
        "Ping": dados["ping"],
        "Latencia_Carga": dados["latencia_carga"],
        "Local_Cliente": dados["local_cliente"],
        "IP_Saida": dados["ip_saida"],
        "Servidores": dados["servidores"],
        "Status": "ok" if valida else "falha",
        "Print": nome_print,
    }

    logger.info(
        f"Resultados: Download={formatar_br(linha['Download'])} Mbps | "
        f"Upload={formatar_br(linha['Upload'])} Mbps | Ping={formatar_br(linha['Ping'])} ms | "
        f"Latencia sob carga={formatar_br(linha['Latencia_Carga'])} ms | Status={linha['Status']}"
    )
    logger.info(
        f"Caminho: cliente='{linha['Local_Cliente']}' | IP de saida='{linha['IP_Saida']}' | "
        f"servidores='{linha['Servidores']}'"
    )
    if not valida:
        logger.warning("Download, Upload ou Ping nao foram capturados nesta afericao (N/A).")

    return linha, False


def realizar_afericoes(ui):
    logger.info("Verificando pre-requisitos...")
    logger.info(f"  Edge      : {CAMINHO_EDGE or 'NAO ENCONTRADO'}")
    logger.info(f"  URL Teste : {URL_TESTE}")
    logger.info(f"  Afericoes : {QTD_AFERICOES}")
    logger.info(f"  Saida     : {DIRETORIO_SAIDA}")

    if not CAMINHO_EDGE:
        logger.error("Microsoft Edge nao foi encontrado no sistema.")
        logger.error("O Edge e nativo do Windows 10/11; verifique se nao foi removido da maquina.")
        return []

    logger.info("Pre-requisitos verificados com sucesso.")

    # Sem --ignore-certificate-errors: a inspecao SSL do agente deve agir como
    # agiria para o usuario real.
    options = EdgeOptions()
    options.add_argument('--start-maximized')

    logger.info("Iniciando Microsoft Edge via Selenium...")
    ui.atualizar(0, QTD_AFERICOES, "Iniciando Edge...")
    try:
        driver = webdriver.Edge(options=options)
    except WebDriverException as e:
        logger.error(f"Falha ao iniciar o Microsoft Edge via Selenium: {e}")
        logger.error("Verifique se o Selenium Manager conseguiu obter o msedgedriver (acesso ao CDN de drivers).")
        return []
    driver.set_page_load_timeout(TIMEOUT_CARREGAMENTO)
    logger.info("Edge iniciado com sucesso.")

    resultados = []

    try:
        for i in range(1, QTD_AFERICOES + 1):
            logger.info(f"--- Afericao {i}/{QTD_AFERICOES} ---")
            linha, bloqueado = executar_afericao(driver, ui, i)
            if bloqueado:
                logger.error("Afericoes restantes canceladas.")
                break

            resultados.append(linha)
            logger.info(f"Afericao {i}/{QTD_AFERICOES} concluida.")
            ui.atualizar(i, QTD_AFERICOES, f"Aferição {i} concluída")

            if i < QTD_AFERICOES:
                time.sleep(PAUSA_ENTRE_AFERICOES)

    except Exception as e:
        logger.error(f"Erro durante as afericoes: {e}", exc_info=True)

    finally:
        logger.info("Encerrando Edge...")
        driver.quit()

    return resultados


def salvar_csv(dados):
    if not dados:
        logger.warning("Nenhum dado coletado para salvar nos CSVs.")
        return

    colunas = ["Afericao", "Data_Hora", "Download", "Upload", "Ping", "Latencia_Carga",
               "Local_Cliente", "IP_Saida", "Servidores", "Status", "Print"]

    with open(CAMINHO_CSV, mode='w', newline='', encoding='utf-8') as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=';')
        writer.writeheader()
        for linha in dados:
            saida = dict(linha)
            for campo in ("Download", "Upload", "Ping", "Latencia_Carga"):
                saida[campo] = formatar_br(linha[campo])
            for campo in ("Local_Cliente", "IP_Saida", "Servidores"):
                saida[campo] = linha[campo] or "N/A"
            writer.writerow(saida)
    logger.info(f"Dados salvos com sucesso em: {CAMINHO_CSV}")

    # --- CSV tematico para o Hub (rede_internet.csv) ---
    validas = [d for d in dados if d["Status"] == "ok"]

    def media(campo):
        vals = [d[campo] for d in validas if d[campo] is not None]
        return sum(vals) / len(vals) if vals else None

    def extremo(campo, funcao):
        vals = [d[campo] for d in validas if d[campo] is not None]
        return funcao(vals) if vals else None

    with open(CAMINHO_CSV_TEMATICO, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Metrica", "Valor", "Unidade"])
        writer.writerow(["Afericoes_Executadas", len(dados), "un"])
        writer.writerow(["Afericoes_Validas", len(validas), "un"])
        writer.writerow(["Download_Media", formatar_ponto(media("Download")), "Mbps"])
        writer.writerow(["Upload_Media", formatar_ponto(media("Upload")), "Mbps"])
        writer.writerow(["Ping_Media", formatar_ponto(media("Ping")), "ms"])
        writer.writerow(["Latencia_Carga_Media", formatar_ponto(media("Latencia_Carga")), "ms"])
        writer.writerow(["Download_Maxima", formatar_ponto(extremo("Download", max)), "Mbps"])
        writer.writerow(["Download_Minima", formatar_ponto(extremo("Download", min)), "Mbps"])
        writer.writerow(["Upload_Maxima", formatar_ponto(extremo("Upload", max)), "Mbps"])
        writer.writerow(["Upload_Minima", formatar_ponto(extremo("Upload", min)), "Mbps"])
        writer.writerow(["Local_Cliente", mais_frequente(d["Local_Cliente"] for d in dados), "texto"])
        writer.writerow(["IP_Saida", mais_frequente(d["IP_Saida"] for d in dados), "texto"])
        writer.writerow(["Servidores", mais_frequente(d["Servidores"] for d in dados), "texto"])
    logger.info(f"{ARQUIVO_CSV_TEMATICO} gerado em: {CAMINHO_CSV_TEMATICO}")


# =============================================================================
# EXECUCAO PRINCIPAL
# =============================================================================
# O exit code e decidido aqui e aplicado pela thread principal: sys.exit dentro
# da worker so encerraria a thread, e o processo sairia com 0 (PASS indevido).
_exit_code = 1

def worker_thread(ui):
    global _exit_code
    _exit_code = 1
    logger.info("=" * 50)
    logger.info("INICIO: Teste de Rede - Internet (fast.com)")
    logger.info("=" * 50)
    logger.info(f"Host: {os.environ.get('COMPUTERNAME', 'N/A')} | User: {os.environ.get('USERNAME', 'N/A')}")
    if HUB_EVIDENCE_DIR:
        logger.info(f"Modo Hub detectado. Evidencias em: {HUB_EVIDENCE_DIR}")
    logger.info(f"Log salvo em: {LOG_FILE}")

    try:
        dados_coletados = realizar_afericoes(ui)
        salvar_csv(dados_coletados)

        validas = sum(1 for d in dados_coletados if d["Status"] == "ok")
        logger.info("=" * 50)
        logger.info(f"FIM: {validas}/{QTD_AFERICOES} afericoes validas.")
        logger.info("=" * 50)

        if validas == QTD_AFERICOES:
            _exit_code = 0
        else:
            logger.error(f"FAIL: o criterio exige {QTD_AFERICOES}/{QTD_AFERICOES} afericoes validas.")
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
