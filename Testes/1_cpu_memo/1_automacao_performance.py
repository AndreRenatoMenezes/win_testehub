import os
import sys
import time
import glob
import csv
import json
import random
import shutil
import logging
import subprocess
import threading
import pyautogui
import pyperclip
import psutil
import pandas as pd
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from pynput import keyboard as kb
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
try:
    from selenium.webdriver.edge.webdriver import WebDriver as EdgeDriver
except ImportError:
    from selenium.webdriver.chromium.webdriver import ChromiumDriver
    # Fallback: construir EdgeDriver a partir do ChromiumDriver (Edge e Chromium)
    class EdgeDriver(ChromiumDriver):
        def __init__(self, service=None, options=None):
            super().__init__(
                browser_name="MicrosoftEdge",
                vendor_prefix="ms",
                service=service,
                options=options,
            )

# =============================================================================
# CONFIGURAcoES DO TESTE
# =============================================================================
TEST_RUNS = 5
DURATION_SECONDS = 300
STABILIZE_SECONDS = 15
COOLDOWN_SECONDS = 300
COOLDOWN_CPU_THRESHOLD = 15.0   # (%) CPU abaixo desse valor = sistema estavel
COOLDOWN_CHECK_INTERVAL = 10    # (s) intervalo entre checagens de CPU no cooldown
PROFILE_NAME = "Agentes_SI_Profile.wpaProfile"

_exit_code = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_PATH = os.environ.get(
    'HUB_EVIDENCE_DIR',
    os.path.join(BASE_DIR, f"Traces_{SESSION_TIMESTAMP}")
)
os.makedirs(OUTPUT_PATH, exist_ok=True)

# =============================================================================
# LOGGING ESTRUTURADO (Melhoria #11)
# =============================================================================
LOG_FILE = os.path.join(OUTPUT_PATH, f"automacao_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("AutomacaoPerformance")
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
# MECANISMO DE PARADA SEGURA (Melhoria #17) — Ctrl+Q
# =============================================================================
_stop_requested = threading.Event()
_ctrl_pressed = False


def _on_key_press(key):
    global _ctrl_pressed
    # Detectar Ctrl pressionado (esquerdo ou direito)
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = True
    # Se Ctrl esta seguro e 'q' foi pressionado → parada segura
    if _ctrl_pressed and hasattr(key, 'char') and key.char in ('q', 'Q', '\x11'):
        logger.warning("Parada segura solicitada pelo usuario (Ctrl+Q).")
        _stop_requested.set()


def _on_key_release(key):
    global _ctrl_pressed
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = False


def check_stop():
    """Verifica se a parada segura foi solicitada. Usar em loops longos."""
    if _stop_requested.is_set():
        raise KeyboardInterrupt("Parada segura solicitada pelo usuario.")


# =============================================================================
# 1. INTERFACE GRaFICA (JANELA SOBREPOSTA) — com indicador de parada
# =============================================================================
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Automacao")

        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"340x140+{largura_tela - 370}+30")
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#1e1e1e")

        # Tornar a janela click-through no Windows (cliques passam direto)
        self.root.update_idletasks()
        self._set_click_through()

        self.lbl_ciclo = tk.Label(
            self.root, text="Preparando...",
            fg="#00ff00", bg="#1e1e1e", font=("Segoe UI", 12, "bold")
        )
        self.lbl_ciclo.pack(pady=(10, 5))

        self.lbl_status = tk.Label(
            self.root, text="Iniciando script...",
            fg="white", bg="#1e1e1e", font=("Segoe UI", 10)
        )
        self.lbl_status.pack(pady=0)

        self.lbl_tempo = tk.Label(
            self.root, text="Tempo restante: --",
            fg="#00d2ff", bg="#1e1e1e", font=("Consolas", 11)
        )
        self.lbl_tempo.pack(pady=5)

        self.lbl_hotkey = tk.Label(
            self.root, text="Ctrl+Q para parada segura",
            fg="#666666", bg="#1e1e1e", font=("Segoe UI", 8)
        )
        self.lbl_hotkey.pack(pady=(0, 5))

    def _set_click_through(self):
        """Torna a janela transparente a cliques no Windows usando ctypes."""
        try:
            import ctypes
            # Constantes da API Win32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            LWA_ALPHA = 0x00000002

            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

            # Obter estilo atual e adicionar LAYERED + TRANSPARENT
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

            # Definir opacidade (230 de 255 ≈ 90% opaco, visivel mas click-through)
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 230, LWA_ALPHA)

            logger.debug("Overlay configurado como click-through.")
        except Exception as e:
            logger.warning(f"Nao foi possivel tornar overlay click-through: {e}")

    def atualizar(self, ciclo, status, tempo="--"):
        texto_ciclo = (
            f"Ciclo Atual: {ciclo} de {TEST_RUNS}" if ciclo > 0 else "Etapa Final"
        )
        self.root.after(0, lambda: self.lbl_ciclo.config(text=texto_ciclo))
        self.root.after(0, lambda: self.lbl_status.config(text=status))
        if tempo != "--":
            self.root.after(
                0, lambda: self.lbl_tempo.config(text=f"Tempo restante: {tempo}s")
            )
        else:
            self.root.after(
                0, lambda: self.lbl_tempo.config(text="Aguarde...")
            )

    def fechar(self):
        self.root.after(0, self.root.destroy)


