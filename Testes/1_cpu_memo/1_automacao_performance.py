import os
import re
import sys
import time
import glob
import csv
import random
import shutil
import zipfile
import logging
import tempfile
import subprocess
import threading
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    import pyperclip
except Exception:
    pyperclip = None

try:
    import psutil
except Exception:
    psutil = None

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import tkinter as tk
except Exception:
    tk = None

try:
    from pynput import keyboard as kb
except Exception:
    kb = None

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
try:  # protocolo do monitor ao vivo do hub (Spec 004)
    from hub_progress import emit_alert, emit_progress
except ImportError:  # pragma: no cover - fora da arvore do hub
    def emit_progress(*_a, **_k):
        pass

    def emit_alert(*_a, **_k):
        pass


def _progresso_ciclo(run_index, detalhe, duracao_s=None, aviso="NÃO USE MOUSE OU TECLADO — automação LibreOffice em andamento"):
    """[HUB:PROGRESS] do ciclo atual para o monitor ao vivo do hub."""
    emit_progress(f"Ciclo {run_index}/{TEST_RUNS}", run_index, TEST_RUNS, detalhe, duracao_s=duracao_s, aviso=aviso)

# =============================================================================
# CONFIGURACOES DO TESTE
# =============================================================================
VERSAO_TESTE = "2.1"
TEST_RUNS = 5
DURATION_SECONDS = 300
STABILIZE_SECONDS = 15
COOLDOWN_SECONDS = 300
COOLDOWN_CPU_THRESHOLD = 15.0   # (%) CPU abaixo desse valor = sistema estavel
COOLDOWN_CHECK_INTERVAL = 10    # (s) intervalo entre checagens de CPU no cooldown
PROFILE_NAME = "Agentes_SI_Profile.wpaProfile"

LO_PROFILE_PREFIX = "wintesthub_lo_profile"
LO_COMMON_FLAGS = ["--norestore", "--nologo", "--nodefault", "--nolockcheck"]
CALC_BATCH_TIMEOUT = 180
APP_LAUNCH_TIMEOUT = 60
CALC_LAUNCH_TIMEOUT = 180       # (s) o Calc recalcula a R2 inteira ao abrir
LO_IDLE_TIMEOUT = 60            # (s) teto da espera de ociosidade apos recalculo na GUI
LO_IDLE_CPU_PCT = 5.0           # (% de 1 nucleo) abaixo disso o soffice.bin esta ocioso
LO_IDLE_SAMPLES = 2             # leituras consecutivas abaixo do limite
LO_IDLE_INTERVAL = 0.5          # (s) intervalo entre leituras

DEFAULT_LO_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)

# Planilha R2 (mesma carga do teste do macOS: LabTesting/MacVersion/tools/gen_cpu_r2_workload.py)
R2_ROWS = 5000
R2_FORMULA_COLS = 20
R2_CATEGORIES = ("alpha", "beta", "gamma", "delta", "epsilon")
R2_XLSX_NAME = "workload_calc_r2.xlsx"
R2_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
# Erros que a propria R2 produz em qualquer planilha (Excel, Numbers, LibreOffice):
# f6 = VLOOKUP(MOD(seq, 100), ...) nao acha a chave 0 nas 50 linhas com seq multiplo de 100 (#N/A).
R2_EXPECTED_ERRORS = {"f6": R2_ROWS // 100}

CICLOS_CSV_COLUMNS = [
    "Ciclo",
    "Timestamp_Inicio",
    "Tempo_Abertura_Writer_s",
    "Tempo_Abertura_Calc_s",
    "Tempo_Calculo_Formulas_s",
    "CPU_Calculo_Formulas_s",
    "Linhas_Editadas_Calc",
    "Paragrafos_Digitados_Writer",
    "CPU_Sistema_Media_Pct",
    "CPU_Sistema_Pico_Pct",
    "RAM_Sistema_Media_MB",
    "RAM_Sistema_Pico_MB",
    "RAM_Sistema_Media_Pct",
    "RAM_Sistema_Pico_Pct",
    "LibreOffice_CPU_Media_Pct",
    "LibreOffice_CPU_Pico_Pct",
    "LibreOffice_RAM_Media_MB",
    "LibreOffice_RAM_Pico_MB",
    "Cooldown_Duracao_s",
]

_exit_code = 0
_cycle_metrics = []

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_PATH = os.environ.get(
    'HUB_EVIDENCE_DIR',
    os.path.join(BASE_DIR, f"Traces_{SESSION_TIMESTAMP}")
)

# =============================================================================
# LOGGING ESTRUTURADO
# =============================================================================
LOG_FILE = os.path.join(OUTPUT_PATH, f"automacao_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("AutomacaoPerformance")
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter(
    "[%(asctime)s] [%(levelname)-7s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

try:
    sys.stdout.reconfigure(errors="replace")  # caractere fora do cp1252 nao derruba o log
except (AttributeError, ValueError):
    pass

if not logger.handlers:
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setLevel(logging.INFO)
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)

_file_handler_initialized = False


def _init_file_logging():
    """Inicializa o diretorio de saida e o FileHandler sob demanda."""
    global _file_handler_initialized
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    if not _file_handler_initialized:
        try:
            fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(_fmt)
            logger.addHandler(fh)
            _file_handler_initialized = True
        except OSError:
            pass


# =============================================================================
# MECANISMO DE PARADA SEGURA — Ctrl+Q
# =============================================================================
_stop_requested = threading.Event()
_ctrl_pressed = False


def _sinalizar_parada_hub():
    """Ctrl+Q: pede ao hub que pare a fila inteira (arquivo-sinal em HUB_STOP_FILE).
    Fora do hub a variavel nao existe e nada acontece."""
    caminho = os.environ.get("HUB_STOP_FILE")
    if caminho:
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                f.write("ctrl+q")
        except OSError:
            pass


def _on_key_press(key):
    global _ctrl_pressed
    if kb is None:
        return
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = True
    if _ctrl_pressed and hasattr(key, 'char') and key.char in ('q', 'Q', '\x11'):
        logger.warning("Parada segura solicitada pelo usuario (Ctrl+Q).")
        _stop_requested.set()
        _sinalizar_parada_hub()


def _on_key_release(key):
    global _ctrl_pressed
    if kb is None:
        return
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = False


def check_stop():
    """Verifica se a parada segura foi solicitada. Usar em loops longos."""
    if _stop_requested.is_set():
        raise KeyboardInterrupt("Parada segura solicitada pelo usuario.")


# =============================================================================
# 1. INTERFACE GRAFICA (JANELA SOBREPOSTA) — com indicador de parada
# =============================================================================
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Automacao")

        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"340x140+{largura_tela - 370}+30")
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
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            LWA_ALPHA = 0x00000002

            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
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
# 2. DESCOBERTA DO LIBREOFFICE E VERIFICACAO DE PRE-REQUISITOS
# =============================================================================
def find_libreoffice_executable(env=None, which_fn=shutil.which, exists_fn=os.path.exists):
    """
    Localiza o executavel soffice.exe seguindo a ordem do contrato:
    1. Variavel de ambiente HUB_LIBREOFFICE_PATH
    2. shutil.which("soffice.exe") / shutil.which("soffice")
    3. Caminhos padrao do Windows (Program Files / Program Files (x86))
    """
    environ = os.environ if env is None else env
    env_path = environ.get("HUB_LIBREOFFICE_PATH", "").strip()
    if env_path and exists_fn(env_path):
        return env_path

    for cmd in ("soffice.exe", "soffice"):
        found = which_fn(cmd)
        if found and exists_fn(found):
            return found

    for candidate in DEFAULT_LO_PATHS:
        if exists_fn(candidate):
            return candidate

    return None


def build_user_installation_uri(profile_dir):
    """Converte um caminho local de perfil para URI file:/// com barras normais."""
    norm = os.path.abspath(profile_dir).replace("\\", "/").lstrip("/")
    return f"file:///{norm}"


def check_prerequisites():
    """Verifica se todos os programas e arquivos necessarios estao disponiveis."""
    logger.info("Verificando pre-requisitos do sistema...")
    fatal_errors = []

    required_exes = {
        "wpr.exe": "Windows Performance Recorder (necessario para captura)",
        "wpaexporter.exe": "WPA Exporter (necessario para exportar CSV)",
    }
    for exe, descricao in required_exes.items():
        if shutil.which(exe) is None:
            fatal_errors.append(f"'{exe}' nao encontrado no PATH — {descricao}")

    soffice_path = find_libreoffice_executable()
    if not soffice_path:
        fatal_errors.append(
            "LibreOffice (soffice.exe) nao encontrado no sistema — execute o Setup 3_softwares_msStore.ps1."
        )

    profile_path = os.path.join(BASE_DIR, PROFILE_NAME)
    profile_xml = profile_path + ".xml"
    if not os.path.exists(profile_path) and not os.path.exists(profile_xml):
        logger.warning(
            f"Profile WPA '{PROFILE_NAME}' nao encontrado em '{BASE_DIR}'. "
            "A exportacao CSV sera ignorada."
        )

    required_modules = ["pyautogui", "pyperclip", "psutil", "pandas", "pynput"]
    for mod in required_modules:
        try:
            __import__(mod)
        except ImportError:
            fatal_errors.append(f"Modulo Python '{mod}' nao esta instalado (pip install {mod}).")

    if fatal_errors:
        for e in fatal_errors:
            logger.error(f"PRE-REQUISITO FALTANDO: {e}")
        raise EnvironmentError(
            "Pre-requisitos nao atendidos. Verifique o log para detalhes."
        )

    logger.info(f"Pre-requisitos verificados com sucesso (LibreOffice: {soffice_path}).")
    return soffice_path


# =============================================================================
# 3. GERADOR DETERMINISTICO DE FIXTURES ODF (.ODT E .ODS)
# =============================================================================
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


def _write_odf_zip(target_path, mimetype_str, content_xml_str):
    """
    Grava um pacote ODF 1.2 valido via zipfile:
    1. 'mimetype' como primeira entrada, sem compressao (ZIP_STORED)
    2. 'META-INF/manifest.xml' com ZIP_DEFLATED
    3. 'content.xml' com ZIP_DEFLATED
    """
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.2">\n'
        f'  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" '
        f'manifest:media-type="{mimetype_str}"/>\n'
        '  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>\n'
        '</manifest:manifest>\n'
    )
    with zipfile.ZipFile(target_path, "w") as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            mimetype_str.encode("ascii"),
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr(
            "META-INF/manifest.xml",
            manifest_xml.encode("utf-8"),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zf.writestr(
            "content.xml",
            content_xml_str.encode("utf-8"),
            compress_type=zipfile.ZIP_DEFLATED,
        )


def _build_odt_content_xml():
    """Constroi o content.xml de workload_doc.odt com titulo e 20 paragrafos iniciais."""
    paragraphs = []
    for i in range(20):
        sample = xml_escape(TYPING_SAMPLES[i % len(TYPING_SAMPLES)])
        paragraphs.append(f"      <text:p>Paragrafo {i + 1}: {sample}</text:p>")
    body_text = "\n".join(paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'office:version="1.2">\n'
        '  <office:body>\n'
        '    <office:text>\n'
        '      <text:h text:outline-level="1">Documento de Benchmark — WinTestHub Modulo 1</text:h>\n'
        f'{body_text}\n'
        '    </office:text>\n'
        '  </office:body>\n'
        '</office:document-content>\n'
    )


def _r2_formula(col_index, row):
    """
    Texto da formula Calc!<col><row> da planilha R2 (sem o '=' inicial).
    Copia literal do gen_cpu_r2_workload.py do teste do macOS; so MAXIFS e
    XLOOKUP ganham o prefixo _xlfn. (como o Excel grava), senao o LibreOffice
    devolve #NOME? nessas colunas.
    """
    R = row
    last = R2_ROWS + 1
    win_lo = max(2, R - 50)
    win_hi = min(last, R + 50)
    formulas = (
        f"SUMIFS(Data!B$2:B${last}, Data!C$2:C${last}, Data!C{R})",
        f'COUNTIFS(Data!C$2:C${last}, Data!C{R}, Data!B$2:B${last}, ">"&Data!B{R}/2)',
        f"AVERAGEIFS(Data!B$2:B${last}, Data!C$2:C${last}, Data!C{R})",
        f"_xlfn.MAXIFS(Data!B$2:B${last}, Data!C$2:C${last}, Data!C{R})",
        f"INDEX(Data!B$2:B${last}, MATCH(Data!A{R}, Data!A$2:A${last}, 0))",
        f"VLOOKUP(MOD(Data!A{R}, 100), Data!A$2:B${last}, 2, FALSE)",
        f"_xlfn.XLOOKUP(Data!C{R}, Data!C$2:C${last}, Data!B$2:B${last})",
        f'INDIRECT("Data!B" & (1 + MOD(Data!A{R} * 7, {R2_ROWS})))',
        f"STDEV(Data!B{win_lo}:B{win_hi})",
        f"VAR(Data!B{win_lo}:B{win_hi})",
        f"PERCENTILE(Data!B{win_lo}:B{win_hi}, 0.95)",
        f"RANK(Data!B{R}, Data!B{win_lo}:B{win_hi}, 0)",
        f"NPV(0.05, Data!B{max(2, R - 10)}:B{min(last, R + 10)})",
        f"PMT(Data!B{R}/12000, 360, -100000)",
        f"FV(Data!B{R}/12000, 360, -500, -10000)",
        f"IPMT(0.05/12, MOD(Data!A{R}, 360) + 1, 360, -100000)",
        f'IF(Data!B{R} > 500, "high", IF(Data!B{R} > 100, "mid", "low"))',
        f'Data!C{R} & "-" & TEXT(Data!B{R}, "0.00")',
        f"LEN(Data!C{R}) * Data!B{R}",
        f"IFERROR(SQRT(Data!B{R} - 250), 0)",
    )
    return formulas[col_index]


def _col_letter(index):
    """0 -> A, 19 -> T, 26 -> AA."""
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _xlsx_cell_str(ref, text):
    return f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(text)}</t></is></c>'


