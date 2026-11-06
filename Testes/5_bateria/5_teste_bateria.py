import os
import re
import sys
import time
import csv
import json
import winreg
import queue
import base64
import random
import shutil
import signal
import uuid
import ctypes
import logging
import threading
import subprocess
import unicodedata
import tkinter as tk
import xml.etree.ElementTree as ET
from ctypes import wintypes
from datetime import datetime
import psutil
import pyautogui
import pyperclip
from pynput import keyboard as kb

# =============================================================================
# CONFIGURACOES DO TESTE
# =============================================================================
# Modulo 5 — Bateria (spec 003): pre-voo de padronizacao (aplicar, conferir e
# registrar), aviso unico ao operador, estabilizacao, fase ociosa e fase de
# escritorio na bateria, evidencias complementares, bateria.csv e restauracao.
# Exit code: 0 somente com coleta valida; qualquer outro caso, 1.

# --- Valores da spec 003 (nao alterar sem nova spec) ---
DURACAO_OCIOSA_S = 60 * 60          # fase ociosa: tela ligada, sem entrada simulada
DURACAO_ESCRITORIO_S = 60 * 60      # fase de escritorio: Edge com documento, planilha e PDF
ESTABILIZACAO_S = 5 * 60            # apos desconectar o carregador, fora da medicao
CARGA_INICIAL_MIN_PCT = 95          # carga minima para iniciar (%)
PROTECAO_BATERIA_PCT = 7            # encerramento controlado ao atingir esta carga (%)
ESCRITORIO_MINIMO_PASS_S = 30 * 60  # minimo medido na fase de escritorio para PASS
INTERVALO_AMOSTRA_S = 60            # amostragem da bateria
ESPERA_CARREGADOR_S = 10 * 60       # espera maxima pela desconexao do carregador
BRILHO_PADRAO_PCT = 50              # brilho da tela na bateria (%)

# --- Parametros tecnicos (plan da spec 003) ---
INTERVALO_TOP_PROCESSOS_S = 5 * 60  # top 10 processos por CPU
INTERVALO_VIGIA_S = 5               # vigia: carregador, protecao de bateria e Ctrl+Q
ESTABILIZAR_EDGE_S = 15             # espera apos abrir o Edge para a fase de escritorio
TIMEOUT_EXPORTACAO_S = 30 * 60      # wpaexporter, por trace
TIMEOUT_COLETOR_S = 15              # resposta do coletor PowerShell
TENTATIVAS_LOGIN = 3                # pedidos de login (Edge/Google) na prontidao
VERSAO_TESTE = "1.0"
PROFILE_NAME = "Agentes_SI_Bateria_Profile.wpaProfile"
WPR_PERFIL = "Power.light"

URLS_PRONTIDAO = [  # paginas de lista: conferem o login sem criar documentos
    "https://docs.google.com/document/u/0/",
    "https://docs.google.com/spreadsheets/u/0/",
]
URLS_ESCRITORIO = [  # as mesmas do Modulo 1
    "https://docs.google.com/document/create",
    "https://docs.google.com/spreadsheets/create",
    "https://dl.dell.com/topicspdf/inspiron-15-3567-laptop_service-manual_pt-br.pdf",
]

# --- GUIDs de energia ---
PLANO_EQUILIBRADO = "381b4222-f694-41f0-9685-ff5bb260df2e"
MODO_MELHOR_DESEMPENHO = "ded574b5-45a0-4f42-8737-46345c09c238"
MODO_EQUILIBRADO = "00000000-0000-0000-0000-000000000000"
MODO_MELHOR_EFICIENCIA = "961cc777-2547-4f9d-8174-7d86181b8a7a"
SUB_VIDEO = "7516b95f-f776-4464-8c53-06167f40cc99"
VIDEOIDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"         # desligar video apos
VIDEODIM = "17aaa29b-8b43-4b94-aafe-35f64daaf1ee"          # esmaecer video apos
VIDEONORMALLEVEL = "aded5e82-b909-4619-9949-f5d71dac0bcb"  # brilho
ADAPTBRIGHT = "fbd9aa66-9553-4097-ba44-ed6e9d65eab8"       # brilho adaptavel
SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
STANDBYIDLE = "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"
HIBERNATEIDLE = "9d7815a6-7ee4-497e-8888-515a05f02364"
SUB_ENERGYSAVER = "de830923-a562-41af-a086-e3a2c6bad2da"
ESBATTTHRESHOLD = "e69653ca-cf7f-4f05-aa73-cb833fa90ad4"   # limite da Economia de energia

NOMES_MODO = {
    MODO_MELHOR_DESEMPENHO: "Melhor desempenho",
    MODO_EQUILIBRADO: "Equilibrado",
    MODO_MELHOR_EFICIENCIA: "Melhor eficiência energética",
}

# Ferramentas de captura exigidas no PATH (mesma orientacao do Modulo 1)
FERRAMENTAS_CAPTURA = {
    "wpr.exe": "Windows Performance Recorder (necessario para captura)",
    "wpaexporter.exe": "WPA Exporter (necessario para exportar CSV)",
}

# --- Arquivos de evidencia (em HUB_EVIDENCE_DIR) ---
ARQ_PREFLIGHT = "bateria_preflight.csv"
COLUNAS_PREFLIGHT = ["Item", "Esperado", "Antes", "Acao", "Depois", "Situacao", "Observacao"]

_exit_code = 1

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')

# --- INTEGRACAO COM O HARDWARE TEST HUB ---
HUB_EVIDENCE_DIR = os.environ.get("HUB_EVIDENCE_DIR")
OUTPUT_PATH = HUB_EVIDENCE_DIR or os.path.join(BASE_DIR, f"Traces_{SESSION_TIMESTAMP}")
os.makedirs(OUTPUT_PATH, exist_ok=True)

# =============================================================================
# LOGGING ESTRUTURADO
# =============================================================================
LOG_FILE = os.path.join(OUTPUT_PATH, f"teste_bateria_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("TesteBateria")
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter(
    "[%(asctime)s] [%(levelname)-7s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
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


_SIMBOLOS_LOG = str.maketrans({"≥": ">=", "≤": "<=", "→": "->", "≈": "~"})


def sem_acento(texto):
    """Remove acentos (os logs ficam sem acento, como nos demais testes).

    O hub le a saida por pipe (cp1252): simbolos fora dessa pagina viram ASCII.
    """
    texto = unicodedata.normalize("NFKD", str(texto).translate(_SIMBOLOS_LOG))
    return "".join(c for c in texto if not unicodedata.combining(c))


# =============================================================================
# MECANISMO DE PARADA SEGURA — Ctrl+Q (copiado de 1_automacao_performance.py)
# =============================================================================
_stop_requested = threading.Event()
_ctrl_pressed = False
_encerrar = threading.Event()   # encerramento controlado da medicao (primeiro motivo vence)


def _on_key_press(key):
    global _ctrl_pressed
    # Detectar Ctrl pressionado (esquerdo ou direito)
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = True
    # Se Ctrl esta seguro e 'q' foi pressionado → parada segura
    if _ctrl_pressed and hasattr(key, 'char') and key.char in ('q', 'Q', '\x11'):
        logger.warning("Parada segura solicitada pelo usuario (Ctrl+Q).")
        _stop_requested.set()


def solicitar_parada(origem):
    """Parada segura pedida fora do teclado (janela do monitor fechada, Ctrl+C no console)."""
    if not _stop_requested.is_set():
        logger.warning(f"Parada segura solicitada: {origem}.")
    _stop_requested.set()


def _on_key_release(key):
    global _ctrl_pressed
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = False


class PrazoDaFase(BaseException):
    """Prazo da fase de escritorio vencido: interrompe a acao em andamento.

    BaseException para atravessar os 'except Exception' do laco de acoes.
    """


_prazo_fase = {"fim": None}   # time.monotonic() do fim da fase de escritorio (so durante ela)


def check_stop():
    """Verifica se a parada segura (ou o encerramento da medicao) foi solicitada.

    Durante a fase de escritorio, levanta PrazoDaFase quando a duracao vence.
    """
    if _stop_requested.is_set():
        raise KeyboardInterrupt("Parada segura solicitada pelo usuario.")
    if _encerrar.is_set():
        raise KeyboardInterrupt("Encerramento da medicao solicitado.")
    fim = _prazo_fase["fim"]
    if fim is not None and time.monotonic() >= fim:
        raise PrazoDaFase()


def pausa(segundos):
    """time.sleep interrompivel por Ctrl+Q e pelo encerramento da medicao."""
    fim = time.monotonic() + segundos
    while True:
        check_stop()
        restante = fim - time.monotonic()
        if restante <= 0:
            return
        _encerrar.wait(min(0.5, restante))


# =============================================================================
# INTERFACE GRAFICA — overlay e janelas (somente na thread principal)
# =============================================================================
# tkinter nao e thread-safe: a worker nunca toca widgets. Ela deixa o texto do
# overlay e os pedidos de janela numa fila que a thread principal consome por
# root.after; quem espera uma resposta aguarda um threading.Event.
_INTERVALO_FILA_UI_MS = 500
FONTE_JANELA = ("Segoe UI", 11)
FONTE_JANELA_NEGRITO = ("Segoe UI", 11, "bold")


class _PedidoJanela:
    def __init__(self, construir):
        self.construir = construir      # construir(root, concluir) -> Toplevel
        self.evento = threading.Event()
        self.cancelar = threading.Event()
        self.resultado = None
        self.janela = None

    def concluir(self, resultado):
        if not self.evento.is_set():
            self.resultado = resultado
            self.evento.set()


class MonitorOverlay:
    # copiado de 1_automacao_performance.py (click-through), adaptado para
    # atualizar(fase, status, detalhe) e para a fila de janelas
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor do Teste de Bateria")

        # adaptado: o pyautogui deixa o processo ciente de DPI; escala a geometria
        escala = max(1.0, self.root.winfo_fpixels('1i') / 96.0)
        largura, altura = int(360 * escala), int(150 * escala)
        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"{largura}x{altura}+{largura_tela - largura - int(30 * escala)}+{int(30 * escala)}")
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#1e1e1e")

        # Tornar a janela click-through no Windows (cliques passam direto)
        self.root.update_idletasks()
        self._set_click_through()

        self.lbl_fase = tk.Label(
            self.root, text="Preparando...",
            fg="#00ff00", bg="#1e1e1e", font=("Segoe UI", 12, "bold")
        )
        self.lbl_fase.pack(pady=(10, 5))

        self.lbl_status = tk.Label(
            self.root, text="Iniciando o teste de bateria...",
            fg="white", bg="#1e1e1e", font=("Segoe UI", 10), wraplength=largura - int(20 * escala)
        )
        self.lbl_status.pack(pady=0)

        self.lbl_detalhe = tk.Label(
            self.root, text="",
            fg="#00d2ff", bg="#1e1e1e", font=("Consolas", 11)
        )
        self.lbl_detalhe.pack(pady=5)

        self.lbl_hotkey = tk.Label(
            self.root, text="Ctrl+Q para parada segura",
            fg="#666666", bg="#1e1e1e", font=("Segoe UI", 8)
        )
        self.lbl_hotkey.pack(pady=(0, 5))

        self._lock = threading.Lock()
        self._texto_pendente = None
        self._pedidos = queue.Queue()
        self._abertos = []
        self._fechar = False
        self.encerrada = threading.Event()
        # adaptado: fechar o monitor (barra de tarefas, Alt+F4) = parada segura; a janela
        # so sai com ui.fechar(), depois que a worker restaurou a maquina
        self.root.protocol("WM_DELETE_WINDOW", lambda: solicitar_parada("janela do monitor fechada pelo usuario"))
        self.root.after(_INTERVALO_FILA_UI_MS, self._processar)

    def _set_click_through(self):
        """Torna a janela transparente a cliques no Windows usando ctypes."""
        try:
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

    # --- chamados pela worker ---
    def atualizar(self, fase, status, detalhe=""):
        with self._lock:
            self._texto_pendente = (fase, status, detalhe)

    def pedir_janela(self, construir, esperar=True, timeout_s=None):
        """Pede uma janela a thread principal.

        esperar=True bloqueia ate a janela chamar concluir(resultado) e devolve
        o resultado; com timeout_s, fecha a janela e devolve 'tempo_esgotado'.
        Ctrl+Q fecha a janela e levanta a parada segura (check_stop).
        esperar=False devolve o pedido na hora (janela nao bloqueante).
        """
        pedido = _PedidoJanela(construir)
        self._pedidos.put(pedido)
        if not esperar:
            return pedido
        inicio = time.monotonic()
        while not pedido.evento.wait(0.5):
            if self.encerrada.is_set():
                return None
            if _stop_requested.is_set():
                pedido.cancelar.set()
                pedido.evento.wait(5)
                check_stop()
            if timeout_s is not None and time.monotonic() - inicio >= timeout_s:
                pedido.cancelar.set()
                pedido.evento.wait(5)
                return "tempo_esgotado"
        return pedido.resultado

    def fechar(self):
        self._fechar = True

    # --- thread principal ---
    def _processar(self):
        try:
            with self._lock:
                texto, self._texto_pendente = self._texto_pendente, None
            if texto:
                fase, status, detalhe = texto
                self.lbl_fase.config(text=fase)
                self.lbl_status.config(text=status)
                self.lbl_detalhe.config(text=detalhe)

            while True:
                try:
                    pedido = self._pedidos.get_nowait()
                except queue.Empty:
                    break
                try:
                    pedido.janela = pedido.construir(self.root, pedido.concluir)
                    self._abertos.append(pedido)
                except Exception as e:
                    logger.error(f"Falha ao abrir janela: {type(e).__name__}: {e}")
                    pedido.concluir(None)

            for pedido in list(self._abertos):
                if pedido.evento.is_set() or pedido.cancelar.is_set():
                    pedido.concluir(None)
                    try:
                        pedido.janela.destroy()
                    except Exception:
                        pass
                    self._abertos.remove(pedido)
        except Exception as e:
            logger.error(f"Falha na fila da interface: {type(e).__name__}: {e}")

        if self._fechar:
            self.encerrada.set()
            self.root.destroy()
            return
        self.root.after(_INTERVALO_FILA_UI_MS, self._processar)


def _nova_janela(root, titulo):
    """Toplevel padrao das janelas de aviso: sempre no topo, fonte legivel."""
    janela = tk.Toplevel(root)
    janela.title(titulo)
    janela.attributes('-topmost', True)
    janela.resizable(False, False)
    janela.configure(padx=24, pady=18)
    return janela


def _centralizar(janela):
    janela.update_idletasks()
    largura, altura = janela.winfo_reqwidth(), janela.winfo_reqheight()
    x = (janela.winfo_screenwidth() - largura) // 2
    y = (janela.winfo_screenheight() - altura) // 3
    janela.geometry(f"+{x}+{y}")
    janela.lift()
    janela.focus_force()


def mostrar_mensagem(ui, titulo, texto, timeout_s=None):
    """Janela com OK, criada pela thread principal; a worker espera o OK."""
    def construir(root, concluir):
        janela = _nova_janela(root, titulo)
        tk.Label(
            janela, text=texto, font=FONTE_JANELA, justify="left", wraplength=520
        ).pack(anchor="w")
        tk.Button(
            janela, text="OK", font=FONTE_JANELA_NEGRITO, width=14,
            command=lambda: concluir("ok")
        ).pack(pady=(16, 0))
        janela.protocol("WM_DELETE_WINDOW", lambda: concluir("ok"))
        _centralizar(janela)
        return janela

    logger.info(f"Janela exibida: {sem_acento(titulo)}")
    resultado = ui.pedir_janela(construir, timeout_s=timeout_s)
    if resultado == "tempo_esgotado":
        logger.warning(f"Janela '{sem_acento(titulo)}' fechada sem resposta apos {timeout_s}s.")
    return resultado


# =============================================================================
# UTILITARIOS DO SISTEMA
# =============================================================================
CREATE_NO_WINDOW = 0x08000000
_PS_PROLOGO = (
    "$ProgressPreference = 'SilentlyContinue'\n"
    "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n"
)


def _comando_ps(script):
    codificado = base64.b64encode((_PS_PROLOGO + script).encode("utf-16-le")).decode("ascii")
    return [
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado,
    ]


def executar_ps(script, timeout=60):
    """Executa um script PowerShell embutido. Retorna (rc, stdout, stderr) em UTF-8.

    rc = None quando o tempo esgota.
    """
    try:
        r = subprocess.run(
            _comando_ps(script), capture_output=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"PowerShell excedeu {timeout}s e foi encerrado.")
        return None, "", "tempo esgotado"
    return (
        r.returncode,
        r.stdout.decode("utf-8", "replace").strip(),
        r.stderr.decode("utf-8", "replace").strip(),
    )


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def status_energia():
    """GetSystemPowerStatus: fonte, BatteryFlag, carga (%) e Economia de energia."""
    st = _SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return {"fonte": "desconhecida", "bateria_flag": 255, "carga_pct": None,
                "economia_ligada": False}
    return {
        "fonte": {0: "bateria", 1: "tomada"}.get(st.ACLineStatus, "desconhecida"),
        "bateria_flag": st.BatteryFlag,                     # 128 = sem bateria, 255 = desconhecido
        "carga_pct": st.BatteryLifePercent if st.BatteryLifePercent <= 100 else None,
        "economia_ligada": st.SystemStatusFlag == 1,
    }


# =============================================================================
# REGISTRO DO PRE-VOO E PILHA DE RESTAURACAO
# =============================================================================
_preflight = []
_preflight_lock = threading.Lock()


def registrar_item(item, esperado, antes, acao, depois, situacao, observacao=""):
    """Registra (ou substitui) a linha de um item no bateria_preflight.csv."""
    linha = {
        "Item": item, "Esperado": esperado, "Antes": antes, "Acao": acao,
        "Depois": depois, "Situacao": situacao, "Observacao": observacao,
    }
    with _preflight_lock:
        for i, existente in enumerate(_preflight):
            if existente["Item"] == item:
                _preflight[i] = linha
                break
        else:
            _preflight.append(linha)
    nivel = logging.WARNING if situacao == "falhou" else logging.INFO
    logger.log(nivel, sem_acento(
        f"Pre-voo | {item}: esperado={esperado} | antes={antes} | acao={acao} | "
        f"depois={depois} | situacao={situacao}" + (f" | {observacao}" if observacao else "")
    ))


def itens_com_falha():
    with _preflight_lock:
        return [l for l in _preflight if l["Situacao"] == "falhou"]


def gravar_preflight_csv():
    caminho = os.path.join(OUTPUT_PATH, ARQ_PREFLIGHT)
    with _preflight_lock:
        linhas = list(_preflight)
    try:
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=COLUNAS_PREFLIGHT, delimiter=";")
            writer.writeheader()
            writer.writerows(linhas)
        logger.info(f"Pre-voo gravado: {caminho} ({len(linhas)} itens)")
        return True
    except OSError as e:
        logger.error(f"Falha ao gravar {ARQ_PREFLIGHT}: {e}")
        return False