# =============================================================================
# 2. VERIFICAcaO DE PRe-REQUISITOS (Melhoria #12)
# =============================================================================
def check_prerequisites():
    """Verifica se todos os programas e arquivos necessarios estao disponiveis."""
    logger.info("Verificando pre-requisitos do sistema...")
    errors = []

    # Verificar executaveis no PATH
    required_exes = {
        "wpr.exe": "Windows Performance Recorder (necessario para captura)",
        "wpaexporter.exe": "WPA Exporter (necessario para exportar CSV)",
    }
    for exe, descricao in required_exes.items():
        if shutil.which(exe) is None:
            errors.append(f"'{exe}' nao encontrado no PATH — {descricao}")

    # Verificar se o Edge esta instalado
    edge_paths = [
        shutil.which("msedge"),
        shutil.which("msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    if not any(p and os.path.exists(p) for p in edge_paths if p):
        errors.append("Microsoft Edge nao encontrado no sistema.")

    # Verificar profile WPA
    profile_path = os.path.join(BASE_DIR, PROFILE_NAME)
    profile_xml = profile_path + ".xml"
    if not os.path.exists(profile_path) and not os.path.exists(profile_xml):
        errors.append(
            f"Profile WPA '{PROFILE_NAME}' nao encontrado em '{BASE_DIR}'. "
            "A exportacao CSV sera ignorada."
        )
        logger.warning(errors[-1])  # Aviso, nao erro fatal

    # Verificar dependências Python
    required_modules = ["pyautogui", "pyperclip", "psutil", "pandas", "pynput"]
    for mod in required_modules:
        try:
            __import__(mod)
        except ImportError:
            errors.append(f"Modulo Python '{mod}' nao esta instalado (pip install {mod}).")

    # Erros fatais vs avisos
    fatal_errors = [e for e in errors if "nao encontrado no PATH" in e or "nao esta instalado" in e]
    if fatal_errors:
        for e in fatal_errors:
            logger.error(f"PRe-REQUISITO FALTANDO: {e}")
        raise EnvironmentError(
            "Pre-requisitos nao atendidos. Verifique o log para detalhes."
        )

    logger.info("Pre-requisitos verificados com sucesso.")


# =============================================================================
# 3. FUNcoES DE SUPORTE
# =============================================================================
def fix_profile_extension(ui):
    """Renomeia arquivos .wpaProfile.xml para .wpaProfile se necessario."""
    ui.atualizar(0, "Verificando arquivos XML...")
    xml_profiles = glob.glob(os.path.join(BASE_DIR, f"{PROFILE_NAME}.xml"))
    for xml_file in xml_profiles:
        correct_name = xml_file.replace(".xml", "")
        os.rename(xml_file, correct_name)
        logger.info(f"Profile corrigido: {os.path.basename(correct_name)}")


def kill_edge(ui, run_index):
    """Encerra o Edge de forma verificavel (Melhoria #2, #4)."""
    ui.atualizar(run_index, "Encerrando instancias do Edge...")
    result = subprocess.run(
        "taskkill /F /IM msedge.exe",
        shell=True, capture_output=True, text=True
    )
    if result.returncode != 0 and "not found" not in result.stderr.lower():
        logger.debug(f"taskkill retornou codigo {result.returncode}: {result.stderr.strip()}")

    time.sleep(3)

    # Verificar se realmente encerrou
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and 'msedge' in proc.info['name'].lower():
            logger.warning("Edge ainda rodando apos taskkill. Forcando via psutil...")
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
    time.sleep(1)



def _get_current_tab_url():
    """
    Lê a URL da aba ativa do Edge via barra de enderecos.
    Retorna a URL em minusculas ou string vazia em caso de erro.
    """
    try:
        original_clipboard = ""
        try:
            original_clipboard = pyperclip.paste()
        except Exception:
            pass

        pyautogui.hotkey('ctrl', 'l')
        time.sleep(0.5)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.3)

        current_url = pyperclip.paste().strip().lower()

        try:
            pyperclip.copy(original_clipboard)
        except Exception:
            pass

        pyautogui.press('escape')
        time.sleep(0.3)

        return current_url

    except Exception as e:
        logger.debug(f"Erro ao ler URL da aba ativa: {e}")
        return ""


def _check_edge_welcome_screen():
    """
    Verifica se o Edge caiu na tela de boas-vindas / primeiro uso.
    Retorna True se detectar tela de welcome.
    """
    current_url = _get_current_tab_url()
    if not current_url:
        return False

    welcome_patterns = [
        "edge://welcome",
        "edge://first-run",
        "edge://settings/profiles",
        "edge://newtab",
    ]

    for pattern in welcome_patterns:
        if pattern in current_url:
            logger.warning(f"Tela de boas-vindas do Edge detectada: {current_url}")
            return True

    return False


def _check_google_login_screen():
    """
    Verifica se alguma aba do Edge esta na tela de login do Google.
    Percorre todas as abas abertas procurando por URLs de autenticacao Google.
    Retorna True se detectar tela de login.
    """
    google_login_patterns = [
        "accounts.google.com/signin",
        "accounts.google.com/servicelogin",
        "accounts.google.com/v3/signin",
        "accounts.google.com/accountchooser",
        "accounts.google.com/interactivelogin",
    ]

    # Verificar a aba ativa primeiro
    current_url = _get_current_tab_url()
    if any(pattern in current_url for pattern in google_login_patterns):
        logger.warning(f"Tela de login do Google detectada na aba ativa: {current_url}")
        return True

    # Percorrer as demais abas (Ctrl+Tab para avancar, verificar cada uma)
    num_tabs = 3  # O teste abre 3 URLs
    for i in range(1, num_tabs):
        pyautogui.hotkey('ctrl', 'tab')
        time.sleep(1.5)
        tab_url = _get_current_tab_url()
        if any(pattern in tab_url for pattern in google_login_patterns):
            logger.warning(f"Tela de login do Google detectada na aba {i + 1}: {tab_url}")
            return True

    return False


def _pause_for_edge_login(ui, run_index):
    """
    Pausa o teste e exibe alerta para o analista fazer login no Edge.
    Bloqueia ate o analista clicar em OK para continuar.
    """
    ui.atualizar(run_index, "⚠ AGUARDANDO LOGIN NO EDGE ⚠", "--")
    logger.warning("Teste PAUSADO — tela de boas-vindas do Edge detectada. Aguardando login do analista.")

    dialog_root = tk.Toplevel()
    dialog_root.withdraw()
    dialog_root.attributes('-topmost', True)

    messagebox.showwarning(
        "Acao Necessaria — Login no Edge",
        "A tela de boas-vindas do Microsoft Edge foi detectada.\n\n"
        "Por favor:\n"
        "1. Faca login na sua conta Microsoft no Edge\n"
        "2. Complete a configuracao inicial do navegador\n"
        "3. Feche todas as abas de boas-vindas\n\n"
        "Apos concluir, clique em OK para continuar o teste.",
        parent=dialog_root
    )

    dialog_root.destroy()
    logger.info("Analista confirmou login no Edge. Retomando teste.")
    ui.atualizar(run_index, "Login confirmado. Retomando...", "--")
    time.sleep(2)


def _pause_for_google_login(ui, run_index):
    """
    Pausa o teste e exibe alerta para o analista fazer login na conta Google.
    Bloqueia ate o analista clicar em OK para continuar.
    """
    ui.atualizar(run_index, "⚠ AGUARDANDO LOGIN NO GOOGLE ⚠", "--")
    logger.warning("Teste PAUSADO — tela de login do Google detectada. Aguardando login do analista.")

    dialog_root = tk.Toplevel()
    dialog_root.withdraw()
    dialog_root.attributes('-topmost', True)

    messagebox.showwarning(
        "Acao Necessaria — Login no Google",
        "A tela de login do Google foi detectada.\n\n"
        "O teste utiliza Google Docs e Google Sheets, que\n"
        "requerem uma conta Google autenticada.\n\n"
        "Por favor:\n"
        "1. Faca login na sua conta Google no navegador\n"
        "2. Aguarde o redirecionamento para o servico Google\n\n"
        "Apos concluir o login, clique em OK para continuar o teste.",
        parent=dialog_root
    )

    dialog_root.destroy()
    logger.info("Analista confirmou login no Google. Retomando teste.")
    ui.atualizar(run_index, "Login Google confirmado. Retomando...", "--")
    time.sleep(2)


def _configure_edge_startup_setting(ui, run_index):
    """
    Usa Selenium para acessar edge://settings/startHomeNTP e clicar na opcao
    'Abrir a pagina de nova guia', evitando restauracao de abas em aberturas futuras.
    Executado apenas na primeira rodada (run_index == 1).
    """
    ui.atualizar(run_index, "Configurando Edge para nao restaurar abas...", "--")
    logger.info("Configurando Edge: desabilitar restauracao de abas via settings...")

    # Fechar Edge — Selenium precisa de instancia propria
    kill_edge(ui, run_index)

    driver = None
    try:
        driver_path = os.path.join(BASE_DIR, "msedgedriver.exe")
        # msedgedriver.exe local e opcional (nao versionado no Git): sem ele,
        # o Selenium Manager (selenium >= 4.6) baixa o driver compativel com o Edge.
        if os.path.isfile(driver_path):
            service = EdgeService(executable_path=driver_path)
        else:
            logger.info("msedgedriver.exe local ausente; usando Selenium Manager.")
            service = EdgeService()
        options = EdgeOptions()
        options.add_argument("--no-first-run")
        options.add_argument("--disable-extensions")

        driver = EdgeDriver(service=service, options=options)
        driver.get("edge://settings/startHomeNTP")
        time.sleep(3)

        # Localizar e clicar no radio button "Abrir a pagina de nova guia"
        # A pagina de settings do Edge usa Shadow DOM, entao tentamos XPath direto primeiro
        try:
            elemento = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//span[contains(text(), 'Abrir a pagina de nova guia')]")
                )
            )
            elemento.click()
            logger.info("Opcao 'Abrir a pagina de nova guia' selecionada via XPath.")
        except Exception:
            # Fallback: acessar via JavaScript + Shadow DOM
            logger.debug("XPath direto falhou. Tentando via JavaScript/Shadow DOM...")
            driver.execute_script("""
                // Buscar todos os spans na pagina (incluindo dentro de shadow roots)
                function findInShadowRoots(root, text) {
                    let spans = root.querySelectorAll('span');
                    for (let span of spans) {
                        if (span.textContent.trim().includes(text)) {
                            return span;
                        }
                    }
                    let shadows = root.querySelectorAll('*');
                    for (let el of shadows) {
                        if (el.shadowRoot) {
                            let found = findInShadowRoots(el.shadowRoot, text);
                            if (found) return found;
                        }
                    }
                    return null;
                }
                let target = findInShadowRoots(document, 'Abrir a pagina de nova guia');
                if (target) {
                    target.click();
                } else {
                    throw new Error('Elemento nao encontrado via Shadow DOM');
                }
            """)
            logger.info("Opcao 'Abrir a pagina de nova guia' selecionada via JavaScript/Shadow DOM.")

        # Aguardar Edge salvar a configuracao automaticamente
        time.sleep(2)
        logger.info("Configuracao de inicializacao do Edge alterada com sucesso.")

    except Exception as e:
        logger.warning(
            f"Nao foi possivel configurar Edge via Selenium: {type(e).__name__}: {e}. "
            "Continuando com flags de linha de comando como fallback."
        )

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        # Garantir que o Edge foi fechado apos Selenium
        kill_edge(ui, run_index)