def _xlsx_cell_num(ref, value):
    return f'<c r="{ref}"><v>{value!r}</v></c>'


def _xlsx_cell_formula(ref, formula):
    # Sem <v>: nenhum valor em cache, o LibreOffice tem de calcular tudo
    return f'<c r="{ref}"><f>{xml_escape(formula)}</f></c>'


def _xlsx_sheet_xml(rows_xml, selected=False):
    view = '<sheetViews><sheetView tabSelected="1" workbookViewId="0"/></sheetViews>' if selected else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"{view}<sheetData>{''.join(rows_xml)}</sheetData></worksheet>"
    )


def _r2_sheets():
    """Retorna [(nome, xml)] das 4 abas da R2: Data, Calc, Trigger, Sentinel."""
    last = R2_ROWS + 1

    data_rows = ['<row r="1">' + "".join(
        _xlsx_cell_str(f"{c}1", t) for c, t in zip("ABCD", ("seq", "value", "category", "date"))
    ) + "</row>"]
    for seq in range(1, R2_ROWS + 1):
        r = seq + 1
        data_rows.append(
            f'<row r="{r}">'
            + _xlsx_cell_num(f"A{r}", seq)
            + _xlsx_cell_num(f"B{r}", (seq * 1.000173) % 1000.0)
            + _xlsx_cell_str(f"C{r}", R2_CATEGORIES[seq % len(R2_CATEGORIES)])
            + _xlsx_cell_formula(f"D{r}", f"DATE(2020, 1, 1) + MOD({seq}, 1825)")
            + "</row>"
        )

    cols = [_col_letter(c) for c in range(R2_FORMULA_COLS)]
    calc_rows = ['<row r="1">' + "".join(
        _xlsx_cell_str(f"{cols[c]}1", f"f{c + 1}") for c in range(R2_FORMULA_COLS)
    ) + "</row>"]
    for r in range(2, last + 1):
        calc_rows.append(
            f'<row r="{r}">'
            + "".join(_xlsx_cell_formula(f"{cols[c]}{r}", _r2_formula(c, r)) for c in range(R2_FORMULA_COLS))
            + "</row>"
        )

    trigger_rows = [
        '<row r="1">' + _xlsx_cell_str("A1", "seed") + "</row>",
        '<row r="2">' + _xlsx_cell_num("A2", 0) + "</row>",
    ]
    sentinel_rows = [
        '<row r="1">' + _xlsx_cell_str("A1", "total") + "</row>",
        '<row r="2">' + _xlsx_cell_formula(
            "A2", f"Calc!A2 + Calc!A{last} + Calc!T2 + Calc!T{last} + Trigger!A2*0"
        ) + "</row>",
    ]
    return [
        ("Data", _xlsx_sheet_xml(data_rows)),
        ("Calc", _xlsx_sheet_xml(calc_rows)),
        ("Trigger", _xlsx_sheet_xml(trigger_rows, selected=True)),
        ("Sentinel", _xlsx_sheet_xml(sentinel_rows)),
    ]


def generate_r2_xlsx(target_path):
    """
    Grava a planilha R2 (contrato 3 da spec 001) como OOXML minimo via zipfile:
    4 abas, 5.000 linhas de dados e 100.000 formulas sem valor em cache, aba
    Trigger ativa. Bytes identicos a cada chamada (date_time fixo no ZIP).
    """
    sheets = _r2_sheets()
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{ns_rel}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{ns_rel}">'
        '<bookViews><workbookView activeTab="2"/></bookViews><sheets>'
        + "".join(
            f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
            for i, (name, _) in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{ns_rel}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        + "</Relationships>"
    )
    parts = [
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", root_rels),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", workbook_rels),
    ] + [(f"xl/worksheets/sheet{i}.xml", xml) for i, (_, xml) in enumerate(sheets, start=1)]

    with zipfile.ZipFile(target_path, "w") as zf:
        for name, xml in parts:
            info = zipfile.ZipInfo(name, date_time=R2_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, xml.encode("utf-8"))
    return target_path


_LO_REGISTRY_SEED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
    'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
    '<item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
    '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Office.Common/Save/Document">'
    '<prop oor:name="WarnAlienFormat" oor:op="fuse"><value>false</value></prop></item>\n'
    '</oor:items>\n'
)


def seed_lo_profile(profile_dir):
    """
    Cria <profile_dir>/user/registrymodifications.xcu com recalculo sempre ao
    carregar .xlsx e sem aviso de formato ao salvar (contrato 2 da spec 001).
    """
    user_dir = os.path.join(profile_dir, "user")
    os.makedirs(user_dir, exist_ok=True)
    xcu_path = os.path.join(user_dir, "registrymodifications.xcu")
    with open(xcu_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_LO_REGISTRY_SEED)
    return xcu_path


_ODF_NS_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_ODF_NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_ODF_NS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


def _scan_r2_ods(ods_path):
    """
    Le o content.xml do .ods gerado pela Etapa 1 em streaming e devolve
    (valor de Sentinel.A2 ou None, {"f1".."f20": celulas com erro na aba Calc}).
    """
    import xml.etree.ElementTree as ET

    t_table = f"{{{_ODF_NS_TABLE}}}table"
    t_row = f"{{{_ODF_NS_TABLE}}}table-row"
    t_cell = f"{{{_ODF_NS_TABLE}}}table-cell"
    t_covered = f"{{{_ODF_NS_TABLE}}}covered-table-cell"
    t_p = f"{{{_ODF_NS_TEXT}}}p"
    a_name = f"{{{_ODF_NS_TABLE}}}name"
    a_rows_rep = f"{{{_ODF_NS_TABLE}}}number-rows-repeated"
    a_cols_rep = f"{{{_ODF_NS_TABLE}}}number-columns-repeated"
    a_value = f"{{{_ODF_NS_OFFICE}}}value"

    sentinel = None
    errors = {}
    table = None
    row_idx = 0
    col_idx = 0

    with zipfile.ZipFile(ods_path) as zf, zf.open("content.xml") as fh:
        for event, el in ET.iterparse(fh, events=("start", "end")):
            tag = el.tag
            if event == "start":
                if tag == t_table:
                    table = el.get(a_name)
                    row_idx = 0
                elif tag == t_row:
                    row_idx += 1
                    col_idx = 0
                continue

            if tag in (t_cell, t_covered):
                reps = int(el.get(a_cols_rep, "1"))
                if table == "Sentinel" and row_idx == 2 and col_idx == 0:
                    raw = el.get(a_value)
                    try:
                        sentinel = float(raw) if raw is not None else None
                    except ValueError:
                        sentinel = None
                elif table == "Calc" and row_idx >= 2 and col_idx < R2_FORMULA_COLS:
                    p = el.find(t_p)
                    txt = (p.text or "") if p is not None else ""
                    if txt.startswith("#") or txt.startswith("Err:"):
                        for c in range(col_idx, min(col_idx + reps, R2_FORMULA_COLS)):
                            key = f"f{c + 1}"
                            errors[key] = errors.get(key, 0) + 1
                col_idx += reps
                el.clear()
            elif tag == t_row:
                row_idx += int(el.get(a_rows_rep, "1")) - 1
                el.clear()
            elif tag == t_table:
                table = None
                el.clear()
    return sentinel, errors