_restauracoes = []
_restauracao_feita = False


def registrar_restauracao(descricao, funcao, na_bateria=False):
    """Empilha a volta de um ajuste. Deve ser chamada logo apos aplicar.

    na_bateria=True: a volta so funciona com a maquina na bateria; ela roda no
    encerramento da medicao, antes do aviso de reconexao (restaurar_na_bateria).
    """
    _restauracoes.append((descricao, funcao, na_bateria))
    logger.debug(f"Restauracao empilhada: {sem_acento(descricao)}")


def _executar_restauracao(descricao, funcao):
    try:
        funcao()
        logger.info(f"Restaurado: {sem_acento(descricao)}")
    except Exception as e:
        logger.error(f"Falha ao restaurar '{sem_acento(descricao)}': {type(e).__name__}: {e}")


def restaurar_na_bateria():
    """Fim da medicao, antes do aviso de reconexao: so as voltas que exigem a bateria (LIFO)."""
    for item in [r for r in reversed(_restauracoes) if r[2]]:
        _restauracoes.remove(item)
        _executar_restauracao(item[0], item[1])


def restaurar_tudo():
    """Desfaz os ajustes em ordem inversa (LIFO). Executa uma unica vez."""
    global _restauracao_feita
    if _restauracao_feita:
        return
    _restauracao_feita = True
    if not _restauracoes:
        logger.info("Restauracao: nenhuma configuracao foi alterada.")
        return
    logger.info(f"Restaurando {len(_restauracoes)} configuracao(oes) alterada(s)...")
    while _restauracoes:
        descricao, funcao, _ = _restauracoes.pop()
        _executar_restauracao(descricao, funcao)


# =============================================================================
# BATERIA — COLETOR POWERSHELL PERSISTENTE
# =============================================================================
# Um unico powershell.exe responde a um pedido por linha ('amostra', 'estatico'
# ou 'sair') com uma linha JSON: a inicializacao do PowerShell (~1-2 s de CPU)
# e paga uma vez no teste inteiro, e nao a cada amostra da fase ociosa.
# Varias baterias: os valores em mWh sao somados. Valor ausente = null.
_PS_COLETOR = r"""
$ErrorActionPreference = 'Stop'
function Valido($v) { return ($null -ne $v) -and ([long]$v -ge 0) -and ([long]$v -lt 2147483647) }
function Somar($objs, $campo) {
    $total = $null
    foreach ($o in $objs) {
        $v = $o.$campo
        if (Valido $v) { if ($null -eq $total) { $total = [long]0 }; $total += [long]$v }
    }
    return $total
}
function Primeiro($objs, $campo) {
    foreach ($o in $objs) { $v = $o.$campo; if (Valido $v) { return [long]$v } }
    return $null
}
function Ler($classe, $ns) { return @(Get-CimInstance -Namespace $ns -ClassName $classe -ErrorAction Stop) }
while ($true) {
    $pedido = [Console]::In.ReadLine()
    if ($null -eq $pedido -or $pedido.Trim() -eq 'sair') { break }
    try {
        switch ($pedido.Trim()) {
            'amostra' {
                $st = Ler 'BatteryStatus' 'root\wmi'
                $carga = $null
                try {
                    $wb = @(Ler 'Win32_Battery' 'root\cimv2')  # @(): o retorno da funcao desembrulha 1 item
                    if ($wb.Count -gt 0) { $carga = [int](($wb | Measure-Object -Property EstimatedChargeRemaining -Average).Average) }
                } catch {}
                $brilho = $null
                try {
                    $mon = @(Ler 'WmiMonitorBrightness' 'root\wmi' | Where-Object { $_.Active })
                    if ($mon.Count -gt 0) { $brilho = [int]$mon[0].CurrentBrightness }
                } catch {}
                $r = [ordered]@{ carga_pct = $carga; energia_mwh = (Somar $st 'RemainingCapacity');
                                 taxa_descarga_mw = (Somar $st 'DischargeRate'); tensao_mv = (Primeiro $st 'Voltage');
                                 brilho_pct = $brilho }
            }
            'estatico' {
                $cheia = $null; try { $cheia = Somar (Ler 'BatteryFullChargedCapacity' 'root\wmi') 'FullChargedCapacity' } catch {}
                $projeto = $null; try { $projeto = Somar (Ler 'BatteryStaticData' 'root\wmi') 'DesignedCapacity' } catch {}
                $ciclos = $null; try { $ciclos = Primeiro (Ler 'BatteryCycleCount' 'root\wmi') 'CycleCount' } catch {}
                $r = [ordered]@{ carga_cheia_mwh = $cheia; projeto_mwh = $projeto; ciclos = $ciclos }
            }
            default { $r = [ordered]@{ erro = "pedido desconhecido: $pedido" } }
        }
    } catch {
        $r = [ordered]@{ erro = $_.Exception.Message }
    }
    [Console]::Out.WriteLine(($r | ConvertTo-Json -Compress))
    [Console]::Out.Flush()
}
"""
CAMPOS_AMOSTRA = ("carga_pct", "energia_mwh", "taxa_descarga_mw", "tensao_mv", "brilho_pct")
CAMPOS_ESTATICO = ("carga_cheia_mwh", "projeto_mwh", "ciclos")


def _inteiro(valor):
    try:
        return None if valor is None else int(valor)
    except (TypeError, ValueError):
        return None


def interpretar_resposta(linha, campos):
    """Linha JSON do coletor -> dict com todos os campos (ausente = None) ou {'erro': ...}."""
    try:
        dados = json.loads(linha)
    except (TypeError, ValueError):
        return {"erro": f"resposta invalida do coletor: {str(linha)[:200]}"}
    if not isinstance(dados, dict):
        return {"erro": f"resposta invalida do coletor: {str(linha)[:200]}"}
    if dados.get("erro"):
        return {"erro": str(dados["erro"])}
    return {campo: _inteiro(dados.get(campo)) for campo in campos}


