"""Teste de rede unificado: speedtest interno (OpenSpeedTest) + fast.com.

As duas fontes sao medidas em rodadas intercaladas (aquecimento interno,
aquecimento internet, interno 1, internet 1, ...), nas mesmas condicoes:

- interno: mede a rede corporativa ate o servidor do lab (URL fora do
  repositorio: HUB_SPEEDTEST_URL ou SpeedtestUrl do config.local.json);
- internet: mede o caminho real do usuario ate a borda da Netflix, inclusive
  atraves do agente zero trust (proxy/tunel/inspecao SSL).

Uma fonte fora do ar vira aviso: PASS quando pelo menos uma termina "ok".
Antes de cada rodada o script mede o trafego de fundo da interface ativa e
registra cabo/Wi-Fi; a estatistica (mediana, quartis, CV) usa so as rodadas
medidas, validas e nao contaminadas. Os calculos ficam em Testes/_lib/rede_calc.py.
Rodadas, limites e tempos: bloco "Rede" do config.json.
"""

import csv
import glob
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from urllib.parse import urlparse

import psutil
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
RAIZ_HUB = os.path.abspath(os.path.join(DIRETORIO_ATUAL, "..", ".."))
sys.path.insert(0, os.path.join(DIRETORIO_ATUAL, "..", "_lib"))
import rede_calc as rc  # noqa: E402

# =============================================================================
# CONFIGURACOES
# =============================================================================
CFG = rc.carregar_config(RAIZ_HUB)
URL_INTERNA = rc.carregar_url_interna(RAIZ_HUB)
URL_FAST = "https://fast.com/"
TIMEOUT_CARREGAMENTO = 30   # s, para a pagina de cada fonte aparecer
ARQUIVO_CSV = "resultado_afericoes.csv"
ARQUIVO_CSV_TEMATICO = "rede.csv"
SESSION_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# --- INTEGRACAO COM O HARDWARE TEST HUB ---
HUB_EVIDENCE_DIR = os.environ.get("HUB_EVIDENCE_DIR")
DIRETORIO_SAIDA = HUB_EVIDENCE_DIR if HUB_EVIDENCE_DIR else DIRETORIO_ATUAL
os.makedirs(DIRETORIO_SAIDA, exist_ok=True)
CAMINHO_CSV = os.path.join(DIRETORIO_SAIDA, ARQUIVO_CSV)
CAMINHO_CSV_TEMATICO = os.path.join(DIRETORIO_SAIDA, ARQUIVO_CSV_TEMATICO)