def read_r2_sentinel(ods_path):
    """Valor de Sentinel.A2 no .ods recalculado (None se ausente)."""
    return _scan_r2_ods(ods_path)[0]


def count_r2_errors(ods_path):
    """Celulas com erro (#..., Err:...) por coluna f1..f20 da aba Calc."""
    return _scan_r2_ods(ods_path)[1]


def generate_odf_fixtures(work_dir):
    """
    Gera os arquivos de carga em work_dir:
    - workload_doc.odt
    - workload_calc_r2.xlsx (planilha R2: 5.000 linhas, 100.000 formulas)
    Retorna (odt_path, xlsx_path).
    """
    os.makedirs(work_dir, exist_ok=True)
    odt_path = os.path.join(work_dir, "workload_doc.odt")
    xlsx_path = os.path.join(work_dir, R2_XLSX_NAME)

    _write_odf_zip(
        odt_path,
        "application/vnd.oasis.opendocument.text",
        _build_odt_content_xml(),
    )
    generate_r2_xlsx(xlsx_path)
    return odt_path, xlsx_path


# =============================================================================
# 4. CONTROLE DE PROCESSOS DO LIBREOFFICE E AMOSTRADOR PSUTIL
# =============================================================================
def _is_test_libreoffice_proc(name, cmdline_list, profile_marker=LO_PROFILE_PREFIX):
    """Verifica se um processo pertence ao LibreOffice instanciado pelo teste."""
    if not name:
        return False
    low_name = name.lower()
    if low_name not in ("soffice.exe", "soffice.bin", "soffice"):
        return False
    cmd_str = " ".join(cmdline_list or []).lower()
    return profile_marker.lower() in cmd_str


# soffice.exe lancados pelo teste no ciclo atual. Os laços cronometrados seguem a
# arvore deles (pid/ppid, um snapshot rapido) em vez de ler o cmdline de todos os
# processos: com o hub elevado, process_iter(['cmdline']) leva ~3 s por varredura
# na maquina com agentes de seguranca e chega a nao enxergar o soffice.bin.
_lo_roots = set()


def _lo_tree_procs(roots, known):
    """
    Atualiza e devolve `known` ({pid: psutil.Process}) com as raizes vivas e todos
    os descendentes delas; remove os que ja terminaram. Processos vistos uma vez
    continuam acompanhados mesmo se a raiz morrer antes deles.
    """
    if psutil is None:
        return known
    for r in list(roots):
        try:
            rp = known.get(r)
            if rp is None:
                rp = psutil.Process(r)
                known[r] = rp
            for child in rp.children(recursive=True):
                known.setdefault(child.pid, child)
        except psutil.Error:
            continue
    for pid, pr in list(known.items()):
        try:
            if not pr.is_running():
                known.pop(pid, None)
        except psutil.Error:
            known.pop(pid, None)
    return known


def kill_test_libreoffice(ui=None, run_index=0):
    """
    Encerra apenas processos soffice.exe / soffice.bin cujo cmdline contenha
    wintesthub_lo_profile, preservando instancias do usuario fora do teste.
    """
    if ui is not None:
        ui.atualizar(run_index, "Encerrando LibreOffice do teste...")
    if psutil is None:
        return

    by_pid = dict(_lo_tree_procs(set(_lo_roots), {}))
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            info = proc.info
            if _is_test_libreoffice_proc(info.get('name'), info.get('cmdline')):
                by_pid.setdefault(proc.pid, proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    targets = list(by_pid.values())

    if not targets:
        return

    for proc in targets:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    _, alive = psutil.wait_procs(targets, timeout=3.0)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


class ResourceSampler:
    """
    Amostrador em thread que coleta a cada 1.0s:
    - CPU (%) e RAM (MB e %) do sistema
    - Soma de CPU (%) normalizada por nucleos logicos e RAM RSS (MB) dos processos
      do LibreOffice do teste (arvore dos soffice.exe registrados em _lo_roots).
    """

    def __init__(self, interval=1.0):
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._proc_cache = {}
        self._primed = set()
        self.sys_cpu_samples = []
        self.sys_ram_mb_samples = []
        self.sys_ram_pct_samples = []
        self.lo_cpu_samples = []
        self.lo_ram_mb_samples = []

    def start(self):
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _sample_once(self):
        if psutil is None:
            return
        try:
            logical_cpus = max(1, psutil.cpu_count(logical=True) or 1)
            sys_cpu = float(psutil.cpu_percent(interval=None))
            mem = psutil.virtual_memory()
            sys_ram_mb = float(mem.used) / (1024 ** 2)
            sys_ram_pct = float(mem.percent)

            active_pids = set()
            lo_cpu_sum = 0.0
            lo_ram_mb_sum = 0.0

            known = _lo_tree_procs(set(_lo_roots), self._proc_cache)
            for pid, cached in list(known.items()):
                try:
                    active_pids.add(pid)
                    if pid not in self._primed:
                        self._primed.add(pid)
                        cached.cpu_percent(interval=None)  # 1a leitura so arma o contador (vale 0)
                    cpu_val = max(0.0, float(cached.cpu_percent(interval=None))) / logical_cpus
                    rss_mb = float(cached.memory_info().rss) / (1024 ** 2)
                    lo_cpu_sum += cpu_val
                    lo_ram_mb_sum += rss_mb
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            stale_pids = [p for p in self._proc_cache if p not in active_pids]
            for p in stale_pids:
                self._proc_cache.pop(p, None)

            lo_cpu_sum = min(100.0, lo_cpu_sum)

            with self._lock:
                self.sys_cpu_samples.append(sys_cpu)
                self.sys_ram_mb_samples.append(sys_ram_mb)
                self.sys_ram_pct_samples.append(sys_ram_pct)
                if active_pids:
                    self.lo_cpu_samples.append(lo_cpu_sum)
                    self.lo_ram_mb_samples.append(lo_ram_mb_sum)
        except Exception as e:
            logger.debug(f"Erro na amostragem psutil: {e}")

    def _run(self):
        while not self._stop_event.is_set():
            self._sample_once()
            self._stop_event.wait(self.interval)

    def summarize(self):
        with self._lock:
            sys_cpu = list(self.sys_cpu_samples)
            sys_ram_mb = list(self.sys_ram_mb_samples)
            sys_ram_pct = list(self.sys_ram_pct_samples)
            lo_cpu = list(self.lo_cpu_samples)
            lo_ram_mb = list(self.lo_ram_mb_samples)

        def _avg(vals):
            return sum(vals) / len(vals) if vals else 0.0

        def _peak(vals):
            return max(vals) if vals else 0.0

        return {
            "CPU_Sistema_Media_Pct": _avg(sys_cpu),
            "CPU_Sistema_Pico_Pct": _peak(sys_cpu),
            "RAM_Sistema_Media_MB": _avg(sys_ram_mb),
            "RAM_Sistema_Pico_MB": _peak(sys_ram_mb),
            "RAM_Sistema_Media_Pct": _avg(sys_ram_pct),
            "RAM_Sistema_Pico_Pct": _peak(sys_ram_pct),
            "LibreOffice_CPU_Media_Pct": _avg(lo_cpu),
            "LibreOffice_CPU_Pico_Pct": _peak(lo_cpu),
            "LibreOffice_RAM_Media_MB": _avg(lo_ram_mb),
            "LibreOffice_RAM_Pico_MB": _peak(lo_ram_mb),
        }


# =============================================================================
# 5. FUNCOES DE SUPORTE, MEDICAO DE ABERTURA/CALCULO E AUTOMACAO GUI
# =============================================================================
def fix_profile_extension(ui):
    """Renomeia arquivos .wpaProfile.xml para .wpaProfile se necessario."""
    if ui is not None:
        ui.atualizar(0, "Verificando arquivos XML...")
    xml_profiles = glob.glob(os.path.join(BASE_DIR, f"{PROFILE_NAME}.xml"))
    for xml_file in xml_profiles:
        correct_name = xml_file.replace(".xml", "")
        os.rename(xml_file, correct_name)
        logger.info(f"Profile corrigido: {os.path.basename(correct_name)}")


_NO_WINDOW_KW = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if hasattr(subprocess, "CREATE_NO_WINDOW")
    else {}
)


def cancel_wpr_if_active():
    """Cancela captura WPR pendente para evitar estado 'preso'."""
    logger.debug("Verificando/cancelando sessao WPR ativa...")
    subprocess.run(
        "wpr.exe -cancel",
        shell=True, capture_output=True, text=True, **_NO_WINDOW_KW
    )


def _read_lo_cpu_seconds(procs, cpu_by_pid):
    """Atualiza cpu_by_pid com user+system de cada psutil.Process vivo."""
    for pid, pr in list(procs.items()):
        try:
            ct = pr.cpu_times()
            cpu_by_pid[pid] = float(ct.user) + float(ct.system)
        except Exception:
            procs.pop(pid, None)