class ColetorBateria:
    """Processo PowerShell persistente que le a bateria pelo WMI (root\\wmi)."""

    def __init__(self, script=None):
        self._script = script or _PS_COLETOR
        self._proc = None
        self._fila = None
        self._lock = threading.Lock()

    def iniciar(self):
        self._proc = subprocess.Popen(
            _comando_ps(self._script), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        self._fila = queue.Queue()
        threading.Thread(target=self._ler, args=(self._proc, self._fila), daemon=True).start()
        logger.info(f"Coletor de bateria iniciado (PID {self._proc.pid}).")

    @staticmethod
    def _ler(proc, fila):
        try:
            for linha in proc.stdout:
                fila.put(linha.decode("utf-8", "replace").strip())
        except (OSError, ValueError):
            pass
        fila.put(None)

    def _pedir_uma_vez(self, pedido):
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("coletor nao esta em execucao")
        while True:  # descarta resposta atrasada de um pedido anterior
            try:
                self._fila.get_nowait()
            except queue.Empty:
                break
        self._proc.stdin.write((pedido + "\n").encode("ascii"))
        self._proc.stdin.flush()
        try:
            linha = self._fila.get(timeout=TIMEOUT_COLETOR_S)
        except queue.Empty:
            raise TimeoutError(f"sem resposta em {TIMEOUT_COLETOR_S}s")
        if linha is None:
            raise RuntimeError("coletor encerrou")
        return linha

    def pedir(self, pedido):
        """'amostra' ou 'estatico'. Reinicia o processo uma vez se ele morrer ou nao responder."""
        campos = CAMPOS_AMOSTRA if pedido == "amostra" else CAMPOS_ESTATICO
        with self._lock:
            for tentativa in (1, 2):
                try:
                    return interpretar_resposta(self._pedir_uma_vez(pedido), campos)
                except (OSError, RuntimeError, TimeoutError) as e:
                    if tentativa == 2:
                        logger.error(f"Coletor de bateria falhou de novo no pedido '{pedido}': {e}")
                        return {"erro": str(e)}
                    logger.warning(f"Coletor de bateria sem resposta ao pedido '{pedido}' ({e}). Reiniciando...")
                    self._encerrar_processo(educado=not isinstance(e, TimeoutError))
                    try:
                        self.iniciar()
                    except OSError as e2:
                        logger.error(f"Nao foi possivel reiniciar o coletor: {e2}")
                        return {"erro": str(e2)}

    def _encerrar_processo(self, educado=True):
        """educado=False: processo travado nao le o 'sair' — encerra direto."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.poll() is None and not educado:
            proc.kill()
        if proc.poll() is None:
            try:
                proc.stdin.write(b"sair\n")
                proc.stdin.flush()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Coletor (PID {proc.pid}) nao encerrou apos kill.")
        try:
            proc.stdin.close()
        except OSError:
            pass

    def fechar(self):
        with self._lock:
            ativo = self._proc is not None
            self._encerrar_processo()
        if ativo:
            logger.info("Coletor de bateria encerrado.")


# =============================================================================
# MODO DE ENERGIA (powrprof via ctypes)
# =============================================================================
# O powercfg nao tem comando para o modo de energia (overlay). PowerGet/Set-
# UserConfiguredDCPowerMode nao sao documentadas: a exportacao e checada antes.
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(texto):
    return GUID.from_buffer_copy(uuid.UUID(texto).bytes_le)


def _texto_guid(g):
    return str(uuid.UUID(bytes_le=bytes(g)))


_powrprof = ctypes.WinDLL("powrprof.dll")


def api_modo_dc_disponivel():
    return (hasattr(_powrprof, "PowerGetUserConfiguredDCPowerMode")
            and hasattr(_powrprof, "PowerSetUserConfiguredDCPowerMode"))


def modo_efetivo():
    """Modo de energia em vigor agora (depende da fonte atual)."""
    g = GUID()
    rc = _powrprof.PowerGetEffectiveOverlayScheme(ctypes.byref(g))
    return _texto_guid(g) if rc == 0 else None


def modo_dc_configurado():
    """Modo que o Windows aplica na bateria."""
    if not api_modo_dc_disponivel():
        return None
    g = GUID()
    rc = _powrprof.PowerGetUserConfiguredDCPowerMode(ctypes.byref(g))
    return _texto_guid(g) if rc == 0 else None


def definir_modo_dc(guid):
    rc = _powrprof.PowerSetUserConfiguredDCPowerMode(ctypes.byref(_guid(guid)))
    if rc != 0:
        raise OSError(f"PowerSetUserConfiguredDCPowerMode retornou {rc}")


def definir_overlay_ativo(guid):
    """Fallback sem a API DC: aplica o modo na fonte atual (usado ja na bateria)."""
    funcao = _powrprof.PowerSetActiveOverlayScheme
    funcao.argtypes = [GUID]
    funcao.restype = wintypes.DWORD
    rc = funcao(_guid(guid))
    if rc != 0:
        raise OSError(f"PowerSetActiveOverlayScheme retornou {rc}")


def nome_modo(guid):
    if not guid:
        return "desconhecido"
    return NOMES_MODO.get(guid.lower(), guid)


# =============================================================================
# POWERCFG E RELATORIO DE BATERIA
# =============================================================================
def _powercfg(args, timeout=120):
    """Executa powercfg. Retorna (rc, saida); rc = None quando o tempo esgota."""
    logger.debug("powercfg " + " ".join(args))
    try:
        r = subprocess.run(
            ["powercfg"] + list(args), capture_output=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"powercfg {args[0]} excedeu {timeout}s.")
        return None, ""
    except OSError as e:
        logger.warning(f"powercfg {args[0]} falhou: {e}")
        return None, ""
    saida = (r.stdout + r.stderr).decode("oem", "replace").strip()
    return r.returncode, saida


def gerar_relatorio_bateria(sufixo, xml=False):
    """powercfg /batteryreport em HTML (e XML). Falha = aviso no log."""
    gerados = {}
    formatos = [("html", [])] + ([("xml", ["/xml"])] if xml else [])
    for extensao, extra in formatos:
        caminho = os.path.join(OUTPUT_PATH, f"bateria_relatorio_{sufixo}.{extensao}")
        rc, saida = _powercfg(["/batteryreport"] + extra + ["/output", caminho])
        if os.path.exists(caminho):
            gerados[extensao] = caminho
            logger.info(f"Relatorio de bateria '{sufixo}' ({extensao}): {caminho}")
        else:
            logger.warning(f"Relatorio de bateria '{sufixo}' ({extensao}) nao gerado (rc={rc}): "
                           f"{sem_acento(saida)[:200]}")
    return gerados


def ler_estatico_xml(caminho):
    """DesignCapacity, FullChargeCapacity e CycleCount do XML do relatorio de bateria."""
    dados = {"carga_cheia_mwh": None, "projeto_mwh": None, "ciclos": None}
    try:
        raiz = ET.parse(caminho).getroot()
    except (OSError, ET.ParseError) as e:
        logger.warning(f"Relatorio de bateria XML ilegivel ({caminho}): {e}")
        return dados
    for bateria in (el for el in raiz.iter() if el.tag.rsplit("}", 1)[-1] == "Battery"):
        valores = {filho.tag.rsplit("}", 1)[-1]: (filho.text or "").strip() for filho in bateria}
        for campo, tag, somar in (("projeto_mwh", "DesignCapacity", True),
                                  ("carga_cheia_mwh", "FullChargeCapacity", True),
                                  ("ciclos", "CycleCount", False)):
            valor = _inteiro(valores.get(tag) or None)
            if valor is None:
                continue
            if dados[campo] is None:
                dados[campo] = valor
            elif somar:
                dados[campo] += valor
    return dados


def dados_estaticos(coletor, caminho_xml=None):
    """Carga cheia, capacidade de projeto e ciclos: coletor; nulos vem do XML 'antes'."""
    dados = coletor.pedir("estatico")
    if dados.get("erro"):
        logger.warning(f"Dados estaticos da bateria pelo WMI falharam: {dados['erro']}")
        dados = {campo: None for campo in CAMPOS_ESTATICO}
    faltando = [campo for campo in CAMPOS_ESTATICO if dados.get(campo) is None]
    if faltando and caminho_xml and os.path.exists(caminho_xml):
        xml = ler_estatico_xml(caminho_xml)
        for campo in faltando:
            if xml.get(campo) is not None:
                dados[campo] = xml[campo]
                logger.info(f"{campo} lido do relatorio de bateria: {xml[campo]}")
    logger.info(f"Bateria: carga cheia={dados['carga_cheia_mwh']} mWh | "
                f"projeto={dados['projeto_mwh']} mWh | ciclos={dados['ciclos']}")
    return dados


# --- Plano de energia e indices por fonte (AC/DC) ---
# A leitura usa /qh (mostra tambem as configuracoes ocultas, como VIDEODIM e
# ESBATTTHRESHOLD) e os indices hexadecimais, que nao mudam com o idioma.
_RE_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_RE_INDICE = re.compile(r"0x([0-9a-fA-F]{8})")
_CHAVE_POLITICA = r"SOFTWARE\Policies\Microsoft\Power\PowerSettings"


def plano_ativo():
    """(GUID, nome) do plano ativo; (None, None) se ilegivel."""
    rc, saida = _powercfg(["/getactivescheme"], timeout=30)
    achado = _RE_GUID.search(saida) if rc == 0 else None
    if not achado:
        return None, None
    nome = re.search(r"\(([^)]*)\)\s*$", saida)
    return achado.group(0).lower(), (nome.group(1).strip() if nome else None)


def definir_plano(guid):
    rc, saida = _powercfg(["/setactive", guid], timeout=30)
    if rc != 0:
        raise OSError(f"powercfg /setactive {guid} falhou: {sem_acento(saida)[:200]}")


def interpretar_qh(saida):
    """(AC, DC): as duas ultimas ocorrencias de 0x######## na saida do /qh.

    Configuracoes de faixa trazem minimo, maximo e incremento antes; os indices
    atuais sao sempre as duas ultimas linhas. None se nao houver os dois valores.
    """
    valores = _RE_INDICE.findall(saida or "")
    if len(valores) < 2:
        return None
    return int(valores[-2], 16), int(valores[-1], 16)


def ler_indices(sub, cfg):
    """(AC, DC) do plano atual; None se a configuracao nao existir.

    Sem resposta do powercfg (tempo esgotado, erro ao executar) ou saida sem os
    indices: OSError — e falha de leitura, nao configuracao inexistente.
    """
    rc, saida = _powercfg(["/qh", "SCHEME_CURRENT", sub, cfg], timeout=30)
    if rc is None:
        raise OSError("leitura do powercfg falhou (tempo esgotado ou erro ao executar)")
    if rc != 0:
        return None
    indices = interpretar_qh(saida)
    if indices is None:
        raise OSError("saída do powercfg /qh sem os índices atuais")
    return indices


def ler_indice_dc(sub, cfg):
    indices = ler_indices(sub, cfg)
    return None if indices is None else indices[1]


def definir_indice(sub, cfg, valor, fonte="dc"):
    """Grava o indice de bateria (dc) ou de tomada (ac) e reaplica o plano atual."""
    opcao = "/setdcvalueindex" if fonte == "dc" else "/setacvalueindex"
    rc, saida = _powercfg([opcao, "SCHEME_CURRENT", sub, cfg, str(int(valor))], timeout=30)
    if rc != 0:
        raise OSError(f"powercfg {opcao} {cfg} falhou: {sem_acento(saida)[:200]}")
    rc, saida = _powercfg(["/setactive", "SCHEME_CURRENT"], timeout=30)
    if rc != 0:
        raise OSError(f"powercfg /setactive SCHEME_CURRENT falhou: {sem_acento(saida)[:200]}")


def _ler_registro_hklm(subchave, valor):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subchave, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as chave:
            return winreg.QueryValueEx(chave, valor)[0]
    except OSError:
        return None


def politica(cfg):
    """Indices impostos por GPO para a configuracao ({'dc': .., 'ac': ..}) ou None."""
    subchave = _CHAVE_POLITICA + "\\" + cfg
    valores = {}
    for fonte, nome in (("dc", "DCSettingIndex"), ("ac", "ACSettingIndex")):
        bruto = _ler_registro_hklm(subchave, nome)
        valores[fonte] = _inteiro(bruto)
    return valores if any(v is not None for v in valores.values()) else None


def politica_plano():
    """GUID do plano imposto por GPO (ActivePowerScheme) ou None."""
    bruto = _ler_registro_hklm(_CHAVE_POLITICA, "ActivePowerScheme")
    return str(bruto).strip("{} ").lower() if bruto else None


# =============================================================================
# PRE-VOO — CHECAGENS RAPIDAS (nao alteram nada)
# =============================================================================
def _contar_baterias_wmi():
    rc, saida, erro = executar_ps(
        "@(Get-CimInstance -ClassName Win32_Battery -ErrorAction SilentlyContinue).Count",
        timeout=30
    )
    try:
        return int(saida.splitlines()[-1])
    except (ValueError, IndexError):
        logger.warning(f"Contagem de Win32_Battery ilegivel (rc={rc}): {saida} {erro}")
        return None


def caminho_perfil_wpa():
    """Perfil WPA de bateria na pasta do teste (aceita tambem o nome com .xml)."""
    for nome in (PROFILE_NAME, PROFILE_NAME + ".xml"):
        caminho = os.path.join(BASE_DIR, nome)
        if os.path.exists(caminho):
            return caminho
    return None


def _falha_rapida(ui, item, esperado, antes, mensagem, observacao=""):
    registrar_item(item, esperado, antes, "conferido", antes, "falhou", observacao)
    logger.error(sem_acento(mensagem))
    ui.atualizar("Pré-voo: teste não iniciado", mensagem, "Veja o log")
    gravar_preflight_csv()
    return False


def checagens_rapidas(ui):
    """Bateria presente -> carga minima -> ferramentas no PATH -> perfil WPA."""
    ui.atualizar("Pré-voo", "Conferindo bateria e ferramentas de captura...")
    st = status_energia()

    # 1. Bateria presente (desktop: BatteryFlag 128, sem nenhuma consulta extra)
    flag = st["bateria_flag"]
    item = "Bateria presente"
    if flag in (128, 255):
        return _falha_rapida(
            ui, item, "sim", f"não (BatteryFlag {flag})",
            "Este teste exige um notebook com bateria reconhecida pelo Windows. "
            "Nenhuma configuração foi alterada.",
            "sem bateria" if flag == 128 else "estado da bateria desconhecido",
        )
    baterias = _contar_baterias_wmi()
    if not baterias:
        return _falha_rapida(
            ui, item, "sim", "não (Win32_Battery ausente)",
            "Este teste exige um notebook com bateria reconhecida pelo Windows. "
            "Nenhuma configuração foi alterada.",
            "Win32_Battery nao retornou bateria",
        )
    registrar_item(item, "sim", "sim", "conferido", "sim", "ok",
                   f"{baterias} bateria(s) no Win32_Battery")

    # 2. Carga inicial minima
    item = "Carga inicial"
    carga = st["carga_pct"]
    esperado = f"≥ {CARGA_INICIAL_MIN_PCT}%"
    if carga is None or carga < CARGA_INICIAL_MIN_PCT:
        atual = "desconhecida" if carga is None else f"{carga}%"
        return _falha_rapida(
            ui, item, esperado, atual,
            f"Carga da bateria em {atual}; o mínimo para iniciar é {CARGA_INICIAL_MIN_PCT}%. "
            "Carregue a bateria na tomada e execute o teste novamente.",
        )
    registrar_item(item, esperado, f"{carga}%", "conferido", f"{carga}%", "ok",
                   f"fonte: {st['fonte']}")

    # 3. Ferramentas de captura no PATH
    item = "Ferramentas de captura"
    esperado = "wpr.exe e wpaexporter.exe no PATH"
    faltando = [exe for exe in FERRAMENTAS_CAPTURA if shutil.which(exe) is None]
    perfil = caminho_perfil_wpa()
    obs_perfil = "" if perfil else f"perfil WPA {PROFILE_NAME} ausente: exportacao CSV sera ignorada"
    if faltando:
        for exe in faltando:
            logger.error(f"PRE-REQUISITO FALTANDO: '{exe}' nao encontrado no PATH — {FERRAMENTAS_CAPTURA[exe]}")
        return _falha_rapida(
            ui, item, esperado, "ausente: " + ", ".join(faltando),
            "Ferramentas de captura não encontradas no PATH: " + ", ".join(faltando) +
            ". Instale o Windows Performance Toolkit (o mesmo do Módulo 1) e inclua-o no PATH.",
            obs_perfil,
        )
    registrar_item(item, esperado, "encontradas", "conferido", "encontradas", "ok", obs_perfil)

    # 4. Perfil WPA: ausente = so aviso (exportacao sera pulada)
    if perfil:
        logger.info(f"Perfil WPA: {perfil}")
    else:
        logger.warning(f"Profile WPA '{PROFILE_NAME}' nao encontrado em '{BASE_DIR}'. "
                       "A exportacao CSV sera ignorada.")
    return True


# =============================================================================
# PRE-VOO — CONFERIDOS (rede e monitor externo, antes de qualquer ajuste)
# =============================================================================
_PS_REDE = r"""
$perfis = @()
foreach ($p in @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)) {
    $ad = Get-NetAdapter -InterfaceIndex $p.InterfaceIndex -ErrorAction SilentlyContinue
    $perfis += [ordered]@{ nome = "$($p.Name)"; alias = "$($p.InterfaceAlias)";
                           ipv4 = "$($p.IPv4Connectivity)"; ipv6 = "$($p.IPv6Connectivity)";
                           meio = "$($ad.PhysicalMediaType)" }
}
$wlan = ''
try { $wlan = (netsh wlan show interfaces) -join "`n" } catch {}
[ordered]@{ perfis = $perfis; wlan = $wlan } | ConvertTo-Json -Compress -Depth 4
"""
_RE_SSID = re.compile(r"^\s*SSID\s*:\s*(.*?)\s*$", re.M)
_RE_SINAL = re.compile(r"(\d{1,3})\s*%")


def interpretar_wlan(texto):
    """(SSID, sinal) do 'netsh wlan show interfaces'; None quando nao informado."""
    texto = texto or ""
    ssid = _RE_SSID.search(texto)
    sinal = _RE_SINAL.search(texto)
    return ((ssid.group(1) or None) if ssid else None,
            f"{sinal.group(1)}%" if sinal else None)


def _tipo_conexao(perfil):
    meio = (perfil.get("meio") or "").lower()
    if "802.11" in meio:
        return "Wi-Fi"
    if "802.3" in meio:
        return "Ethernet"
    return perfil.get("alias") or perfil.get("meio") or "desconhecido"


def conferir_rede():
    """Conexao com acesso a internet pelo perfil de rede do Windows (nao altera nada)."""
    item, esperado = "Conexão de rede", "com acesso à internet"
    rc, saida, erro = executar_ps(_PS_REDE, timeout=60)
    try:
        dados = json.loads(saida) if saida else {}
    except ValueError:
        dados = {}
    perfis = dados.get("perfis") or []
    if isinstance(perfis, dict):
        perfis = [perfis]
    com_internet = [p for p in perfis if "Internet" in (p.get("ipv4"), p.get("ipv6"))]
    escolhido = (com_internet or perfis or [None])[0]
    if escolhido is None:
        registrar_item(item, esperado, "sem conexão", "conferido", "sem conexão", "falhou",
                       "nenhum perfil de rede conectado" + (f" ({sem_acento(erro)[:120]})" if erro else ""))
        return "falhou"
    tipo = _tipo_conexao(escolhido)
    ssid, sinal = interpretar_wlan(dados.get("wlan")) if tipo == "Wi-Fi" else (None, None)
    texto = f"{tipo} | {ssid or escolhido.get('nome') or 'indisponível'} | {sinal or 'indisponível'}"
    if com_internet:
        registrar_item(item, esperado, texto, "conferido", texto, "ok",
                       f"perfil {escolhido.get('nome')}: IPv4 {escolhido.get('ipv4')}, IPv6 {escolhido.get('ipv6')}")
        return "ok"
    registrar_item(item, esperado, texto, "conferido", texto, "falhou",
                   "sem acesso à internet: conecte a rede e execute o teste novamente")
    return "falhou"


# Tecnologias de saida de video internas (WmiMonitorConnectionParams)
_SAIDAS_INTERNAS = {0x80000000, 6, 11, 13}   # interna, LVDS, eDP, UDI embutido
_NOMES_SAIDA = {0: "VGA", 4: "DVI", 5: "HDMI", 10: "DisplayPort", 12: "UDI", 15: "Miracast"}


def conferir_monitor():
    """Nenhum monitor externo: 1 monitor no desktop e toda saida ativa interna."""
    item, esperado = "Monitor externo", "nenhum"
    quantidade = ctypes.windll.user32.GetSystemMetrics(80)  # SM_CMONITORS
    rc, saida, _ = executar_ps(
        "Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorConnectionParams "
        "-ErrorAction SilentlyContinue | Where-Object { $_.Active } | "
        "ForEach-Object { [uint32]$_.VideoOutputTechnology }", timeout=30
    )
    tecnologias = [int(x) for x in saida.split() if x.strip().lstrip("-").isdigit()]
    externas = [t for t in tecnologias if t not in _SAIDAS_INTERNAS]
    obs = f"{quantidade} monitor(es) no desktop; saídas ativas: " + (
        ", ".join(hex(t) if t > 255 else str(t) for t in tecnologias) or "indisponível")
    if quantidade == 1 and not externas:
        registrar_item(item, esperado, "nenhum", "conferido", "nenhum", "ok", obs)
        return "ok"
    nomes = ", ".join(_NOMES_SAIDA.get(t, f"tipo {t}") for t in externas) or "monitor adicional"
    texto = f"conectado ({nomes})"
    registrar_item(item, esperado, texto, "conferido", texto, "falhou",
                   "monitor externo conectado: desconecte-o e execute o teste novamente; " + obs)
    return "falhou"


# =============================================================================
# PRE-VOO — AJUSTES (aplicar, reler e registrar; cada ajuste empilha a volta)
# =============================================================================
def _fmt_segundos(valor):
    if valor is None:
        return "ilegível"
    return "nunca" if valor == 0 else f"{valor} s"


def _fmt_pct(valor):
    return "ilegível" if valor is None else f"{valor}%"


def _fmt_ligado(valor):
    return {0: "desligado", 1: "ligado"}.get(valor, "ilegível" if valor is None else str(valor))


def ajustar_item(item, esperado, ler, aplicar, restaurar, formatar, bloqueio=None):
    """Le 'antes'; igual -> ok; diferente -> aplica, empilha a restauracao e rele.

    bloqueio(): texto quando uma politica impoe outro valor (o teste nao a contorna).
    Retorna a situacao registrada: ok | ajustado | falhou.
    """
    esperado_txt = formatar(esperado)
    try:
        antes = ler()
    except Exception as e:
        registrar_item(item, esperado_txt, "ilegível", "nenhuma", "ilegível", "falhou",
                       f"leitura falhou: {e}")
        return "falhou"
    antes_txt = formatar(antes)
    motivo = bloqueio() if bloqueio else None
    if motivo:
        registrar_item(item, esperado_txt, antes_txt, "nenhuma", antes_txt, "falhou", motivo)
        return "falhou"
    if antes == esperado:
        registrar_item(item, esperado_txt, antes_txt, "nenhuma", antes_txt, "ok")
        return "ok"

    erro = None
    try:
        aplicar()
    except Exception as e:
        erro = e
    finally:
        # empilhada antes de reler: mesmo um ajuste parcial e desfeito no fim
        registrar_restauracao(f"{item} -> {antes_txt}", lambda: restaurar(antes))
    try:
        depois = ler()
    except Exception:
        depois = None
    depois_txt = formatar(depois)
    if erro is None and depois == esperado:
        registrar_item(item, esperado_txt, antes_txt, "ajustado", depois_txt, "ajustado")
        return "ajustado"
    obs = f"ajuste falhou: {erro}" if erro else "valor relido diferente do esperado"
    registrar_item(item, esperado_txt, antes_txt, "ajustado", depois_txt, "falhou", obs)
    return "falhou"


def _bloqueio_politica(cfg, fonte, esperado, formatar):
    imposto = (politica(cfg) or {}).get(fonte)
    if imposto is not None and imposto != esperado:
        return f"bloqueado por política (valor imposto: {formatar(imposto)})"
    return None


def _ajustar_indice_dc(item, sub, cfg, esperado, formatar):
    """Configuracao de bateria (DC) do plano atual no valor esperado."""
    try:
        existe = ler_indices(sub, cfg) is not None
    except OSError as e:
        registrar_item(item, formatar(esperado), "ilegível", "nenhuma", "ilegível", "falhou", str(e))
        return "falhou"
    if not existe:
        registrar_item(item, formatar(esperado), "inexistente", "nenhuma", "inexistente",
                       "não aplicável", "configuração não existe no plano de energia")
        return "não aplicável"
    return ajustar_item(
        item, esperado,
        ler=lambda: ler_indice_dc(sub, cfg),
        aplicar=lambda: definir_indice(sub, cfg, esperado, "dc"),
        restaurar=lambda valor: definir_indice(sub, cfg, valor, "dc"),
        formatar=formatar,
        bloqueio=lambda: _bloqueio_politica(cfg, "dc", esperado, formatar),
    )


def ajustar_plano():
    nomes = {}

    def ler():
        guid, nome = plano_ativo()
        if guid:
            nomes[guid] = nome
        return guid

    def formatar(guid):
        if guid == PLANO_EQUILIBRADO:
            return "Equilibrado"
        return nomes.get(guid) or guid or "ilegível"

    def bloqueio():
        imposto = politica_plano()
        if imposto and imposto != PLANO_EQUILIBRADO:
            return f"bloqueado por política (plano imposto: {formatar(imposto)})"
        return None

    return ajustar_item("Plano de energia", PLANO_EQUILIBRADO, ler,
                        lambda: definir_plano(PLANO_EQUILIBRADO), definir_plano, formatar, bloqueio)


def ajustar_modo_dc():
    item = "Modo de energia na bateria"
    if not api_modo_dc_disponivel():
        registrar_item(item, "Melhor desempenho", "indisponível", "adiado para a estabilização",
                       "indisponível", "ok",
                       "API do modo de energia na bateria ausente nesta versão do Windows; "
                       "o modo será aplicado e conferido já na bateria")
        return "ok"
    return ajustar_item(item, MODO_MELHOR_DESEMPENHO, modo_dc_configurado,
                        lambda: definir_modo_dc(MODO_MELHOR_DESEMPENHO), definir_modo_dc, nome_modo)


def ajustar_economia():
    """Economia de energia desligada e sem acionamento automatico (limite DC = 0).

    Se continuar ligada na tomada, tambem o limite AC = 0. Ligada manualmente
    (limites ja em 0) = falhou: o operador desliga nas Configuracoes.
    """
    item = "Economia de energia"
    esperado = "desligada, limite 0%"

    def texto(ligada, limite):
        return f"{'ligada' if ligada else 'desligada'}, limite {_fmt_pct(limite)}"

    ligada = status_energia()["economia_ligada"]
    try:
        indices = ler_indices(SUB_ENERGYSAVER, ESBATTTHRESHOLD)
    except OSError as e:
        registrar_item(item, esperado, "ilegível", "nenhuma", "ilegível", "falhou", str(e))
        return "falhou"
    if indices is None:
        situacao = "falhou" if ligada else "não aplicável"
        estado = "ligada" if ligada else "desligada"
        registrar_item(item, esperado, estado, "nenhuma", estado, situacao,
                       "limite de acionamento inexistente no plano de energia"
                       + ("; Economia ligada: desligue-a nas Configurações do Windows" if ligada else ""))
        return situacao
    ac_antes, dc_antes = indices
    antes_txt = texto(ligada, dc_antes)
    motivo = _bloqueio_politica(ESBATTTHRESHOLD, "dc", 0, _fmt_pct)
    if motivo:
        registrar_item(item, esperado, antes_txt, "nenhuma", antes_txt, "falhou", motivo)
        return "falhou"

    alterou, obs = False, ""
    try:
        if dc_antes != 0:
            alterou = True
            try:
                definir_indice(SUB_ENERGYSAVER, ESBATTTHRESHOLD, 0, "dc")
            finally:
                registrar_restauracao(f"{item}: limite na bateria -> {dc_antes}%",
                                      lambda: definir_indice(SUB_ENERGYSAVER, ESBATTTHRESHOLD, dc_antes, "dc"))
        if status_energia()["economia_ligada"] and ac_antes != 0:
            alterou = True
            try:
                definir_indice(SUB_ENERGYSAVER, ESBATTTHRESHOLD, 0, "ac")
            finally:
                registrar_restauracao(f"{item}: limite na tomada -> {ac_antes}%",
                                      lambda: definir_indice(SUB_ENERGYSAVER, ESBATTTHRESHOLD, ac_antes, "ac"))
            time.sleep(2)
    except OSError as e:
        obs = f"ajuste falhou: {e}"

    try:
        indices = ler_indices(SUB_ENERGYSAVER, ESBATTTHRESHOLD)
    except OSError as e:
        indices, obs = None, obs or str(e)
    dc_depois = None if indices is None else indices[1]
    ligada_depois = status_energia()["economia_ligada"]
    depois_txt = texto(ligada_depois, dc_depois)
    if not obs and dc_depois == 0 and not ligada_depois:
        situacao = "ajustado" if alterou else "ok"
        registrar_item(item, esperado, antes_txt, "ajustado" if alterou else "nenhuma", depois_txt, situacao)
        return situacao
    if not obs:
        obs = ("Economia ligada manualmente: desligue-a nas Configurações do Windows (Sistema > Energia)"
               if ligada_depois else "valor relido diferente do esperado")
    registrar_item(item, esperado, antes_txt, "ajustado" if alterou else "nenhuma", depois_txt, "falhou", obs)
    return "falhou"


def ajustar_esmaecimento():
    return _ajustar_indice_dc("Esmaecimento da tela na bateria", SUB_VIDEO, VIDEODIM, 0, _fmt_segundos)


def ajustar_suspensao():
    return _ajustar_indice_dc("Suspensão na bateria", SUB_SLEEP, STANDBYIDLE, 0, _fmt_segundos)


def ajustar_hibernacao():
    return _ajustar_indice_dc("Hibernação na bateria", SUB_SLEEP, HIBERNATEIDLE, 0, _fmt_segundos)


def ajustar_desligar_video():
    return _ajustar_indice_dc("Desligar vídeo na bateria", SUB_VIDEO, VIDEOIDLE, 0, _fmt_segundos)


# --- Brilho ---
def brilho_atual():
    """Brilho efetivo (%) do monitor ativo, pelo WMI; None se indisponivel."""
    rc, saida, _ = executar_ps(
        "@(Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorBrightness -ErrorAction Stop "
        "| Where-Object { $_.Active })[0].CurrentBrightness", timeout=30
    )
    return _inteiro(saida.splitlines()[-1]) if rc == 0 and saida else None


def aplicar_brilho(pct):
    """WmiSetBrightness no monitor interno (muda o brilho da fonte atual)."""
    rc, saida, erro = executar_ps(
        "$m = @(Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop)[0]\n"
        f"Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness "
        f"-Arguments @{{ Timeout = [uint32]0; Brightness = [byte]{int(pct)} }} -ErrorAction Stop | Out-Null",
        timeout=30
    )
    if rc != 0:
        raise OSError(f"WmiSetBrightness falhou: {sem_acento(erro)[:200]}")


def ajustar_brilho_dc():
    """Brilho de bateria (VIDEONORMALLEVEL DC) = 50%.

    Antes, empilha a volta do brilho efetivo: roda depois da volta do indice
    (LIFO) e garante que a tela termine no brilho original da fonte em uso.
    """
    item = "Brilho na bateria"
    original_ac = brilho_atual() if status_energia()["fonte"] == "tomada" else None
    try:
        indices = ler_indices(SUB_VIDEO, VIDEONORMALLEVEL)
    except OSError:
        indices = None   # _ajustar_indice_dc registra a falha de leitura
    original_ac_indice, original_dc = indices if indices else (None, None)

    def voltar_brilho_efetivo():
        # O WmiSetBrightness grava o brilho da fonte em uso no plano: se ele
        # rodou na tomada, o indice AC tambem precisa voltar.
        try:
            atuais = ler_indices(SUB_VIDEO, VIDEONORMALLEVEL)
        except OSError as e:
            atuais = None
            logger.warning(f"Brilho na tomada (indice AC) nao conferido: {sem_acento(e)}")
        if original_ac_indice is not None and atuais and atuais[0] != original_ac_indice:
            definir_indice(SUB_VIDEO, VIDEONORMALLEVEL, original_ac_indice, "ac")
            logger.info(f"Brilho na tomada (indice AC) {atuais[0]}% -> {original_ac_indice}%")
        fonte = status_energia()["fonte"]
        alvo = original_ac if fonte == "tomada" else original_dc
        atual = brilho_atual()
        if alvo is not None and atual is not None and atual != alvo:
            aplicar_brilho(alvo)
            logger.info(f"Brilho efetivo {atual}% -> {alvo}% ({fonte})")

    if original_ac is not None or original_dc is not None:
        registrar_restauracao(
            f"Brilho efetivo -> {_fmt_pct(original_ac)} na tomada / {_fmt_pct(original_dc)} na bateria",
            voltar_brilho_efetivo)
    return _ajustar_indice_dc(item, SUB_VIDEO, VIDEONORMALLEVEL, BRILHO_PADRAO_PCT, _fmt_pct)


# --- Brilho adaptavel (so existe com sensor de luz ambiente) ---
def tem_sensor_luz():
    rc, saida, erro = executar_ps(
        "[Windows.Devices.Sensors.LightSensor, Windows.Devices.Sensors, ContentType = WindowsRuntime] | Out-Null\n"
        "if ($null -eq [Windows.Devices.Sensors.LightSensor]::GetDefault()) { 'sem_sensor' } else { 'com_sensor' }",
        timeout=30
    )
    if rc != 0 or saida not in ("sem_sensor", "com_sensor"):
        raise OSError(f"deteccao do sensor de luz falhou: {sem_acento(erro or saida)[:200]}")
    return saida == "com_sensor"


def ajustar_brilho_adaptavel():
    item = "Brilho adaptável na bateria"
    try:
        sensor = tem_sensor_luz()
    except OSError as e:
        registrar_item(item, "desligado", "ilegível", "nenhuma", "ilegível", "falhou", str(e))
        return "falhou"
    if not sensor:
        registrar_item(item, "desligado", "sem sensor de luz", "nenhuma", "sem sensor de luz",
                       "não aplicável", "máquina sem sensor de luz ambiente")
        return "não aplicável"
    return _ajustar_indice_dc(item, SUB_VIDEO, ADAPTBRIGHT, 0, _fmt_ligado)


# --- Bluetooth (Windows.Devices.Radios, o mesmo controle do botao do Windows) ---
_PS_RADIOS = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$tipo) {
    $task = $asTask.MakeGenericMethod($tipo).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
$tipoLista = [System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]]
$tipoAcesso = [Windows.Devices.Radios.RadioAccessStatus]
$acesso = Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) $tipoAcesso
$bt = @(Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) $tipoLista | Where-Object { "$($_.Kind)" -eq 'Bluetooth' })
$acao = '__ACAO__'
$resultado = ''
if ($acao -ne 'ler') {
    foreach ($r in $bt) { $resultado = "$(Await ($r.SetStateAsync([Windows.Devices.Radios.RadioState]::$acao)) $tipoAcesso)" }
    Start-Sleep -Seconds 2
    $bt = @(Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) $tipoLista | Where-Object { "$($_.Kind)" -eq 'Bluetooth' })
}
[ordered]@{ acesso = "$acesso"; estados = @($bt | ForEach-Object { "$($_.State)" }); resultado = $resultado } | ConvertTo-Json -Compress
"""