# =============================================================================
# LOGGING
# =============================================================================
LOG_FILE = os.path.join(DIRETORIO_SAIDA, f"teste_rede_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("TesteRede")
logger.setLevel(logging.DEBUG)
_fmt = logging.Formatter("[%(asctime)s] [%(levelname)-7s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
try:
    sys.stdout.reconfigure(errors="replace")  # caractere fora do cp1252 nao derruba o log
except (AttributeError, ValueError):
    pass
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(_fmt)
logger.addHandler(_fh)
logger.addHandler(_ch)

CREATE_NO_WINDOW = 0x08000000

# =============================================================================
# DOM DAS PAGINAS
# =============================================================================
# OpenSpeedTest (validado em 2026-11-25): o teste acabou quando #oDoLiveStatus
# mostra "All done" (~32 s); os resultados ficam na propria pagina.
JS_OST = """
const t = id => { const e = document.getElementById(id); return e ? (e.textContent || '').trim() : ''; };
return {status: t('oDoLiveStatus'), ao_vivo: t('oDoLiveSpeed'), download: t('downResult'),
        upload: t('upRestxt'), ping: t('pingResult'), jitter: t('jitterDesk')};
"""
OST_CONCLUIDO = "all done"

# fast.com (IDs validados em 2026-10-07 e 2026-11-25; independentes do idioma)
ID_DOWNLOAD, ID_DOWNLOAD_UNID = "speed-value", "speed-units"
ID_UPLOAD, ID_UPLOAD_UNID = "upload-value", "upload-units"
ID_LATENCIA, ID_LATENCIA_UNID = "latency-value", "latency-units"
ID_LATENCIA_CARGA, ID_LATENCIA_CARGA_UNID = "bufferbloat-value", "bufferbloat-units"
ID_LOCAL_CLIENTE, ID_IP_SAIDA, ID_SERVIDORES = "user-location", "user-ip", "server-locations"
ID_ERRO, ID_MAIS_DETALHES = "error-results-msg", "show-more-details-link"
CLASSE_CONCLUIDO = "succeeded"
IDS_LEITURA = [ID_DOWNLOAD, ID_DOWNLOAD_UNID, ID_UPLOAD, ID_UPLOAD_UNID, ID_LATENCIA, ID_LATENCIA_UNID,
               ID_LATENCIA_CARGA, ID_LATENCIA_CARGA_UNID, ID_LOCAL_CLIENTE, ID_IP_SAIDA, ID_SERVIDORES, ID_ERRO]
JS_SNAPSHOT = """
const out = {};
for (const id of arguments[0]) {
    const el = document.getElementById(id);
    out[id] = el ? {texto: (el.textContent || '').trim(), classe: (el.className || '').toString(),
                    visivel: el.getClientRects().length > 0} : null;
}
return out;
"""
# Painel "Configuracoes" do fast.com (validado em 2026-11-25): salva em
# localStorage (minDuration/maxDuration/minConnections/maxConnections).
JS_FAST_CONFIG = """
const [con, dur] = arguments;
const link = document.getElementById('settings-link');
if (!link) { return false; }
link.click();
const set = (id, v) => { const e = document.getElementById(id); if (!e) { return false; }
  e.value = String(v); e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true})); return true; };
const ok = set('min-connections-input', con) && set('max-connections-input', con)
        && set('min-duration-input', dur) && set('max-duration-input', dur);
const p = document.getElementById('persist-config-input');
const salvar = document.getElementById('apply-config');
if (!ok || !p || !salvar) { return false; }
if (!p.checked) { p.click(); }
salvar.click();
return true;
"""
JS_LOCAL_STORAGE = "return Object.fromEntries(Object.keys(localStorage).map(k => [k, localStorage.getItem(k)]));"


# =============================================================================
# OVERLAY VISUAL (FEEDBACK FLUTUANTE CLICK-THROUGH)
# =============================================================================
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Rede")
        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"380x120+{largura_tela - 410}+30")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#1e1e1e")
        self.root.update_idletasks()
        self._set_click_through()
        self.lbl_ciclo = tk.Label(self.root, text="Preparando...", fg="#00ff00", bg="#1e1e1e",
                                  font=("Segoe UI", 12, "bold"))
        self.lbl_ciclo.pack(pady=(10, 5))
        self.lbl_status = tk.Label(self.root, text="Iniciando teste de rede...", fg="white", bg="#1e1e1e",
                                   font=("Segoe UI", 10))
        self.lbl_status.pack(pady=0)
        self.lbl_tempo = tk.Label(self.root, text="Aguarde...", fg="#00d2ff", bg="#1e1e1e", font=("Consolas", 11))
        self.lbl_tempo.pack(pady=5)

    def _set_click_through(self):
        """Torna a janela transparente a cliques no Windows usando ctypes."""
        try:
            import ctypes
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, LWA_ALPHA = -20, 0x00080000, 0x00000020, 0x00000002
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 230, LWA_ALPHA)
        except Exception:
            pass

    def atualizar(self, progresso=None, status=None, decorrido=None):
        def aplicar():
            if progresso is not None:
                self.lbl_ciclo.config(text=progresso)
            if status is not None:
                self.lbl_status.config(text=status)
            self.lbl_tempo.config(text=f"Tempo da rodada: {decorrido}s" if decorrido is not None else "Aguarde...")
        self.root.after(0, aplicar)

    def fechar(self):
        self.root.after(0, self.root.destroy)


# =============================================================================
# SISTEMA: COMANDOS, INTERFACE ATIVA, TRAFEGO DE FUNDO, ICMP
# =============================================================================
def executar(args, timeout=60):
    """Comando nativo -> (rc, texto). Saida em UTF-8 ou na codepage OEM do console."""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"Falha ao executar {args[0]}: {e}")
        return None, ""
    saida = r.stdout or b""
    try:
        return r.returncode, saida.decode("utf-8")
    except UnicodeDecodeError:
        return r.returncode, saida.decode("cp850", "replace")