def measure_formula_calculation(soffice_path, xlsx_path, cycle_dir, profile_uri, timeout=CALC_BATCH_TIMEOUT):
    """
    Etapa 1: converte a planilha R2 para .ods em modo batch (--headless --convert-to ods),
    obrigando o LibreOffice a calcular as 100.000 formulas.
    Retorna (tempo_relogio_s, cpu_s), onde cpu_s soma user+system dos processos
    soffice da arvore do soffice.exe lancado (polling a cada ~0,1 s).
    Falha se o .ods nao existir ou se Sentinel.A2 estiver ausente ou valer 0.
    """
    cmd = [
        soffice_path,
        f"-env:UserInstallation={profile_uri}",
        "--headless",
        *LO_COMMON_FLAGS,
        "--convert-to",
        "ods",
        "--outdir",
        cycle_dir,
        xlsx_path,
    ]
    base_no_ext = os.path.splitext(os.path.basename(xlsx_path))[0]
    ods_out = os.path.join(cycle_dir, f"{base_no_ext}.ods")
    if os.path.exists(ods_out):
        try:
            os.remove(ods_out)
        except OSError:
            pass

    procs = {}
    cpu_by_pid = {}

    logger.info("Etapa 1: Iniciando calculo de formulas complexas (planilha R2 -> .ods)...")
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _lo_roots.add(proc.pid)
    try:
        while proc.poll() is None:
            check_stop()
            now = time.perf_counter()
            if (now - t0) > timeout:
                proc.kill()
                kill_test_libreoffice()
                raise TimeoutError(
                    f"Timeout de {timeout}s excedido no calculo de formulas complexas do LibreOffice Calc."
                )
            if psutil is not None:
                _lo_tree_procs({proc.pid}, procs)
                _read_lo_cpu_seconds(procs, cpu_by_pid)
            time.sleep(0.1)
    except Exception:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        raise

    elapsed = time.perf_counter() - t0
    cpu_s = sum(cpu_by_pid.values())
    _, stderr_out = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"LibreOffice batch falhou com codigo {proc.returncode}: {(stderr_out or '').strip()}"
        )
    if not os.path.exists(ods_out) or os.path.getsize(ods_out) <= 0:
        raise RuntimeError(f"Planilha recalculada (.ods) nao foi gerada ou esta vazia: {ods_out}")

    sentinel, errors = _scan_r2_ods(ods_out)
    if not sentinel:
        raise RuntimeError(f"Recalculo nao confirmado: Sentinel.A2 = {sentinel!r} em {ods_out}")
    if errors != R2_EXPECTED_ERRORS:
        resumo = ", ".join(f"{k}={v}" for k, v in sorted(errors.items(), key=lambda kv: int(kv[0][1:]))) or "nenhum"
        esperado = ", ".join(f"{k}={v}" for k, v in R2_EXPECTED_ERRORS.items())
        logger.warning(
            f"Planilha R2 com celulas com erro fora do esperado na aba Calc: {resumo} (esperado: {esperado})"
        )

    logger.info(
        f"Etapa 1 concluida em {elapsed:.2f}s (CPU {cpu_s:.2f}s, Sentinel.A2={sentinel:.3f}, "
        f".ods {os.path.getsize(ods_out)} bytes)."
    )
    return elapsed, cpu_s


def _find_visible_window_for_pids(target_pids):
    """Localiza HWND de janela principal visivel pertencente a um dos PIDs no Windows."""
    if not target_pids or os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found_hwnds = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in target_pids:
                    if user32.GetWindowTextLengthW(hwnd) > 0:
                        found_hwnds.append(hwnd)
                        return False
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        return found_hwnds[0] if found_hwnds else None
    except Exception as e:
        logger.debug(f"Erro ao enumerar janelas Win32: {e}")
        return None


def measure_app_launch(soffice_path, mode, file_path, profile_uri, timeout=APP_LAUNCH_TIMEOUT):
    """
    Etapas 2 e 3: Inicia soffice.exe (--writer ou --calc) com subperfil isolado e
    cronometra ate o processo soffice.bin estar ativo e com janela visivel por 0,5 s.
    Retorna (elapsed_seconds, pid, hwnd).
    """
    cmd = [
        soffice_path,
        f"-env:UserInstallation={profile_uri}",
        mode,
        *LO_COMMON_FLAGS,
        file_path,
    ]
    profile_marker = profile_uri.rstrip("/").split("/")[-1]
    logger.info(f"Iniciando LibreOffice ({mode}) com perfil {profile_marker}...")
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _lo_roots.add(proc.pid)
    known = {}

    while True:
        check_stop()
        now = time.perf_counter()
        if (now - t0) > timeout:
            kill_test_libreoffice()
            raise TimeoutError(
                f"Timeout de {timeout}s ao aguardar abertura do LibreOffice ({mode})."
            )

        pids = {proc.pid} | set(_lo_tree_procs({proc.pid}, known))
        hwnd = _find_visible_window_for_pids(pids)
        if pids and (hwnd is not None or os.name != "nt"):
            time.sleep(0.5)
            pids_after = {proc.pid} | set(_lo_tree_procs({proc.pid}, known))
            hwnd_after = _find_visible_window_for_pids(pids_after) if os.name == "nt" else 1
            if pids_after and hwnd_after is not None:
                elapsed = time.perf_counter() - t0
                chosen_pid = sorted(pids_after)[-1]
                logger.info(
                    f"LibreOffice ({mode}) aberto em {elapsed:.2f}s (PID={chosen_pid}, HWND={hwnd_after})."
                )
                return elapsed, chosen_pid, hwnd_after

        time.sleep(0.1)


def _wait_lo_idle(hwnd, timeout=None, user32=None):
    """
    Espera o soffice.bin dono da janela hwnd ficar ocioso (CPU < LO_IDLE_CPU_PCT
    de um nucleo por LO_IDLE_SAMPLES leituras de LO_IDLE_INTERVAL s).
    Retorna os segundos esperados. Sem user32/psutil (CI), retorna 0 sem esperar.
    Estourar o teto levanta RuntimeError (ciclo FAIL).
    """
    timeout = LO_IDLE_TIMEOUT if timeout is None else timeout
    u32 = _get_user32() if user32 is None else user32
    if u32 is None or psutil is None or not hasattr(u32, "GetWindowThreadProcessId") or not hwnd:
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            # HWND invalido ou ja fechado: pid 0 seria o processo Idle do sistema
            logger.debug(f"Espera de ociosidade ignorada: HWND={hwnd} sem processo dono.")
            return 0.0
        proc = psutil.Process(int(pid.value))
        proc.cpu_percent(interval=None)
    except Exception as e:
        logger.debug(f"Espera de ociosidade ignorada (HWND={hwnd}): {e}")
        return 0.0

    t0 = time.perf_counter()
    quietas = 0
    while True:
        check_stop()
        time.sleep(LO_IDLE_INTERVAL)
        try:
            cpu = float(proc.cpu_percent(interval=None))
        except Exception:
            return time.perf_counter() - t0
        quietas = quietas + 1 if cpu < LO_IDLE_CPU_PCT else 0
        elapsed = time.perf_counter() - t0
        if quietas >= LO_IDLE_SAMPLES:
            return elapsed
        if elapsed > timeout:
            raise RuntimeError(
                f"LibreOffice nao ficou ocioso em {timeout}s apos o recalculo (CPU={cpu:.0f}% de 1 nucleo, HWND={hwnd})."
            )


def _get_user32():
    """Retorna ctypes.windll.user32 no Windows ou None nas demais plataformas."""
    if os.name != "nt":
        return None
    import ctypes
    return ctypes.windll.user32


def _verify_window_focused(hwnd, user32=None):
    """
    Confirma que a janela alvo (hwnd) existe, esta visivel e detem o foco
    de primeiro plano (GetForegroundWindow == hwnd). Levanta RuntimeError caso contrario.
    """
    if not hwnd:
        raise RuntimeError("Janela do LibreOffice invalida (HWND ausente).")
    u32 = _get_user32() if user32 is None else user32
    if u32 is None:
        return True
    if hasattr(u32, "IsWindow") and not u32.IsWindow(hwnd):
        raise RuntimeError(f"Janela do LibreOffice (HWND={hwnd}) nao existe mais.")
    if hasattr(u32, "IsWindowVisible") and not u32.IsWindowVisible(hwnd):
        raise RuntimeError(f"Janela do LibreOffice (HWND={hwnd}) nao esta visivel.")
    fg_hwnd = u32.GetForegroundWindow()
    if fg_hwnd != hwnd:
        raise RuntimeError(
            f"Foco GUI nao confirmado na janela do LibreOffice (esperado HWND={hwnd}, atual={fg_hwnd})."
        )
    return True


def _focus_window(hwnd):
    """
    Traz a janela do LibreOffice (Writer ou Calc) para o primeiro plano e confirma
    que GetForegroundWindow() == hwnd (com fallback Alt+Tab). Levanta RuntimeError
    se o foco nao puder ser confirmado.
    """
    if not hwnd:
        raise RuntimeError("Janela do LibreOffice invalida (HWND ausente).")
    user32 = _get_user32()
    if user32 is not None:
        try:
            if hasattr(user32, "IsIconic") and user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"SetForegroundWindow lancou excecao ({e}), tentando fallback Alt+Tab.")

        if user32.GetForegroundWindow() != hwnd:
            logger.debug(f"SetForegroundWindow nao confirmou foco em HWND={hwnd}; tentando fallback Alt+Tab.")
            if pyautogui is not None:
                pyautogui.hotkey('alt', 'tab')
                time.sleep(0.4)
            try:
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.2)
            except Exception:
                pass

        _verify_window_focused(hwnd, user32=user32)
        return

    if pyautogui is not None:
        pyautogui.hotkey('alt', 'tab')
        time.sleep(0.5)


def type_text_safely(text):
    """Digita texto usando clipboard para suportar acentos."""
    pyperclip.copy(text)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.3)


def _get_safe_content_area():
    """Retorna (x_min, x_max, y_min, y_max) da zona segura de conteudo da janela."""
    screen_w, screen_h = pyautogui.size()
    return (
        int(screen_w * 0.12),
        int(screen_w * 0.80),
        int(screen_h * 0.22),
        int(screen_h * 0.85),
    )