def radios_bluetooth(acao="ler"):
    """acao: 'ler', 'Off' ou 'On'. Retorna {acesso, estados, resultado} ou {'erro': ...}."""
    rc, saida, erro = executar_ps(_PS_RADIOS.replace("__ACAO__", acao), timeout=60)
    try:
        dados = json.loads(saida.splitlines()[-1])
    except (ValueError, IndexError):
        return {"erro": sem_acento(erro or saida)[:200] or f"rc={rc}"}
    estados = dados.get("estados") or []
    dados["estados"] = [estados] if isinstance(estados, str) else list(estados)
    return dados


def _bluetooth_texto(estados):
    if not estados:
        return "ausente"
    return "ligado" if any(e == "On" for e in estados) else "desligado"


_bluetooth_preflight = {"estado": None}   # 'desligado' | 'ausente' (para o bateria.csv)


def ajustar_bluetooth():
    item, esperado = "Bluetooth", "desligado"
    dados = radios_bluetooth("ler")
    if dados.get("erro"):
        registrar_item(item, esperado, "ilegível", "nenhuma", "ilegível", "falhou",
                       f"leitura dos rádios falhou: {dados['erro']}")
        return "falhou"
    antes = _bluetooth_texto(dados["estados"])
    if antes == "ausente":
        _bluetooth_preflight["estado"] = "ausente"
        registrar_item(item, esperado, "ausente", "nenhuma", "ausente", "não aplicável",
                       "máquina sem rádio Bluetooth")
        return "não aplicável"
    if antes == "desligado":
        _bluetooth_preflight["estado"] = "desligado"
        registrar_item(item, esperado, antes, "nenhuma", antes, "ok")
        return "ok"
    if dados.get("acesso") != "Allowed":
        registrar_item(item, esperado, antes, "nenhuma", antes, "falhou",
                       f"bloqueado pelo sistema ou por política (acesso: {dados.get('acesso')})")
        return "falhou"
    try:
        depois_dados = radios_bluetooth("Off")
    finally:
        registrar_restauracao("Bluetooth -> ligado", _religar_bluetooth)
    depois = "ilegível" if depois_dados.get("erro") else _bluetooth_texto(depois_dados["estados"])
    if depois == "desligado":
        _bluetooth_preflight["estado"] = "desligado"
        registrar_item(item, esperado, antes, "ajustado", depois, "ajustado")
        return "ajustado"
    motivo = depois_dados.get("erro") or f"resultado: {depois_dados.get('resultado')}"
    registrar_item(item, esperado, antes, "ajustado", depois, "falhou",
                   f"bloqueado pelo sistema ou por política ({motivo})")
    return "falhou"


def _religar_bluetooth():
    dados = radios_bluetooth("On")
    if dados.get("erro") or _bluetooth_texto(dados["estados"]) != "ligado":
        raise OSError(f"Bluetooth nao voltou a ligar: {dados}")


# Ordem do plan (fluxo_principal, passo 4)
AJUSTES = [
    ajustar_plano,
    ajustar_modo_dc,
    ajustar_economia,
    ajustar_brilho_dc,
    ajustar_esmaecimento,
    ajustar_brilho_adaptavel,
    ajustar_bluetooth,
    ajustar_suspensao,
    ajustar_hibernacao,
    ajustar_desligar_video,
]


# =============================================================================
# EDGE E SIMULACAO DE ESCRITORIO (copiado de 1_automacao_performance.py)
# =============================================================================
# copiado de 1_automacao_performance.py (adaptacoes marcadas em cada funcao).
# Reaproveitado por copia (o Modulo 1 nao e importado), sem o passo Selenium
# (_configure_edge_startup_setting) e sem ciclos/cooldown: uma sessao continua.
# Adaptado na simulacao de escritorio (type_text_safely a simulate_pdf_reading):
# as esperas usam pausa() em vez de time.sleep(), para a fase parar no prazo e
# reagir ao Ctrl+Q e ao encerramento da medicao em ate 0,5 s, mesmo no meio de uma acao.
EDGE_FLAGS = [
    "--disable-session-crashed-bubble",
    "--disable-features=msEdgeTabRestorationService",
]
_edge = {"aberto_pelo_teste": False}


class LoginExigido(Exception):
    """Boas-vindas do Edge ou login do Google ao abrir a fase de escritorio."""