def _check_extra_tabs(expected_tab_count):
    """
    Verifica se o Edge possui mais abas abertas do que o esperado.
    Usa Ctrl+9 (ultima aba) e Ctrl+N (ultima aba esperada) para comparar.
    Se as URLs forem diferentes, existem abas extras.
    Retorna True se houver abas alem das esperadas.
    """
    try:
        # Ctrl+9 no Edge vai para a uLTIMA aba aberta
        pyautogui.hotkey('ctrl', '9')
        time.sleep(1.0)
        url_last = _get_current_tab_url()

        # Ctrl+<N> vai para a aba na posicao N (1-indexed)
        pyautogui.hotkey('ctrl', str(expected_tab_count))
        time.sleep(1.0)
        url_expected_last = _get_current_tab_url()

        # Se as URLs diferem, Ctrl+9 apontou para uma aba alem da esperada
        if url_last != url_expected_last:
            logger.warning(
                f"Abas extras detectadas no Edge. "
                f"ultima aba esperada (Ctrl+{expected_tab_count}): {url_expected_last} | "
                f"ultima aba real (Ctrl+9): {url_last}"
            )
            return True

        # Voltar para a primeira aba
        pyautogui.hotkey('ctrl', '1')
        time.sleep(0.5)

        logger.info(f"Edge possui exatamente {expected_tab_count} aba(s). OK.")
        return False

    except Exception as e:
        logger.debug(f"Erro ao verificar abas extras: {e}")
        return False


def open_edge_and_verify(ui, run_index, urls):
    """Abre o Edge sem restaurar sessao anterior e verifica se iniciou."""
    # Na primeira rodada, configurar Edge para nao restaurar abas via settings
    if run_index == 1:
        _configure_edge_startup_setting(ui, run_index)

    ui.atualizar(run_index, "Configurando Edge (sem restauracao de sessao)...")

    ui.atualizar(run_index, "Abrindo Edge com carga de trabalho...")

    edge_flags = [
        "--disable-session-crashed-bubble",
        "--disable-features=msEdgeTabRestorationService",
    ]
    subprocess.Popen(
        ["start", "msedge"] + edge_flags + urls,
        shell=True
    )
    time.sleep(5)

    # Verificar se o Edge esta rodando
    edge_found = False
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and 'msedge' in proc.info['name'].lower():
            edge_found = True
            break

    if not edge_found:
        logger.error("Edge nao iniciou apos abertura. Tentando novamente...")
        subprocess.Popen(
            ["start", "msedge"] + edge_flags + urls,
            shell=True
        )
        time.sleep(5)

        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and 'msedge' in proc.info['name'].lower():
                edge_found = True
                break

        if not edge_found:
            raise RuntimeError("Nao foi possivel iniciar o Microsoft Edge.")

    logger.info("Edge iniciado com sucesso.")

    # Verificar se caiu na tela de boas-vindas do Edge
    if _check_edge_welcome_screen():
        _pause_for_edge_login(ui, run_index)

        # Apos login, fechar o Edge e reabrir com as URLs de teste
        logger.info("Reabrindo Edge com as URLs de teste apos login no Edge...")
        kill_edge(ui, run_index)
        subprocess.Popen(
            ["start", "msedge"] + edge_flags + urls,
            shell=True
        )
        time.sleep(5)
        logger.info("Edge reaberto com URLs de teste.")

    # Verificar se caiu na tela de login do Google (Docs/Sheets requerem conta)
    if _check_google_login_screen():
        _pause_for_google_login(ui, run_index)

        # Apos login no Google, fechar o Edge e reabrir com as URLs de teste
        logger.info("Reabrindo Edge com as URLs de teste apos login no Google...")
        kill_edge(ui, run_index)
        subprocess.Popen(
            ["start", "msedge"] + edge_flags + urls,
            shell=True
        )
        time.sleep(5)
        logger.info("Edge reaberto com URLs de teste.")

    # Verificar se o Edge tem abas extras alem das do teste
    expected_tabs = len(urls)
    if _check_extra_tabs(expected_tabs):
        logger.warning("Abas extras encontradas. Fechando Edge e reabrindo somente com as URLs do teste...")
        kill_edge(ui, run_index)
        subprocess.Popen(
            ["start", "msedge"] + edge_flags + urls,
            shell=True
        )
        time.sleep(5)
        logger.info("Edge reaberto apenas com as URLs do teste.")