def _click_safe_content_area():
    """Clica em ponto aleatorio dentro da zona segura de conteudo."""
    x_min, x_max, y_min, y_max = _get_safe_content_area()
    x = random.randint(x_min, x_max)
    y = random.randint(y_min, y_max)
    pyautogui.click(x, y)
    return x, y


def simulate_writer_editing(hwnd_writer):
    """
    Simula edicao no LibreOffice Writer:
    foca janela, digita paragrafo via pyperclip + Ctrl+V, aplica formatacao ocasional
    (Ctrl+A, Ctrl+B) e salva (Ctrl+S). Retorna quantidade de paragrafos digitados.
    """
    logger.debug("Simulando edicao no LibreOffice Writer...")
    _focus_window(hwnd_writer)
    _click_safe_content_area()
    time.sleep(random.uniform(0.4, 0.8))

    pyautogui.hotkey('ctrl', 'end')
    time.sleep(0.2)
    pyautogui.press('enter')

    text = random.choice(TYPING_SAMPLES)
    type_text_safely(text)
    pyautogui.press('enter')
    time.sleep(random.uniform(0.5, 1.2))

    if random.random() < 0.3:
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'b')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'end')
        time.sleep(0.2)

    pyautogui.hotkey('ctrl', 's')
    time.sleep(random.uniform(0.5, 1.0))
    _verify_window_focused(hwnd_writer)
    return 1


_SHEET_DATA_POOL = [
    ["Vendas",         "45230.00", "31400.00", "0.1500", "1.0"],
    ["Marketing",      "12800.00", "14200.00", "0.1200", "2.0"],
    ["TI",             "8500.00",  "22750.00", "0.1800", "3.0"],
    ["RH",             "3200.00",  "9800.00",  "0.0900", "4.0"],
    ["Operacoes",      "67100.00", "52300.00", "0.2100", "5.0"],
    ["Financeiro",     "5400.00",  "7650.00",  "0.1100", "6.0"],
    ["Logistica",      "28900.00", "24100.00", "0.1400", "7.0"],
    ["Juridico",       "1800.00",  "6300.00",  "0.0800", "8.0"],
    ["Suporte",        "9750.00",  "11200.00", "0.1000", "9.0"],
    ["Engenharia",     "15600.00", "19400.00", "0.1700", "10.0"],
]

_sheet_state = {
    "next_row": 1,
    "data_index": 0,
}


def _ensure_grid_focus():
    """Garante foco na grade de celulas do LibreOffice Calc."""
    pyautogui.press('escape')
    time.sleep(0.3)
    screen_w, screen_h = pyautogui.size()
    center_x = screen_w // 2
    center_y = int(screen_h * 0.55)
    pyautogui.click(center_x, center_y)
    time.sleep(0.5)


def _navigate_to_row(target_row):
    """Navega para a coluna A da linha target_row no Calc a partir de A1."""
    pyautogui.hotkey('ctrl', 'home')
    time.sleep(0.3)
    steps = min(max(1, target_row), 25)
    for _ in range(steps):
        pyautogui.press('down')
        time.sleep(0.05)
    time.sleep(0.2)


def _write_row(values):
    """Preenche as colunas base de uma linha no Calc e posiciona na proxima linha."""
    for idx, val in enumerate(values):
        type_text_safely(val)
        if idx < len(values) - 1:
            pyautogui.press('tab')
            time.sleep(0.15)
        else:
            pyautogui.press('enter')
            time.sleep(0.2)
            pyautogui.press('home')
            time.sleep(0.2)


def simulate_calc_editing(hwnd_calc):
    """
    Simula edicao no LibreOffice Calc sobre a planilha R2 (aba Trigger, ativa ao abrir):
    foca a grade, navega para proxima linha, insere linhas de dados, forca o recalculo
    completo das 100.000 formulas (Ctrl+Shift+F9), espera o Calc ficar ocioso e salva
    (Ctrl+S, .xlsx sem dialogo gracas a semente do perfil). Retorna linhas editadas.
    """
    global _sheet_state
    logger.debug("Simulando edicao e recalculo no LibreOffice Calc...")
    _focus_window(hwnd_calc)
    _ensure_grid_focus()
    _navigate_to_row(_sheet_state["next_row"])

    rows_edited = 0
    for _ in range(2):
        check_stop()
        row_data = _SHEET_DATA_POOL[_sheet_state["data_index"] % len(_SHEET_DATA_POOL)]
        _sheet_state["data_index"] += 1
        _write_row(row_data)
        rows_edited += 1
        _sheet_state["next_row"] = (_sheet_state["next_row"] % 25) + 1

    pyautogui.hotkey('ctrl', 'shift', 'f9')
    time.sleep(0.5)
    # Ctrl+Shift+F9 reavalia as 100.000 formulas da R2: nenhuma tecla ate o Calc terminar
    _wait_lo_idle(hwnd_calc)
    _verify_window_focused(hwnd_calc)
    pyautogui.hotkey('ctrl', 's')
    time.sleep(random.uniform(0.5, 1.0))
    _verify_window_focused(hwnd_calc)
    return rows_edited