def kill_edge(ui=None):
    """Encerra o Edge de forma verificavel.

    copiado de 1_automacao_performance.py; adaptado: so 'msedge.exe' (o original
    casa 'msedge' no nome e derruba tambem o msedgewebview2.exe de outros apps).
    """
    if ui:
        ui.atualizar("Edge", "Encerrando instâncias do Edge...")
    result = subprocess.run(
        "taskkill /F /IM msedge.exe",
        shell=True, capture_output=True
    )
    # adaptado: a saida do taskkill vem na pagina OEM; 128 = nenhum msedge.exe aberto
    if result.returncode not in (0, 128):
        erro = result.stderr.decode("oem", "replace").strip()
        logger.debug(f"taskkill retornou codigo {result.returncode}: {sem_acento(erro)}")

    time.sleep(3)

    # Verificar se realmente encerrou
    for proc in psutil.process_iter(['name']):
        if (proc.info['name'] or "").lower() == "msedge.exe":
            logger.warning("Edge ainda rodando apos taskkill. Forcando via psutil...")
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
    time.sleep(1)
    _edge["aberto_pelo_teste"] = False


def _edge_rodando():
    return any((p.info['name'] or "").lower() == "msedge.exe" for p in psutil.process_iter(['name']))


def abrir_edge(ui, urls):
    """Abre o Edge sem restaurar sessao anterior (copiado de open_edge_and_verify)."""
    ui.atualizar("Edge", "Abrindo o Edge...")
    _edge["aberto_pelo_teste"] = True
    subprocess.Popen(["start", "msedge"] + EDGE_FLAGS + urls, shell=True)
    time.sleep(5)
    if not _edge_rodando():
        logger.error("Edge nao iniciou apos abertura. Tentando novamente...")
        subprocess.Popen(["start", "msedge"] + EDGE_FLAGS + urls, shell=True)
        time.sleep(5)
        if not _edge_rodando():
            raise RuntimeError("Nao foi possivel iniciar o Microsoft Edge.")
    logger.info("Edge iniciado com sucesso.")


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


def _check_google_login_screen(num_tabs):
    """
    Verifica se alguma aba do Edge esta na tela de login do Google.
    Percorre todas as abas abertas procurando por URLs de autenticacao Google.
    Retorna True se detectar tela de login. (adaptado: num_tabs parametrizado)
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
    for i in range(1, num_tabs):
        pyautogui.hotkey('ctrl', 'tab')
        time.sleep(1.5)
        tab_url = _get_current_tab_url()
        if any(pattern in tab_url for pattern in google_login_patterns):
            logger.warning(f"Tela de login do Google detectada na aba {i + 1}: {tab_url}")
            return True

    return False


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


# Textos das janelas de login (os do Modulo 1, com acentuacao)
_TEXTO_LOGIN = {
    "boas-vindas do Edge": (
        "Ação Necessária — Login no Edge",
        "A tela de boas-vindas do Microsoft Edge foi detectada.\n\n"
        "Por favor:\n"
        "1. Faça login na sua conta Microsoft no Edge\n"
        "2. Complete a configuração inicial do navegador\n"
        "3. Feche todas as abas de boas-vindas\n\n"
        "Após concluir, clique em OK para continuar o teste.",
    ),
    "login do Google": (
        "Ação Necessária — Login no Google",
        "A tela de login do Google foi detectada.\n\n"
        "O teste utiliza Google Docs e Google Sheets, que\n"
        "requerem uma conta Google autenticada.\n\n"
        "Por favor:\n"
        "1. Faça login na sua conta Google no navegador\n"
        "2. Aguarde o redirecionamento para o serviço Google\n\n"
        "Após concluir o login, clique em OK para continuar o teste.",
    ),
}


def _pendencia_edge(num_abas):
    """'boas-vindas do Edge', 'login do Google' ou None (Edge pronto)."""
    if _check_edge_welcome_screen():
        return "boas-vindas do Edge"
    if _check_google_login_screen(num_abas):
        return "login do Google"
    return None


def verificar_prontidao_edge(ui):
    """Na tomada: Edge e conta Google prontos para a fase de escritorio.

    Usa as paginas de lista do Docs/Sheets (nao cria documentos). Boas-vindas ou
    login -> janela pedindo o login -> reabre e confere, ate TENTATIVAS_LOGIN.
    """
    item, esperado = "Edge e conta Google", "prontos"
    pedidos, antes, pendencia = 0, None, None
    try:
        while True:
            check_stop()
            kill_edge(ui)
            abrir_edge(ui, URLS_PRONTIDAO)
            ui.atualizar("Pré-voo", "Conferindo Edge e conta Google...")
            pendencia = _pendencia_edge(len(URLS_PRONTIDAO))
            if antes is None:
                antes = f"{pendencia} pendente" if pendencia else "prontos"
            if pendencia is None or pedidos >= TENTATIVAS_LOGIN:
                break
            pedidos += 1
            titulo, texto = _TEXTO_LOGIN[pendencia]
            ui.atualizar("Pré-voo", f"⚠ AGUARDANDO {pendencia.upper()} ⚠",
                         f"Pedido {pedidos} de {TENTATIVAS_LOGIN}")
            logger.warning(f"Teste PAUSADO — {pendencia} detectado. Aguardando login do analista "
                           f"(pedido {pedidos} de {TENTATIVAS_LOGIN}).")
            mostrar_mensagem(ui, titulo, texto)
            logger.info("Analista confirmou o login. Conferindo de novo...")
    except RuntimeError as e:
        kill_edge(ui)
        registrar_item(item, esperado, "Edge não iniciou", "conferido", "Edge não iniciou", "falhou", str(e))
        return "falhou"
    kill_edge(ui)
    obs = f"{pedidos} pedido(s) de login ao operador" if pedidos else ""
    if pendencia is None:
        registrar_item(item, esperado, antes, "conferido", "prontos", "ok", obs)
        return "ok"
    registrar_item(item, esperado, antes, "conferido", f"{pendencia} pendente", "falhou",
                   f"{pendencia} continua pendente após {TENTATIVAS_LOGIN} pedidos de login; "
                   "faça o login no Edge na tomada e execute o teste novamente")
    return "falhou"


def abrir_edge_para_escritorio(ui):
    """Abre o Edge com URLS_ESCRITORIO; login pedido aqui (ja na bateria) = LoginExigido."""
    kill_edge(ui)
    abrir_edge(ui, URLS_ESCRITORIO)
    pendencia = _pendencia_edge(len(URLS_ESCRITORIO))
    if pendencia:
        raise LoginExigido(pendencia)
    if _check_extra_tabs(len(URLS_ESCRITORIO)):
        logger.warning("Abas extras encontradas. Fechando Edge e reabrindo somente com as URLs do teste...")
        kill_edge(ui)
        abrir_edge(ui, URLS_ESCRITORIO)
        logger.info("Edge reaberto apenas com as URLs do teste.")
    ui.atualizar("Transição", "Estabilizando páginas do Edge...")
    pausa(ESTABILIZAR_EDGE_S)


def type_text_safely(text):
    """Digita texto usando clipboard para suportar acentos."""
    pyperclip.copy(text)
    pyautogui.hotkey('ctrl', 'v')
    pausa(0.3)


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
    pausa(random.uniform(3.0, 5.0))  # Esperar aba carregar

    # Escape para fechar qualquer popup de restauracao, sugestao, etc.
    pyautogui.press('escape')
    pausa(random.uniform(0.3, 0.5))

    x_min, x_max, y_min, y_max = _get_safe_content_area()
    center_x = (x_min + x_max) // 2
    center_y = (y_min + y_max) // 2
    pyautogui.click(center_x, center_y)
    pausa(random.uniform(0.8, 1.5))  # Esperar foco estabilizar


def simulate_document_editing(elapsed_ratio):
    """Simula edicao de documento Google Docs (Aba 1)."""
    logger.debug("Simulando edicao de documento...")

    # Clicar na area de edicao para garantir foco
    _click_safe_content_area()
    pausa(random.uniform(0.8, 1.5))

    # Digitar texto variado
    text = random.choice(TYPING_SAMPLES)
    type_text_safely(text)
    pausa(random.uniform(1.0, 2.5))
    pyautogui.press('enter')
    pausa(random.uniform(2.0, 4.0))

    # Ocasionalmente selecionar e formatar texto
    if random.random() < 0.3:
        pyautogui.hotkey('ctrl', 'a')  # Selecionar tudo
        pausa(random.uniform(1.0, 2.0))
        pyautogui.hotkey('ctrl', 'b')  # Negrito
        pausa(random.uniform(1.0, 2.0))
        _click_safe_content_area()
        pausa(random.uniform(1.0, 2.0))

    # Simular leitura/reposicionamento do cursor na area de edicao
    _click_safe_content_area()
    pausa(random.uniform(1.5, 3.0))


# ---------------------------------------------------------------------------
# SIMULACAO ESTRUTURADA DE PLANILHA
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
    pausa(random.uniform(0.4, 0.7))
    pyautogui.press('escape')  # Segundo Escape para menus aninhados
    pausa(random.uniform(0.3, 0.5))

    # Clicar no centro da tela — ponto mais seguro da grade
    screen_w, screen_h = pyautogui.size()
    center_x = screen_w // 2
    center_y = int(screen_h * 0.55)  # Levemente abaixo do centro (evita toolbar)
    pyautogui.click(center_x, center_y)
    pausa(random.uniform(0.8, 1.2))


def _navigate_to_cell_a1():
    """Navega para A1 no Google Sheets usando Ctrl+Home."""
    pyautogui.hotkey('ctrl', 'Home')
    pausa(random.uniform(0.12, 1.2))


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
            pausa(random.uniform(0.08, 0.15))
        pausa(random.uniform(0.3, 0.5))
    else:
        # Para muitas linhas, repetir setas em blocos menores com pausas
        remaining = target_row
        while remaining > 0:
            batch = min(remaining, 20)
            for _ in range(batch):
                pyautogui.press('down')
                pausa(random.uniform(0.05, 0.10))
            remaining -= batch
            pausa(random.uniform(0.2, 0.4))
        pausa(random.uniform(0.3, 0.5))


def _type_cell_value(value):
    """
    Digita um valor na celula atual do Google Sheets.
    Usa clipboard para suporte a acentos e caracteres especiais.
    """
    type_text_safely(value)
    pausa(random.uniform(0.5, 1.0))


def _advance_to_next_column():
    """Avanca para a proxima coluna usando Tab."""
    pyautogui.press('tab')
    pausa(random.uniform(0.25, 0.50))


def _advance_to_next_row_col_a():
    """
    Apos preencher a ultima coluna de uma linha, move para coluna A da proxima.
    Usa Right para confirmar o valor, Down para descer uma linha e Home para
    voltar a coluna A — garantindo posicao correta.
    """
    pyautogui.press('right')       # Confirma o valor da celula atual
    pausa(random.uniform(0.5, 0.8))
    pyautogui.press('down')
    pausa(random.uniform(0.5, 0.8))
    pyautogui.press('home')        # Volta a coluna A da linha atual
    pausa(random.uniform(0.5, 0.8))


def _write_row(values):
    """
    Escreve uma linha completa de dados na planilha.
    Digita cada valor e navega entre colunas.
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
        pausa(random.uniform(1.5, 3.0))

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
            pausa(random.uniform(1.5, 3.5))

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
    pausa(random.uniform(1.0, 2.0))

    # Scroll variado simulando leitura
    for _ in range(random.randint(1, 3)):
        action = random.choice(['pagedown', 'scroll_down', 'scroll_up'])
        if action == 'pagedown':
            pyautogui.press('pagedown')
        elif action == 'scroll_down':
            pyautogui.scroll(-random.randint(2, 5))
        else:
            pyautogui.scroll(random.randint(1, 3))
        pausa(random.uniform(3.0, 6.0))


# Mapa de acoes por aba (indice da aba → funcao de simulacao)
TAB_ACTIONS = [
    simulate_document_editing,
    simulate_spreadsheet_editing,
    simulate_pdf_reading,
]


def executar_fase_escritorio(duracao_s):
    """Laco continuo de TAB_ACTIONS ate a duracao (o ciclo do Modulo 1, sem cooldown).

    A fase para no prazo, mesmo no meio de uma acao (PrazoDaFase pelo check_stop
    das pausas). Erro pontual = aviso no log e segue; Ctrl+Q ou encerramento da
    medicao levantam KeyboardInterrupt (check_stop); fail-safe do pyautogui = parada segura.
    """
    global _sheet_state
    _sheet_state = {"next_row": 0, "data_index": 0, "headers_written": False}
    nomes = {0: "documento", 1: "planilha", 2: "PDF"}
    contagem = {nome: 0 for nome in nomes.values()}
    inicio = time.monotonic()
    current_tab = 0  # Rastrear aba atual (0=Doc, 1=Sheets, 2=PDF)
    _prazo_fase["fim"] = inicio + duracao_s
    try:
        pyautogui.hotkey('ctrl', '1')  # garante a primeira aba como atual
        pausa(1)
        while True:
            check_stop()
            elapsed = time.monotonic() - inicio
            if elapsed >= duracao_s:
                break
            elapsed_ratio = elapsed / duracao_s
            try:
                # Executar acao especifica da aba atual
                TAB_ACTIONS[current_tab](elapsed_ratio)
                contagem[nomes[current_tab]] += 1
                logger.debug(f"Acao concluida na aba {nomes[current_tab]}.")

                # Pausa realista entre acoes (interrompivel)
                pausa(random.uniform(4.0, 10.0))

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
                logger.warning(f"Erro durante automacao (continuando): {type(e).__name__}: {e}")
                pausa(2)
    except PrazoDaFase:
        logger.debug("Prazo da fase de escritorio atingido.")
    finally:
        _prazo_fase["fim"] = None
        logger.info(f"Simulacao de escritorio: acoes por aba = {contagem} "
                    f"em {time.monotonic() - inicio:.0f}s")


# =============================================================================
# PRE-VOO — ORQUESTRADOR
# =============================================================================
def _falha_preflight(ui, falhas):
    """Itens fora do padrao: restaura, lista os pendentes em pt-BR e nao mede."""
    gravar_preflight_csv()
    restaurar_tudo()
    logger.error("Pre-voo nao conferiu; medicao nao iniciada. Itens pendentes: "
                 + sem_acento("; ".join(l["Item"] for l in falhas)))
    linhas = []
    for l in falhas:
        linha = f"• {l['Item']}: esperado {l['Esperado']}, encontrado {l['Depois']}"
        if l["Observacao"]:
            linha += f" ({l['Observacao']})"
        linhas.append(linha)
    ui.atualizar("Pré-voo: teste não iniciado", "Itens fora do padrão. Veja a janela e o log.")
    mostrar_mensagem(
        ui, "Teste de bateria não iniciado",
        "O pré-voo encontrou itens fora do padrão e a medição não foi iniciada:\n\n"
        + "\n".join(linhas)
        + "\n\nAs configurações alteradas pelo teste já foram restauradas. "
          "Corrija os itens e execute o teste novamente.",
        timeout_s=ESPERA_CARREGADOR_S,
    )
    return False


def executar_preflight(ui):
    """Pre-voo na tomada. True = tudo conferido e ajustado (a medicao pode comecar)."""
    if not checagens_rapidas(ui):
        return False
    check_stop()

    # Conferidos antes de qualquer ajuste: rede e monitor externo e, depois,
    # a prontidao do Edge e da conta Google (login resolvido ainda na tomada).
    ui.atualizar("Pré-voo", "Conferindo rede e monitor externo...")
    conferir_rede()
    conferir_monitor()
    falhas = itens_com_falha()
    if falhas:
        return _falha_preflight(ui, falhas)
    verificar_prontidao_edge(ui)
    falhas = itens_com_falha()
    if falhas:
        return _falha_preflight(ui, falhas)

    ui.atualizar("Pré-voo", "Ajustando energia, brilho e Bluetooth...")
    for ajuste in AJUSTES:
        check_stop()
        ajuste()
    gravar_preflight_csv()
    falhas = itens_com_falha()
    if falhas:
        return _falha_preflight(ui, falhas)
    logger.info("Pre-voo concluido: todos os itens conferidos.")
    return True


# =============================================================================
# MEDICAO — ESTADO COMPARTILHADO
# =============================================================================
MOTIVOS_PASS = ("concluido", "protecao_bateria")
_medicao = {
    "iniciada": False,       # carregador desconectado: a medicao comecou
    "motivo": None,          # primeiro motivo de encerramento registrado
    "conferencia_ok": False, # conferencia na bateria (estabilizacao)
}
_medicao_lock = threading.Lock()
_coletor = {"obj": None}