def cancel_wpr_if_active():
    """Cancela captura WPR pendente para evitar estado 'preso' (Melhoria #18)."""
    logger.debug("Verificando/cancelando sessao WPR ativa...")
    subprocess.run(
        "wpr.exe -cancel",
        shell=True, capture_output=True, text=True
    )


def type_text_safely(text):
    """Digita texto usando clipboard para suportar acentos (Melhoria #1)."""
    pyperclip.copy(text)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.3)


# =============================================================================
# 4. SIMULAcaO DE CARGA DE TRABALHO REALISTA (Melhorias #6, #7, #8, #9)
# =============================================================================
# Textos variados para simular digitacao realista
TYPING_SAMPLES = [
    "O projeto continua avancando de acordo com as expectativas iniciais.",
    "A equipe mantem o monitoramento constante dos indicadores de qualidade.",
    "Os resultados parciais demonstram a eficacia da estrategia adotada.",
    "O alinhamento continuo entre as areas tem garantido o progresso fluido.",
    "As etapas de validacao estao ocorrendo sem impedimentos criticos.",
    "Todos os requisitos documentados permanecem sob analise rigorosa.",
    "A comunicacao transparente tem sido fundamental para evitar gargalos.",
    "O foco principal segue direcionado para a entrega de valor ao cliente."
]

SPREADSHEET_DATA = None  # Removido — substituido pelo sistema abaixo


def _get_safe_content_area():
    """
    Retorna (x_min, x_max, y_min, y_max) da zona segura de conteudo,
    evitando barra de abas, barra de enderecos, botao '+', scrollbar e overlay.

    Zonas perigosas evitadas:
    - Topo (< 18% da tela): abas, barra de endereco, botao nova aba (+)
    - Direita (> 82%): scrollbar, overlay no canto superior direito
    - Base (> 88%): barra de tarefas do Windows
    - Esquerda (< 8%): sidebar do Edge
    """
    screen_w, screen_h = pyautogui.size()
    return (
        int(screen_w * 0.08),   # x_min
        int(screen_w * 0.82),   # x_max
        int(screen_h * 0.18),   # y_min
        int(screen_h * 0.88),   # y_max
    )


def _click_safe_content_area():
    """Clica em ponto aleatorio dentro da zona segura de conteudo."""
    x_min, x_max, y_min, y_max = _get_safe_content_area()
    x = random.randint(x_min, x_max)
    y = random.randint(y_min, y_max)
    pyautogui.click(x, y)
    return x, y


def _focus_content_after_tab_switch():
    """
    Apos trocar de aba, garante que o foco esta na area de conteudo.
    Espera a aba carregar, pressiona Escape (fecha popups) e clica no
    centro seguro da tela para ativar a area de edicao.
    """
    time.sleep(random.uniform(3.0, 5.0))  # Esperar aba carregar

    # Escape para fechar qualquer popup de restauracao, sugestao, etc.
    pyautogui.press('escape')
    time.sleep(random.uniform(0.3, 0.5))

    x_min, x_max, y_min, y_max = _get_safe_content_area()
    center_x = (x_min + x_max) // 2
    center_y = (y_min + y_max) // 2
    pyautogui.click(center_x, center_y)
    time.sleep(random.uniform(0.8, 1.5))  # Esperar foco estabilizar


def simulate_document_editing(elapsed_ratio):
    """Simula edicao de documento Google Docs (Aba 1)."""
    logger.debug("Simulando edicao de documento...")

    # Clicar na area de edicao para garantir foco
    _click_safe_content_area()
    time.sleep(random.uniform(0.8, 1.5))

    # Digitar texto variado
    text = random.choice(TYPING_SAMPLES)
    type_text_safely(text)
    time.sleep(random.uniform(1.0, 2.5))
    pyautogui.press('enter')
    time.sleep(random.uniform(2.0, 4.0))

    # Ocasionalmente selecionar e formatar texto
    if random.random() < 0.3:
        pyautogui.hotkey('ctrl', 'a')  # Selecionar tudo
        time.sleep(random.uniform(1.0, 2.0))
        pyautogui.hotkey('ctrl', 'b')  # Negrito
        time.sleep(random.uniform(1.0, 2.0))
        _click_safe_content_area()
        time.sleep(random.uniform(1.0, 2.0))

    # Simular leitura/reposicionamento do cursor na area de edicao
    _click_safe_content_area()
    time.sleep(random.uniform(1.5, 3.0))

# ---------------------------------------------------------------------------
# SIMULAcaO ESTRUTURADA DE PLANILHA
# ---------------------------------------------------------------------------
# Cabecalhos fixos — escritos na primeira visita
_SHEET_HEADERS = ["Departamento", "Receita", "Despesa", "Lucro", "Margem(%)"]

# Pool de linhas de dados realistas — simulando controle financeiro mensal
_SHEET_DATA_POOL = [
    ["Vendas",           "45.230",  "31.400",  "13.830",  "30,6%"],
    ["Marketing",        "12.800",  "14.200",  "-1.400",  "-10,9%"],
    ["TI",               "8.500",   "22.750",  "-14.250", "-167,6%"],
    ["RH",               "3.200",   "9.800",   "-6.600",  "-206,3%"],
    ["Operacoes",        "67.100",  "52.300",  "14.800",  "22,1%"],
    ["Financeiro",       "5.400",   "7.650",   "-2.250",  "-41,7%"],
    ["Logistica",        "28.900",  "24.100",  "4.800",   "16,6%"],
    ["Juridico",         "1.800",   "6.300",   "-4.500",  "-250,0%"],
    ["Suporte",          "9.750",   "11.200",  "-1.450",  "-14,9%"],
    ["Diretoria",        "2.100",   "15.800",  "-13.700", "-652,4%"],
    ["Compras",          "4.600",   "8.900",   "-4.300",  "-93,5%"],
    ["Qualidade",        "3.350",   "5.100",   "-1.750",  "-52,2%"],
    ["Engenharia",       "15.600",  "19.400",  "-3.800",  "-24,4%"],
    ["Atendimento",      "11.200",  "8.700",   "2.500",   "22,3%"],
    ["P&D",              "1.900",   "18.500",  "-16.600", "-873,7%"],
    ["Administrativo",   "2.800",   "6.200",   "-3.400",  "-121,4%"],
    ["Comercial",        "38.400",  "27.600",  "10.800",  "28,1%"],
    ["Producao",         "52.700",  "41.300",  "11.400",  "21,6%"],
]