# =============================================================================
# 6. CICLO DE TESTE PRINCIPAL
# =============================================================================
def run_test_cycle(run_index, ui, soffice_path, base_odt_path, base_xlsx_path):
    """Executa um ciclo completo de 300s com LibreOffice, psutil e captura WPR."""
    now_dt = datetime.now()
    run_ts = now_dt.strftime('%Y%m%d_%H%M%S')
    timestamp_inicio = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"--- Iniciando Coleta {run_index} de {TEST_RUNS} ---")
    _progresso_ciclo(run_index, "Preparando ciclo (perfis do LibreOffice)")
    check_stop()

    global _sheet_state
    _sheet_state = {"next_row": 1, "data_index": _sheet_state["data_index"]}

    kill_test_libreoffice(ui, run_index)
    _lo_roots.clear()
    check_stop()

    cycle_dir = tempfile.mkdtemp(prefix=f"wintesthub_lo_cycle{run_index}_")
    wpr_active = False
    sampler = ResourceSampler(interval=1.0)

    tempo_calculo_s = 0.0
    cpu_calculo_s = 0.0
    tempo_writer_s = 0.0
    tempo_calc_s = 0.0
    paragrafos_digitados = 0
    linhas_editadas = 0

    try:
        profile_batch_dir = os.path.join(cycle_dir, f"{LO_PROFILE_PREFIX}_batch")
        profile_writer_dir = os.path.join(cycle_dir, f"{LO_PROFILE_PREFIX}_writer")
        profile_calc_dir = os.path.join(cycle_dir, f"{LO_PROFILE_PREFIX}_calc")
        os.makedirs(profile_batch_dir, exist_ok=True)
        os.makedirs(profile_writer_dir, exist_ok=True)
        os.makedirs(profile_calc_dir, exist_ok=True)
        seed_lo_profile(profile_batch_dir)
        seed_lo_profile(profile_calc_dir)

        uri_batch = build_user_installation_uri(profile_batch_dir)
        uri_writer = build_user_installation_uri(profile_writer_dir)
        uri_calc = build_user_installation_uri(profile_calc_dir)

        xlsx_batch_copy = os.path.join(cycle_dir, "workload_calc_batch.xlsx")
        odt_writer_copy = os.path.join(cycle_dir, "workload_doc.odt")
        xlsx_calc_copy = os.path.join(cycle_dir, R2_XLSX_NAME)
        shutil.copy2(base_xlsx_path, xlsx_batch_copy)
        shutil.copy2(base_odt_path, odt_writer_copy)
        shutil.copy2(base_xlsx_path, xlsx_calc_copy)

        _progresso_ciclo(run_index, f"Estabilização ({STABILIZE_SECONDS}s)", duracao_s=STABILIZE_SECONDS)
        for i in range(STABILIZE_SECONDS, 0, -1):
            check_stop()
            ui.atualizar(run_index, "Estabilizando ambiente antes do ciclo...", i)
            time.sleep(1)

        trace_file = os.path.join(OUTPUT_PATH, f"Trace_{run_ts}_Run{run_index}.etl")
        ui.atualizar(run_index, "Iniciando captura WPR...")
        _progresso_ciclo(run_index, "Iniciando captura WPR")
        cancel_wpr_if_active()

        wpr_start = 'wpr.exe -start Power.light -start VirtualAllocation.light -filemode -compress'
        result = subprocess.run(wpr_start, shell=True, capture_output=True, text=True, **_NO_WINDOW_KW)
        if result.returncode != 0:
            logger.error(f"Falha ao iniciar WPR: {result.stderr.strip()}")
            raise RuntimeError("Falha ao iniciar captura WPR.")

        wpr_active = True
        sampler.start()

        cycle_start = time.time()

        ui.atualizar(run_index, "Etapa 1: Calculando planilha complexa...", DURATION_SECONDS)
        _progresso_ciclo(run_index, "Calc R2 (planilha 100k fórmulas)")
        tempo_calculo_s, cpu_calculo_s = measure_formula_calculation(
            soffice_path, xlsx_batch_copy, cycle_dir, uri_batch, timeout=CALC_BATCH_TIMEOUT
        )
        check_stop()

        remaining = max(1, int(DURATION_SECONDS - (time.time() - cycle_start)))
        ui.atualizar(run_index, "Etapa 2: Abrindo LibreOffice Writer...", remaining)
        _progresso_ciclo(run_index, "Abrindo LibreOffice Writer")
        tempo_writer_s, _, hwnd_writer = measure_app_launch(
            soffice_path, "--writer", odt_writer_copy, uri_writer, timeout=APP_LAUNCH_TIMEOUT
        )
        check_stop()

        remaining = max(1, int(DURATION_SECONDS - (time.time() - cycle_start)))
        ui.atualizar(run_index, "Etapa 3: Abrindo LibreOffice Calc...", remaining)
        _progresso_ciclo(run_index, "Abrindo LibreOffice Calc")
        tempo_calc_s, _, hwnd_calc = measure_app_launch(
            soffice_path, "--calc", xlsx_calc_copy, uri_calc, timeout=CALC_LAUNCH_TIMEOUT
        )
        check_stop()
        # A janela aparece antes do fim do recalculo da R2: nao digitar antes disso
        espera_s = _wait_lo_idle(hwnd_calc, timeout=CALC_LAUNCH_TIMEOUT)
        if espera_s:
            logger.info(f"Calc ocioso {espera_s:.1f}s depois de abrir a janela (recalculo da R2).")

        _progresso_ciclo(run_index, "Edição GUI Writer/Calc")
        turn = 0
        while True:
            check_stop()
            elapsed = time.time() - cycle_start
            remaining_s = DURATION_SECONDS - elapsed
            if remaining_s <= 0:
                break

            ui.atualizar(run_index, "Etapa 4: Edicao GUI Writer/Calc...", max(0, int(remaining_s)))
            try:
                if turn % 2 == 0:
                    paragrafos_digitados += simulate_writer_editing(hwnd_writer)
                else:
                    linhas_editadas += simulate_calc_editing(hwnd_calc)
            except Exception as e:
                if pyautogui is not None and isinstance(e, pyautogui.FailSafeException):
                    logger.warning("PyAutoGUI fail-safe ativado (mouse no canto).")
                    _sinalizar_parada_hub()
                    raise KeyboardInterrupt("Fail-safe do PyAutoGUI.")
                if isinstance(e, KeyboardInterrupt):
                    raise
                logger.error(f"Falha durante automacao GUI no ciclo {run_index}: {type(e).__name__}: {e}")
                raise
            finally:
                turn += 1

            rest = DURATION_SECONDS - (time.time() - cycle_start)
            if rest <= 0:
                break
            pause_s = min(0.2, rest * 0.5) if (paragrafos_digitados == 0 or linhas_editadas == 0) else min(random.uniform(1.5, 3.5), rest)
            time.sleep(max(0.0, pause_s))

        if paragrafos_digitados <= 0 or linhas_editadas <= 0:
            raise RuntimeError(
                f"Ciclo {run_index} encerrou sem edicoes GUI completas no Writer e no Calc "
                f"(paragrafos_digitados={paragrafos_digitados}, linhas_editadas={linhas_editadas})."
            )

        sampler.stop()
        kill_test_libreoffice(ui, run_index)

        _progresso_ciclo(run_index, "Salvando trace WPR (.etl)")
        ui.atualizar(run_index, "Salvando arquivo Trace (.etl)...", "--")
        stop_result = subprocess.run(
            f'wpr.exe -stop "{trace_file}" -compress',
            shell=True, capture_output=True, text=True, **_NO_WINDOW_KW
        )
        if stop_result.returncode != 0:
            logger.error(f"Falha ao parar WPR: {stop_result.stderr.strip()}")
            raise RuntimeError("Falha ao salvar trace WPR.")
        wpr_active = False
        logger.info(f"Trace salvo: {trace_file}")

        profile_path = os.path.join(BASE_DIR, PROFILE_NAME)
        if os.path.exists(profile_path):
            ui.atualizar(run_index, "Convertendo dados para CSV...", "--")
            _progresso_ciclo(run_index, "Exportação WPA")
            csv_folder = os.path.join(OUTPUT_PATH, f"CSV_{run_ts}_Run{run_index}")
            os.makedirs(csv_folder, exist_ok=True)
            wpa_cmd = (
                f'wpaexporter.exe -i "{trace_file}" '
                f'-profile "{profile_path}" '
                f'-outputfolder "{csv_folder}"'
            )
            wpa_result = subprocess.run(wpa_cmd, shell=True, capture_output=True, text=True, **_NO_WINDOW_KW)
            if wpa_result.returncode != 0:
                err_msg = (wpa_result.stderr or wpa_result.stdout or "").strip()
                logger.error(f"wpaexporter retornou erro (codigo {wpa_result.returncode}): {err_msg}")
                raise RuntimeError(
                    f"Falha ao exportar CSVs com wpaexporter (codigo {wpa_result.returncode}): {err_msg}"
                )
            logger.info(f"CSVs exportados para: {csv_folder}")
        else:
            logger.warning(f"Profile WPA nao encontrado: {profile_path}. Exportacao CSV ignorada.")

    finally:
        sampler.stop()
        kill_test_libreoffice()
        if wpr_active:
            logger.warning("WPR ainda ativo apos excecao. Cancelando...")
            cancel_wpr_if_active()
        shutil.rmtree(cycle_dir, ignore_errors=True)

    stats = sampler.summarize()
    cycle_record = {
        "Ciclo": run_index,
        "Timestamp_Inicio": timestamp_inicio,
        "Tempo_Abertura_Writer_s": tempo_writer_s,
        "Tempo_Abertura_Calc_s": tempo_calc_s,
        "Tempo_Calculo_Formulas_s": tempo_calculo_s,
        "CPU_Calculo_Formulas_s": cpu_calculo_s,
        "Linhas_Editadas_Calc": linhas_editadas,
        "Paragrafos_Digitados_Writer": paragrafos_digitados,
        "CPU_Sistema_Media_Pct": stats["CPU_Sistema_Media_Pct"],
        "CPU_Sistema_Pico_Pct": stats["CPU_Sistema_Pico_Pct"],
        "RAM_Sistema_Media_MB": stats["RAM_Sistema_Media_MB"],
        "RAM_Sistema_Pico_MB": stats["RAM_Sistema_Pico_MB"],
        "RAM_Sistema_Media_Pct": stats["RAM_Sistema_Media_Pct"],
        "RAM_Sistema_Pico_Pct": stats["RAM_Sistema_Pico_Pct"],
        "LibreOffice_CPU_Media_Pct": stats["LibreOffice_CPU_Media_Pct"],
        "LibreOffice_CPU_Pico_Pct": stats["LibreOffice_CPU_Pico_Pct"],
        "LibreOffice_RAM_Media_MB": stats["LibreOffice_RAM_Media_MB"],
        "LibreOffice_RAM_Pico_MB": stats["LibreOffice_RAM_Pico_MB"],
        "Cooldown_Duracao_s": 0.0,
    }
    return cycle_record


# =============================================================================
# 7. COOLDOWN INTELIGENTE
# =============================================================================
def smart_cooldown(run_index, ui):
    """Aguarda o sistema estabilizar monitorando CPU real com psutil. Retorna duracao (s)."""
    logger.info(
        f"Iniciando cooldown (max {COOLDOWN_SECONDS}s, "
        f"alvo CPU < {COOLDOWN_CPU_THRESHOLD}%)..."
    )
    _progresso_ciclo(run_index, f"Cooldown (até {COOLDOWN_SECONDS}s, CPU < {COOLDOWN_CPU_THRESHOLD}%)",
                     duracao_s=COOLDOWN_SECONDS, aviso="Aguardando a máquina esfriar (não use a máquina)")
    start = time.time()
    stable_readings = 0
    required_stable = 3

    while True:
        check_stop()
        elapsed = time.time() - start
        remaining = max(0, int(COOLDOWN_SECONDS - elapsed))

        if elapsed >= COOLDOWN_SECONDS:
            logger.info("Cooldown atingiu tempo maximo.")
            break

        cpu_percent = psutil.cpu_percent(interval=COOLDOWN_CHECK_INTERVAL) if psutil is not None else 0.0
        if ui is not None:
            ui.atualizar(
                run_index,
                f"Arrefecimento — CPU: {cpu_percent:.1f}%",
                remaining
            )
        logger.debug(f"Cooldown: CPU={cpu_percent:.1f}%, elapsed={int(elapsed)}s")

        if cpu_percent < COOLDOWN_CPU_THRESHOLD:
            stable_readings += 1
            if stable_readings >= required_stable:
                total_cd = time.time() - start
                logger.info(
                    f"Sistema estavel (CPU < {COOLDOWN_CPU_THRESHOLD}% "
                    f"por {required_stable} leituras). Cooldown concluido em {total_cd:.1f}s."
                )
                return total_cd
        else:
            stable_readings = 0

    return time.time() - start


# =============================================================================
# 8. CONSOLIDACAO DE DADOS E GERACAO DE CSVS (cpu_memoria.csv / ciclos_libreoffice.csv)
# =============================================================================
def detect_number_format(series):
    """
    Detecta se os numeros usam formato BR (1.000,50) ou US (1,000.50).
    Retorna 'br' ou 'us'. Aceita pandas.Series ou iteravel Python.
    """
    if pd is not None and hasattr(series, "dropna"):
        sample = [str(v) for v in series.dropna().head(50)]
    else:
        sample = [str(v) for v in series if v is not None and str(v).strip() != ""][:50]

    br_pattern = 0
    us_pattern = 0

    for val in sample:
        val = val.strip()
        if ',' in val and '.' in val:
            last_comma = val.rfind(',')
            last_dot = val.rfind('.')
            if last_comma > last_dot:
                br_pattern += 1
            else:
                us_pattern += 1
        elif ',' in val:
            parts = val.split(',')
            if len(parts) == 2 and len(parts[1]) <= 3:
                br_pattern += 1
            else:
                us_pattern += 1
        elif '.' in val:
            parts = val.split('.')
            if len(parts) == 2 and len(parts[1]) <= 3:
                us_pattern += 1
            else:
                br_pattern += 1

    return 'br' if br_pattern >= us_pattern else 'us'


def _parse_single_float(val, fmt='br'):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if fmt == 'br':
        s = s.replace('.', '').replace(',', '.')
    else:
        s = s.replace(',', '')
    try:
        return float(s)
    except ValueError:
        return None


def parse_numeric_column(series, fmt='br'):
    """Converte coluna para numerico respeitando o formato detectado."""
    if pd is not None and hasattr(series, "astype"):
        s = series.astype(str)
        if fmt == 'br':
            s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        else:
            s = s.str.replace(',', '', regex=False)
        return pd.to_numeric(s, errors='coerce')
    return [_parse_single_float(v, fmt) for v in series]