def registrar_encerramento(motivo, detalhe=""):
    """Sinaliza o encerramento controlado da medicao. O primeiro motivo vence."""
    with _medicao_lock:
        primeiro = _medicao["motivo"] is None
        if primeiro:
            _medicao["motivo"] = motivo
    if primeiro:
        nivel = logging.INFO if motivo == "concluido" else logging.WARNING
        logger.log(nivel, f"Encerramento da medicao: {motivo}" + (f" — {sem_acento(detalhe)}" if detalhe else ""))
    _encerrar.set()


def motivo_encerramento():
    with _medicao_lock:
        return _medicao["motivo"]


# =============================================================================
# AVISO DE DESCONEXAO, TELA LIGADA E ESTABILIZACAO
# =============================================================================
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
_kernel32.SetThreadExecutionState.restype = wintypes.DWORD

CHECKLIST_FISICO = [
    "Periféricos desconectados (mouse, teclado, pendrive, fone)",
    "Dock / hub USB desconectado",
    "Luz do teclado apagada",
]


def manter_tela_ligada(ligar):
    """SetThreadExecutionState na thread chamadora (a worker): tela ligada e sem
    suspensao/bloqueio por inatividade, sem simular entrada do usuario."""
    flags = ES_CONTINUOUS | ((ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED) if ligar else 0)
    if _kernel32.SetThreadExecutionState(flags) == 0:
        logger.warning("SetThreadExecutionState falhou.")
    else:
        logger.info("Tela mantida ligada (SetThreadExecutionState)." if ligar
                    else "SetThreadExecutionState liberado.")


def sessao_bloqueada():
    """Tela de bloqueio/login ativa: o LogonUI.exe so roda nessa situacao."""
    return any((p.info["name"] or "").lower() == "logonui.exe" for p in psutil.process_iter(["name"]))


def aviso_desconexao(ui):
    """Aviso unico: checklist fisico + estado do carregador + contagem regressiva.

    Retorna 'iniciar' (checklist confirmado E carregador desconectado),
    'tempo_esgotado' ou 'cancelado' (botao, fechar a janela ou Ctrl+Q).
    """
    def construir(root, concluir):
        janela = _nova_janela(root, "Teste de bateria — desconecte o carregador")
        estado = {"confirmado": False, "fonte": None, "tiques": 0, "fim": False,
                  "inicio": time.monotonic()}

        def finalizar(resultado):
            estado["fim"] = True
            concluir(resultado)

        tk.Label(janela, text="Pré-voo concluído. Para iniciar a medição:",
                 font=FONTE_JANELA_NEGRITO).pack(anchor="w")
        tk.Label(janela, justify="left", font=FONTE_JANELA, text=(
            "1. Desconecte o carregador da tomada — a desconexão é detectada sozinha.\n"
            "2. Confira e marque os três itens abaixo e clique em 'Confirmo o checklist'.\n"
            "A medição começa quando as duas coisas estiverem feitas. Depois disso,\n"
            "não use a máquina até o aviso de que o carregador pode ser reconectado."
        )).pack(anchor="w", pady=(4, 10))

        marcas = [tk.BooleanVar(value=False) for _ in CHECKLIST_FISICO]
        caixas = []

        def atualizar_botao():
            pronto = all(v.get() for v in marcas) and not estado["confirmado"]
            btn_confirmar.config(state="normal" if pronto else "disabled")

        for texto, marca in zip(CHECKLIST_FISICO, marcas):
            caixa = tk.Checkbutton(janela, text=texto, variable=marca, font=FONTE_JANELA,
                                   command=atualizar_botao)
            caixa.pack(anchor="w")
            caixas.append(caixa)

        lbl_carregador = tk.Label(janela, text="Carregador: verificando...", font=FONTE_JANELA_NEGRITO)
        lbl_carregador.pack(anchor="w", pady=(12, 0))
        lbl_contagem = tk.Label(janela, text="", font=("Consolas", 12))
        lbl_contagem.pack(anchor="w", pady=(2, 10))

        botoes = tk.Frame(janela)
        botoes.pack(fill="x", pady=(6, 0))

        def confirmar():
            estado["confirmado"] = True
            for caixa in caixas:
                caixa.config(state="disabled")
            btn_confirmar.config(text="Checklist confirmado", state="disabled")
            logger.info("Checklist fisico confirmado pelo operador.")

        btn_confirmar = tk.Button(botoes, text="Confirmo o checklist", font=FONTE_JANELA_NEGRITO,
                                  width=22, state="disabled", command=confirmar)
        btn_confirmar.pack(side="left")
        tk.Button(botoes, text="Cancelar teste", font=FONTE_JANELA, width=16,
                  command=lambda: finalizar("cancelado")).pack(side="right")
        janela.protocol("WM_DELETE_WINDOW", lambda: finalizar("cancelado"))

        def tique():
            if estado["fim"]:
                return
            restante = ESPERA_CARREGADOR_S - (time.monotonic() - estado["inicio"])
            if restante <= 0:
                finalizar("tempo_esgotado")
                return
            if estado["tiques"] % 2 == 0:   # estado do carregador a cada 2 s
                estado["fonte"] = status_energia()["fonte"]
                if estado["fonte"] == "bateria":
                    lbl_carregador.config(text="Carregador: DESCONECTADO ✓", fg="#1a7f37")
                else:
                    lbl_carregador.config(text="Carregador: conectado — desconecte-o", fg="#b35900")
            estado["tiques"] += 1
            lbl_contagem.config(text=f"Tempo restante: {int(restante) // 60:02d}:{int(restante) % 60:02d}")
            if estado["confirmado"] and estado["fonte"] == "bateria":
                finalizar("iniciar")
                return
            janela.after(1000, tique)

        _centralizar(janela)
        tique()
        return janela

    ui.atualizar("Aguardando o operador", "Desconecte o carregador e confirme o checklist.",
                 f"Limite: {ESPERA_CARREGADOR_S // 60} min")
    logger.info(f"Aviso de desconexao exibido (limite {ESPERA_CARREGADOR_S}s).")
    try:
        resultado = ui.pedir_janela(construir)
    except KeyboardInterrupt:
        resultado = "cancelado"
    logger.info(f"Aviso de desconexao: {resultado}")
    return resultado or "cancelado"


_ESTADO_CARREGADOR = {"tomada": "conectado", "bateria": "desconectado"}


def registrar_fisicos(resultado, fonte_antes):
    """Linhas 'Fisicos' do pre-voo apos o aviso de desconexao.

    fonte_antes: fonte lida antes do aviso (o teste pode ter comecado ja na bateria).
    """
    fonte = status_energia()["fonte"]
    desconectado = fonte == "bateria"
    if not desconectado:
        obs = f"não desconectado em {ESPERA_CARREGADOR_S // 60} min"
    elif fonte_antes == "bateria":
        obs = "já desconectado antes do aviso"
    else:
        obs = "detectado automaticamente"
    registrar_item("Carregador desconectado", "desconectado",
                   _ESTADO_CARREGADOR.get(fonte_antes, "desconhecido"), "conferido",
                   "desconectado" if desconectado else "conectado",
                   "ok" if desconectado else "falhou", obs)
    confirmado = resultado == "iniciar"
    for item in ("Periféricos e dock desconectados", "Luz do teclado apagada"):
        registrar_item(item, "sim", "não informado",
                       "confirmado pelo operador" if confirmado else "nenhuma",
                       "confirmado" if confirmado else "não confirmado",
                       "ok" if confirmado else "falhou")
    gravar_preflight_csv()


def conferir_na_bateria(coletor):
    """Estabilizacao, ja na bateria: brilho, modo e Economia efetivos.

    Brilho != 50 -> WmiSetBrightness(50) uma vez e rele (cobre driver que nao
    respeita o plano); sem a API DC, o modo e aplicado aqui. Retorna True se ok.
    """
    ok = True

    # Brilho efetivo
    amostra = coletor.pedir("amostra")
    brilho = amostra.get("brilho_pct")
    item = "Brilho efetivo"
    if brilho is None:
        registrar_item(item, f"{BRILHO_PADRAO_PCT}%", "ilegível", "nenhuma", "ilegível",
                       "não aplicável", "brilho do monitor indisponível pelo WMI")
    elif brilho == BRILHO_PADRAO_PCT:
        registrar_item(item, f"{BRILHO_PADRAO_PCT}%", f"{brilho}%", "conferido", f"{brilho}%", "ok")
    elif status_energia()["fonte"] != "bateria":
        # na tomada o WmiSetBrightness mudaria o brilho da tomada; a vigia encerra a medicao
        ok = False
        registrar_item(item, f"{BRILHO_PADRAO_PCT}%", f"{brilho}%", "conferido", f"{brilho}%", "falhou",
                       "carregador reconectado antes da conferência")
    else:
        try:
            aplicar_brilho(BRILHO_PADRAO_PCT)
            time.sleep(2)
            depois = coletor.pedir("amostra").get("brilho_pct")
            obs = ""
        except OSError as e:
            depois, obs = brilho, str(e)
        situacao = "ajustado" if depois == BRILHO_PADRAO_PCT else "falhou"
        ok &= situacao == "ajustado"
        registrar_item(item, f"{BRILHO_PADRAO_PCT}%", f"{brilho}%", "ajustado", _fmt_pct(depois), situacao,
                       obs or ("brilho de bateria do plano não aplicado pelo driver; reaplicado pelo WMI"
                               if situacao == "ajustado" else "o driver não aceitou o brilho de 50%"))

    # Modo de energia efetivo
    item = "Modo de energia efetivo"
    modo = modo_efetivo()
    if modo == MODO_MELHOR_DESEMPENHO:
        registrar_item(item, "Melhor desempenho", nome_modo(modo), "conferido", nome_modo(modo), "ok")
    elif not api_modo_dc_disponivel():
        erro = ""
        try:
            definir_overlay_ativo(MODO_MELHOR_DESEMPENHO)
        except (OSError, AttributeError) as e:
            erro = f"ajuste falhou: {e}"
        finally:
            # a volta tambem precisa da bateria: roda no fim da medicao, antes do aviso de reconexao
            registrar_restauracao(f"Modo de energia na bateria -> {nome_modo(modo)}",
                                  lambda: _voltar_overlay_bateria(modo), na_bateria=True)
        depois = modo_efetivo()
        situacao = "ajustado" if not erro and depois == MODO_MELHOR_DESEMPENHO else "falhou"
        ok &= situacao == "ajustado"
        if erro:
            obs = erro
        elif situacao == "falhou":
            obs = "o Windows não aplicou o modo Melhor desempenho na bateria"
        else:
            obs = "aplicado já na bateria (API do modo na bateria ausente)"
        registrar_item(item, "Melhor desempenho", nome_modo(modo), "ajustado", nome_modo(depois), situacao, obs)
    else:
        ok = False
        registrar_item(item, "Melhor desempenho", nome_modo(modo), "conferido", nome_modo(modo), "falhou",
                       "o Windows não aplicou o modo configurado para a bateria")

    # Economia de energia efetiva
    item = "Economia de energia efetiva"
    ligada = status_energia()["economia_ligada"]
    estado = "ligada" if ligada else "desligada"
    registrar_item(item, "desligada", estado, "conferido", estado, "falhou" if ligada else "ok",
                   "a Economia de energia ligou na bateria" if ligada else "")
    ok &= not ligada

    gravar_preflight_csv()
    return ok


def _voltar_overlay_bateria(modo_anterior):
    if status_energia()["fonte"] == "bateria":
        definir_overlay_ativo(modo_anterior)
    else:
        logger.warning(f"Modo de energia na bateria ficou em Melhor desempenho; o anterior era "
                       f"{sem_acento(nome_modo(modo_anterior))} (restaure manualmente na bateria).")


def estabilizar(ui, coletor):
    """ESTABILIZACAO_S fora da medicao, com a conferencia dos valores efetivos.

    Falha na conferencia = encerramento controlado ('padronizacao_na_bateria').
    """
    logger.info(f"Estabilizacao: {ESTABILIZACAO_S}s na bateria antes de medir.")
    inicio = time.monotonic()
    pausa(min(10, ESTABILIZACAO_S))   # o Windows aplica o brilho de bateria na transicao
    ok = conferir_na_bateria(coletor)
    _medicao["conferencia_ok"] = ok
    if not ok:
        falhas = [l["Item"] for l in itens_com_falha()]
        registrar_encerramento("padronizacao_na_bateria", "; ".join(falhas))
        return False
    restante = ESTABILIZACAO_S - (time.monotonic() - inicio)
    if restante > 0:
        pausa(restante)
    return True


# =============================================================================
# MEDICAO — AMOSTRAS, TOP 10 PROCESSOS E THREAD DE MONITORAMENTO
# =============================================================================
ARQ_AMOSTRAS = "bateria_amostras.csv"
COLUNAS_AMOSTRAS = [
    "Data_Hora", "Fase", "Tipo", "Decorrido_Fase_s", "Carga_Pct", "Energia_Restante_mWh",
    "Taxa_Descarga_mW", "Tensao_mV", "Fonte", "Brilho_Pct", "Modo_Energia", "Economia_Energia", "Desvio",
]
ARQ_TOP = "bateria_top_processos.csv"
COLUNAS_TOP = ["Data_Hora", "Fase", "Posicao", "Processo", "PID", "CPU_Pct", "Memoria_MB"]
FASES_MEDIDAS = ("ociosa", "escritorio")
NOMES_FASE = {
    "estabilizacao": "Estabilização", "ociosa": "Fase ociosa", "transicao": "Transição",
    "escritorio": "Fase de escritório", "encerramento": "Encerramento",
}
DURACAO_FASE = {"estabilizacao": ESTABILIZACAO_S, "ociosa": DURACAO_OCIOSA_S,
                "escritorio": DURACAO_ESCRITORIO_S}
ESPACO_MINIMO_TRACES_B = 5 * 1024 ** 3

_fase = {"nome": None, "inicio": None}
_marcos = {}            # fase -> {"inicio": amostra, "fim": amostra, "completa": bool}
_amostras_medidas = []  # (fase, brilho, modo) das amostras das fases medidas
_desvios = {"total": 0, "avisados": set()}
_amostra_final = {"valor": None}
_csv_lock = threading.Lock()


def definir_fase(nome):
    with _medicao_lock:
        _fase["nome"], _fase["inicio"] = nome, time.monotonic()
    logger.info(f"Fase: {nome}")


def _decimal(valor, casas=1):
    """Decimal com virgula (CSVs de evidencia); ausente = vazio."""
    return "" if valor is None else f"{valor:.{casas}f}".replace(".", ",")


def _celula(valor):
    return "" if valor is None else str(valor)