# Estado global da planilha — rastreia proxima linha a ser preenchida
_sheet_state = {
    "next_row": 0,          # Proxima linha (0 = cabecalho ainda nao escrito)
    "data_index": 0,        # indice no pool de dados
    "headers_written": False,
}


def _ensure_grid_focus():
    """
    Garante que o foco esta na grade do Google Sheets (nao em menus/toolbar).
    1. Escape fecha qualquer menu, popup ou modo de edicao de celula aberto.
    2. Clique no centro da tela (zona segura da grade, evitando toolbar/sidebar).
    3. Pequena pausa para o foco estabilizar.
    """
    pyautogui.press('escape')
    time.sleep(random.uniform(0.4, 0.7))
    pyautogui.press('escape')  # Segundo Escape para menus aninhados
    time.sleep(random.uniform(0.3, 0.5))

    # Clicar no centro da tela — ponto mais seguro da grade
    screen_w, screen_h = pyautogui.size()
    center_x = screen_w // 2
    center_y = int(screen_h * 0.55)  # Levemente abaixo do centro (evita toolbar)
    pyautogui.click(center_x, center_y)
    time.sleep(random.uniform(0.8, 1.2))


def _navigate_to_cell_a1():
    """Navega para A1 no Google Sheets usando Ctrl+Home."""
    pyautogui.hotkey('ctrl', 'Home')
    time.sleep(random.uniform(0.12, 1.2))


def _navigate_to_row(target_row):
    """
    Navega para a coluna A de uma linha especifica no Google Sheets.
    Usa Ctrl+Home para ir a A1, depois setas para baixo.
    target_row: 0=A1 (cabecalho), 1=A2 (primeira linha de dados), etc.
    """
    _navigate_to_cell_a1()

    if target_row <= 0:
        return

    # Para poucas linhas, usar setas individuais (mais confiavel)
    if target_row <= 30:
        for i in range(target_row):
            pyautogui.press('down')
            time.sleep(random.uniform(0.08, 0.15))
        time.sleep(random.uniform(0.3, 0.5))
    else:
        # Para muitas linhas, usar Ctrl+G (caixa de navegacao do Sheets)
        # ou repetir setas em blocos menores com pausas
        remaining = target_row
        while remaining > 0:
            batch = min(remaining, 20)
            for _ in range(batch):
                pyautogui.press('down')
                time.sleep(random.uniform(0.05, 0.10))
            remaining -= batch
            time.sleep(random.uniform(0.2, 0.4))
        time.sleep(random.uniform(0.3, 0.5))


def _type_cell_value(value):
    """
    Digita um valor na celula atual do Google Sheets.
    Usa clipboard para suporte a acentos e caracteres especiais.
    """
    type_text_safely(value)
    time.sleep(random.uniform(0.5, 1.0))


def _advance_to_next_column():
    """Avanca para a proxima coluna usando seta direita (mais confiavel que Tab)."""
    pyautogui.press('tab')
    time.sleep(random.uniform(0.25, 0.50))


def _advance_to_next_row_col_a():
    """
    Apos preencher a ultima coluna de uma linha, move para coluna A da proxima.
    Usa Enter para confirmar o valor, Home para voltar a coluna A,
    e Down para descer uma linha — garantindo posicao correta.
    """
    pyautogui.press('right')       # Confirma o valor da celula atual
    time.sleep(random.uniform(0.5, 0.8))
    pyautogui.press('down')       # Confirma o valor da celula atual
    time.sleep(random.uniform(0.5, 0.8))
    pyautogui.press('home')        # Volta a coluna A da linha atual
    time.sleep(random.uniform(0.5, 0.8))


def _write_row(values):
    """
    Escreve uma linha completa de dados na planilha.
    Digita cada valor e navega entre colunas com setas.
    Ao final, posiciona o cursor em A da proxima linha.
    """
    num_cols = len(values)
    for col_idx, value in enumerate(values):
        _type_cell_value(value)

        if col_idx < num_cols - 1:
            # Nao e a ultima coluna → avancar para a direita
            _advance_to_next_column()
        else:
            # ultima coluna → confirmar e ir para col A da proxima linha
            _advance_to_next_row_col_a()


def simulate_spreadsheet_editing(elapsed_ratio):

    global _sheet_state
    logger.debug(
        f"Simulando planilha — linha atual: {_sheet_state['next_row']}, "
        f"cabecalho escrito: {_sheet_state['headers_written']}"
    )

    # ── 1. Garantir foco na grade da planilha ──
    _ensure_grid_focus()

    # ── 2. Escrever cabecalho na primeira visita ──
    if not _sheet_state["headers_written"]:
        logger.debug("Escrevendo cabecalho da planilha...")

        # Ir para A1
        _navigate_to_cell_a1()

        # Escrever cabecalho
        _write_row(_SHEET_HEADERS)

        _sheet_state["headers_written"] = True
        _sheet_state["next_row"] = 1  # Linha 0 = cabecalho; dados comecam na 1

        # Pausa — simulando "pensando no que preencher"
        time.sleep(random.uniform(1.5, 3.0))

        # Cursor ja esta em A2 apos _write_row, pronto para dados
        logger.debug("Cabecalho escrito. Cursor posicionado em A2.")
    else:
        # ── 3. Navegar ate a proxima linha vazia ──
        logger.debug(f"Navegando para linha {_sheet_state['next_row']} (A{_sheet_state['next_row'] + 1})...")
        _navigate_to_row(_sheet_state["next_row"])

    # ── 4. Preencher 3 linhas de dados ──
    rows_filled = 0
    for row in range(3):
        # Pegar proximo registro do pool (circular)
        data_idx = _sheet_state["data_index"] % len(_SHEET_DATA_POOL)
        row_data = _SHEET_DATA_POOL[data_idx]
        _sheet_state["data_index"] += 1

        current_row_num = _sheet_state['next_row'] + row
        logger.debug(
            f"  Preenchendo linha {current_row_num} "
            f"(A{current_row_num + 1}): {row_data[0]}"
        )

        _write_row(row_data)
        rows_filled += 1

        # Pausa entre linhas — simulando consulta de dados
        if row < 2:
            time.sleep(random.uniform(1.5, 3.5))

    _sheet_state["next_row"] += rows_filled
    logger.info(
        f"Planilha: {rows_filled} linhas preenchidas "
        f"(total de linhas de dados: {_sheet_state['next_row'] - 1}, "
        f"proxima linha: A{_sheet_state['next_row'] + 1})"
    )