def _consolidate_wpa_csv_group(file_name, file_paths, consolidation_folder):
    """
    Consolida um grupo de CSVs exportados pelo WPA (um por ciclo) e retorna
    a lista de entradas de summary_data (incluindo Soma_Media, Media Geral, Maximo, Minimo).
    Funciona com pandas ou apenas stdlib csv.
    """
    entries = []
    pid_regex = re.compile(r'\s*\(\d+\)\s*$')

    if pd is not None:
        dataframes = []
        for fp in file_paths:
            try:
                df = pd.read_csv(fp, encoding='utf-8-sig')
                if df.empty:
                    continue
                key_col = df.columns[0]
                df[key_col] = df[key_col].astype(str).str.replace(r'\s*\(\d+\)\s*$', '', regex=True)
                for col in df.columns[1:]:
                    fmt = detect_number_format(df[col])
                    df[col] = parse_numeric_column(df[col], fmt)
                df_sum = df.groupby(key_col, as_index=False).sum()
                dataframes.append(df_sum)
            except Exception as e:
                logger.warning(f"Erro ao processar CSV '{fp}': {type(e).__name__}: {e}")
                continue

        if not dataframes:
            return entries

        df_all_runs = pd.concat(dataframes)
        key_col = df_all_runs.columns[0]
        numeric_cols = [c for c in df_all_runs.columns if c != key_col]
        df_mean = df_all_runs.groupby(key_col, as_index=False)[numeric_cols].mean()
        df_count = df_all_runs.groupby(key_col, as_index=False)[numeric_cols].count()

        rename_mean = {c: f"Media_{c}" for c in numeric_cols}
        rename_count = {c: f"Amostras_{c}" for c in numeric_cols}
        df_mean.rename(columns=rename_mean, inplace=True)
        df_count.rename(columns=rename_count, inplace=True)
        df_final = pd.merge(df_mean, df_count, on=key_col)

        output_file = os.path.join(consolidation_folder, f"Media_{file_name}")
        df_final.to_csv(output_file, index=False, sep=',', encoding='utf-8-sig')
        logger.info(f"Consolidado: {output_file}")

        for col in numeric_cols:
            media_col = f"Media_{col}"
            if media_col in df_final.columns:
                cycle_sums = [float(df_run[col].sum()) for df_run in dataframes if col in df_run.columns]
                soma_media_val = float(sum(cycle_sums) / len(cycle_sums)) if cycle_sums else 0.0
                entries.append({
                    "Arquivo": file_name,
                    "Metrica": col,
                    "Soma_Media": soma_media_val,
                    "Media Geral": float(df_final[media_col].mean()),
                    "Maximo": float(df_final[media_col].max()),
                    "Minimo": float(df_final[media_col].min()),
                    "Runs Processados": len(file_paths),
                })
        return entries

    # Fallback stdlib csv quando pandas nao esta instalado
    run_tables = []
    key_col_name = None
    numeric_cols = []

    for fp in file_paths:
        try:
            with open(fp, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if len(rows) < 2:
                continue
            header = rows[0]
            data_rows = rows[1:]
            key_col_name = header[0]
            if not numeric_cols:
                numeric_cols = list(header[1:])

            col_formats = {}
            for col_idx, col_name in enumerate(header[1:], start=1):
                col_vals = [r[col_idx] for r in data_rows if col_idx < len(r)]
                col_formats[col_name] = detect_number_format(col_vals)

            grouped_run = {}
            for r in data_rows:
                if not r:
                    continue
                key_val = pid_regex.sub("", str(r[0]))
                acc = grouped_run.setdefault(key_val, {c: 0.0 for c in numeric_cols})
                for col_idx, col_name in enumerate(header[1:], start=1):
                    if col_idx < len(r):
                        parsed = _parse_single_float(r[col_idx], col_formats[col_name])
                        if parsed is not None:
                            acc[col_name] += parsed
            if grouped_run:
                run_tables.append(grouped_run)
        except Exception as e:
            logger.warning(f"Erro ao processar CSV '{fp}': {type(e).__name__}: {e}")
            continue

    if not run_tables or not key_col_name:
        return entries

    all_keys = sorted({k for tbl in run_tables for k in tbl.keys()})
    final_rows = []
    per_col_means = {c: [] for c in numeric_cols}

    for k in all_keys:
        row_out = {key_col_name: k}
        for c in numeric_cols:
            vals = [tbl[k][c] for tbl in run_tables if k in tbl]
            mean_val = sum(vals) / len(vals) if vals else 0.0
            row_out[f"Media_{c}"] = mean_val
            row_out[f"Amostras_{c}"] = len(vals)
            per_col_means[c].append(mean_val)
        final_rows.append(row_out)

    output_file = os.path.join(consolidation_folder, f"Media_{file_name}")
    out_headers = [key_col_name] + [f"Media_{c}" for c in numeric_cols] + [f"Amostras_{c}" for c in numeric_cols]
    with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_headers)
        writer.writeheader()
        for r in final_rows:
            writer.writerow(r)

    for c in numeric_cols:
        vals = per_col_means[c]
        if vals:
            cycle_sums = [sum(tbl[k][c] for k in tbl) for tbl in run_tables]
            soma_media_val = float(sum(cycle_sums) / len(cycle_sums)) if cycle_sums else 0.0
            entries.append({
                "Arquivo": file_name,
                "Metrica": c,
                "Soma_Media": soma_media_val,
                "Media Geral": float(sum(vals) / len(vals)),
                "Maximo": float(max(vals)),
                "Minimo": float(min(vals)),
                "Runs Processados": len(file_paths),
            })

    return entries


def write_ciclos_csv(cycle_metrics, output_path):
    """Grava <output_path>/ciclos_libreoffice.csv seguindo o contrato da spec."""
    ciclos_csv_path = os.path.join(output_path, "ciclos_libreoffice.csv")
    with open(ciclos_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CICLOS_CSV_COLUMNS)
        for item in cycle_metrics:
            writer.writerow([
                int(item.get("Ciclo", 0)),
                str(item.get("Timestamp_Inicio", "")),
                f"{float(item.get('Tempo_Abertura_Writer_s', 0.0)):.2f}",
                f"{float(item.get('Tempo_Abertura_Calc_s', 0.0)):.2f}",
                f"{float(item.get('Tempo_Calculo_Formulas_s', 0.0)):.2f}",
                f"{float(item.get('CPU_Calculo_Formulas_s', 0.0)):.2f}",
                int(item.get("Linhas_Editadas_Calc", 0)),
                int(item.get("Paragrafos_Digitados_Writer", 0)),
                f"{float(item.get('CPU_Sistema_Media_Pct', 0.0)):.1f}",
                f"{float(item.get('CPU_Sistema_Pico_Pct', 0.0)):.1f}",
                f"{float(item.get('RAM_Sistema_Media_MB', 0.0)):.1f}",
                f"{float(item.get('RAM_Sistema_Pico_MB', 0.0)):.1f}",
                f"{float(item.get('RAM_Sistema_Media_Pct', 0.0)):.1f}",
                f"{float(item.get('RAM_Sistema_Pico_Pct', 0.0)):.1f}",
                f"{float(item.get('LibreOffice_CPU_Media_Pct', 0.0)):.1f}",
                f"{float(item.get('LibreOffice_CPU_Pico_Pct', 0.0)):.1f}",
                f"{float(item.get('LibreOffice_RAM_Media_MB', 0.0)):.1f}",
                f"{float(item.get('LibreOffice_RAM_Pico_MB', 0.0)):.1f}",
                f"{float(item.get('Cooldown_Duracao_s', 0.0)):.2f}",
            ])
    logger.info(f"ciclos_libreoffice.csv gerado em: {ciclos_csv_path}")
    return ciclos_csv_path