def _anexar_csv(arquivo, colunas, linhas):
    """Append + flush (evidencia parcial preservada); cabecalho so na criacao."""
    caminho = os.path.join(OUTPUT_PATH, arquivo)
    with _csv_lock:
        novo = not os.path.exists(caminho) or os.path.getsize(caminho) == 0
        with open(caminho, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            if novo:
                writer.writerow(colunas)
            writer.writerows(linhas)
            f.flush()


def coletar_amostra(tipo="periodica"):
    """Grava uma linha em bateria_amostras.csv e devolve a amostra (marcos e metricas)."""
    st = status_energia()
    coletor = _coletor["obj"]
    dados = coletor.pedir("amostra") if coletor else {"erro": "coletor nao iniciado"}
    if dados.get("erro"):
        logger.warning(f"Amostra sem leitura do WMI: {dados['erro']}")
        dados = {campo: None for campo in CAMPOS_AMOSTRA}
    modo = modo_efetivo()
    agora = time.monotonic()
    with _medicao_lock:
        fase, inicio = _fase["nome"], _fase["inicio"]
    carga = st["carga_pct"] if st["carga_pct"] is not None else dados["carga_pct"]
    brilho = dados["brilho_pct"]

    desvio = False
    if fase in FASES_MEDIDAS:
        tipos = []
        if brilho is not None and brilho != BRILHO_PADRAO_PCT:
            tipos.append(f"brilho {brilho}%")
        if modo != MODO_MELHOR_DESEMPENHO:
            tipos.append(f"modo {sem_acento(nome_modo(modo))}")
        if st["economia_ligada"]:
            tipos.append("Economia de energia ligada")
        desvio = bool(tipos)
        with _medicao_lock:
            _amostras_medidas.append((fase, brilho, nome_modo(modo)))
            if desvio:
                _desvios["total"] += 1
            novos = [t for t in tipos if t.split(" ")[0] not in _desvios["avisados"]]
            _desvios["avisados"].update(t.split(" ")[0] for t in tipos)
        for t in novos:
            logger.warning(f"Desvio de padronizacao na fase {fase}: {t}. "
                           "A execucao nao deve ser usada como comparacao.")

    amostra = {
        "t": agora, "fase": fase, "tipo": tipo,
        "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "decorrido_s": int(agora - inicio) if inicio is not None else None,
        "carga_pct": carga, "energia_mwh": dados["energia_mwh"],
        "taxa_descarga_mw": dados["taxa_descarga_mw"], "tensao_mv": dados["tensao_mv"],
        "fonte": st["fonte"], "brilho_pct": brilho, "modo": nome_modo(modo),
        "economia": "ligada" if st["economia_ligada"] else "desligada",
        "desvio": desvio,
    }
    try:
        _anexar_csv(ARQ_AMOSTRAS, COLUNAS_AMOSTRAS, [[
            amostra["data_hora"], fase, tipo, _celula(amostra["decorrido_s"]), _celula(carga),
            _celula(amostra["energia_mwh"]), _celula(amostra["taxa_descarga_mw"]),
            _celula(amostra["tensao_mv"]), amostra["fonte"], _celula(brilho), amostra["modo"],
            amostra["economia"], "sim" if desvio else "nao",
        ]])
    except OSError as e:
        logger.error(f"Falha ao gravar {ARQ_AMOSTRAS}: {e}")
    logger.debug(f"Amostra {fase}/{tipo}: {carga}% {amostra['energia_mwh']} mWh "
                 f"{amostra['taxa_descarga_mw']} mW brilho={brilho} fonte={amostra['fonte']}")
    return amostra


def amostra_marco(tipo):
    """Marco no limite exato da fase (inicio_fase / fim_fase), guardado para as metricas."""
    amostra = coletar_amostra(tipo)
    marco = _marcos.setdefault(amostra["fase"], {})
    marco["inicio" if tipo == "inicio_fase" else "fim"] = amostra
    return amostra


def _preparar_top_processos():
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def coletar_top_processos():
    """Top 10 por CPU media na janela desde a leitura anterior (% da maquina)."""
    cpus = psutil.cpu_count() or 1
    lista = []
    for proc in psutil.process_iter(["name", "memory_info"]):
        if proc.pid == 0:   # System Idle Process
            continue
        try:
            cpu = proc.cpu_percent(None) / cpus
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        memoria = proc.info["memory_info"]
        lista.append((cpu, proc.info["name"] or "?", proc.pid,
                      memoria.rss / 1048576 if memoria else None))
    lista.sort(key=lambda item: item[0], reverse=True)
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fase = _fase["nome"]
    linhas = [[data_hora, fase, posicao, nome, pid, _decimal(cpu, 2), _decimal(memoria, 1)]
              for posicao, (cpu, nome, pid, memoria) in enumerate(lista[:10], start=1)]
    try:
        _anexar_csv(ARQ_TOP, COLUNAS_TOP, linhas)
    except OSError as e:
        logger.error(f"Falha ao gravar {ARQ_TOP}: {e}")
    logger.debug("Top processos: " + ", ".join(f"{l[3]}={l[5]}" for l in linhas[:3]))


class MonitorMedicao(threading.Thread):
    """Da estabilizacao ao fim da medicao: vigia (tique de INTERVALO_VIGIA_S),
    amostra a cada INTERVALO_AMOSTRA_S e top 10 a cada INTERVALO_TOP_PROCESSOS_S.
    O overlay so muda a cada amostra (redesenho de tela e custo na fase ociosa)."""

    def __init__(self, ui):
        super().__init__(name="monitor", daemon=True)
        self.ui = ui
        self._parar = threading.Event()

    def run(self):
        _preparar_top_processos()
        inicio = time.monotonic()
        proxima_amostra = inicio
        proximo_top = inicio + INTERVALO_TOP_PROCESSOS_S
        bloqueio_visto = False
        while not self._parar.is_set():
            try:
                self._vigiar()
                agora = time.monotonic()
                if agora >= proxima_amostra:
                    amostra = coletar_amostra("periodica")
                    proxima_amostra = max(proxima_amostra + INTERVALO_AMOSTRA_S, agora + 1)
                    self._atualizar_overlay(amostra)
                    if sessao_bloqueada():
                        if not bloqueio_visto:
                            logger.warning(f"Sessao bloqueada (LogonUI.exe) observada na fase {amostra['fase']}.")
                        bloqueio_visto = True
                    else:
                        bloqueio_visto = False
                if agora >= proximo_top:
                    coletar_top_processos()
                    proximo_top += INTERVALO_TOP_PROCESSOS_S
            except Exception as e:
                logger.warning(f"Monitor: {type(e).__name__}: {e}")
            self._parar.wait(INTERVALO_VIGIA_S)

    def _vigiar(self):
        st = status_energia()
        if st["fonte"] == "tomada":
            registrar_encerramento("carregador_reconectado", "carregador reconectado durante a medicao")
        elif st["carga_pct"] is not None and st["carga_pct"] <= PROTECAO_BATERIA_PCT:
            registrar_encerramento("protecao_bateria", f"carga em {st['carga_pct']}%")
        if _stop_requested.is_set():
            registrar_encerramento("parada_segura", "pedida pelo operador (Ctrl+Q, janela do monitor ou Ctrl+C)")

    def _atualizar_overlay(self, amostra):
        fase = amostra["fase"]
        detalhe = ""
        if fase in DURACAO_FASE and amostra["decorrido_s"] is not None:
            restante = max(0, DURACAO_FASE[fase] - amostra["decorrido_s"])
            detalhe = f"Restam ~{(restante + 59) // 60} min"
        carga = "?" if amostra["carga_pct"] is None else amostra["carga_pct"]
        self.ui.atualizar(NOMES_FASE.get(fase, fase), f"Carga da bateria: {carga}% — não use a máquina", detalhe)

    def parar(self):
        self._parar.set()
        self.join(timeout=2 * TIMEOUT_COLETOR_S + 10)


# =============================================================================
# MEDICAO — CAPTURA WPR POR FASE
# =============================================================================
_wpr = {"ativo": False, "fase": None, "traces": {}}   # traces: "Ociosa"/"Escritorio" -> caminho .etl
_TIMEOUT_WPR_STOP_S = 30 * 60   # stop/merge de um trace de 60 min leva minutos


def _executar_wpr(args, timeout):
    logger.debug("wpr.exe " + " ".join(args))
    try:
        r = subprocess.run(["wpr.exe"] + args, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return None, f"tempo esgotado ({timeout}s)"
    except OSError as e:
        return None, str(e)
    return r.returncode, (r.stdout + r.stderr).decode("oem", "replace").strip()


def wpr_cancelar():
    rc, saida = _executar_wpr(["-cancel"], 300)
    logger.debug(f"wpr -cancel: rc={rc}")


def wpr_iniciar(nome_fase):
    """nome_fase ("Ociosa"/"Escritorio") nomeia o .etl, mesmo se o stop vier de um encerramento."""
    rc, saida = _executar_wpr(["-start", WPR_PERFIL, "-filemode", "-compress"], 300)
    if rc != 0:
        raise RuntimeError(f"Falha ao iniciar a captura WPR (rc={rc}): {sem_acento(saida)[-300:]}")
    _wpr["ativo"], _wpr["fase"] = True, nome_fase
    logger.info(f"Captura WPR iniciada ({WPR_PERFIL}).")


def wpr_parar(nome_fase):
    """wpr -stop Trace_Bateria_<Fase>_<ts>.etl -compress. Retorna o caminho ou None."""
    caminho = os.path.join(OUTPUT_PATH, f"Trace_Bateria_{nome_fase}_{SESSION_TIMESTAMP}.etl")
    logger.info(f"Salvando trace da fase {nome_fase} (.etl)...")
    rc, saida = _executar_wpr(["-stop", caminho, "-compress"], _TIMEOUT_WPR_STOP_S)
    if rc == 0 and os.path.exists(caminho):
        _wpr["ativo"] = False
        _wpr["traces"][nome_fase] = caminho
        logger.info(f"Trace salvo: {caminho}")
        return caminho
    logger.error(f"Falha ao salvar o trace da fase {nome_fase} (rc={rc}): {sem_acento(saida)[-300:]}")
    return None


def parar_wpr_ativo(nome_fase):
    """Encerramento antecipado: -stop preserva o parcial; -cancel so se o stop falhar."""
    if not _wpr["ativo"]:
        return
    if wpr_parar(nome_fase) is None:
        logger.warning("Cancelando a captura WPR para nao deixar sessao presa.")
        wpr_cancelar()
        _wpr["ativo"] = False


def avisar_espaco_livre():
    try:
        livre = shutil.disk_usage(OUTPUT_PATH).free
    except OSError:
        return
    if livre < ESPACO_MINIMO_TRACES_B:
        logger.warning(f"Pouco espaco livre no disco das evidencias: {livre / 1024 ** 3:.1f} GB "
                       "(cada trace de 60 min pode ter centenas de MB).")


# =============================================================================
# MEDICAO — FASES
# =============================================================================
def _motivo_interrupcao():
    """KeyboardInterrupt na medicao: motivo ja registrado (vigia) ou parada segura."""
    if motivo_encerramento() is None:
        registrar_encerramento("parada_segura", "Ctrl+Q ou fail-safe do pyautogui")


def executar_medicao(ui):
    """Estabilizacao -> fase ociosa -> transicao -> fase de escritorio -> encerramento.

    Os marcos de cada fase ficam em _marcos (inclusive em encerramento antecipado).
    """
    monitor = MonitorMedicao(ui)
    definir_fase("estabilizacao")
    monitor.start()
    try:
        try:
            if not estabilizar(ui, _coletor["obj"]):
                return
        except KeyboardInterrupt:
            _motivo_interrupcao()
            return

        # Fase ociosa: nenhum app aberto pelo teste, nenhuma entrada simulada
        avisar_espaco_livre()
        wpr_cancelar()
        wpr_iniciar("Ociosa")
        definir_fase("ociosa")
        amostra_marco("inicio_fase")
        interrompida = _encerrar.wait(DURACAO_OCIOSA_S)
        amostra_marco("fim_fase")
        _marcos["ociosa"]["completa"] = not interrompida
        # o stop/merge do trace ja fica fora da fase medida
        definir_fase("encerramento" if interrompida else "transicao")
        parar_wpr_ativo("Ociosa")
        if interrompida:
            return

        # Transicao (fora das metricas)
        if sessao_bloqueada():
            registrar_encerramento("sessao_bloqueada",
                                   "sessao bloqueada no inicio da fase de escritorio")
            return
        try:
            abrir_edge_para_escritorio(ui)
        except LoginExigido as e:
            registrar_encerramento("login_exigido", f"{e} ao abrir o Edge ja na bateria")
            return
        except KeyboardInterrupt:
            _motivo_interrupcao()
            return

        # Fase de escritorio: simulacao continua do Modulo 1
        wpr_iniciar("Escritorio")
        definir_fase("escritorio")
        amostra_marco("inicio_fase")
        try:
            executar_fase_escritorio(DURACAO_ESCRITORIO_S)
            # A medicao terminou no prazo: religar o carregador ou Ctrl+Q durante o
            # stop do trace nao invalida mais a coleta (o primeiro motivo vence).
            registrar_encerramento("concluido")
        except KeyboardInterrupt:
            _motivo_interrupcao()
        finally:
            amostra_marco("fim_fase")
            _marcos["escritorio"]["completa"] = motivo_encerramento() == "concluido"
            definir_fase("encerramento")
            parar_wpr_ativo("Escritorio")
    finally:
        # Encerramento (normal ou antecipado): trace ativo, monitor, amostra final,
        # voltas que exigem a bateria (antes do aviso de reconexao), Edge
        if _wpr["ativo"]:
            parar_wpr_ativo(_wpr["fase"] or "Parcial")
        monitor.parar()
        if _fase["nome"] != "encerramento":
            definir_fase("encerramento")
        try:
            _amostra_final["valor"] = coletar_amostra("periodica")
        except Exception as e:
            logger.warning(f"Amostra final falhou: {e}")
        restaurar_na_bateria()
        if _edge["aberto_pelo_teste"]:
            kill_edge(ui)


# =============================================================================
# POS-MEDICAO — EVIDENCIAS COMPLEMENTARES (falha = aviso; nao muda o resultado)
# =============================================================================
def mostrar_aviso(ui, titulo, texto):
    """Janela com OK que nao bloqueia a worker."""
    def construir(root, concluir):
        janela = _nova_janela(root, titulo)
        tk.Label(janela, text=texto, font=FONTE_JANELA, justify="left", wraplength=520).pack(anchor="w")
        tk.Button(janela, text="OK", font=FONTE_JANELA_NEGRITO, width=14,
                  command=lambda: concluir("ok")).pack(pady=(16, 0))
        janela.protocol("WM_DELETE_WINDOW", lambda: concluir("ok"))
        _centralizar(janela)
        return janela

    ui.pedir_janela(construir, esperar=False)


def avisar_reconexao(ui):
    logger.info("Medicao encerrada: o carregador ja pode ser reconectado.")
    ui.atualizar("Medição encerrada", "O carregador já pode ser reconectado.",
                 "Exportando evidências...")
    mostrar_aviso(
        ui, "Teste de bateria — medição encerrada",
        "A medição terminou: o carregador já pode ser reconectado.\n\n"
        "O teste ainda vai converter os traces e gerar os relatórios complementares, "
        "o que pode levar alguns minutos. Não é preciso acompanhar.",
    )


def exportar_traces(ui):
    """wpaexporter por trace -> CSV_<Fase>_<ts>/. Falha ou timeout = aviso; .etl preservado."""
    if not _wpr["traces"]:
        logger.warning("Nenhum trace gravado: exportacao CSV ignorada.")
        return
    perfil = caminho_perfil_wpa()
    for nome_fase, etl in _wpr["traces"].items():
        if not perfil:
            logger.warning(f"Profile WPA '{PROFILE_NAME}' nao encontrado: exportacao do trace {nome_fase} "
                           f"ignorada. Trace preservado em {etl}")
            continue
        pasta = os.path.join(OUTPUT_PATH, f"CSV_{nome_fase}_{SESSION_TIMESTAMP}")
        os.makedirs(pasta, exist_ok=True)
        ui.atualizar("Medição encerrada", f"Convertendo o trace da fase {nome_fase} para CSV...",
                     "O carregador já pode ser reconectado")
        logger.info(f"Exportando trace {nome_fase} com o perfil WPA...")
        cmd = ["wpaexporter.exe", "-i", etl, "-profile", perfil, "-outputfolder", pasta]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_EXPORTACAO_S,
                               creationflags=CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            logger.warning(f"wpaexporter excedeu {TIMEOUT_EXPORTACAO_S}s no trace {nome_fase}. "
                           f"Trace preservado em {etl}")
            continue
        except OSError as e:
            logger.warning(f"wpaexporter nao executou ({e}). Trace preservado em {etl}")
            continue
        gerados = [x for x in os.listdir(pasta) if x.lower().endswith(".csv")]
        if r.returncode != 0 or not gerados:
            erro = (r.stderr or r.stdout).decode("oem", "replace").strip()[-300:]
            logger.warning(f"wpaexporter retornou erro no trace {nome_fase} (rc={r.returncode}): "
                           f"{sem_acento(erro)}. Trace preservado em {etl}")
        else:
            logger.info(f"CSVs exportados para: {pasta} ({len(gerados)} arquivos)")


def gerar_srum():
    caminho = os.path.join(OUTPUT_PATH, "bateria_srum.csv")
    rc, saida = _powercfg(["/srumutil", "/output", caminho, "/csv"], timeout=600)
    if os.path.exists(caminho):
        logger.info(f"Relatorio SRUM: {caminho}")
    else:
        logger.warning(f"Relatorio SRUM nao gerado (rc={rc}): {sem_acento(saida)[-200:]}")


def gerar_relatorio_energia():
    caminho = os.path.join(OUTPUT_PATH, "bateria_relatorio_energia.html")
    logger.info("Gerando o relatorio de energia (powercfg /energy, 60 s de observacao)...")
    rc, saida = _powercfg(["/energy", "/output", caminho, "/duration", "60"], timeout=600)
    if os.path.exists(caminho):   # rc != 0 so indica problemas de eficiencia no relatorio
        logger.info(f"Relatorio de energia: {caminho}")
    else:
        logger.warning(f"Relatorio de energia nao gerado (rc={rc}): {sem_acento(saida)[-200:]}")


def pos_medicao(ui):
    """Relatorio 'depois' -> aviso de reconexao -> exportacao WPA -> SRUM -> relatorio de energia."""
    etapas = [
        ("relatorio de bateria 'depois'", lambda: gerar_relatorio_bateria("depois")),
        ("aviso de reconexao", lambda: avisar_reconexao(ui)),
        ("exportacao dos traces", lambda: exportar_traces(ui)),
        ("relatorio SRUM", gerar_srum),
        ("relatorio de energia", gerar_relatorio_energia),
    ]
    for nome, etapa in etapas:
        try:
            etapa()
        except Exception as e:
            logger.warning(f"Pos-medicao: {nome} falhou ({type(e).__name__}: {e}).")


# =============================================================================
# METRICAS, bateria.csv E DECISAO DE PASS/FAIL
# =============================================================================
ARQ_TEMATICO = "bateria.csv"


def calcular_metricas_fase(inicio, fim, carga_cheia_mwh):
    """Metricas de uma fase a partir das amostras-marco (funcao pura).

    Energia = E_inicio - E_fim (mWh); taxa media (W) = energia / horas / 1000;
    queda (pp e pp/h); autonomia (h) = carga cheia / taxa media (mW). Sem mWh num
    marco, ou capacidade em unidade relativa (carga cheia <= 100): energia =
    (%_inicio - %_fim)/100 x carga cheia, marcada como estimada. Sem dados = None.
    """
    metricas = {"duracao_min": None, "energia_mwh": None, "taxa_w": None, "queda_pp": None,
                "queda_pp_h": None, "autonomia_h": None, "estimada": False}
    if not inicio or not fim:
        return metricas
    duracao_s = fim["t"] - inicio["t"]
    metricas["duracao_min"] = max(0.0, duracao_s / 60)
    if duracao_s <= 0:
        return metricas
    horas = duracao_s / 3600
    pct_ini, pct_fim = inicio.get("carga_pct"), fim.get("carga_pct")
    if pct_ini is not None and pct_fim is not None:
        metricas["queda_pp"] = pct_ini - pct_fim
        metricas["queda_pp_h"] = metricas["queda_pp"] / horas
    e_ini, e_fim = inicio.get("energia_mwh"), fim.get("energia_mwh")
    relativa = carga_cheia_mwh is not None and carga_cheia_mwh <= 100
    if e_ini is not None and e_fim is not None and not relativa:
        metricas["energia_mwh"] = e_ini - e_fim
    elif metricas["queda_pp"] is not None and carga_cheia_mwh:
        metricas["energia_mwh"] = metricas["queda_pp"] / 100 * carga_cheia_mwh
        metricas["estimada"] = True
    if metricas["energia_mwh"] is not None:
        metricas["taxa_w"] = metricas["energia_mwh"] / horas / 1000
        if metricas["energia_mwh"] > 0 and carga_cheia_mwh:
            metricas["autonomia_h"] = carga_cheia_mwh / (metricas["energia_mwh"] / horas)
    return metricas


def decidir_exit_code(estado):
    """0 somente com coleta valida: pre-voo e conferencia na bateria ok, fase ociosa
    completa, >= ESCRITORIO_MINIMO_PASS_S na fase de escritorio com motivo
    'concluido' ou 'protecao_bateria', energia (medida ou estimada) nas duas fases,
    e bateria.csv e bateria_amostras.csv gravados."""
    valido = (
        bool(estado.get("preflight_ok"))
        and bool(estado.get("conferencia_ok"))
        and bool(estado.get("ociosa_completa"))
        and (estado.get("escritorio_s") or 0) >= ESCRITORIO_MINIMO_PASS_S
        and estado.get("motivo") in MOTIVOS_PASS
        and bool(estado.get("energia_ok"))
        and bool(estado.get("bateria_csv"))
        and bool(estado.get("amostras_csv"))
    )
    return 0 if valido else 1


def _ponto(valor):
    """bateria.csv: decimal com ponto e 2 casas; ausente = N/A."""
    return "N/A" if valor is None else f"{valor:.2f}"


def _inteiro_ou_na(valor):
    return "N/A" if valor is None else str(int(valor))


def _predominante(valores):
    valores = [v for v in valores if v is not None]
    if not valores:
        return None
    return max(set(valores), key=valores.count)


def linhas_bateria_csv(coleta_valida, motivo, ociosa, escritorio, estaticos,
                       carga_inicial, carga_final, plano, modo, brilho, bluetooth, desvios):
    """Linhas do bateria.csv (Metrica, Valor, Unidade), na ordem do plan."""
    linhas = [
        ["Versao_Teste", VERSAO_TESTE, "texto"],
        ["Coleta_Valida", "sim" if coleta_valida else "nao", "texto"],
        ["Motivo_Encerramento", motivo or "N/A", "texto"],
    ]
    for prefixo, m in (("Ociosa", ociosa), ("Escritorio", escritorio)):
        linhas += [
            [f"{prefixo}_Duracao_Medida", _ponto(m["duracao_min"]), "min"],
            [f"{prefixo}_Energia_Consumida", _ponto(m["energia_mwh"]), "mWh"],
            [f"{prefixo}_Taxa_Media_Descarga", _ponto(m["taxa_w"]), "W"],
            [f"{prefixo}_Queda_Carga", _ponto(m["queda_pp"]), "pp"],
            [f"{prefixo}_Queda_Carga_Hora", _ponto(m["queda_pp_h"]), "pp/h"],
            [f"{prefixo}_Autonomia_Projetada", _ponto(m["autonomia_h"]), "h"],
        ]
    linhas += [
        ["Energia_Estimada", "sim" if (ociosa["estimada"] or escritorio["estimada"]) else "nao", "texto"],
        ["Carga_Bateria_Inicial", _inteiro_ou_na(carga_inicial), "%"],
        ["Carga_Bateria_Final", _inteiro_ou_na(carga_final), "%"],
        ["Capacidade_Carga_Cheia", _inteiro_ou_na(estaticos.get("carga_cheia_mwh")), "mWh"],
        ["Capacidade_Projeto", _inteiro_ou_na(estaticos.get("projeto_mwh")), "mWh"],
        ["Ciclos_Carga", _inteiro_ou_na(estaticos.get("ciclos")), "un"],
        ["Plano_Energia", plano or "N/A", "texto"],
        ["Modo_Energia", modo or "N/A", "texto"],
        ["Brilho", _inteiro_ou_na(brilho), "%"],
        ["Bluetooth", bluetooth or "N/A", "texto"],
        ["Desvios_Padronizacao", str(desvios), "un"],
    ]
    return linhas


def _amostras_gravadas():
    caminho = os.path.join(OUTPUT_PATH, ARQ_AMOSTRAS)
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return sum(1 for _ in f) > 1
    except OSError:
        return False


def concluir_resultado(ui, estaticos):
    """Metricas por fase, bateria.csv e exit code (chamado sempre que a medicao comecou)."""
    carga_cheia = estaticos.get("carga_cheia_mwh")
    ociosa = calcular_metricas_fase(_marcos.get("ociosa", {}).get("inicio"),
                                    _marcos.get("ociosa", {}).get("fim"), carga_cheia)
    escritorio = calcular_metricas_fase(_marcos.get("escritorio", {}).get("inicio"),
                                        _marcos.get("escritorio", {}).get("fim"), carga_cheia)
    for nome, m in (("ociosa", ociosa), ("escritorio", escritorio)):
        logger.info(f"Metricas {nome}: duracao={_ponto(m['duracao_min'])} min | energia={_ponto(m['energia_mwh'])} mWh | "
                    f"taxa={_ponto(m['taxa_w'])} W | queda={_ponto(m['queda_pp'])} pp | "
                    f"autonomia={_ponto(m['autonomia_h'])} h" + (" (estimada)" if m["estimada"] else ""))

    inicio_ociosa = _marcos.get("ociosa", {}).get("inicio")
    final = _amostra_final["valor"]
    with _medicao_lock:
        medidas = list(_amostras_medidas)
        desvios = _desvios["total"]
    plano = next((l["Depois"] for l in _preflight if l["Item"] == "Plano de energia"), None)
    estado = {
        "preflight_ok": not any(l["Situacao"] == "falhou" for l in _preflight),
        "conferencia_ok": _medicao["conferencia_ok"],
        "ociosa_completa": _marcos.get("ociosa", {}).get("completa", False),
        "escritorio_s": (escritorio["duracao_min"] or 0) * 60,
        "motivo": motivo_encerramento(),
        "energia_ok": ociosa["energia_mwh"] is not None and escritorio["energia_mwh"] is not None,
        "bateria_csv": True,          # provisorio: o arquivo e gravado com o resultado
        "amostras_csv": _amostras_gravadas(),
    }
    provisorio = decidir_exit_code(estado)
    linhas = linhas_bateria_csv(
        coleta_valida=provisorio == 0, motivo=estado["motivo"], ociosa=ociosa, escritorio=escritorio,
        estaticos=estaticos, carga_inicial=(inicio_ociosa or {}).get("carga_pct"),
        carga_final=(final or {}).get("carga_pct"), plano=plano,
        modo=_predominante([m for _, _, m in medidas]), brilho=_predominante([b for _, b, _ in medidas]),
        bluetooth=_bluetooth_preflight["estado"], desvios=desvios,
    )
    caminho = os.path.join(OUTPUT_PATH, ARQ_TEMATICO)
    try:
        with open(caminho, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["Metrica", "Valor", "Unidade"]] + linhas)
        logger.info(f"CSV tematico gravado: {caminho}")
        estado["bateria_csv"] = True
    except OSError as e:
        logger.error(f"Falha ao gravar {ARQ_TEMATICO}: {e}")
        estado["bateria_csv"] = False
    codigo = decidir_exit_code(estado)
    if codigo == 0:
        ui.atualizar("Teste concluído", "Coleta válida (PASS).", "Restaurando as configurações...")
    else:
        ui.atualizar("Teste concluído", f"Coleta inválida (FAIL): {estado['motivo']}.", "Veja o log")
    logger.info(f"Resultado: {'PASS' if codigo == 0 else 'FAIL'} — {estado}")
    return codigo


# =============================================================================
# THREAD PRINCIPAL DE TRABALHO
# =============================================================================
# O exit code e decidido aqui e aplicado pela thread principal: encerrar o
# processo de dentro da worker so encerraria a thread.
def worker_thread(ui):
    global _exit_code
    _exit_code = 1
    if HUB_EVIDENCE_DIR:
        logger.info(f"Modo Hub detectado. Evidencias em: {HUB_EVIDENCE_DIR}")
    else:
        logger.warning(f"HUB_EVIDENCE_DIR ausente. Evidencias em: {OUTPUT_PATH}")
    fim = "pre-voo nao conferiu"
    estaticos = {campo: None for campo in CAMPOS_ESTATICO}
    try:
        # 1-5. Pre-voo na tomada
        if not executar_preflight(ui):
            time.sleep(5)
            return

        # 6. Relatorio 'antes', coletor e dados estaticos (ainda na tomada)
        ui.atualizar("Pré-voo", "Gerando o relatório de bateria e iniciando o coletor...")
        relatorios = gerar_relatorio_bateria("antes", xml=True)
        coletor = ColetorBateria()
        coletor.iniciar()
        _coletor["obj"] = coletor
        estaticos = dados_estaticos(coletor, relatorios.get("xml"))

        # 7. Aviso unico de desconexao
        fonte_antes = status_energia()["fonte"]
        resultado = aviso_desconexao(ui)
        registrar_fisicos(resultado, fonte_antes)
        if resultado == "tempo_esgotado":
            fim = "carregador_nao_desconectado"
            registrar_encerramento(fim, f"limite de {ESPERA_CARREGADOR_S}s")
            ui.atualizar("Teste não iniciado",
                         f"O carregador não foi desconectado em {ESPERA_CARREGADOR_S // 60} min.", "Veja o log")
            time.sleep(5)
            return
        if resultado != "iniciar":
            raise KeyboardInterrupt("Teste cancelado pelo operador no aviso de desconexao.")

        # 8-13. Medicao: tela ligada sem entrada simulada, estabilizacao e as duas fases
        _medicao["iniciada"] = True
        manter_tela_ligada(True)
        registrar_restauracao("Tela ligada (SetThreadExecutionState)", lambda: manter_tela_ligada(False))
        ui.atualizar("Estabilização", "Medição iniciada na bateria.", f"{ESTABILIZACAO_S // 60} min fora da medição")
        executar_medicao(ui)
        fim = motivo_encerramento()

    except KeyboardInterrupt:
        if _medicao["iniciada"]:
            _motivo_interrupcao()
        fim = motivo_encerramento() or "parada_segura"
        logger.warning(f"Execucao interrompida ({fim}).")
        ui.atualizar("Parada segura", "Interrompido pelo usuário.")

    except Exception as err:
        fim = "erro"
        registrar_encerramento("erro", f"{type(err).__name__}: {err}")
        logger.critical(f"Falha durante a execucao: {err}", exc_info=True)
        ui.atualizar("Erro", "Erro inesperado! Verifique o log.")

    finally:
        # 14-16. Pos-medicao e resultado: sempre que a medicao comecou
        if _medicao["iniciada"]:
            try:
                pos_medicao(ui)
            except Exception as e:
                logger.warning(f"Pos-medicao falhou: {type(e).__name__}: {e}")
            try:
                _exit_code = concluir_resultado(ui, estaticos)
            except Exception as e:
                _exit_code = 1
                logger.error(f"Falha ao calcular o resultado: {type(e).__name__}: {e}", exc_info=True)
            fim = motivo_encerramento() or fim
        # 17. Qualquer caminho: trace ativo, restauracao, tela, Edge, coletor
        try:
            if _wpr["ativo"]:
                parar_wpr_ativo(_wpr["fase"] or "Parcial")
        except Exception as e:
            logger.warning(f"Captura WPR: {e}")
        restaurar_tudo()
        if _medicao["iniciada"]:
            manter_tela_ligada(False)
        if _edge["aberto_pelo_teste"]:
            try:
                kill_edge()
            except Exception as e:
                logger.warning(f"Falha ao fechar o Edge: {e}")
        if _coletor["obj"]:
            _coletor["obj"].fechar()
        logger.info(f"FIM: {'PASS' if _exit_code == 0 else 'FAIL'} — {fim}")
        time.sleep(3)
        ui.fechar()


# =============================================================================
# EXECUCAO PRINCIPAL
# =============================================================================
if __name__ == "__main__":
    logger.info(f"=== Teste de Bateria (Modulo 5) — Versao {VERSAO_TESTE} ===")
    logger.info(f"Diretorio base: {BASE_DIR}")
    logger.info(f"Saida: {OUTPUT_PATH}")
    logger.info(f"Log: {LOG_FILE}")

    # Iniciar listener de parada segura
    kb_listener = kb.Listener(on_press=_on_key_press, on_release=_on_key_release)
    kb_listener.daemon = True
    kb_listener.start()
    logger.info("Listener de parada segura ativo (Ctrl+Q).")

    # Ctrl+C no console = parada segura (um KeyboardInterrupt dentro de um callback do
    # tkinter seria engolido; fora dele, encerraria o mainloop sem restaurar)
    signal.signal(signal.SIGINT, lambda signum, frame: solicitar_parada("Ctrl+C no console"))

    ui_overlay = MonitorOverlay()
    worker = threading.Thread(target=worker_thread, args=(ui_overlay,), daemon=True)
    worker.start()
    try:
        ui_overlay.root.mainloop()
    except KeyboardInterrupt:
        logger.warning("Interrupcao na thread principal: parada segura.")
    finally:
        # O mainloop so volta sozinho pelo ui.fechar() da worker. Qualquer outra saida
        # espera a worker restaurar a maquina antes de encerrar o processo (ela e daemon).
        if worker.is_alive():
            _stop_requested.set()
            ui_overlay.encerrada.set()   # pedidos de janela pendentes devolvem na hora
            espera_s = _TIMEOUT_WPR_STOP_S + 2 * TIMEOUT_EXPORTACAO_S + 15 * 60
            logger.info("Aguardando a restauracao das configuracoes antes de sair...")
            worker.join(espera_s)
            if worker.is_alive():
                logger.error(f"A worker nao terminou em {espera_s}s: restauracao pode estar incompleta "
                             "(use a coluna Antes do bateria_preflight.csv).")

    kb_listener.stop()
    logger.info("Script encerrado.")
    sys.exit(_exit_code)