def simulate_pdf_reading(elapsed_ratio):
    """Simula leitura de PDF (Aba 3)."""
    logger.debug("Simulando leitura de PDF...")

    # Garantir foco na area do PDF antes de scrollar
    _click_safe_content_area()
    time.sleep(random.uniform(1.0, 2.0))

    # Scroll variado simulando leitura
    for _ in range(random.randint(1, 3)):
        action = random.choice(['pagedown', 'scroll_down', 'scroll_up'])
        if action == 'pagedown':
            pyautogui.press('pagedown')
        elif action == 'scroll_down':
            pyautogui.scroll(-random.randint(2, 5))
        else:
            pyautogui.scroll(random.randint(1, 3))
        time.sleep(random.uniform(3.0, 6.0))


# Mapa de acoes por aba (indice da aba → funcao de simulacao)
TAB_ACTIONS = [
    simulate_document_editing,
    simulate_spreadsheet_editing,
    simulate_pdf_reading,
]


# =============================================================================
# 5. CICLO DE TESTE PRINCIPAL
# =============================================================================
def run_test_cycle(run_index, ui):
    """Executa um ciclo completo de teste com captura WPR."""
    run_ts = datetime.now().strftime('%Y%m%d_%H%M%S')  # Timestamp local (Melhoria #10)
    logger.info(f"--- Iniciando Coleta {run_index} de {TEST_RUNS} ---")
    check_stop()

    # Resetar estado da planilha (cada ciclo abre uma planilha nova)
    global _sheet_state
    _sheet_state = {"next_row": 0, "data_index": _sheet_state["data_index"], "headers_written": False}

    # Encerrar Edge existente
    kill_edge(ui, run_index)
    check_stop()

    # Abrir Edge com verificacao
    urls = [
        "https://docs.google.com/document/create",
        "https://docs.google.com/spreadsheets/create",
        "https://dl.dell.com/topicspdf/inspiron-15-3567-laptop_service-manual_pt-br.pdf"
    ]
    open_edge_and_verify(ui, run_index, urls)
    check_stop()

    # Estabilizar
    for i in range(STABILIZE_SECONDS, 0, -1):
        check_stop()
        ui.atualizar(run_index, "Estabilizando paginas do Edge...", i)
        time.sleep(1)

    # Iniciar Captura WPR (com cleanup previo — Melhoria #18)
    trace_file = os.path.join(OUTPUT_PATH, f"Trace_{run_ts}_Run{run_index}.etl")
    ui.atualizar(run_index, "Iniciando captura WPR...")

    cancel_wpr_if_active()  # Limpar sessao anterior se existir

    wpr_start = 'wpr.exe -start Power.light -start VirtualAllocation.light -filemode -compress'
    result = subprocess.run(wpr_start, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Falha ao iniciar WPR: {result.stderr.strip()}")
        raise RuntimeError("Falha ao iniciar captura WPR.")

    wpr_active = True  # Flag para cleanup no finally

    try:
        # Automacao com acoes variadas por aba (Melhorias #6, #7, #8, #9)
        start_time = time.time()
        current_tab = 0  # Rastrear aba atual (0=Doc, 1=Sheets, 2=PDF)

        while True:
            check_stop()
            elapsed = time.time() - start_time
            remaining = int(DURATION_SECONDS - elapsed)
            if remaining <= 0:
                break

            elapsed_ratio = elapsed / DURATION_SECONDS
            ui.atualizar(run_index, "Simulando uso de escritorio...", remaining)

            try:
                # Executar acao especifica da aba atual
                TAB_ACTIONS[current_tab](elapsed_ratio)

                # Pausa realista entre acoes
                time.sleep(random.uniform(4.0, 10.0))

                # Alternar para proxima aba (Ctrl+Tab)
                pyautogui.hotkey('ctrl', 'tab')
                current_tab = (current_tab + 1) % len(TAB_ACTIONS)

                # Aguardar carregamento da aba e clicar na area de conteudo
                _focus_content_after_tab_switch()

            except pyautogui.FailSafeException:
                logger.warning("PyAutoGUI fail-safe ativado (mouse no canto).")
                raise KeyboardInterrupt("Fail-safe do PyAutoGUI.")
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # Melhoria #3: Logar erros em vez de silenciar
                logger.warning(f"Erro durante automacao (continuando): {type(e).__name__}: {e}")
                time.sleep(2)

        # Parar captura WPR
        ui.atualizar(run_index, "Salvando arquivo Trace (.etl)...", "--")
        stop_result = subprocess.run(
            f'wpr.exe -stop "{trace_file}" -compress',
            shell=True, capture_output=True, text=True
        )
        if stop_result.returncode != 0:
            logger.error(f"Falha ao parar WPR: {stop_result.stderr.strip()}")
            raise RuntimeError("Falha ao salvar trace WPR.")
        wpr_active = False
        logger.info(f"Trace salvo: {trace_file}")

    finally:
        # Melhoria #18: Garantir que WPR seja cancelado se ficou ativo
        if wpr_active:
            logger.warning("WPR ainda ativo apos excecao. Cancelando...")
            cancel_wpr_if_active()

    # Exportacao WPA
    profile_path = os.path.join(BASE_DIR, PROFILE_NAME)
    if os.path.exists(profile_path):
        ui.atualizar(run_index, "Convertendo dados para CSV...", "--")
        csv_folder = os.path.join(OUTPUT_PATH, f"CSV_{run_ts}_Run{run_index}")
        os.makedirs(csv_folder, exist_ok=True)
        wpa_cmd = (
            f'wpaexporter.exe -i "{trace_file}" '
            f'-profile "{profile_path}" '
            f'-outputfolder "{csv_folder}"'
        )
        wpa_result = subprocess.run(wpa_cmd, shell=True, capture_output=True, text=True)
        if wpa_result.returncode != 0:
            logger.warning(f"wpaexporter retornou erro: {wpa_result.stderr.strip()}")
        else:
            logger.info(f"CSVs exportados para: {csv_folder}")
    else:
        logger.warning(f"Profile WPA nao encontrado: {profile_path}. Exportacao CSV ignorada.")


# =============================================================================
# 6. COOLDOWN INTELIGENTE (Melhoria #13)
# =============================================================================
def smart_cooldown(run_index, ui):
    """Aguarda o sistema estabilizar monitorando CPU real com psutil."""
    logger.info(
        f"Iniciando cooldown (max {COOLDOWN_SECONDS}s, "
        f"alvo CPU < {COOLDOWN_CPU_THRESHOLD}%)..."
    )
    start = time.time()
    stable_readings = 0
    required_stable = 3  # Precisa de N leituras consecutivas abaixo do threshold

    while True:
        check_stop()
        elapsed = int(time.time() - start)
        remaining = max(0, COOLDOWN_SECONDS - elapsed)

        if elapsed >= COOLDOWN_SECONDS:
            logger.info("Cooldown atingiu tempo maximo.")
            break

        cpu_percent = psutil.cpu_percent(interval=COOLDOWN_CHECK_INTERVAL)
        ui.atualizar(
            run_index,
            f"Arrefecimento — CPU: {cpu_percent:.1f}%",
            remaining
        )
        logger.debug(f"Cooldown: CPU={cpu_percent:.1f}%, elapsed={elapsed}s")

        if cpu_percent < COOLDOWN_CPU_THRESHOLD:
            stable_readings += 1
            if stable_readings >= required_stable:
                logger.info(
                    f"Sistema estavel (CPU < {COOLDOWN_CPU_THRESHOLD}% "
                    f"por {required_stable} leituras). Cooldown concluido em {elapsed}s."
                )
                break
        else:
            stable_readings = 0


# =============================================================================
# 7. CONSOLIDAcaO DE DADOS (Melhorias #5, #14, #15)
# =============================================================================
def detect_number_format(series):
    """
    Detecta se os numeros usam formato BR (1.000,50) ou US (1,000.50).
    Retorna 'br' ou 'us'. (Melhoria #14)
    """
    sample = series.dropna().astype(str).head(50)
    br_pattern = 0
    us_pattern = 0

    for val in sample:
        val = val.strip()
        # Formato BR: ponto como milhar, virgula como decimal → "1.234,56"
        if ',' in val and '.' in val:
            last_comma = val.rfind(',')
            last_dot = val.rfind('.')
            if last_comma > last_dot:
                br_pattern += 1
            else:
                us_pattern += 1
        elif ',' in val:
            # Pode ser BR decimal ou US milhar
            parts = val.split(',')
            if len(parts) == 2 and len(parts[1]) <= 3:
                br_pattern += 1  # Provavelmente decimal BR
            else:
                us_pattern += 1
        elif '.' in val:
            parts = val.split('.')
            if len(parts) == 2 and len(parts[1]) <= 3:
                us_pattern += 1
            else:
                br_pattern += 1  # Ponto como milhar sem decimal

    return 'br' if br_pattern >= us_pattern else 'us'


def parse_numeric_column(series, fmt='br'):
    """Converte coluna para numerico respeitando o formato detectado."""
    s = series.astype(str)
    if fmt == 'br':
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
    else:
        s = s.str.replace(',', '', regex=False)
    return pd.to_numeric(s, errors='coerce')


def consolidate_results(ui):
    """Consolida CSVs com deteccao automatica de formato e contagem de amostras."""
    ui.atualizar(0, "Consolidando arquivos CSV...", "--")
    logger.info("Iniciando consolidacao de resultados...")

    consolidation_folder = os.path.join(OUTPUT_PATH, "Resultados_Consolidados")
    os.makedirs(consolidation_folder, exist_ok=True)

    csv_files = glob.glob(os.path.join(OUTPUT_PATH, "CSV_*", "*.csv"))
    if not csv_files:
        logger.warning("Nenhum arquivo CSV encontrado para consolidacao.")
        return

    grouped_csvs = {}
    for f in csv_files:
        grouped_csvs.setdefault(os.path.basename(f), []).append(f)

    summary_data = []  # Para relatorio resumido (Melhoria #16)

    for file_name, file_paths in grouped_csvs.items():
        dataframes = []
        for fp in file_paths:
            try:
                df = pd.read_csv(fp, encoding='utf-8-sig')
                if df.empty:
                    logger.debug(f"CSV vazio ignorado: {fp}")
                    continue

                key_col = df.columns[0]
                df[key_col] = (
                    df[key_col].astype(str)
                    .str.replace(r'\s*\(\d+\)\s*$', '', regex=True)
                )

                # Melhoria #14: Detectar formato numerico por coluna
                for col in df.columns[1:]:
                    fmt = detect_number_format(df[col])
                    df[col] = parse_numeric_column(df[col], fmt)

                df_sum = df.groupby(key_col, as_index=False).sum()
                dataframes.append(df_sum)

            except Exception as e:
                # Melhoria #5: Logar erros de CSV em vez de silenciar
                logger.warning(f"Erro ao processar CSV '{fp}': {type(e).__name__}: {e}")
                continue

        if dataframes:
            df_all_runs = pd.concat(dataframes)
            key_col = df_all_runs.columns[0]

            # Melhoria #15: Calcular media E contagem de amostras
            numeric_cols = [c for c in df_all_runs.columns if c != key_col]
            df_mean = df_all_runs.groupby(key_col, as_index=False)[numeric_cols].mean()
            df_count = df_all_runs.groupby(key_col, as_index=False)[numeric_cols].count()

            # Renomear colunas
            rename_mean = {c: f"Media_{c}" for c in numeric_cols}
            rename_count = {c: f"Amostras_{c}" for c in numeric_cols}
            df_mean.rename(columns=rename_mean, inplace=True)
            df_count.rename(columns=rename_count, inplace=True)

            # Mesclar media + contagem
            df_final = pd.merge(df_mean, df_count, on=key_col)

            output_file = os.path.join(consolidation_folder, f"Media_{file_name}")
            df_final.to_csv(output_file, index=False, sep=',', encoding='utf-8-sig')
            logger.info(f"Consolidado: {output_file}")

            # Coletar dados para relatorio resumido
            for col in numeric_cols:
                media_col = f"Media_{col}"
                if media_col in df_final.columns:
                    summary_data.append({
                        "Arquivo": file_name,
                        "Metrica": col,
                        "Media Geral": df_final[media_col].mean(),
                        "Maximo": df_final[media_col].max(),
                        "Minimo": df_final[media_col].min(),
                        "Runs Processados": len(file_paths),
                    })

    # Melhoria #16: Gerar relatorio resumido
    if summary_data:
        generate_summary_report(summary_data, consolidation_folder)

    # --- CSV tematico para o Hub (cpu_memoria.csv) ---
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()

    cpu_memo_csv_path = os.path.join(OUTPUT_PATH, "cpu_memoria.csv")
    try:
        with open(cpu_memo_csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Metrica", "Valor", "Unidade"])
            writer.writerow(["Ciclos_Executados", TEST_RUNS, "un"])
            writer.writerow(["Duracao_Por_Ciclo", DURATION_SECONDS, "s"])
            writer.writerow(["CPU_Frequencia_Atual", f"{cpu_freq.current:.0f}" if cpu_freq else "N/A", "MHz"])
            writer.writerow(["CPU_Frequencia_Max", f"{cpu_freq.max:.0f}" if cpu_freq and cpu_freq.max else "N/A", "MHz"])
            writer.writerow(["CPU_Nucleos_Fisicos", psutil.cpu_count(logical=False), "un"])
            writer.writerow(["CPU_Nucleos_Logicos", psutil.cpu_count(logical=True), "un"])
            writer.writerow(["RAM_Total_GB", f"{mem.total / (1024**3):.2f}", "GB"])
            writer.writerow(["RAM_Disponivel_GB", f"{mem.available / (1024**3):.2f}", "GB"])
            writer.writerow(["RAM_Uso_Percentual", f"{mem.percent:.1f}", "%"])
            if summary_data:
                for entry in summary_data:
                    safe_name = entry["Metrica"].replace(",", "_")
                    writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Media", f"{entry['Media Geral']:.2f}", ""])
                    writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Max", f"{entry['Maximo']:.2f}", ""])
                    writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Min", f"{entry['Minimo']:.2f}", ""])
        logger.info(f"cpu_memoria.csv gerado em: {cpu_memo_csv_path}")
    except Exception as e:
        logger.warning(f"Erro ao gerar cpu_memoria.csv: {e}")


# =============================================================================
# 8. RELAToRIO RESUMIDO (Melhoria #16)
# =============================================================================
def generate_summary_report(summary_data, output_folder):
    """Gera relatorio HTML consolidado com os principais indicadores."""
    logger.info("Gerando relatorio resumido...")

    df_summary = pd.DataFrame(summary_data)
    report_csv = os.path.join(output_folder, "Relatorio_Resumo.csv")
    df_summary.to_csv(report_csv, index=False, encoding='utf-8-sig')

    # Relatorio HTML
    report_html = os.path.join(output_folder, "Relatorio_Resumo.html")
    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <title>Relatorio de Performance — {SESSION_TIMESTAMP}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, sans-serif;
            max-width: 1000px;
            margin: 40px auto;
            padding: 0 20px;
            background: #f5f5f5;
            color: #333;
        }}
        h1 {{
            color: #1a1a2e;
            border-bottom: 3px solid #16213e;
            padding-bottom: 10px;
        }}
        h2 {{ color: #16213e; margin-top: 30px; }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
            background: white;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12);
        }}
        th {{
            background: #16213e;
            color: white;
            padding: 12px 15px;
            text-align: left;
        }}
        td {{
            padding: 10px 15px;
            border-bottom: 1px solid #eee;
        }}
        tr:hover td {{ background: #f0f4ff; }}
        .info-box {{
            background: #e8f4fd;
            border-left: 4px solid #2196F3;
            padding: 15px;
            margin: 20px 0;
            border-radius: 0 4px 4px 0;
        }}
        .footer {{ color: #888; font-size: 0.85em; margin-top: 40px; }}
    </style>
</head>
<body>
    <h1>Relatorio de Performance</h1>

    <div class="info-box">
        <strong>Sessao:</strong> {SESSION_TIMESTAMP}<br>
        <strong>Ciclos executados:</strong> {TEST_RUNS}<br>
        <strong>Duracao por ciclo:</strong> {DURATION_SECONDS}s<br>
        <strong>Diretorio de saida:</strong> {OUTPUT_PATH}
    </div>

    <h2>Resumo das Metricas</h2>
    {df_summary.to_html(index=False, float_format='%.2f', border=0)}

    <p class="footer">
        Gerado automaticamente em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
        pela Automacao de Testes de Performance.
    </p>
</body>
</html>"""

    with open(report_html, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logger.info(f"Relatorio resumido gerado: {report_html}")
    logger.info(f"Dados resumidos em CSV: {report_csv}")


# =============================================================================
# THREAD PRINCIPAL DE TRABALHO
# =============================================================================
def worker_thread(ui):
    global _exit_code
    try:
        check_prerequisites()
        fix_profile_extension(ui)

        for run in range(1, TEST_RUNS + 1):
            check_stop()
            run_test_cycle(run, ui)

            if run < TEST_RUNS:
                # Melhoria #13: Cooldown inteligente com monitoramento de CPU
                smart_cooldown(run, ui)

        consolidate_results(ui)

        ui.atualizar(0, "Teste Finalizado com Sucesso!", "--")
        logger.info("=== Todos os testes concluidos com sucesso! ===")
        logger.info(f"Resultados em: {OUTPUT_PATH}")
        time.sleep(3)

    except KeyboardInterrupt:
        logger.warning("Execucao interrompida pelo usuario.")
        cancel_wpr_if_active()  # Melhoria #18
        ui.atualizar(0, "Interrompido pelo usuario.", "--")
        _exit_code = 1
        time.sleep(3)

    except EnvironmentError as err:
        logger.error(f"Erro de ambiente: {err}")
        ui.atualizar(0, "Erro de pre-requisitos! Veja o log.", "--")
        _exit_code = 1
        time.sleep(5)

    except Exception as err:
        logger.critical(f"Falha durante a execucao: {err}", exc_info=True)
        cancel_wpr_if_active()  # Melhoria #18
        ui.atualizar(0, "Erro! Verifique o log.", "--")
        _exit_code = 1
        time.sleep(5)

    finally:
        # Garantir Edge fechado ao final
        subprocess.run(
            "taskkill /F /IM msedge.exe",
            shell=True, capture_output=True, text=True
        )
        ui.fechar()


# =============================================================================
# EXECUcaO PRINCIPAL
# =============================================================================
if __name__ == "__main__":
    logger.info("=== Automacao de Testes de Performance — Versao 2.0 ===")
    logger.info(f"Diretorio base: {BASE_DIR}")
    logger.info(f"Saida: {OUTPUT_PATH}")
    logger.info(f"Log: {LOG_FILE}")
    logger.info(f"Configuracao: {TEST_RUNS} ciclos × {DURATION_SECONDS}s + cooldown inteligente")

    # Iniciar listener de parada segura (Melhoria #17)
    kb_listener = kb.Listener(on_press=_on_key_press, on_release=_on_key_release)
    kb_listener.daemon = True
    kb_listener.start()
    logger.info("Listener de parada segura ativo (Ctrl+Q).")

    # Inicia a Interface (UI)
    ui_overlay = MonitorOverlay()

    # Dispara a automacao em segundo plano
    script_thread = threading.Thread(target=worker_thread, args=(ui_overlay,), daemon=True)
    script_thread.start()

    # Mantem a janela grafica rodando no loop principal
    ui_overlay.root.mainloop()

    # Cleanup
    kb_listener.stop()
    logger.info("Script encerrado.")
    sys.exit(_exit_code)