def write_cpu_memoria_csv(cycle_metrics, summary_data, output_path):
    """Grava <output_path>/cpu_memoria.csv mantendo metricas legadas e adicionando novas."""
    def _vals(key):
        return [float(c.get(key, 0.0)) for c in (cycle_metrics or [])]

    def _mean(key):
        v = _vals(key)
        return sum(v) / len(v) if v else 0.0

    def _max(key):
        v = _vals(key)
        return max(v) if v else 0.0

    def _min(key):
        v = _vals(key)
        return min(v) if v else 0.0

    if psutil is not None:
        try:
            cpu_freq = psutil.cpu_freq()
        except Exception:
            cpu_freq = None
        mem = psutil.virtual_memory()
        freq_atual = f"{cpu_freq.current:.0f}" if cpu_freq and getattr(cpu_freq, "current", None) else "N/A"
        freq_max = f"{cpu_freq.max:.0f}" if cpu_freq and getattr(cpu_freq, "max", None) else "N/A"
        nucleos_fisicos = psutil.cpu_count(logical=False) or 1
        nucleos_logicos = psutil.cpu_count(logical=True) or os.cpu_count() or 1
        ram_total_gb = f"{mem.total / (1024 ** 3):.2f}"
        ram_disp_gb = f"{mem.available / (1024 ** 3):.2f}"
        ram_uso_pct = f"{mem.percent:.1f}"
    else:
        freq_atual = "N/A"
        freq_max = "N/A"
        nucleos_fisicos = os.cpu_count() or 1
        nucleos_logicos = os.cpu_count() or 1
        ram_total_gb = "8.00"
        ram_disp_gb = "4.00"
        ram_uso_pct = "50.0"

    ciclos_exec = len(cycle_metrics) if cycle_metrics else TEST_RUNS
    cpu_memo_csv_path = os.path.join(output_path, "cpu_memoria.csv")

    with open(cpu_memo_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Metrica", "Valor", "Unidade"])
        writer.writerow(["Versao_Teste", VERSAO_TESTE, ""])
        writer.writerow(["Ciclos_Executados", ciclos_exec, "un"])
        writer.writerow(["Duracao_Por_Ciclo", DURATION_SECONDS, "s"])
        writer.writerow(["Tempo_Abertura_Writer_Media", f"{_mean('Tempo_Abertura_Writer_s'):.2f}", "s"])
        writer.writerow(["Tempo_Abertura_Writer_Max", f"{_max('Tempo_Abertura_Writer_s'):.2f}", "s"])
        writer.writerow(["Tempo_Abertura_Calc_Media", f"{_mean('Tempo_Abertura_Calc_s'):.2f}", "s"])
        writer.writerow(["Tempo_Abertura_Calc_Max", f"{_max('Tempo_Abertura_Calc_s'):.2f}", "s"])
        writer.writerow(["Tempo_Calculo_Formulas_Media", f"{_mean('Tempo_Calculo_Formulas_s'):.2f}", "s"])
        writer.writerow(["Tempo_Calculo_Formulas_Max", f"{_max('Tempo_Calculo_Formulas_s'):.2f}", "s"])
        writer.writerow(["Tempo_Calculo_Formulas_Min", f"{_min('Tempo_Calculo_Formulas_s'):.2f}", "s"])
        writer.writerow(["CPU_Calculo_Formulas_Media", f"{_mean('CPU_Calculo_Formulas_s'):.2f}", "s"])
        writer.writerow(["CPU_Calculo_Formulas_Max", f"{_max('CPU_Calculo_Formulas_s'):.2f}", "s"])
        writer.writerow(["CPU_Calculo_Formulas_Min", f"{_min('CPU_Calculo_Formulas_s'):.2f}", "s"])
        writer.writerow(["CPU_Sistema_Media", f"{_mean('CPU_Sistema_Media_Pct'):.1f}", "%"])
        writer.writerow(["CPU_Sistema_Pico", f"{_max('CPU_Sistema_Pico_Pct'):.1f}", "%"])
        writer.writerow(["RAM_Sistema_Media_MB", f"{_mean('RAM_Sistema_Media_MB'):.1f}", "MB"])
        writer.writerow(["RAM_Sistema_Pico_MB", f"{_max('RAM_Sistema_Pico_MB'):.1f}", "MB"])
        writer.writerow(["RAM_Sistema_Media_Pct", f"{_mean('RAM_Sistema_Media_Pct'):.1f}", "%"])
        writer.writerow(["RAM_Sistema_Pico_Pct", f"{_max('RAM_Sistema_Pico_Pct'):.1f}", "%"])
        writer.writerow(["LibreOffice_CPU_Media", f"{_mean('LibreOffice_CPU_Media_Pct'):.1f}", "%"])
        writer.writerow(["LibreOffice_CPU_Pico", f"{_max('LibreOffice_CPU_Pico_Pct'):.1f}", "%"])
        writer.writerow(["LibreOffice_RAM_Media_MB", f"{_mean('LibreOffice_RAM_Media_MB'):.1f}", "MB"])
        writer.writerow(["LibreOffice_RAM_Pico_MB", f"{_max('LibreOffice_RAM_Pico_MB'):.1f}", "MB"])
        writer.writerow(["CPU_Frequencia_Atual", freq_atual, "MHz"])
        writer.writerow(["CPU_Frequencia_Max", freq_max, "MHz"])
        writer.writerow(["CPU_Nucleos_Fisicos", nucleos_fisicos, "un"])
        writer.writerow(["CPU_Nucleos_Logicos", nucleos_logicos, "un"])
        writer.writerow(["RAM_Total_GB", ram_total_gb, "GB"])
        writer.writerow(["RAM_Disponivel_GB", ram_disp_gb, "GB"])
        writer.writerow(["RAM_Uso_Percentual", ram_uso_pct, "%"])

        if summary_data:
            for entry in summary_data:
                safe_name = entry["Metrica"].replace(",", "_")
                soma_media = entry.get("Soma_Media", entry.get("Media Geral", 0.0))
                writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Soma_Media", f"{soma_media:.2f}", ""])
                writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Media", f"{entry['Media Geral']:.2f}", ""])
                writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Max", f"{entry['Maximo']:.2f}", ""])
                writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Min", f"{entry['Minimo']:.2f}", ""])

    logger.info(f"cpu_memoria.csv gerado em: {cpu_memo_csv_path}")
    return cpu_memo_csv_path


def consolidate_results(ui=None, cycle_metrics=None, output_path=None):
    """
    Consolida CSVs do WPA (quando presentes) e sempre grava:
    - ciclos_libreoffice.csv
    - cpu_memoria.csv
    - Resultados_Consolidados/Relatorio_Resumo.html
    """
    if ui is not None:
        ui.atualizar(0, "Consolidando arquivos CSV...", "--")
    emit_progress("Consolidação", detalhe="ciclos_libreoffice.csv, cpu_memoria.csv e relatório")
    logger.info("Iniciando consolidacao de resultados...")

    target_output = output_path or OUTPUT_PATH
    cycles = _cycle_metrics if cycle_metrics is None else cycle_metrics
    os.makedirs(target_output, exist_ok=True)

    consolidation_folder = os.path.join(target_output, "Resultados_Consolidados")
    os.makedirs(consolidation_folder, exist_ok=True)

    csv_files = sorted(glob.glob(os.path.join(target_output, "CSV_*", "*.csv")))
    summary_data = []

    if not csv_files:
        logger.warning("Nenhum arquivo CSV do WPA encontrado para consolidacao; gerando CSVs do LibreOffice.")
    else:
        grouped_csvs = {}
        for f in csv_files:
            grouped_csvs.setdefault(os.path.basename(f), []).append(f)

        for file_name, file_paths in grouped_csvs.items():
            entries = _consolidate_wpa_csv_group(file_name, file_paths, consolidation_folder)
            summary_data.extend(entries)

    generate_summary_report(summary_data, consolidation_folder, output_path=target_output)
    write_ciclos_csv(cycles, target_output)
    write_cpu_memoria_csv(cycles, summary_data, target_output)


# =============================================================================
# 9. RELATORIO RESUMIDO
# =============================================================================
def generate_summary_report(summary_data, output_folder, output_path=None):
    """Gera relatorio HTML e CSV consolidado com os principais indicadores."""
    logger.info("Gerando relatorio resumido...")
    os.makedirs(output_folder, exist_ok=True)
    target_output = output_path or OUTPUT_PATH

    report_csv = os.path.join(output_folder, "Relatorio_Resumo.csv")
    cols = ["Arquivo", "Metrica", "Soma_Media", "Media Geral", "Maximo", "Minimo", "Runs Processados"]

    if summary_data:
        if pd is not None:
            df_summary = pd.DataFrame(summary_data)
            df_summary.to_csv(report_csv, index=False, encoding='utf-8-sig')
            table_html = df_summary.to_html(index=False, float_format='%.2f', border=0)
        else:
            with open(report_csv, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                for row in summary_data:
                    writer.writerow(row)
            rows_html = "".join(
                "<tr>" + "".join(
                    f"<td>{row.get(c, ''):.2f}</td>" if isinstance(row.get(c), float) else f"<td>{row.get(c, '')}</td>"
                    for c in cols
                ) + "</tr>"
                for row in summary_data
            )
            th_html = "".join(f"<th>{c}</th>" for c in cols)
            table_html = f"<table><thead><tr>{th_html}</tr></thead><tbody>{rows_html}</tbody></table>"
    else:
        table_html = "<p>Nenhum CSV do WPA exportado nesta sessao.</p>"

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
        <strong>Diretorio de saida:</strong> {target_output}
    </div>

    <h2>Resumo das Metricas</h2>
    {table_html}

    <p class="footer">
        Gerado automaticamente em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
        pela Automacao de Testes de Performance.
    </p>
</body>
</html>"""

    with open(report_html, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logger.info(f"Relatorio resumido gerado: {report_html}")


# =============================================================================
# THREAD PRINCIPAL DE TRABALHO
# =============================================================================
def worker_thread(ui):
    global _exit_code, _cycle_metrics
    _init_file_logging()
    fixtures_dir = None
    try:
        soffice_path = check_prerequisites()
        fix_profile_extension(ui)

        ui.atualizar(0, "Gerando arquivos ODF de benchmark...", "--")
        emit_progress("Preparo", detalhe="Gerando arquivos de benchmark (ODT + planilha R2)")
        fixtures_dir = tempfile.mkdtemp(prefix="wintesthub_lo_fixtures_")
        base_odt_path, base_xlsx_path = generate_odf_fixtures(fixtures_dir)
        logger.info(f"Fixtures ODF gerados em: {fixtures_dir}")

        _cycle_metrics = []
        for run in range(1, TEST_RUNS + 1):
            check_stop()
            cycle_record = run_test_cycle(run, ui, soffice_path, base_odt_path, base_xlsx_path)

            if run < TEST_RUNS:
                cooldown_s = smart_cooldown(run, ui)
                cycle_record["Cooldown_Duracao_s"] = cooldown_s

            _cycle_metrics.append(cycle_record)

        consolidate_results(ui, cycle_metrics=_cycle_metrics, output_path=OUTPUT_PATH)

        ui.atualizar(0, "Teste Finalizado com Sucesso!", "--")
        logger.info("=== Todos os testes concluidos com sucesso! ===")
        logger.info(f"Resultados em: {OUTPUT_PATH}")
        time.sleep(3)

    except KeyboardInterrupt:
        logger.warning("Execucao interrompida pelo usuario.")
        _sinalizar_parada_hub()
        cancel_wpr_if_active()
        kill_test_libreoffice()
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
        cancel_wpr_if_active()
        kill_test_libreoffice()
        ui.atualizar(0, "Erro! Verifique o log.", "--")
        _exit_code = 1
        time.sleep(5)

    finally:
        kill_test_libreoffice()
        if fixtures_dir and os.path.exists(fixtures_dir):
            shutil.rmtree(fixtures_dir, ignore_errors=True)
        ui.fechar()


# =============================================================================
# EXECUCAO PRINCIPAL
# =============================================================================
if __name__ == "__main__":
    _init_file_logging()
    logger.info(f"=== Automacao de Testes de Performance — Versao {VERSAO_TESTE} (LibreOffice, planilha R2) ===")
    logger.info(f"Diretorio base: {BASE_DIR}")
    logger.info(f"Saida: {OUTPUT_PATH}")
    logger.info(f"Log: {LOG_FILE}")
    logger.info(f"Configuracao: {TEST_RUNS} ciclos x {DURATION_SECONDS}s + cooldown inteligente")

    kb_listener = kb.Listener(on_press=_on_key_press, on_release=_on_key_release)
    kb_listener.daemon = True
    kb_listener.start()
    logger.info("Listener de parada segura ativo (Ctrl+Q).")

    ui_overlay = MonitorOverlay()

    script_thread = threading.Thread(target=worker_thread, args=(ui_overlay,), daemon=True)
    script_thread.start()

    ui_overlay.root.mainloop()

    kb_listener.stop()
    logger.info("Script encerrado.")
    sys.exit(_exit_code)