def meios_adaptadores():
    """{nome do adaptador: PhysicalMediaType} via Get-NetAdapter (uma vez por execucao)."""
    cmd = ("Get-NetAdapter -ErrorAction SilentlyContinue | Select-Object Name, PhysicalMediaType | "
           "ConvertTo-Json -Compress")
    _, texto = executar(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                         "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + cmd], timeout=60)
    try:
        dados = json.loads(texto) if texto.strip() else []
    except ValueError:
        return {}
    if isinstance(dados, dict):
        dados = [dados]
    return {str(d.get("Name")): str(d.get("PhysicalMediaType") or "") for d in dados if d.get("Name")}


def interface_ativa(host_interno=""):
    """Nome da interface da rota usada para sair (UDP connect nao envia pacote)."""
    ip_local = None
    for destino in ("8.8.8.8", host_interno):
        if not destino:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((destino, 80))
                ip_local = s.getsockname()[0]
                break
        except OSError:
            continue
    if ip_local:
        for nome, enderecos in psutil.net_if_addrs().items():
            if any(a.family == socket.AF_INET and a.address == ip_local for a in enderecos):
                return nome
    return None


_avisou_netsh = False


def ler_conexao(meios, host_interno=""):
    """Interface, tipo (cabo/wifi), link e, no Wi-Fi, banda, canal, sinal e BSSID."""
    global _avisou_netsh
    nic = interface_ativa(host_interno)
    stats = psutil.net_if_stats().get(nic) if nic else None
    amb = {"Interface": nic, "Conexao_Tipo": rc.tipo_por_meio(meios.get(nic or ""), nic or ""),
           "Link_Mbps": float(stats.speed) if stats and stats.speed else None,
           "Wifi_Banda": None, "Wifi_Canal": None, "Wifi_Sinal": None, "Wifi_BSSID": None}
    if amb["Conexao_Tipo"] == "wifi":
        _, texto = executar(["netsh", "wlan", "show", "interfaces"], timeout=15)
        w = rc.parse_wlan(texto, nic)
        if w:
            amb.update({"Wifi_Banda": w.get("banda"), "Wifi_Canal": w.get("canal"),
                        "Wifi_Sinal": f"{w['sinal']}%" if w.get("sinal") is not None else None,
                        "Wifi_BSSID": w.get("bssid")})
        elif not _avisou_netsh:
            _avisou_netsh = True
            logger.warning("netsh wlan nao informou a interface (no Windows 11 ele exige a permissao de "
                           "Localizacao): banda, canal, sinal e BSSID ficam N/A.")
    return amb


def medir_fundo(nic, segundos):
    """Trafego (kbps, rx+tx) da interface numa janela sem nenhum teste rodando."""
    def ler():
        por_nic = psutil.net_io_counters(pernic=True)
        c = por_nic.get(nic) if nic else None
        c = c or psutil.net_io_counters()
        return c.bytes_sent + c.bytes_recv
    antes = ler()
    time.sleep(segundos)
    return rc.kbps(ler() - antes, segundos)


def aguardar_calmaria(ui, nic, tentativas=6):
    """Antes da 1a rodada: o Edge recem-aberto baixa componentes por alguns segundos.

    Espera ate tentativas x JanelaFundoSeg pelo trafego de fundo ficar abaixo do
    limite; se nao ficar, segue (cada rodada ainda mede e marca a contaminacao).
    """
    for i in range(1, tentativas + 1):
        ui.atualizar(None, f"Aguardando a rede acalmar ({i}/{tentativas})...")
        fundo = medir_fundo(nic, CFG["JanelaFundoSeg"])
        if fundo <= CFG["LimiteTrafegoFundoKbps"]:
            logger.info(f"Trafego de fundo antes da 1a rodada: {fundo:.0f} kbps (ok).")
            return True
        logger.info(f"Trafego de fundo ainda alto antes da 1a rodada: {fundo:.0f} kbps; aguardando...")
    logger.warning("O trafego de fundo nao baixou do limite antes da 1a rodada: as rodadas acima dele "
                   "serao marcadas como contaminadas.")
    return False


def medir_icmp(host, quantidade):
    """(ping mediano, jitter, respostas) de 'ping -n N' ao host."""
    _, texto = executar(["ping", "-n", str(quantidade), "-w", "1000", host], timeout=quantidade * 2 + 10)
    tempos = rc.tempos_ping(texto)
    ping, jitter = rc.ping_e_jitter(tempos)
    return ping, jitter, len(tempos)


def salvar_screenshot(driver, prefixo):
    nome = f"{prefixo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        driver.save_screenshot(os.path.join(DIRETORIO_SAIDA, nome))
        return nome
    except WebDriverException as e:
        logger.error(f"Falha ao salvar screenshot {nome}: {e}")
        return None


def detalhe_erro(e):
    """Primeira linha da mensagem do Selenium; sem mensagem (ex.: TimeoutException), o tipo."""
    msg = (getattr(e, "msg", None) or "").strip()
    return msg.splitlines()[0] if msg else type(e).__name__


def limpar_perfis_orfaos():
    """Apaga perfis temporarios de execucoes interrompidas (processo morto antes do finally)."""
    for caminho in glob.glob(os.path.join(tempfile.gettempdir(), "hub_rede_*")):
        shutil.rmtree(caminho, ignore_errors=True)


# =============================================================================
# FONTES
# =============================================================================
class Fonte:
    """Um Edge com perfil temporario proprio (sem cache, extensoes nem sync)."""
    nome = ""
    rotulo = ""
    ignorar_certificado = False

    def __init__(self):
        self.driver = None
        self.perfil = None
        self.motivo_off = ""

    @property
    def off(self):
        return bool(self.motivo_off)

    def abrir_edge(self):
        self.perfil = tempfile.mkdtemp(prefix=f"hub_rede_{self.nome}_")
        o = EdgeOptions()
        for arg in (f"--user-data-dir={self.perfil}", "--no-first-run", "--no-default-browser-check",
                    "--disable-sync", "--disable-extensions", "--disable-background-networking",
                    "--disable-component-update",
                    # janela em segundo plano nao pode ter timers estrangulados no meio da medicao
                    "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling", "--start-maximized"):
            o.add_argument(arg)
        if self.ignorar_certificado:
            # o speedtest interno e acessado por IP via HTTPS
            o.add_argument("--ignore-certificate-errors")
        self.driver = webdriver.Edge(options=o)
        self.driver.set_page_load_timeout(TIMEOUT_CARREGAMENTO)

    def frente(self, outra):
        """Traz esta janela para a frente (print certo) e minimiza a outra."""
        for drv, acao in ((getattr(outra, "driver", None), "minimize_window"), (self.driver, "maximize_window")):
            if drv is None:
                continue
            try:
                getattr(drv, acao)()
            except WebDriverException:
                pass

    def ocioso(self):
        """Pagina em branco entre rodadas: nada desta fonte trafega na janela de fundo da outra."""
        if self.driver is None:
            return
        try:
            self.driver.get("about:blank")
        except WebDriverException:
            pass

    def encerrar(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except WebDriverException:
                pass
            self.driver = None
        if self.perfil:
            for _ in range(5):  # o Edge solta os arquivos do perfil alguns instantes depois
                shutil.rmtree(self.perfil, ignore_errors=True)
                if not os.path.exists(self.perfil):
                    break
                time.sleep(1)
            self.perfil = None


class FonteInterna(Fonte):
    nome, rotulo, ignorar_certificado = "interno", "Interno", True

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.host = urlparse(url).hostname if url else ""
        self.icmp_ativo = CFG["PingsICMP"] > 0
        if not url:
            self.motivo_off = "URL do speedtest interno nao configurada"

    def preparar(self):
        self.abrir_edge()

    def medir(self, ui, progresso):
        r = {}
        if self.icmp_ativo:
            ui.atualizar(progresso, "Interno: ping ICMP ao servidor...")
            ping, jitter, respostas = medir_icmp(self.host, CFG["PingsICMP"])
            r["Ping_ICMP"], r["Jitter_ICMP"] = ping, jitter
            if respostas == 0:
                self.icmp_ativo = False
                logger.warning(f"O servidor interno ({self.host}) nao responde a ping: Ping_ICMP/Jitter_ICMP "
                               "ficam N/A no restante da execucao.")
        ui.atualizar(progresso, "Interno: abrindo o speedtest...")
        try:
            self.driver.get(self.url)
            WebDriverWait(self.driver, TIMEOUT_CARREGAMENTO).until(
                EC.presence_of_element_located((By.ID, "startButtonDesk")))
        except (TimeoutException, WebDriverException) as e:
            r.update(Status="falha", Motivo=f"pagina do speedtest interno nao carregou ({detalhe_erro(e)})")
            r["Print"] = salvar_screenshot(self.driver, "Evidencia_Rede_Interno_Falha")
            return r
        time.sleep(3)  # o app termina de montar o medidor depois do botao existir
        btn = self.driver.find_element(By.ID, "startButtonDesk")
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('click', {bubbles: true}));", btn)
        inicio = time.time()
        snap = {}
        while True:
            decorrido = int(time.time() - inicio)
            snap = self.driver.execute_script(JS_OST) or {}
            if OST_CONCLUIDO in str(snap.get("status", "")).lower():
                break
            if decorrido >= CFG["TimeoutInternoSeg"]:
                r.update(Status="falha", Motivo=f"speedtest interno nao concluiu em {CFG['TimeoutInternoSeg']}s")
                break
            ui.atualizar(progresso, f"Interno: {snap.get('ao_vivo', '-')} {snap.get('status', '')}", decorrido)
            time.sleep(1)
        r["Duracao_s"] = time.time() - inicio
        logger.debug(f"Snapshot final (interno): {snap}")
        r["Download"] = rc.parse_numero(snap.get("download"))
        r["Upload"] = rc.parse_numero(snap.get("upload"))
        r["Ping"] = rc.parse_numero(snap.get("ping"))
        r["Jitter"] = rc.parse_numero(snap.get("jitter"))
        if "Status" not in r:
            if any(r[k] is None or r[k] <= 0 for k in ("Download", "Upload")) or r["Ping"] is None:
                r.update(Status="falha", Motivo="resultado incompleto na pagina do speedtest interno")
            else:
                r["Status"] = "ok"
        return r


class FonteInternet(Fonte):
    nome, rotulo = "internet", "Internet"

    def __init__(self):
        super().__init__()
        self.config_pedida = f"fixa({CFG['FastDuracaoSeg']}s,{CFG['FastConexoes']})"

    def preparar(self):
        """Abre o Edge e grava a configuracao fixa no painel do fast.com (persiste no perfil)."""
        self.abrir_edge()
        try:
            self.driver.get(URL_FAST)
            WebDriverWait(self.driver, TIMEOUT_CARREGAMENTO).until(
                EC.presence_of_element_located((By.ID, "settings-link")))
            time.sleep(2)
            aplicou = self.driver.execute_script(JS_FAST_CONFIG, CFG["FastConexoes"], CFG["FastDuracaoSeg"])
            time.sleep(1)
            ls = self.driver.execute_script(JS_LOCAL_STORAGE) or {}
            if aplicou and rc.config_fast_aplicada(ls, CFG["FastDuracaoSeg"], CFG["FastConexoes"]):
                logger.info(f"fast.com configurado: duracao {CFG['FastDuracaoSeg']}s (min = max), "
                            f"{CFG['FastConexoes']} conexoes paralelas (min = max).")
            else:
                logger.warning("Painel de configuracoes do fast.com nao encontrado ou nao salvou: "
                               "as rodadas usam a configuracao padrao do site (Config_Fast=padrao).")
        except TimeoutException:
            logger.warning("fast.com nao carregou ao configurar; a primeira rodada confirma o acesso.")
        except WebDriverException as e:
            logger.warning(f"Falha ao configurar o fast.com ({detalhe_erro(e)}); a primeira rodada confirma o acesso.")
        self.ocioso()  # o "Salvar" reinicia a medicao do site: nao pode vazar para a rodada seguinte

    def bloqueio(self, motivo):
        logger.error(f"fast.com inacessivel ou bloqueado pela politica de rede: {motivo}")
        try:
            logger.error(f"  Pagina exibida: titulo='{self.driver.title}' | url='{self.driver.current_url}'")
        except WebDriverException:
            pass
        logger.error("  Verifique o agente zero trust/proxy: fast.com, api.fast.com e *.oca.nflxvideo.net "
                     "precisam estar liberados.")
        return {"Status": "bloqueio", "Motivo": f"fast.com bloqueado: {motivo}",
                "Print": salvar_screenshot(self.driver, "Evidencia_Rede_Internet_Bloqueio")}

    def medir(self, ui, progresso):
        ui.atualizar(progresso, "Internet: abrindo fast.com...")
        try:
            self.driver.get(URL_FAST)  # o fast.com inicia a medicao sozinho
            WebDriverWait(self.driver, TIMEOUT_CARREGAMENTO).until(
                EC.presence_of_element_located((By.ID, ID_DOWNLOAD)))
        except TimeoutException:
            return self.bloqueio(f"interface de medicao nao carregou em {TIMEOUT_CARREGAMENTO}s")
        except WebDriverException as e:
            return self.bloqueio(f"falha ao acessar {URL_FAST} ({detalhe_erro(e)})")
        inicio = time.time()
        try:
            ls = self.driver.execute_script(JS_LOCAL_STORAGE) or {}
        except WebDriverException:
            ls = {}
        config = self.config_pedida if rc.config_fast_aplicada(
            ls, CFG["FastDuracaoSeg"], CFG["FastConexoes"]) else "padrao"
        # exibe upload e latencias, para aparecerem no print
        self.driver.execute_script("const l = document.getElementById(arguments[0]); if (l) { l.click(); }",
                                   ID_MAIS_DETALHES)
        dados, snap = {}, {}
        r = {"Config_Fast": config}
        while True:
            decorrido = int(time.time() - inicio)
            snap = self.driver.execute_script(JS_SNAPSHOT, IDS_LEITURA) or {}
            dados = interpretar_fast(snap)
            if dados["erro_visivel"]:
                texto = (snap.get(ID_ERRO) or {}).get("texto", "")
                b = self.bloqueio(f"o fast.com nao alcancou seus servidores de medicao ('{texto}')")
                b["Config_Fast"] = config
                return b
            if dados["concluido"]:
                break
            if decorrido >= CFG["TimeoutInternetSeg"]:
                r.update(Status="falha", Motivo=f"fast.com nao concluiu em {CFG['TimeoutInternetSeg']}s")
                break
            parcial = (snap.get(ID_DOWNLOAD) or {}).get("texto", "-")
            unidade = (snap.get(ID_DOWNLOAD_UNID) or {}).get("texto", "")
            ui.atualizar(progresso, f"Internet: {parcial} {unidade}", decorrido)
            time.sleep(1)
        r["Duracao_s"] = time.time() - inicio
        logger.debug(f"Snapshot final (internet): {snap}")
        r.update({"Download": dados["download"], "Upload": dados["upload"], "Ping": dados["ping"],
                  "Latencia_Carga": dados["latencia_carga"], "Local_Cliente": dados["local_cliente"],
                  "IP_Saida": dados["ip_saida"], "Servidores": dados["servidores"]})
        if "Status" not in r:
            if any(r[k] is None for k in ("Download", "Upload", "Ping")):
                r.update(Status="falha", Motivo="download, upload ou ping nao capturados no fast.com")
            else:
                r["Status"] = "ok"
        return r


def interpretar_fast(snap):
    """Metricas de um snapshot do DOM do fast.com."""
    def texto(id_):
        return (snap.get(id_) or {}).get("texto", "")

    def concluido(id_):
        return CLASSE_CONCLUIDO in (snap.get(id_) or {}).get("classe", "").split()

    def valor(id_, id_unid, fatores, padrao):
        return rc.converter(texto(id_), texto(id_unid), fatores, padrao) if concluido(id_) else None

    download = valor(ID_DOWNLOAD, ID_DOWNLOAD_UNID, rc.FATOR_MBPS, "mbps")
    upload = valor(ID_UPLOAD, ID_UPLOAD_UNID, rc.FATOR_MBPS, "mbps")
    ping = valor(ID_LATENCIA, ID_LATENCIA_UNID, rc.FATOR_MS, "ms")
    carga = rc.converter(texto(ID_LATENCIA_CARGA), texto(ID_LATENCIA_CARGA_UNID), rc.FATOR_MS, "ms")
    # velocidade zero com status concluido nao e uma medicao valida
    download = download if download and download > 0 else None
    upload = upload if upload and upload > 0 else None
    servidores = " | ".join(p.strip() for p in rc.reparar_texto(texto(ID_SERVIDORES)).split("|") if p.strip())
    return {"download": download, "upload": upload, "ping": ping, "latencia_carga": carga,
            "local_cliente": texto(ID_LOCAL_CLIENTE), "ip_saida": texto(ID_IP_SAIDA), "servidores": servidores,
            "concluido": concluido(ID_DOWNLOAD) and concluido(ID_LATENCIA) and concluido(ID_UPLOAD),
            "erro_visivel": bool((snap.get(ID_ERRO) or {}).get("visivel"))}


# =============================================================================
# SAIDA
# =============================================================================
def salvar_csvs(rodadas, motivos_off):
    """Regrava os dois CSVs (chamado a cada rodada: um processo morto deixa o parcial)."""
    with open(CAMINHO_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rc.COLUNAS_RODADA, delimiter=";")
        w.writeheader()
        for r in rodadas:
            w.writerow(rc.linha_rodada_csv(r, CFG["Aquecimento"]))
    with open(CAMINHO_CSV_TEMATICO, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Metrica", "Valor", "Unidade"])
        w.writerows(rc.linhas_rede_csv(rodadas, CFG, motivos_off))


def texto_progresso(feitas, fontes):
    partes = []
    for f in fontes.values():
        if f.off and feitas[f.nome] == 0:
            partes.append(f"{f.rotulo} off")
        else:
            partes.append(f"{f.rotulo} {feitas[f.nome]}/{CFG['Rodadas']}")
    return " · ".join(partes)


# =============================================================================
# EXECUCAO
# =============================================================================
def realizar_afericoes(ui):
    logger.info("Verificando pre-requisitos...")
    logger.info(f"  URL interna : {URL_INTERNA or 'NAO CONFIGURADA'}")
    logger.info(f"  Internet    : {URL_FAST}")
    logger.info(f"  Rodadas     : {CFG['Rodadas']} por fonte (+{CFG['Aquecimento']} de aquecimento), intercaladas")
    logger.info(f"  Config Rede : {json.dumps(CFG, ensure_ascii=True)}")
    logger.info(f"  Saida       : {DIRETORIO_SAIDA}")

    limpar_perfis_orfaos()
    fontes = {"interno": FonteInterna(URL_INTERNA), "internet": FonteInternet()}
    rodadas = []
    meios = meios_adaptadores()
    logger.debug(f"Adaptadores (PhysicalMediaType): {meios}")
    host_interno = fontes["interno"].host or ""
    try:
        for f in fontes.values():
            if f.off:
                logger.warning(f"{f.rotulo}: off -- {f.motivo_off}")
                continue
            ui.atualizar(None, f"Preparando o Edge ({f.rotulo})...")
            try:
                f.preparar()
            except WebDriverException as e:
                f.motivo_off = f"falha ao iniciar o Edge ({detalhe_erro(e)})"
                logger.error(f"{f.rotulo}: {f.motivo_off}. Verifique o msedgedriver (Selenium Manager).")
        for f in fontes.values():
            if not f.off:
                f.ocioso()
        aguardar_calmaria(ui, ler_conexao(meios, host_interno)["Interface"])

        feitas = {n: 0 for n in fontes}
        falhas_seguidas = {n: 0 for n in fontes}
        for n, nome in rc.ordem_rodadas(CFG["Rodadas"], CFG["Aquecimento"]):
            f = fontes[nome]
            if f.off:
                continue
            outra = fontes["internet" if nome == "interno" else "interno"]
            aquec = n <= 0
            rotulo_n = f"aquecimento {n + CFG['Aquecimento']}" if aquec else f"{n}/{CFG['Rodadas']}"
            progresso = texto_progresso(feitas, fontes) + (" (aquecimento)" if aquec else "")
            logger.info(f"--- {f.rotulo} {rotulo_n} ---")

            amb = ler_conexao(meios, host_interno)
            ui.atualizar(progresso, f"{f.rotulo}: medindo trafego de fundo ({CFG['JanelaFundoSeg']}s)...")
            fundo = medir_fundo(amb["Interface"], CFG["JanelaFundoSeg"])
            f.frente(outra)
            r = {"Fonte": nome, "Rodada": n, "Aquecimento": "sim" if aquec else "nao",
                 "Data_Hora": datetime.now().strftime("%Y%m%d_%H%M%S"), **amb,
                 "Trafego_Fundo_Kbps": fundo,
                 "Contaminada": "sim" if fundo > CFG["LimiteTrafegoFundoKbps"] else "nao"}
            anterior = next((x.get("Wifi_BSSID") for x in reversed(rodadas) if x.get("Wifi_BSSID")), None)
            if anterior and amb["Wifi_BSSID"] and amb["Wifi_BSSID"] != anterior:
                logger.warning(f"O Wi-Fi trocou de AP antes de {rc.nome_rodada(r, CFG['Aquecimento'])} "
                               f"(BSSID {anterior} -> {amb['Wifi_BSSID']}): roaming no meio do teste.")
            try:
                r.update(f.medir(ui, progresso))
            except WebDriverException as e:
                r.update(Status="falha", Motivo=f"erro de automacao ({detalhe_erro(e)})")
            except Exception as e:  # erro isolado conta so esta rodada como falha
                logger.error(f"Erro inesperado na rodada: {e}", exc_info=True)
                r.update(Status="falha", Motivo=f"erro inesperado ({type(e).__name__}: {e})")
            if not r.get("Print") and f.driver is not None and r.get("Status") != "bloqueio":
                sufixo = f"A{n + CFG['Aquecimento']}" if aquec else f"{n:02d}"
                r["Print"] = salvar_screenshot(f.driver, f"Evidencia_Rede_{f.rotulo}_{sufixo}")
            f.ocioso()
            rodadas.append(r)

            if r["Status"] == "ok":
                falhas_seguidas[nome] = 0
            else:
                falhas_seguidas[nome] += 1
                logger.warning(f"{f.rotulo} {rotulo_n}: {r['Status']} -- {r.get('Motivo')}")
                if r["Status"] == "bloqueio":
                    f.motivo_off = r["Motivo"]
                elif falhas_seguidas[nome] >= CFG["MaxFalhasSeguidas"]:
                    f.motivo_off = f"{falhas_seguidas[nome]} falhas seguidas (ultima: {r.get('Motivo')})"
                if f.off:
                    logger.error(f"{f.rotulo}: rodadas restantes canceladas -- {f.motivo_off}")
            if not aquec:
                feitas[nome] += 1
            if r["Contaminada"] == "sim":
                logger.warning(f"{f.rotulo} {rotulo_n}: trafego de fundo de {fundo:.0f} kbps antes da rodada "
                               f"(limite {CFG['LimiteTrafegoFundoKbps']}): rodada fora da estatistica.")
            logger.info(
                f"{f.rotulo} {rotulo_n}: Download={rc.fmt_br(r.get('Download'))} Mbps | "
                f"Upload={rc.fmt_br(r.get('Upload'))} Mbps | Ping={rc.fmt_br(r.get('Ping'))} ms | "
                f"Fundo={fundo:.0f} kbps | {amb['Conexao_Tipo']} {amb['Interface']} | Status={r['Status']}")
            salvar_csvs(rodadas, {k: v.motivo_off for k, v in fontes.items()})
    finally:
        logger.info("Encerrando os Edges...")
        for f in fontes.values():
            f.encerrar()
    return rodadas, {k: v.motivo_off for k, v in fontes.items()}


_exit_code = 1


def worker_thread(ui):
    global _exit_code
    _exit_code = 1
    logger.info("=" * 60)
    logger.info("INICIO: Teste de Rede (interno + internet, rodadas intercaladas)")
    logger.info("=" * 60)
    logger.info(f"Host: {os.environ.get('COMPUTERNAME', 'N/A')} | User: {os.environ.get('USERNAME', 'N/A')}")
    if HUB_EVIDENCE_DIR:
        logger.info(f"Modo Hub detectado. Evidencias em: {HUB_EVIDENCE_DIR}")
    logger.info(f"Log salvo em: {LOG_FILE}")
    try:
        rodadas, motivos = realizar_afericoes(ui)
        salvar_csvs(rodadas, motivos)
        resumo = rc.resumo_fontes(rodadas, CFG, motivos)
        logger.info("=" * 60)
        for nome in rc.FONTES:
            s = resumo[nome]
            down, up = s["stats"]["Download"], s["stats"]["Upload"]
            logger.info(
                f"{rc.PREFIXO[nome]}: {s['status'].upper()} | validas {s['validas']}/{s['executadas']} | "
                f"Download mediana {rc.fmt_br(down['mediana'])} Mbps (CV {rc.fmt_br(down['cv'])}%) | "
                f"Upload mediana {rc.fmt_br(up['mediana'])} Mbps (CV {rc.fmt_br(up['cv'])}%) | "
                f"Estavel={s['estavel']}" + (f" | {s['motivo']}" if s["motivo"] else ""))
        _exit_code = rc.exit_code({k: v["status"] for k, v in resumo.items()})
        logger.info(f"FIM: {'PASS' if _exit_code == 0 else 'FAIL (nenhuma fonte terminou ok)'}")
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Erro fatal: {e}", exc_info=True)
        _exit_code = 1
    finally:
        ui.fechar()


if __name__ == "__main__":
    ui = MonitorOverlay()
    threading.Thread(target=worker_thread, args=(ui,), daemon=True).start()
    ui.root.mainloop()
    sys.exit(_exit_code)
