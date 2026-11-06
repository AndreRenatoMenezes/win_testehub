import os
import re
import sys
import csv
import json
import time
import ctypes
import socket
import shutil
import logging
import platform
import threading
import subprocess
import unicodedata
import base64
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# =============================================================================
# CONFIGURACOES DO TESTE
# =============================================================================
# Modulo 6 — Wi-Fi Fast Transition (spec 004): coleta de compatibilidade
# (adaptador, driver, BIOS, SO, energia, APs), caminhada de 5 min com painel
# ao vivo no navegador, classificacao de cada roaming (FT / Nao FT /
# Indeterminado), relatorio HTML com graficos e wifi_ft.csv.
# Exit code: 0 somente se houve pelo menos 1 roaming FT; qualquer outro caso, 1.

# --- Valores da spec 004 (nao alterar sem nova spec) ---
DURACAO_CAMINHADA_S = int(os.environ.get("WIFI_FT_DURACAO_S", 5 * 60))
INICIO_AUTOMATICO_S = int(os.environ.get("WIFI_FT_INICIO_AUTO_S", 60))
INTERVALO_AMOSTRA_S = 0.25      # BSSID/RSSI via wlanapi
INTERVALO_PING_S = 0.2          # ping ICMP por destino
TIMEOUT_PING_MS = 1000
HOST_INTERNET = "8.8.8.8"

# --- Parametros tecnicos (plan da spec 004) ---
INTERVALO_AKM_S = 2.0           # releitura da AKM conectada (netsh)
INTERVALO_BSS_S = 10.0          # releitura do cache de BSS (sem varredura forcada)
JANELA_PAINEL_S = 90            # historico enviado ao painel
JANELA_INTERRUPCAO_S = 3.0      # janela de pings em torno de cada troca
LIMITE_TROCA_DEMORADA_MS = 1000 # troca (inicio → fim pelas notificacoes) acima disso e sinalizada
ESPERA_FINAL_PAINEL_S = 15      # servidor no ar apos concluir, para o painel buscar o relatorio
TIMEOUT_PS_S = 90
VERSAO_TESTE = "1.1"

# AKM suite selectors (OUI 00-0f-ac) — IEEE 802.11-2020, tabela 9-151
AKM_NOMES = {
    1: "802.1X", 2: "PSK", 3: "FT-802.1X", 4: "FT-PSK", 5: "802.1X-SHA256",
    6: "PSK-SHA256", 7: "TDLS", 8: "SAE", 9: "FT-SAE", 11: "802.1X Suite-B",
    12: "802.1X Suite-B-192", 13: "FT-802.1X-SHA384", 14: "FILS-SHA256",
    15: "FILS-SHA384", 16: "FT-FILS-SHA256", 17: "FT-FILS-SHA384", 18: "OWE",
    19: "FT-PSK-SHA384", 20: "PSK-SHA384", 24: "SAE-EXT-KEY", 25: "FT-SAE-EXT-KEY",
}
AKMS_FT = {3, 4, 9, 13, 16, 17, 19, 25}

CLASSE_FT = "FT"
CLASSE_NAO_FT = "Não FT"
CLASSE_INDET = "Indeterminado"

# --- Arquivos de evidencia (em HUB_EVIDENCE_DIR) ---
ARQ_TEMATICO = "wifi_ft.csv"
ARQ_AMOSTRAS = "wifi_ft_amostras.csv"
ARQ_PINGS = "wifi_ft_pings.csv"
ARQ_ROAMINGS = "wifi_ft_roamings.csv"
ARQ_EVENTOS = "wifi_ft_eventos_wlan.csv"
ARQ_COMPAT = "wifi_ft_compatibilidade.json"
ARQ_RELATORIO = "wifi_ft_relatorio.html"

_exit_code = 1

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')

# --- INTEGRACAO COM O HARDWARE TEST HUB ---
HUB_EVIDENCE_DIR = os.environ.get("HUB_EVIDENCE_DIR")
OUTPUT_PATH = HUB_EVIDENCE_DIR or os.path.join(BASE_DIR, f"Traces_{SESSION_TIMESTAMP}")
os.makedirs(OUTPUT_PATH, exist_ok=True)
BRUTOS_DIR = os.path.join(OUTPUT_PATH, "brutos")
os.makedirs(BRUTOS_DIR, exist_ok=True)

# =============================================================================
# LOGGING ESTRUTURADO
# =============================================================================
LOG_FILE = os.path.join(OUTPUT_PATH, f"teste_wifi_ft_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("TesteWifiFT")
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


def normalizar(texto):
    """Minusculas e sem acento — para casar rotulos do netsh em pt-BR e en-US."""
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


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


def executar_ps(script, timeout=TIMEOUT_PS_S):
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


_CODEPAGE_OEM = f"cp{ctypes.windll.kernel32.GetOEMCP()}"


def executar_cmd(args, timeout=60):
    """Executa um comando nativo (netsh, powercfg). Retorna (rc, texto)."""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        logger.warning(f"Comando excedeu {timeout}s: {' '.join(args)}")
        return None, ""
    except OSError as e:
        logger.warning(f"Falha ao executar {' '.join(args)}: {e}")
        return None, ""
    saida = r.stdout or b""
    try:
        texto = saida.decode("utf-8")  # netsh em builds recentes ja sai em UTF-8
    except UnicodeDecodeError:
        texto = saida.decode(_CODEPAGE_OEM, "replace")
    return r.returncode, texto


def salvar_bruto(nome, texto):
    try:
        with open(os.path.join(BRUTOS_DIR, nome), "w", encoding="utf-8") as f:
            f.write(texto or "")
    except OSError as e:
        logger.warning(f"Nao foi possivel gravar {nome}: {e}")


def fmt_mac(raw):
    return ":".join(f"{b:02x}" for b in raw)


def canal_da_frequencia(khz):
    """(canal, banda) a partir da frequencia central em kHz."""
    mhz = khz // 1000
    if 2412 <= mhz <= 2472:
        return (mhz - 2407) // 5, "2,4 GHz"
    if mhz == 2484:
        return 14, "2,4 GHz"
    if 5150 <= mhz <= 5895:
        return (mhz - 5000) // 5, "5 GHz"
    if 5925 <= mhz <= 7125:
        return (mhz - 5950) // 5, "6 GHz"
    return None, None


def banda_do_canal(canal):
    if canal is None:
        return None
    return "2,4 GHz" if canal <= 14 else "5 GHz"


# =============================================================================
# API NATIVA DE WLAN (wlanapi.dll) VIA CTYPES
# =============================================================================
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def texto(self):
        d4 = bytes(self.Data4)
        return f"{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-{d4[:2].hex()}-{d4[2:].hex()}"


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", GUID), ("strInterfaceDescription", ctypes.c_wchar * 256),
                ("isState", ctypes.c_uint)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD),
                ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_char * 32)]

    def texto(self):
        return self.ucSSID[:self.uSSIDLength].decode("utf-8", "replace")


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("dot11Ssid", DOT11_SSID), ("dot11BssType", ctypes.c_uint),
                ("dot11Bssid", ctypes.c_ubyte * 6), ("dot11PhyType", ctypes.c_uint),
                ("uDot11PhyIndex", wintypes.ULONG), ("wlanSignalQuality", wintypes.ULONG),
                ("ulRxRate", wintypes.ULONG), ("ulTxRate", wintypes.ULONG)]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("bSecurityEnabled", wintypes.BOOL), ("bOneXEnabled", wintypes.BOOL),
                ("dot11AuthAlgorithm", ctypes.c_uint), ("dot11CipherAlgorithm", ctypes.c_uint)]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("isState", ctypes.c_uint), ("wlanConnectionMode", ctypes.c_uint),
                ("strProfileName", ctypes.c_wchar * 256),
                ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
                ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES)]


class WLAN_RATE_SET(ctypes.Structure):
    _fields_ = [("uRateSetLength", wintypes.ULONG), ("usRateSet", wintypes.USHORT * 126)]


class WLAN_BSS_ENTRY(ctypes.Structure):
    _fields_ = [("dot11Ssid", DOT11_SSID), ("uPhyId", wintypes.ULONG),
                ("dot11Bssid", ctypes.c_ubyte * 6), ("dot11BssType", ctypes.c_uint),
                ("dot11BssPhyType", ctypes.c_uint), ("lRssi", wintypes.LONG),
                ("uLinkQuality", wintypes.ULONG), ("bInRegDomain", ctypes.c_ubyte),
                ("usBeaconPeriod", wintypes.USHORT), ("ullTimestamp", ctypes.c_ulonglong),
                ("ullHostTimestamp", ctypes.c_ulonglong), ("usCapabilityInformation", wintypes.USHORT),
                ("ulChCenterFrequency", wintypes.ULONG), ("wlanRateSet", WLAN_RATE_SET),
                ("ulIeOffset", wintypes.ULONG), ("ulIeSize", wintypes.ULONG)]


class WLAN_BSS_LIST(ctypes.Structure):
    _fields_ = [("dwTotalSize", wintypes.DWORD), ("dwNumberOfItems", wintypes.DWORD),
                ("wlanBssEntries", WLAN_BSS_ENTRY * 1)]


class WLAN_NOTIFICATION_DATA(ctypes.Structure):
    _fields_ = [("NotificationSource", wintypes.DWORD), ("NotificationCode", wintypes.DWORD),
                ("InterfaceGuid", GUID), ("dwDataSize", wintypes.DWORD), ("pData", ctypes.c_void_p)]


class WLAN_MSM_NOTIFICATION_DATA(ctypes.Structure):
    _fields_ = [("wlanConnectionMode", ctypes.c_uint), ("strProfileName", ctypes.c_wchar * 256),
                ("dot11Ssid", DOT11_SSID), ("dot11BssType", ctypes.c_uint),
                ("dot11MacAddr", ctypes.c_ubyte * 6), ("bSecurityEnabled", wintypes.BOOL),
                ("bFirstPeer", wintypes.BOOL), ("bLastPeer", wintypes.BOOL),
                ("wlanReasonCode", wintypes.DWORD)]


WLAN_NOTIFICATION_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(WLAN_NOTIFICATION_DATA), ctypes.c_void_p)

OPCODE_CURRENT_CONNECTION = 7
OPCODE_CHANNEL_NUMBER = 8
OPCODE_INTERFACE_STATE = 6
OPCODE_RSSI = 0x10000102
ESTADO_CONECTADO = 1
ESTADO_DESCONECTADO = 4
ESTADOS_WLAN = {0: "nao pronto", 1: "conectado", 2: "ad hoc", 3: "desconectando",
                4: "desconectado", 5: "associando", 6: "descobrindo", 7: "autenticando"}
FONTE_ACM = 0x08
FONTE_MSM = 0x10
NOTIF_ACM = {9: "acm_conexao_iniciada", 10: "acm_conexao_concluida", 11: "acm_falha_conexao",
             20: "acm_desconectando", 21: "acm_desconectado", 7: "acm_varredura_concluida"}
NOTIF_MSM = {1: "msm_associando", 2: "msm_associado", 3: "msm_autenticando", 4: "msm_conectado",
             5: "msm_roaming_inicio", 6: "msm_roaming_fim", 9: "msm_desassociando",
             10: "msm_desconectado", 15: "msm_link_degradado", 16: "msm_link_melhorado"}
PHY_TIPOS = {4: "802.11a", 5: "802.11b", 6: "802.11g", 7: "802.11n", 8: "802.11ac",
             9: "802.11ad", 10: "802.11ax", 11: "802.11be"}


class Wlan:
    """Acesso de leitura a wlanapi.dll. Nao altera configuracao e nao forca varreduras."""

    def __init__(self):
        self.api = ctypes.WinDLL("wlanapi.dll")
        self.handle = wintypes.HANDLE()
        versao = wintypes.DWORD()
        r = self.api.WlanOpenHandle(2, None, ctypes.byref(versao), ctypes.byref(self.handle))
        if r != 0:
            raise OSError(f"WlanOpenHandle falhou (codigo {r}). O servico WLAN AutoConfig esta ativo?")
        self.guid = None
        self.descricao = None
        self._callback = None

    def interfaces(self):
        lista = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
        r = self.api.WlanEnumInterfaces(self.handle, None, ctypes.byref(lista))
        if r != 0:
            return []
        try:
            n = lista.contents.dwNumberOfItems
            itens = ctypes.cast(ctypes.addressof(lista.contents.InterfaceInfo),
                                ctypes.POINTER(WLAN_INTERFACE_INFO * n)).contents if n else []
            saida = []
            for it in itens:
                saida.append({"guid": GUID.from_buffer_copy(it.InterfaceGuid), "descricao": it.strInterfaceDescription, "estado": it.isState})
            return saida
        finally:
            self.api.WlanFreeMemory(lista)

    def selecionar(self, guid, descricao):
        self.guid = guid
        self.descricao = descricao

    def _consultar(self, opcode, ctype):
        tamanho = wintypes.DWORD()
        ptr = ctypes.c_void_p()
        tipo = ctypes.c_uint()
        r = self.api.WlanQueryInterface(self.handle, ctypes.byref(self.guid), opcode, None,
                                        ctypes.byref(tamanho), ctypes.byref(ptr), ctypes.byref(tipo))
        if r != 0 or not ptr.value:
            return None
        try:
            valor = ctypes.cast(ptr, ctypes.POINTER(ctype)).contents
            if ctype in (ctypes.c_long, ctypes.c_ulong, ctypes.c_uint):
                return valor.value
            copia = ctype()
            ctypes.memmove(ctypes.byref(copia), ptr, ctypes.sizeof(ctype))
            return copia
        finally:
            self.api.WlanFreeMemory(ptr)

    def amostra(self):
        """Estado atual da conexao. Campos None quando nao conectado."""
        c = self._consultar(OPCODE_CURRENT_CONNECTION, WLAN_CONNECTION_ATTRIBUTES)
        if c is None or c.isState != ESTADO_CONECTADO:
            estado = c.isState if c is not None else self._consultar(OPCODE_INTERFACE_STATE, ctypes.c_uint)
            return {"conectado": False, "estado": estado}
        a = c.wlanAssociationAttributes
        canal = self._consultar(OPCODE_CHANNEL_NUMBER, ctypes.c_ulong)
        return {
            "conectado": True,
            "estado": c.isState,
            "ssid": a.dot11Ssid.texto(),
            "bssid": fmt_mac(a.dot11Bssid),
            "qualidade": a.wlanSignalQuality,
            "rssi": self._consultar(OPCODE_RSSI, ctypes.c_long),
            "canal": canal,
            "phy": PHY_TIPOS.get(a.dot11PhyType, str(a.dot11PhyType)),
            "rx_mbps": a.ulRxRate / 1000.0,
            "tx_mbps": a.ulTxRate / 1000.0,
            "perfil": c.strProfileName,
            "onex": bool(c.wlanSecurityAttributes.bOneXEnabled),
        }

    def lista_bss(self):
        """BSSs do cache de varredura do Windows, com os IEs interpretados."""
        lista = ctypes.POINTER(WLAN_BSS_LIST)()
        r = self.api.WlanGetNetworkBssList(self.handle, ctypes.byref(self.guid), None, 1, False,
                                           None, ctypes.byref(lista))
        if r != 0:
            return []
        try:
            n = lista.contents.dwNumberOfItems
            if not n:
                return []
            itens = ctypes.cast(ctypes.addressof(lista.contents.wlanBssEntries),
                                ctypes.POINTER(WLAN_BSS_ENTRY * n)).contents
            saida = []
            for e in itens:
                ies = ctypes.string_at(ctypes.addressof(e) + e.ulIeOffset, e.ulIeSize)
                canal, banda = canal_da_frequencia(e.ulChCenterFrequency)
                info = {"ssid": e.dot11Ssid.texto(), "bssid": fmt_mac(e.dot11Bssid),
                        "rssi": e.lRssi, "qualidade": e.uLinkQuality, "canal": canal, "banda": banda,
                        "phy": PHY_TIPOS.get(e.dot11BssPhyType, str(e.dot11BssPhyType))}
                info.update(interpretar_ies(ies))
                saida.append(info)
            return saida
        finally:
            self.api.WlanFreeMemory(lista)

    def registrar_notificacoes(self, destino):
        """destino(fonte, codigo, mac|None) e chamado na thread da wlanapi."""
        def _cb(p, _ctx):
            try:
                d = p.contents
                mac = None
                if d.NotificationSource == FONTE_MSM and d.pData and d.dwDataSize >= ctypes.sizeof(WLAN_MSM_NOTIFICATION_DATA):
                    msm = ctypes.cast(d.pData, ctypes.POINTER(WLAN_MSM_NOTIFICATION_DATA)).contents
                    mac = fmt_mac(msm.dot11MacAddr)
                destino(d.NotificationSource, d.NotificationCode, mac)
            except Exception:  # noqa: BLE001 — excecao num callback nativo derrubaria o processo
                pass

        self._callback = WLAN_NOTIFICATION_CALLBACK(_cb)
        anterior = wintypes.DWORD()
        r = self.api.WlanRegisterNotification(self.handle, FONTE_ACM | FONTE_MSM, True,
                                              self._callback, None, None, ctypes.byref(anterior))
        if r != 0:
            logger.warning(f"WlanRegisterNotification falhou (codigo {r}); duracoes so por amostragem.")
            self._callback = None
            return False
        return True

    def fechar(self):
        try:
            if self._callback is not None:
                anterior = wintypes.DWORD()
                self.api.WlanRegisterNotification(self.handle, 0, True, None, None, None, ctypes.byref(anterior))
            self.api.WlanCloseHandle(self.handle, None)
        except OSError:
            pass


def interpretar_ies(ies):
    """RSN (48) → AKMs e MFP; MDE (54) → 802.11r; RM (70) → 802.11k; ExtCap (127) → 802.11v."""
    info = {"akms": [], "mdid": None, "ft_sobre_ds": None, "k": False, "v": False,
            "mfp_capaz": None, "mfp_obrigatorio": None}
    i = 0
    while i + 2 <= len(ies):
        eid, tam = ies[i], ies[i + 1]
        corpo = ies[i + 2:i + 2 + tam]
        if len(corpo) < tam:
            break
        if eid == 48 and tam >= 8:
            pos = 6
            n_par = int.from_bytes(corpo[pos:pos + 2], "little")
            pos += 2 + 4 * n_par
            if pos + 2 <= tam:
                n_akm = int.from_bytes(corpo[pos:pos + 2], "little")
                pos += 2
                for k in range(n_akm):
                    sel = corpo[pos + 4 * k:pos + 4 * k + 4]
                    if len(sel) == 4:
                        info["akms"].append(sel[3] if sel[:3] == b"\x00\x0f\xac" else f"{sel[:3].hex('-')}:{sel[3]}")
                pos += 4 * n_akm
                if pos + 2 <= tam:
                    caps = int.from_bytes(corpo[pos:pos + 2], "little")
                    info["mfp_obrigatorio"] = bool(caps & 0x40)
                    info["mfp_capaz"] = bool(caps & 0x80)
        elif eid == 54 and tam >= 3:
            info["mdid"] = corpo[:2].hex()
            info["ft_sobre_ds"] = bool(corpo[2] & 0x01)
        elif eid == 70 and tam >= 1:
            info["k"] = bool(corpo[0] & 0x02)  # Neighbor Report capability
        elif eid == 127 and tam >= 3:
            info["v"] = bool(corpo[2] & 0x08)  # bit 19: BSS Transition
        i += 2 + tam
    info["ft_anunciado"] = info["mdid"] is not None and any(isinstance(a, int) and a in AKMS_FT for a in info["akms"])
    return info


def nome_akm(akm):
    if akm is None:
        return "N/A"
    if isinstance(akm, int):
        return f"{AKM_NOMES.get(akm, 'desconhecida')} (00-0f-ac:{akm:02x})"
    return str(akm)


# =============================================================================
# NETSH — AKM CONECTADA E DEMAIS CAMPOS DA INTERFACE
# =============================================================================
_RE_AKM = re.compile(r"akm\s*=\s*([0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}):([0-9a-f]+)", re.I)
_RE_MAC = re.compile(r"\b([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b", re.I)
_RE_CAMPO = re.compile(r"^\s*([^:\r\n]+?)\s*:\s?(.*?)\s*$")

_ROTULOS_INTERFACE = {
    "nome": "nome", "name": "nome",
    "descricao": "descricao", "description": "descricao",
    "ssid": "ssid", "ap bssid": "bssid", "bssid": "bssid",
    "banda": "banda", "band": "banda", "canal": "canal", "channel": "canal",
    "tipo de radio": "radio", "radio type": "radio",
    "autenticacao": "autenticacao", "authentication": "autenticacao",
    "criptografia": "cifra", "cipher": "cifra",
    "sinal": "sinal", "signal": "sinal", "rssi": "rssi",
    "perfil": "perfil", "profile": "perfil",
    "taxa de recepcao (mbps)": "rx_mbps", "receive rate (mbps)": "rx_mbps",
    "taxa de transmissao (mbps)": "tx_mbps", "transmit rate (mbps)": "tx_mbps",
    "estado": "estado", "state": "estado",
}


def interpretar_netsh_interfaces(texto, guid_txt):
    """Bloco da interface (pelo GUID) de 'netsh wlan show interfaces'. Retorna dict ou None."""
    texto = texto.replace("\r\n", "\n")
    pos = texto.lower().find(guid_txt.lower())
    if pos < 0:
        return None
    inicio = texto.rfind("\n\n", 0, pos)
    fim = texto.find("\n\n", pos)
    bloco = texto[inicio if inicio >= 0 else 0: fim if fim >= 0 else len(texto)]
    campos = {}
    for linha in bloco.splitlines():
        m = _RE_CAMPO.match(linha)
        if not m:
            continue
        chave = _ROTULOS_INTERFACE.get(normalizar(m.group(1)))
        if chave and chave not in campos:
            campos[chave] = m.group(2).strip()
    m = _RE_AKM.search(bloco)
    if m:
        oui, tipo = m.group(1).lower(), int(m.group(2), 16)
        campos["akm"] = tipo if oui == "00-0f-ac" else f"{oui}:{tipo}"
        campos["akm_bruto"] = m.group(0)
    else:
        campos["akm"] = None
    if "bssid" in campos:
        mm = _RE_MAC.search(campos["bssid"])
        campos["bssid"] = mm.group(1).lower() if mm else None
    return campos


def ler_interface_netsh(guid_txt):
    rc, texto = executar_cmd(["netsh", "wlan", "show", "interfaces"], timeout=15)
    if rc is None:
        return None, ""
    return interpretar_netsh_interfaces(texto, guid_txt), texto


def capacidade_declarada(texto, rotulos):
    """True/False/None para uma linha de 'netsh wlan show wirelesscapabilities'."""
    for linha in texto.splitlines():
        m = _RE_CAMPO.match(linha)
        if not m:
            continue
        chave = normalizar(m.group(1))
        if any(r in chave for r in rotulos):
            valor = normalizar(m.group(2))
            if any(n in valor for n in ("sem suporte", "nao suport", "not supported", "unsupported")) or valor in ("nao", "no"):
                return False
            if any(s in valor for s in ("com suporte", "suportado", "supported")) or valor in ("sim", "yes"):
                return True
            return None
    return None


# =============================================================================
# COLETA DE COMPATIBILIDADE
# =============================================================================
_PS_COMPAT = r"""
$guid = '{__GUID__}'
$r = [ordered]@{}
$a = Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceGuid -eq $guid } | Select-Object -First 1
if ($a) {
  $r.adaptador = $a | Select-Object Name, InterfaceDescription, MacAddress, Status, LinkSpeed, ifIndex,
      DriverVersion, DriverDate, DriverProvider, DriverInformation, NdisVersion, PnPDeviceID, MediaType
  $r.avancadas = @(Get-NetAdapterAdvancedProperty -Name $a.Name -ErrorAction SilentlyContinue |
      Select-Object DisplayName, DisplayValue, RegistryKeyword)
  $r.energia_adaptador = Get-NetAdapterPowerManagement -Name $a.Name -ErrorAction SilentlyContinue |
      Select-Object AllowComputerToTurnOffDevice, DeviceSleepOnDisconnect, SelectiveSuspend, WakeOnMagicPacket, WakeOnPattern
  $pnp = $a.PnPDeviceID -replace '\\', '\\'
  $r.driver = Get-CimInstance Win32_PnPSignedDriver -Filter "DeviceID='$pnp'" -ErrorAction SilentlyContinue |
      Select-Object DeviceName, DriverVersion, @{n='DriverDate';e={if($_.DriverDate){$_.DriverDate.ToUniversalTime().ToString('yyyy-MM-dd')}}},
          Manufacturer, DriverProviderName, InfName, IsSigned, Signer
  $ip = Get-NetIPConfiguration -InterfaceIndex $a.ifIndex -ErrorAction SilentlyContinue
  $r.ip = [ordered]@{
    ipv4 = @($ip.IPv4Address | ForEach-Object { $_.IPAddress })
    gateway = @($ip.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
    dns = @($ip.DNSServer | Where-Object { $_.AddressFamily -eq 2 } | ForEach-Object { $_.ServerAddresses })
  }
}
$r.outros_adaptadores_ativos = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceGuid -ne $guid } |
    Select-Object Name, InterfaceDescription, HardwareInterface, MediaType)
$r.bios = Get-CimInstance Win32_BIOS | Select-Object Manufacturer, SMBIOSBIOSVersion, Version,
    @{n='ReleaseDate';e={if($_.ReleaseDate){$_.ReleaseDate.ToUniversalTime().ToString('yyyy-MM-dd')}}}, SerialNumber
$r.computador = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, SystemFamily, SystemSKUNumber
$r.placa = Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product, Version
$so = Get-CimInstance Win32_OperatingSystem
$cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction SilentlyContinue
$r.so = [ordered]@{ Caption = $so.Caption; Version = $so.Version; Build = "$($so.BuildNumber).$($cv.UBR)";
    DisplayVersion = $cv.DisplayVersion; Arquitetura = $so.OSArchitecture }
$r.servico_wlan = (Get-Service WlanSvc -ErrorAction SilentlyContinue).Status.ToString()
$r | ConvertTo-Json -Depth 5
"""

SUB_WIRELESS = "19cad22d-5f5e-4b09-91f2-b5a6eb2b1e34"
WIRELESS_POWER = "12bbebe6-58d6-4636-95bb-3217ef867c1a"
MODOS_ECONOMIA_WIFI = {0: "Desempenho máximo", 1: "Economia baixa", 2: "Economia média", 3: "Economia máxima"}


def ler_energia_wifi():
    """(nome do plano ativo, modo CA, modo bateria) da economia de energia do adaptador sem fio."""
    _, ativo = executar_cmd(["powercfg", "/getactivescheme"], timeout=15)
    _, q = executar_cmd(["powercfg", "/q", "SCHEME_CURRENT", SUB_WIRELESS, WIRELESS_POWER], timeout=15)
    salvar_bruto("powercfg_wireless.txt", f"{ativo}\n{q}")
    m = re.search(r"\(([^)]+)\)\s*\*?\s*$", ativo.strip())
    plano = m.group(1) if m else ativo.strip() or None
    valores = re.findall(r":\s*0x([0-9a-f]{8})\s*$", q, re.I | re.M)
    # As duas ultimas linhas hexadecimais sao o indice atual em CA e em bateria.
    ca = dc = None
    if len(valores) >= 2:
        ca, dc = int(valores[-2], 16), int(valores[-1], 16)
    return plano, ca, dc


def coletar_compatibilidade(guid_txt, ssid, conexao_netsh):
    logger.info("Coletando dados de compatibilidade (adaptador, driver, BIOS, SO, energia)...")
    compat = {"coletado_em": datetime.now().isoformat(timespec="seconds")}

    rc, saida, erro = executar_ps(_PS_COMPAT.replace("__GUID__", guid_txt))
    salvar_bruto("powershell_compatibilidade.json", saida or erro)
    try:
        compat.update(json.loads(saida) if saida else {})
    except json.JSONDecodeError:
        logger.warning(f"Coleta PowerShell sem JSON valido (rc={rc}): {erro[:300]}")

    for nome, args in [
        ("netsh_interfaces.txt", ["netsh", "wlan", "show", "interfaces"]),
        ("netsh_drivers.txt", ["netsh", "wlan", "show", "drivers"]),
        ("netsh_wirelesscapabilities.txt", ["netsh", "wlan", "show", "wirelesscapabilities"]),
        ("netsh_networks_bssid.txt", ["netsh", "wlan", "show", "networks", "mode=bssid"]),
        ("netsh_profile.txt", ["netsh", "wlan", "show", "profile", f"name={ssid}"]),  # sem key=clear
    ]:
        _, texto = executar_cmd(args, timeout=30)
        salvar_bruto(nome, texto)
        compat[nome.replace(".txt", "")] = texto

    caps = compat.get("netsh_wirelesscapabilities", "")
    drivers = compat.get("netsh_drivers", "")
    compat["capacidades"] = {
        "fast_transition": capacidade_declarada(caps, ["transicao rapida", "fast transition", "fast bss transition"]),
        "dot11k": capacidade_declarada(caps, ["dot11k", "802.11k", "relatorio de vizinho", "neighbor report"]),
        "dot11v": capacidade_declarada(caps, ["802.11v", "transicao de bss", "bss transition"]),
        "sae": capacidade_declarada(caps, ["autenticacao sae", "sae authentication"]),
        "mbo": capacidade_declarada(caps, ["mbo"]),
        "mfp": capacidade_declarada(caps, ["quadros de gerenciamento protegido", "protected management frames"]),
        "randomizacao_mac": capacidade_declarada(caps, ["randomizacao de mac", "mac randomization"]),
        "firmware": _valor_campo(caps, ["versao do firmware", "firmware version"]),
        "wdi": _valor_campo(caps, ["versao wdi (windows)", "wdi version (windows)"]),
        "radios_suportados": _valor_campo(drivers, ["tipos de radio com suporte", "radio types supported"]),
        "wpa3_personal": "wpa3-personal" in drivers.lower(),
        "wpa3_enterprise": "wpa3-enterprise" in drivers.lower(),
        "80211w": _valor_campo(drivers, ["suporte para protecao de quadro de gerenciamento 802.11w",
                                        "802.11w management frame protection supported"]),
        "tipo_driver": _valor_campo(drivers, ["tipo", "type"]),
    }

    plano, ca, dc = ler_energia_wifi()
    compat["energia"] = {"plano_ativo": plano,
                         "economia_wifi_ca": MODOS_ECONOMIA_WIFI.get(ca, ca),
                         "economia_wifi_bateria": MODOS_ECONOMIA_WIFI.get(dc, dc),
                         "_indices": [ca, dc]}
    compat["conexao"] = conexao_netsh or {}
    compat["host"] = platform.node()
    return compat


def _valor_campo(texto, rotulos):
    for linha in texto.splitlines():
        m = _RE_CAMPO.match(linha)
        if m and normalizar(m.group(1)) in rotulos:
            return m.group(2).strip() or None
    return None


def _data_iso(valor):
    if not valor:
        return None
    m = re.search(r"/Date\((\d+)", str(valor))
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000).strftime("%Y-%m-%d")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(valor))
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(valor))
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return str(valor)


def driver_resumo(compat):
    drv = compat.get("driver") or {}
    ad = compat.get("adaptador") or {}
    return {
        "nome": drv.get("DeviceName") or ad.get("InterfaceDescription"),
        "versao": drv.get("DriverVersion") or ad.get("DriverVersion"),
        "data": _data_iso(drv.get("DriverDate") or ad.get("DriverDate")),
        "fornecedor": drv.get("DriverProviderName") or ad.get("DriverProvider"),
        "inf": drv.get("InfName"),
        "assinado": drv.get("IsSigned"),
    }


def gerar_achados(compat, aps, conexao, roamings):
    achados = []

    def add(nivel, texto):
        achados.append({"nivel": nivel, "texto": texto})

    caps = compat.get("capacidades", {})
    ft = caps.get("fast_transition")
    if ft is True:
        add("ok", "O driver declara suporte a Transição Rápida (802.11r).")
    elif ft is False:
        add("erro", "O driver/adaptador NÃO declara suporte a Transição Rápida (802.11r). Atualize o driver ou verifique o modelo do adaptador.")
    else:
        add("alerta", "Não foi possível ler a capacidade de Transição Rápida em 'netsh wlan show wirelesscapabilities'.")

    akm = conexao.get("akm")
    if isinstance(akm, int) and akm in AKMS_FT:
        add("ok", f"A conexão usa AKM de Fast Transition: {nome_akm(akm)}.")
    elif akm is None:
        add("alerta", "O driver não informou a AKM conectada no netsh; a classificação FT pode ficar indeterminada.")
    else:
        add("erro", f"A rede conectada usa {nome_akm(akm)}, que não é uma AKM de Fast Transition. "
                    "Verifique se o 802.11r está habilitado no SSID da controladora/AP.")

    da_rede = [a for a in aps if a.get("ssid") == conexao.get("ssid")]
    com_ft = [a for a in da_rede if a.get("ft_anunciado")]
    if len(da_rede) <= 1:
        add("alerta", "Somente 1 AP do SSID estava visível no início. Durante a caminhada, passe por áreas cobertas por outros APs.")
    if da_rede:
        if com_ft:
            add("ok", f"{len(com_ft)} de {len(da_rede)} APs visíveis anunciam 802.11r (Mobility Domain + AKM FT).")
        else:
            add("erro", "Nenhum AP visível do SSID anuncia 802.11r (sem Mobility Domain Element/AKM FT).")
        mdids = {a["mdid"] for a in com_ft if a.get("mdid")}
        if len(mdids) > 1:
            add("alerta", f"APs com Mobility Domain diferentes ({', '.join(sorted(mdids))}): FT só ocorre dentro do mesmo domínio.")
        if any(not a.get("k") for a in da_rede):
            add("alerta", "Há APs sem 802.11k (Neighbor Report): o cliente pode demorar mais para escolher o próximo AP.")
        if any(not a.get("v") for a in da_rede):
            add("alerta", "Há APs sem 802.11v (BSS Transition Management).")

    if caps.get("dot11k") is False:
        add("alerta", "O adaptador não declara 802.11k (Neighbor Report).")
    if caps.get("dot11v") is False:
        add("alerta", "O adaptador não declara 802.11v (BSS Transition).")

    for p in compat.get("avancadas") or []:
        nome = normalizar(p.get("DisplayName"))
        valor = normalizar(str(p.get("DisplayValue")))
        if "roaming aggressiveness" in nome or "agressividade" in nome:
            if "lowest" in valor or "1." in valor or "mais baixa" in valor:
                add("alerta", f"Roaming Aggressiveness em '{p.get('DisplayValue')}': o adaptador tende a segurar o AP antigo.")
            else:
                add("ok", f"Roaming Aggressiveness: {p.get('DisplayValue')}.")
        if ("mimo power save" in nome) and "no smps" not in valor and "auto" not in valor:
            add("alerta", f"MIMO Power Save em '{p.get('DisplayValue')}' pode reduzir desempenho durante o roaming.")

    energia = compat.get("energia", {})
    ca, dc = (energia.get("_indices") or [None, None])
    if ca is not None and ca >= 2:
        add("alerta", f"Economia de energia do adaptador sem fio na tomada: {energia.get('economia_wifi_ca')}.")
    if dc is not None and dc >= 2:
        add("alerta", f"Economia de energia do adaptador sem fio na bateria: {energia.get('economia_wifi_bateria')}.")

    drv = driver_resumo(compat)
    try:
        idade = (datetime.now() - datetime.strptime(drv["data"], "%Y-%m-%d")).days
        if idade > 730:
            add("alerta", f"Driver Wi-Fi com mais de 2 anos ({drv['data']}). Drivers antigos têm bugs conhecidos de roaming/FT.")
    except (TypeError, ValueError, KeyError):
        pass

    virtuais = [o for o in compat.get("outros_adaptadores_ativos") or [] if not o.get("HardwareInterface")]
    if virtuais:
        nomes = ", ".join(o.get("InterfaceDescription") or o.get("Name") for o in virtuais)
        add("alerta", f"Adaptadores virtuais/VPN ativos podem afetar a latência durante o roaming: {nomes}.")

    if roamings:
        desc = [r for r in roamings if r.get("desconexao")]
        if desc:
            add("erro", f"{len(desc)} troca(s) de AP com desconexão (reconexão completa, não é FT).")
    return achados


# =============================================================================
# PING ICMP (iphlpapi.dll)
# =============================================================================
class IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                ("OptionsSize", ctypes.c_ubyte), ("OptionsData", ctypes.c_void_p)]


class ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", wintypes.ULONG), ("Status", wintypes.ULONG), ("RoundTripTime", wintypes.ULONG),
                ("DataSize", wintypes.USHORT), ("Reserved", wintypes.USHORT), ("Data", ctypes.c_void_p),
                ("Options", IP_OPTION_INFORMATION)]


class Pinger:
    def __init__(self, ip):
        self.api = ctypes.WinDLL("iphlpapi.dll")
        self.api.IcmpCreateFile.restype = wintypes.HANDLE
        self.api.IcmpSendEcho.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.WORD,
                                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
        self.api.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.IcmpCreateFile()
        self.endereco = int.from_bytes(socket.inet_aton(ip), "little")
        self.dados = ctypes.create_string_buffer(b"HubWifiFT" * 4)
        self.tam_dados = 32
        self.resposta = ctypes.create_string_buffer(ctypes.sizeof(ICMP_ECHO_REPLY) + self.tam_dados + 8)

    def ping(self, timeout_ms):
        """RTT em ms (float) ou None se perdido."""
        t = time.perf_counter()
        n = self.api.IcmpSendEcho(self.handle, self.endereco, self.dados, self.tam_dados, None,
                                  self.resposta, len(self.resposta), timeout_ms)
        dt = (time.perf_counter() - t) * 1000
        if n == 0:
            return None
        rep = ICMP_ECHO_REPLY.from_buffer(self.resposta)
        if rep.Status != 0:
            return None
        return round(dt, 2)  # perf_counter: resolucao abaixo de 1 ms (RoundTripTime e inteiro)

    def fechar(self):
        try:
            self.api.IcmpCloseHandle(self.handle)
        except OSError:
            pass


# =============================================================================
# ESTADO COMPARTILHADO (monitor, pings, painel)
# =============================================================================
class Estado:
    def __init__(self):
        self.lock = threading.Lock()
        self.fase = "aguardando"          # aguardando → caminhada → processando → concluido
        self.t_base = time.perf_counter() # zera ao iniciar a caminhada (perf_counter: < 1 ms; monotonic ~15,6 ms no Windows)
        self.inicio_dt = None
        self.fim_dt = None
        self.aguardando_desde = time.monotonic()
        self.amostras = []                # dicts: t, hora, conectado, estado, bssid, rssi, qualidade, canal, rx, tx
        self.pings = {"gateway": [], "internet": []}   # (t, rtt|None)
        self.akm_leituras = []            # (t, bssid, akm)
        self.eventos = []                 # (t, hora, nome, mac)
        self.roamings = []
        self.aps = {}                     # bssid → dict (label, idx, canal, banda, ies...)
        self.ultimo_conectado = None      # ultima amostra conectada
        self.desconexao_pendente = False
        self.conexao = {}                 # ultima leitura completa (painel)
        self.ssid = None
        self.gateway = None
        self.internet_ok = None
        self.pedido_inicio = threading.Event()
        self.pedido_fim = threading.Event()
        self.parar = threading.Event()
        self.reler_akm = threading.Event()
        self.relatorio_html = None
        self.resultado = None
        self.motivo = None

    def t(self):
        return round(time.perf_counter() - self.t_base, 4)

    def label_ap(self, bssid):
        """Rotulo fixo por ordem de aparicao (AP1, AP2...) — a cor segue o AP, nunca o rank."""
        ap = self.aps.get(bssid)
        if ap is None:
            ap = {"bssid": bssid, "idx": len(self.aps), "label": f"AP{len(self.aps) + 1}"}
            self.aps[bssid] = ap
        return ap


ESTADO = Estado()


def thread_monitor(wlan):
    """Amostra a conexao a cada 250 ms e detecta trocas de BSSID."""
    proximo_bss = 0.0
    while not ESTADO.parar.is_set():
        inicio = time.monotonic()
        try:
            a = wlan.amostra()
        except OSError as e:
            logger.debug(f"Falha na amostra WLAN: {e}")
            a = {"conectado": False, "estado": None}
        with ESTADO.lock:
            t = ESTADO.t()
            a["t"] = t
            a["hora"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if a["conectado"]:
                ap = ESTADO.label_ap(a["bssid"])
                ap.setdefault("canal", a.get("canal"))
                ap.setdefault("banda", banda_do_canal(a.get("canal")))
                a["ap"] = ap["label"]
                ESTADO.conexao.update({k: a.get(k) for k in ("bssid", "rssi", "qualidade", "canal", "phy",
                                                              "rx_mbps", "tx_mbps", "ssid")})
                ESTADO.conexao["ap"] = ap["label"]
                ESTADO.conexao["ap_idx"] = ap["idx"]
                ESTADO.conexao["banda"] = banda_do_canal(a.get("canal"))
                ESTADO.conexao["conectado"] = True
                ant = ESTADO.ultimo_conectado
                if ESTADO.fase == "caminhada" and ant is not None and ant["bssid"] != a["bssid"]:
                    registrar_roaming(ant, a)
                    ESTADO.reler_akm.set()
                ESTADO.ultimo_conectado = a
                ESTADO.desconexao_pendente = False
            else:
                ESTADO.conexao["conectado"] = False
                ESTADO.conexao["estado"] = ESTADOS_WLAN.get(a.get("estado"), a.get("estado"))
                if a.get("estado") == ESTADO_DESCONECTADO:
                    ESTADO.desconexao_pendente = True
            if ESTADO.fase in ("aguardando", "caminhada"):
                ESTADO.amostras.append(a)
        if time.monotonic() >= proximo_bss:
            proximo_bss = time.monotonic() + INTERVALO_BSS_S
            atualizar_bss(wlan)
        espera = INTERVALO_AMOSTRA_S - (time.monotonic() - inicio)
        if espera > 0:
            ESTADO.parar.wait(espera)


def registrar_roaming(ant, novo):
    """Chamado com o lock adquirido."""
    ap_o = ESTADO.aps.get(ant["bssid"], {})
    ap_d = ESTADO.aps.get(novo["bssid"], {})
    r = {
        "n": len(ESTADO.roamings) + 1,
        "hora": novo["hora"],
        "t": novo["t"],
        "t_ultimo_origem": ant["t"],
        "bssid_origem": ant["bssid"], "ap_origem": ap_o.get("label"),
        "bssid_destino": novo["bssid"], "ap_destino": ap_d.get("label"),
        "canal_origem": ant.get("canal"), "canal_destino": novo.get("canal"),
        "banda_origem": banda_do_canal(ant.get("canal")), "banda_destino": banda_do_canal(novo.get("canal")),
        "rssi_antes": ant.get("rssi"), "rssi_depois": novo.get("rssi"),
        "desconexao": ESTADO.desconexao_pendente or _houve_evento(ant["t"], novo["t"], {"acm_desconectado", "msm_desconectado"}),
        "duracao_amostragem_ms": round((novo["t"] - ant["t"]) * 1000),
        "akm_depois": None, "classificacao": CLASSE_INDET,
    }
    ESTADO.roamings.append(r)
    logger.info(f"Roaming #{r['n']}: {r['ap_origem']} ({r['bssid_origem']}) -> {r['ap_destino']} ({r['bssid_destino']}), "
                f"RSSI {r['rssi_antes']} -> {r['rssi_depois']} dBm")


def _houve_evento(t0, t1, nomes):
    return any(t0 <= e[0] <= t1 and e[2] in nomes for e in ESTADO.eventos)


def atualizar_bss(wlan):
    try:
        lista = wlan.lista_bss()
    except OSError as e:
        logger.debug(f"Falha ao ler o cache de BSS: {e}")
        return
    with ESTADO.lock:
        for b in lista:
            if ESTADO.ssid and b["ssid"] != ESTADO.ssid:
                continue
            ap = ESTADO.label_ap(b["bssid"])
            rssi_max = max(ap.get("rssi_max", -200), b["rssi"])
            ap.update({k: v for k, v in b.items() if k != "qualidade"})
            ap["rssi_max"] = rssi_max
            ap.setdefault("visto_em", ESTADO.t())


def thread_akm(guid_txt):
    """Rele a AKM conectada (netsh) a cada 2 s, e logo apos cada troca de AP."""
    while not ESTADO.parar.is_set():
        ESTADO.reler_akm.wait(INTERVALO_AKM_S)
        ESTADO.reler_akm.clear()
        if ESTADO.parar.is_set():
            break
        campos, _ = ler_interface_netsh(guid_txt)
        if not campos or not campos.get("bssid"):
            continue
        with ESTADO.lock:
            ESTADO.akm_leituras.append((ESTADO.t(), campos["bssid"], campos.get("akm")))
            ESTADO.conexao["akm"] = campos.get("akm")
            ESTADO.conexao["akm_nome"] = nome_akm(campos.get("akm"))
            ESTADO.conexao["autenticacao"] = campos.get("autenticacao")


def thread_ping(destino, ip):
    try:
        p = Pinger(ip)
    except (OSError, ValueError) as e:
        logger.warning(f"Ping para {destino} ({ip}) indisponivel: {e}")
        return
    try:
        while not ESTADO.parar.is_set():
            inicio = time.monotonic()
            with ESTADO.lock:
                t = ESTADO.t()
            rtt = p.ping(TIMEOUT_PING_MS)
            with ESTADO.lock:
                if ESTADO.fase in ("aguardando", "caminhada"):
                    ESTADO.pings[destino].append((t, rtt))
            espera = INTERVALO_PING_S - (time.monotonic() - inicio)
            if espera > 0:
                ESTADO.parar.wait(espera)
    finally:
        p.fechar()


def receber_notificacao(fonte, codigo, mac):
    nome = (NOTIF_MSM if fonte == FONTE_MSM else NOTIF_ACM).get(codigo)
    if nome is None:
        return
    with ESTADO.lock:
        if ESTADO.fase in ("aguardando", "caminhada"):
            ESTADO.eventos.append((ESTADO.t(), datetime.now().strftime("%H:%M:%S.%f")[:-3], nome, mac))
            if nome in ("acm_desconectado", "msm_desconectado"):
                ESTADO.desconexao_pendente = True


# =============================================================================
# CLASSIFICACAO E METRICAS
# =============================================================================
def avaliar_roamings():
    """Atualiza AKM, classificacao, duracao e interrupcao de cada roaming. Chamar com o lock."""
    rs = ESTADO.roamings
    for i, r in enumerate(rs):
        t_prox = rs[i + 1]["t"] if i + 1 < len(rs) else float("inf")
        leitura = next((l for l in ESTADO.akm_leituras
                        if r["t_ultimo_origem"] <= l[0] < t_prox and l[1] == r["bssid_destino"]), None)
        r["akm_depois"] = leitura[2] if leitura else None
        r["akm_nome"] = nome_akm(r["akm_depois"])
        if leitura is None:
            r["classificacao"] = CLASSE_INDET
        elif r["desconexao"]:
            r["classificacao"] = CLASSE_NAO_FT
        elif isinstance(r["akm_depois"], int) and r["akm_depois"] in AKMS_FT:
            r["classificacao"] = CLASSE_FT
        else:
            r["classificacao"] = CLASSE_NAO_FT

        # Tempo de troca pelas notificacoes MSM, em duas fases:
        #   reassociacao = roaming_inicio → autenticando (troca pelo ar com o AP novo; o que a WLC mede)
        #   conclusao    = autenticando → roaming_fim (chaves, porta e aviso dentro do Windows)
        # O inicio e procurado desde o fim do roaming anterior: tentativas demoradas comecam
        # segundos antes de o BSSID mudar na amostragem.
        r.update(duracao_ms=r["duracao_amostragem_ms"], fonte_duracao="amostragem (250 ms)",
                 reassociacao_ms=None, conclusao_ms=None, t_fim_notif=None, troca_demorada=False)
        limite = float("-inf")
        if i > 0:
            ant = rs[i - 1]
            limite = max(ant["t"], ant.get("t_fim_notif") or ant["t"])
        candidatos = [e for e in ESTADO.eventos if limite < e[0] <= r["t"] + 1.0
                      and e[2] in ("msm_roaming_fim", "msm_conectado", "msm_associado")]
        fim = next((e for e in candidatos if e[3] == r["bssid_destino"]), candidatos[0] if candidatos else None)
        if fim:
            ini = [e for e in ESTADO.eventos if limite < e[0] < fim[0]
                   and e[2] in ("msm_roaming_inicio", "msm_associando")]
            if ini:
                t_ini = ini[-1][0]
                aut = next((e for e in ESTADO.eventos if t_ini < e[0] <= fim[0] and e[2] == "msm_autenticando"), None)
                r["duracao_ms"] = round((fim[0] - t_ini) * 1000)
                r["fonte_duracao"] = "notificações WLAN"
                r["t_fim_notif"] = fim[0]
                if aut:
                    r["reassociacao_ms"] = round((aut[0] - t_ini) * 1000)
                    r["conclusao_ms"] = round((fim[0] - aut[0]) * 1000)
                r["troca_demorada"] = r["duracao_ms"] > LIMITE_TROCA_DEMORADA_MS

        for destino in ("gateway", "internet"):
            gap, pico = interrupcao(ESTADO.pings[destino], r["t_ultimo_origem"] - JANELA_INTERRUPCAO_S,
                                    r["t"] + JANELA_INTERRUPCAO_S)
            r[f"interrupcao_{destino}_ms"] = gap
            r[f"pico_{destino}_ms"] = pico


def interrupcao(pings, t0, t1):
    """(maior intervalo sem resposta em ms, pico de RTT) na janela. None se nao ha pings."""
    janela = [p for p in pings if t0 <= p[0] <= t1]
    if not janela or all(p[1] is None for p in janela):
        return None, None
    maior = 0.0
    ultimo_ok = None
    perdendo = False
    for t, rtt in janela:
        if rtt is None:
            perdendo = True
            continue
        if perdendo and ultimo_ok is not None:
            maior = max(maior, (t - ultimo_ok) * 1000 - INTERVALO_PING_S * 1000)
        perdendo = False
        ultimo_ok = t
    pico = max(p[1] for p in janela if p[1] is not None)
    return round(max(maior, 0)), round(pico, 1)


def estatisticas_ping(lista):
    if not lista:
        return {"enviados": 0, "perda_pct": None, "media_ms": None, "p95_ms": None, "max_ms": None}
    ok = sorted(p[1] for p in lista if p[1] is not None)
    perda = 100.0 * (len(lista) - len(ok)) / len(lista)
    if not ok:
        return {"enviados": len(lista), "perda_pct": 100.0, "media_ms": None, "p95_ms": None, "max_ms": None}
    return {"enviados": len(lista), "perda_pct": round(perda, 2), "media_ms": round(sum(ok) / len(ok), 2),
            "p95_ms": round(ok[min(len(ok) - 1, int(len(ok) * 0.95))], 2), "max_ms": round(ok[-1], 2)}


def _media(v):
    v = [x for x in v if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def _mediana(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    meio = len(v) // 2
    return round(float(v[meio]) if len(v) % 2 else (v[meio - 1] + v[meio]) / 2, 1)


def _maximo(v):
    v = [x for x in v if x is not None]
    return max(v) if v else None


# =============================================================================
# PAINEL AO VIVO (http.server em 127.0.0.1)
# =============================================================================
def estado_painel():
    with ESTADO.lock:
        avaliar_roamings()
        t = ESTADO.t()
        t0 = t - JANELA_PAINEL_S
        if ESTADO.fase == "aguardando":
            restante_auto = max(0, INICIO_AUTOMATICO_S - (time.monotonic() - ESTADO.aguardando_desde))
            restante = DURACAO_CAMINHADA_S
        else:
            restante_auto = 0
            restante = max(0, DURACAO_CAMINHADA_S - t) if ESTADO.fase == "caminhada" else 0
        cont = {c: sum(1 for r in ESTADO.roamings if r["classificacao"] == c)
                for c in (CLASSE_FT, CLASSE_NAO_FT, CLASSE_INDET)}
        return {
            "fase": ESTADO.fase,
            "t": t,
            "duracao_s": DURACAO_CAMINHADA_S,
            "restante_s": round(restante, 1),
            "inicio_auto_s": round(restante_auto, 1),
            "ssid": ESTADO.ssid,
            "gateway": ESTADO.gateway,
            "internet": HOST_INTERNET,
            "conexao": dict(ESTADO.conexao),
            "aps": sorted(({"bssid": a["bssid"], "label": a["label"], "idx": a["idx"], "canal": a.get("canal"),
                            "banda": a.get("banda"), "ft": a.get("ft_anunciado")} for a in ESTADO.aps.values()),
                          key=lambda a: a["idx"]),
            "amostras": [[s["t"], s.get("rssi"), ESTADO.aps[s["bssid"]]["idx"] if s.get("conectado") else -1]
                         for s in ESTADO.amostras if s["t"] >= t0],
            "pings": {k: [[p[0], p[1]] for p in v if p[0] >= t0] for k, v in ESTADO.pings.items()},
            "roamings": [{k: r.get(k) for k in ("n", "hora", "t", "ap_origem", "ap_destino", "bssid_origem",
                                                 "bssid_destino", "rssi_antes", "rssi_depois", "classificacao",
                                                 "akm_nome", "duracao_ms", "reassociacao_ms", "conclusao_ms",
                                                 "troca_demorada", "interrupcao_gateway_ms", "desconexao")}
                         for r in ESTADO.roamings],
            "contadores": cont,
            "relatorio": bool(ESTADO.relatorio_html),
            "resultado": ESTADO.resultado,
            "motivo": ESTADO.motivo,
        }


class PainelHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silencia o log padrao do http.server
        pass

    def _responder(self, codigo, corpo, tipo):
        dados = corpo.encode("utf-8") if isinstance(corpo, str) else corpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        try:
            self.wfile.write(dados)
        except ConnectionError:  # navegador fechou ou navegou para o relatorio
            pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(ASSETS_DIR, "dashboard.html"), encoding="utf-8") as f:
                self._responder(200, f.read(), "text/html; charset=utf-8")
        elif self.path.startswith("/api/estado"):
            self._responder(200, json.dumps(estado_painel(), ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/relatorio" and ESTADO.relatorio_html:
            with open(ESTADO.relatorio_html, encoding="utf-8") as f:
                self._responder(200, f.read(), "text/html; charset=utf-8")
        else:
            self._responder(404, "nao encontrado", "text/plain; charset=utf-8")

    def do_POST(self):
        if self.path == "/api/iniciar":
            ESTADO.pedido_inicio.set()
            self._responder(200, "{}", "application/json")
        elif self.path == "/api/encerrar":
            ESTADO.pedido_fim.set()
            self._responder(200, "{}", "application/json")
        else:
            self._responder(404, "{}", "application/json")


class ServidorPainel(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):
            logger.debug("Erro no servidor do painel", exc_info=True)


def abrir_navegador(url):
    candidatos = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Microsoft\Edge\Application\msedge.exe"),
    ]
    for exe in candidatos:
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--new-window", "--start-maximized"])
                return True
            except OSError as e:
                logger.warning(f"Falha ao abrir o Edge: {e}")
    try:
        os.startfile(url)
        return True
    except OSError as e:
        logger.warning(f"Falha ao abrir o navegador: {e}")
        return False


# =============================================================================
# EVIDENCIAS POS-CAMINHADA
# =============================================================================
def exportar_log_wlan(inicio_utc):
    destino = os.path.join(BRUTOS_DIR, "wlan_autoconfig_operational.evtx")
    consulta = f"*[System[TimeCreated[@SystemTime>='{inicio_utc.strftime('%Y-%m-%dT%H:%M:%S')}.000Z']]]"
    rc, _ = executar_cmd(["wevtutil", "epl", "Microsoft-Windows-WLAN-AutoConfig/Operational", destino,
                          f"/q:{consulta}", "/ow:true"], timeout=60)
    if rc != 0:
        logger.warning("Nao foi possivel exportar o log WLAN-AutoConfig/Operational.")
    script = (f"Get-WinEvent -FilterHashtable @{{LogName='Microsoft-Windows-WLAN-AutoConfig/Operational';"
              f"StartTime=[datetime]'{inicio_utc.astimezone().strftime('%Y-%m-%d %H:%M:%S')}'}} -ErrorAction SilentlyContinue |"
              " Sort-Object TimeCreated | ForEach-Object { \"[$($_.TimeCreated.ToString('HH:mm:ss.fff'))] $($_.Id) $($_.Message)\"; '' }")
    _, saida, _ = executar_ps(script, timeout=60)
    salvar_bruto("wlan_autoconfig_operational.txt", saida)


def gerar_wlanreport():
    rc, texto = executar_cmd(["netsh", "wlan", "show", "wlanreport", "duration=1"], timeout=180)
    salvar_bruto("netsh_wlanreport.txt", texto)
    origem = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\WlanReport\wlan-report-latest.html")
    if rc == 0 and os.path.exists(origem):
        try:
            shutil.copy2(origem, os.path.join(BRUTOS_DIR, "wlan-report.html"))
        except OSError as e:
            logger.warning(f"Nao foi possivel copiar o wlanreport: {e}")
    else:
        logger.warning("netsh wlan show wlanreport nao gerou o relatorio (exige Admin).")


# =============================================================================
# SAIDAS: CSVs, JSON E RELATORIO HTML
# =============================================================================
def _num_br(v, casas=1):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.{casas}f}".replace(".", ",")
    return str(v)


def _csv_tematico(v, casas=2):
    if v is None or v == "":
        return "N/A"
    if isinstance(v, bool):
        return "Sim" if v else "Nao"
    if isinstance(v, float):
        return f"{v:.{casas}f}"
    return str(v)


def gravar_csv(nome, colunas, linhas, delimitador=";"):
    caminho = os.path.join(OUTPUT_PATH, nome)
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=delimitador)
        w.writerow(colunas)
        w.writerows(linhas)
    return caminho


def gravar_detalhes(inicio_dt):
    def hora(t):
        return (inicio_dt + timedelta(seconds=t)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    gravar_csv(ARQ_AMOSTRAS,
               ["T_s", "Data_Hora", "Conectado", "Estado", "AP", "BSSID", "RSSI_dBm", "Qualidade_pct",
                "Canal", "Banda", "PHY", "Rx_Mbps", "Tx_Mbps"],
               [[_num_br(float(s["t"]), 3), hora(s["t"]), "Sim" if s["conectado"] else "Nao",
                 ESTADOS_WLAN.get(s.get("estado"), s.get("estado")), s.get("ap", ""), s.get("bssid", ""),
                 s.get("rssi", ""), s.get("qualidade", ""), s.get("canal", ""), banda_do_canal(s.get("canal")) or "",
                 s.get("phy", ""), _num_br(s.get("rx_mbps")), _num_br(s.get("tx_mbps"))] for s in ESTADO.amostras])
    linhas = []
    for destino, ip in (("gateway", ESTADO.gateway), ("internet", HOST_INTERNET)):
        for t, rtt in ESTADO.pings[destino]:
            linhas.append([_num_br(float(t), 3), hora(t), destino, ip, "Sim" if rtt is not None else "Nao",
                           _num_br(rtt, 2) if rtt is not None else ""])
    linhas.sort(key=lambda l: float(l[0].replace(",", ".")))
    gravar_csv(ARQ_PINGS, ["T_s", "Data_Hora", "Destino", "IP", "Respondeu", "RTT_ms"], linhas)
    gravar_csv(ARQ_ROAMINGS,
               ["Roaming", "Data_Hora", "T_s", "AP_Origem", "BSSID_Origem", "Canal_Origem", "Banda_Origem",
                "AP_Destino", "BSSID_Destino", "Canal_Destino", "Banda_Destino", "RSSI_Antes_dBm", "RSSI_Depois_dBm",
                "AKM_Depois", "Desconexao", "Duracao_ms", "Reassociacao_ms", "Conclusao_Windows_ms", "Troca_Demorada",
                "Fonte_Duracao", "Interrupcao_Gateway_ms",
                "Pico_Gateway_ms", "Interrupcao_Internet_ms", "Pico_Internet_ms", "Classificacao"],
               [[r["n"], hora(r["t"]), _num_br(float(r["t"]), 3), r["ap_origem"], r["bssid_origem"], r["canal_origem"],
                 r["banda_origem"], r["ap_destino"], r["bssid_destino"], r["canal_destino"], r["banda_destino"],
                 r["rssi_antes"], r["rssi_depois"], r["akm_nome"], "Sim" if r["desconexao"] else "Nao",
                 r["duracao_ms"], _num_br(r["reassociacao_ms"]), _num_br(r["conclusao_ms"]),
                 "Sim" if r["troca_demorada"] else "Nao",
                 r["fonte_duracao"], r["interrupcao_gateway_ms"] if r["interrupcao_gateway_ms"] is not None else "",
                 _num_br(r["pico_gateway_ms"]), r["interrupcao_internet_ms"] if r["interrupcao_internet_ms"] is not None else "",
                 _num_br(r["pico_internet_ms"]), r["classificacao"]] for r in ESTADO.roamings])
    gravar_csv(ARQ_EVENTOS, ["T_s", "Hora", "Evento", "MAC"],
               [[_num_br(float(e[0]), 3), e[1], e[2], e[3] or ""] for e in ESTADO.eventos])


def calcular_resumo(compat, conexao_inicial):
    rs = ESTADO.roamings
    drv = driver_resumo(compat)
    bios = compat.get("bios") or {}
    ad = compat.get("adaptador") or {}
    gw = estatisticas_ping(ESTADO.pings["gateway"])
    inet = estatisticas_ping(ESTADO.pings["internet"])
    rssis = [s.get("rssi") for s in ESTADO.amostras if s.get("conectado") and s.get("rssi") is not None]
    da_rede = [a for a in ESTADO.aps.values() if a.get("ssid", ESTADO.ssid) == ESTADO.ssid]
    duracao = round((ESTADO.fim_dt - ESTADO.inicio_dt).total_seconds(), 1) if ESTADO.inicio_dt and ESTADO.fim_dt else None
    so = compat.get("so") or {}
    return {
        "SSID": (ESTADO.ssid, ""),
        "Autenticacao": (conexao_inicial.get("autenticacao"), ""),
        "Cifra": (conexao_inicial.get("cifra"), ""),
        "AKM_Conectada": (nome_akm(conexao_inicial.get("akm")), ""),
        "AKM_FT": (isinstance(conexao_inicial.get("akm"), int) and conexao_inicial.get("akm") in AKMS_FT, ""),
        "Adaptador": (ad.get("InterfaceDescription") or drv.get("nome"), ""),
        "Driver_Versao": (drv.get("versao"), ""),
        "Driver_Data": (drv.get("data"), ""),
        "Driver_Fornecedor": (drv.get("fornecedor"), ""),
        "Firmware_Adaptador": (compat.get("capacidades", {}).get("firmware"), ""),
        "BIOS_Versao": (bios.get("SMBIOSBIOSVersion"), ""),
        "BIOS_Data": (_data_iso(bios.get("ReleaseDate")), ""),
        "SO_Build": (so.get("Build"), ""),
        "Suporte_FT_Declarado": (compat.get("capacidades", {}).get("fast_transition"), ""),
        "Suporte_80211k_Declarado": (compat.get("capacidades", {}).get("dot11k"), ""),
        "Suporte_80211v_Declarado": (compat.get("capacidades", {}).get("dot11v"), ""),
        "APs_Vistos": (len(da_rede), "APs"),
        "APs_Com_FT_Anunciado": (sum(1 for a in da_rede if a.get("ft_anunciado")), "APs"),
        "APs_Utilizados": (len({s["bssid"] for s in ESTADO.amostras if s.get("conectado")}), "APs"),
        "Duracao_Caminhada": (duracao, "s"),
        "Roamings_Total": (len(rs), "trocas"),
        "Roamings_FT": (sum(1 for r in rs if r["classificacao"] == CLASSE_FT), "trocas"),
        "Roamings_Nao_FT": (sum(1 for r in rs if r["classificacao"] == CLASSE_NAO_FT), "trocas"),
        "Roamings_Indeterminados": (sum(1 for r in rs if r["classificacao"] == CLASSE_INDET), "trocas"),
        "Roamings_Com_Desconexao": (sum(1 for r in rs if r["desconexao"]), "trocas"),
        "Roaming_Tempo_Medio": (_media([r["duracao_ms"] for r in rs]), "ms"),
        "Roaming_Tempo_Mediana": (_mediana([r["duracao_ms"] for r in rs]), "ms"),
        "Roaming_Tempo_Max": (_maximo([r["duracao_ms"] for r in rs]), "ms"),
        "Roaming_Reassociacao_Media": (_media([r["reassociacao_ms"] for r in rs]), "ms"),
        "Roaming_Reassociacao_Mediana": (_mediana([r["reassociacao_ms"] for r in rs]), "ms"),
        "Roaming_Reassociacao_Max": (_maximo([r["reassociacao_ms"] for r in rs]), "ms"),
        "Roaming_Conclusao_Windows_Media": (_media([r["conclusao_ms"] for r in rs]), "ms"),
        "Roaming_Conclusao_Windows_Mediana": (_mediana([r["conclusao_ms"] for r in rs]), "ms"),
        "Roaming_Conclusao_Windows_Max": (_maximo([r["conclusao_ms"] for r in rs]), "ms"),
        "Roamings_Demorados": (sum(1 for r in rs if r["troca_demorada"]), "trocas"),
        "Interrupcao_Gateway_Media": (_media([r["interrupcao_gateway_ms"] for r in rs]), "ms"),
        "Interrupcao_Gateway_Max": (_maximo([r["interrupcao_gateway_ms"] for r in rs]), "ms"),
        "Interrupcao_Internet_Media": (_media([r["interrupcao_internet_ms"] for r in rs]), "ms"),
        "Interrupcao_Internet_Max": (_maximo([r["interrupcao_internet_ms"] for r in rs]), "ms"),
        "Perda_Gateway": (gw["perda_pct"], "%"),
        "Latencia_Gateway_Media": (gw["media_ms"], "ms"),
        "Latencia_Gateway_P95": (gw["p95_ms"], "ms"),
        "Perda_Internet": (inet["perda_pct"] if ESTADO.internet_ok else None, "%"),
        "Latencia_Internet_Media": (inet["media_ms"] if ESTADO.internet_ok else None, "ms"),
        "Latencia_Internet_P95": (inet["p95_ms"] if ESTADO.internet_ok else None, "ms"),
        "RSSI_Min": (min(rssis) if rssis else None, "dBm"),
        "RSSI_Medio": (_media(rssis), "dBm"),
        "RSSI_Max": (max(rssis) if rssis else None, "dBm"),
        "Resultado": (ESTADO.resultado, ""),
    }, gw, inet


def secoes_compatibilidade(compat, conexao_inicial):
    def s(v):
        if v is None or v == "":
            return "N/A"
        if isinstance(v, bool):
            return "Sim" if v else "Não"
        if isinstance(v, list):
            return ", ".join(str(x) for x in v) or "N/A"
        return str(v)

    ad = compat.get("adaptador") or {}
    drv = driver_resumo(compat)
    caps = compat.get("capacidades", {})
    bios = compat.get("bios") or {}
    pc = compat.get("computador") or {}
    placa = compat.get("placa") or {}
    so = compat.get("so") or {}
    en = compat.get("energia", {})
    pm = compat.get("energia_adaptador") or {}
    ip = compat.get("ip") or {}
    secs = [
        {"titulo": "Adaptador Wi-Fi", "linhas": [
            ["Modelo", s(ad.get("InterfaceDescription"))], ["Nome da interface", s(ad.get("Name"))],
            ["MAC", s(ad.get("MacAddress"))], ["Velocidade do link", s(ad.get("LinkSpeed"))],
            ["Versão NDIS", s(ad.get("NdisVersion"))], ["PnP ID", s(ad.get("PnPDeviceID"))]]},
        {"titulo": "Driver", "linhas": [
            ["Versão", s(drv["versao"])], ["Data", s(drv["data"])], ["Fornecedor", s(drv["fornecedor"])],
            ["Arquivo INF", s(drv["inf"])], ["Assinado", s(drv["assinado"])], ["Tipo", s(caps.get("tipo_driver"))],
            ["Tipos de rádio", s(caps.get("radios_suportados"))], ["802.11w (MFP)", s(caps.get("80211w"))],
            ["WPA3-Personal", s(caps.get("wpa3_personal"))], ["WPA3-Enterprise", s(caps.get("wpa3_enterprise"))],
            ["Firmware", s(caps.get("firmware"))], ["Versão WDI", s(caps.get("wdi"))]]},
        {"titulo": "Capacidades declaradas (wirelesscapabilities)", "linhas": [
            ["Transição Rápida (802.11r)", s(caps.get("fast_transition"))],
            ["Neighbor Report (802.11k)", s(caps.get("dot11k"))],
            ["BSS Transition (802.11v)", s(caps.get("dot11v"))],
            ["Autenticação SAE (WPA3)", s(caps.get("sae"))], ["MBO", s(caps.get("mbo"))],
            ["Quadros de gerenciamento protegidos", s(caps.get("mfp"))],
            ["Randomização de MAC", s(caps.get("randomizacao_mac"))]]},
        {"titulo": "Sistema", "linhas": [
            ["Fabricante", s(pc.get("Manufacturer"))], ["Modelo", s(pc.get("Model"))],
            ["Família", s(pc.get("SystemFamily"))], ["Placa-mãe", s(f"{placa.get('Manufacturer', '')} {placa.get('Product', '')}".strip())],
            ["BIOS — fabricante", s(bios.get("Manufacturer"))], ["BIOS — versão", s(bios.get("SMBIOSBIOSVersion"))],
            ["BIOS — data", s(_data_iso(bios.get("ReleaseDate")))],
            ["Sistema operacional", s(so.get("Caption"))], ["Versão / build", s(f"{so.get('DisplayVersion', '')} — {so.get('Build', '')}")],
            ["Serviço WLAN AutoConfig", s(compat.get("servico_wlan"))]]},
        {"titulo": "Energia", "linhas": [
            ["Plano ativo", s(en.get("plano_ativo"))],
            ["Economia do adaptador sem fio — tomada", s(en.get("economia_wifi_ca"))],
            ["Economia do adaptador sem fio — bateria", s(en.get("economia_wifi_bateria"))],
            ["Permitir que o computador desligue o dispositivo", s(pm.get("AllowComputerToTurnOffDevice"))],
            ["Suspender ao desconectar (WoWLAN)", s(pm.get("DeviceSleepOnDisconnect"))]]},
        {"titulo": "Rede conectada (início do teste)", "linhas": [
            ["SSID", s(ESTADO.ssid)], ["BSSID inicial", s(conexao_inicial.get("bssid"))],
            ["Autenticação", s(conexao_inicial.get("autenticacao"))], ["Cifra", s(conexao_inicial.get("cifra"))],
            ["AKM conectada", nome_akm(conexao_inicial.get("akm"))], ["Tipo de rádio", s(conexao_inicial.get("radio"))],
            ["Banda / canal", s(f"{conexao_inicial.get('banda', '')} / {conexao_inicial.get('canal', '')}")],
            ["Sinal / RSSI", s(f"{conexao_inicial.get('sinal', '')} / {conexao_inicial.get('rssi', '')} dBm")],
            ["IPv4", s(ip.get("ipv4"))], ["Gateway", s(ESTADO.gateway)], ["DNS", s(ip.get("dns"))]]},
        {"titulo": "Propriedades avançadas do adaptador", "linhas": [
            [p.get("DisplayName"), s(p.get("DisplayValue"))] for p in compat.get("avancadas") or []]},
        {"titulo": "Outros adaptadores ativos", "linhas": [
            [o.get("Name"), f"{o.get('InterfaceDescription')} ({'físico' if o.get('HardwareInterface') else 'virtual'})"]
            for o in compat.get("outros_adaptadores_ativos") or []] or [["—", "Nenhum"]]},
    ]
    return secs


def gerar_relatorio(compat, conexao_inicial, resumo, gw, inet, achados):
    aps = sorted(ESTADO.aps.values(), key=lambda a: a["idx"])
    dados = {
        "meta": {"titulo": "Wi-Fi Fast Transition (802.11r)", "versao": VERSAO_TESTE, "host": platform.node(),
                 "inicio": ESTADO.inicio_dt.strftime("%d/%m/%Y %H:%M:%S") if ESTADO.inicio_dt else None,
                 "fim": ESTADO.fim_dt.strftime("%d/%m/%Y %H:%M:%S") if ESTADO.fim_dt else None,
                 "resultado": ESTADO.resultado, "motivo": ESTADO.motivo, "ssid": ESTADO.ssid,
                 "gateway": ESTADO.gateway, "internet": HOST_INTERNET, "internet_ok": ESTADO.internet_ok},
        "resumo": {k: v[0] for k, v in resumo.items()},
        "ping": {"gateway": gw, "internet": inet},
        "aps": [{"label": a["label"], "idx": a["idx"], "bssid": a["bssid"], "canal": a.get("canal"),
                 "banda": a.get("banda"), "phy": a.get("phy"), "rssi_max": a.get("rssi_max"),
                 "akms": [nome_akm(x) for x in a.get("akms", [])], "ft": a.get("ft_anunciado"),
                 "mdid": a.get("mdid"), "ft_ds": a.get("ft_sobre_ds"), "k": a.get("k"), "v": a.get("v"),
                 "mfp": a.get("mfp_capaz"), "com_ies": "akms" in a} for a in aps],
        "amostras": [[s["t"], s.get("rssi"), ESTADO.aps[s["bssid"]]["idx"] if s.get("conectado") else -1]
                     for s in ESTADO.amostras],
        "pings": {k: [[p[0], p[1]] for p in v] for k, v in ESTADO.pings.items()},
        "roamings": ESTADO.roamings,
        "compat": secoes_compatibilidade(compat, conexao_inicial),
        "achados": achados,
    }
    with open(os.path.join(ASSETS_DIR, "relatorio.html"), encoding="utf-8") as f:
        modelo = f.read()
    corpo = json.dumps(dados, ensure_ascii=False, default=str).replace("</", "<\\/")
    html = modelo.replace("/*__DADOS__*/null", corpo)
    caminho = os.path.join(OUTPUT_PATH, ARQ_RELATORIO)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)
    return caminho


def gravar_tematico(resumo):
    linhas = [[k, _csv_tematico(v), u] for k, (v, u) in resumo.items()]
    gravar_csv(ARQ_TEMATICO, ["Metrica", "Valor", "Unidade"], linhas, delimitador=",")


# =============================================================================
# FLUXO PRINCIPAL
# =============================================================================
def preflight(wlan):
    """Seleciona a interface Wi-Fi conectada. Retorna (guid_txt, amostra, campos_netsh) ou levanta RuntimeError."""
    ifaces = wlan.interfaces()
    if not ifaces:
        raise RuntimeError("Nenhum adaptador Wi-Fi encontrado nesta máquina.")
    conectadas = [i for i in ifaces if i["estado"] == ESTADO_CONECTADO]
    if not conectadas:
        estados = ", ".join(f"{i['descricao']} ({ESTADOS_WLAN.get(i['estado'], i['estado'])})" for i in ifaces)
        raise RuntimeError(f"O Wi-Fi não está conectado ({estados}). Conecte na rede destino antes de iniciar o teste.")
    iface = conectadas[0]
    wlan.selecionar(iface["guid"], iface["descricao"])
    guid_txt = iface["guid"].texto()
    amostra = wlan.amostra()
    if not amostra.get("conectado"):
        raise RuntimeError("A conexão Wi-Fi caiu durante o pré-voo. Reconecte e execute novamente.")
    campos, texto = ler_interface_netsh(guid_txt)
    salvar_bruto("netsh_interfaces_inicio.txt", texto)
    campos = campos or {}
    campos.setdefault("bssid", amostra["bssid"])
    campos["rssi"] = amostra.get("rssi")
    campos["canal"] = campos.get("canal") or amostra.get("canal")
    logger.info(f"Adaptador: {iface['descricao']} | SSID: {amostra['ssid']} | BSSID: {amostra['bssid']} | "
                f"RSSI: {amostra.get('rssi')} dBm | Canal: {amostra.get('canal')}")
    logger.info(f"Autenticacao: {campos.get('autenticacao')} | Cifra: {campos.get('cifra')} | AKM: {nome_akm(campos.get('akm'))}")
    return guid_txt, amostra, campos


def decidir_resultado():
    rs = ESTADO.roamings
    n_ft = sum(1 for r in rs if r["classificacao"] == CLASSE_FT)
    if n_ft >= 1:
        return 0, f"{n_ft} de {len(rs)} roaming(s) com Fast Transition."
    if not rs:
        return 1, ("Nenhuma troca de AP aconteceu durante a caminhada. Ande até áreas cobertas por outros APs "
                   "do mesmo SSID (afaste-se bem do AP inicial) e execute novamente.")
    n_nao = sum(1 for r in rs if r["classificacao"] == CLASSE_NAO_FT)
    if n_nao:
        return 1, f"{len(rs)} roaming(s), nenhum com Fast Transition ({n_nao} sem FT). Veja os achados de compatibilidade."
    return 1, f"{len(rs)} roaming(s), mas a AKM após a troca não pôde ser lida (indeterminado)."


def main():
    global _exit_code
    _exit_code = 1
    logger.info("=" * 70)
    logger.info(f"MODULO 6 — WI-FI FAST TRANSITION (802.11r) — v{VERSAO_TESTE}")
    logger.info("=" * 70)
    if HUB_EVIDENCE_DIR:
        logger.info(f"Modo Hub detectado. Evidencias em: {HUB_EVIDENCE_DIR}")
    else:
        logger.warning(f"HUB_EVIDENCE_DIR ausente. Evidencias em: {OUTPUT_PATH}")

    wlan = None
    servidor = None
    threads = []
    try:
        try:
            wlan = Wlan()
            guid_txt, amostra, conexao_inicial = preflight(wlan)
        except (RuntimeError, OSError) as e:
            logger.error(f"FALHA: {e}")
            return 1

        ESTADO.ssid = amostra["ssid"]
        compat = coletar_compatibilidade(guid_txt, ESTADO.ssid, conexao_inicial)
        gws = (compat.get("ip") or {}).get("gateway") or []
        ESTADO.gateway = gws[0] if gws else None
        if not ESTADO.gateway:
            logger.warning("Gateway padrao nao encontrado; ping do gateway desativado.")
        atualizar_bss(wlan)
        aps_inicio = [dict(a) for a in ESTADO.aps.values()]
        for a in sorted(aps_inicio, key=lambda x: x["idx"]):
            logger.info(f"  {a['label']} {a['bssid']} canal {a.get('canal')} RSSI {a.get('rssi')} dBm | "
                        f"AKMs {[nome_akm(x) for x in a.get('akms', [])]} | MDID {a.get('mdid')} | "
                        f"11k {a.get('k')} | 11v {a.get('v')}")
        achados_iniciais = gerar_achados(compat, aps_inicio, conexao_inicial, [])
        for a in achados_iniciais:
            (logger.info if a["nivel"] == "ok" else logger.warning)(f"[{a['nivel'].upper()}] {a['texto']}")

        # Monitor, AKM e pings comecam ja na espera, para o painel mostrar dados ao vivo
        wlan.registrar_notificacoes(receber_notificacao)
        threads = [threading.Thread(target=thread_monitor, args=(wlan,), daemon=True),
                   threading.Thread(target=thread_akm, args=(guid_txt,), daemon=True)]
        if ESTADO.gateway:
            threads.append(threading.Thread(target=thread_ping, args=("gateway", ESTADO.gateway), daemon=True))
        threads.append(threading.Thread(target=thread_ping, args=("internet", HOST_INTERNET), daemon=True))
        for th in threads:
            th.start()

        servidor = ServidorPainel(("127.0.0.1", 0), PainelHandler)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{servidor.server_address[1]}/"
        logger.info(f"Painel ao vivo: {url}")
        abrir_navegador(url)

        # Espera o clique em 'Iniciar caminhada' (ou inicio automatico)
        ESTADO.aguardando_desde = time.monotonic()
        if not ESTADO.pedido_inicio.wait(INICIO_AUTOMATICO_S):
            logger.info(f"Inicio automatico apos {INICIO_AUTOMATICO_S}s.")
        with ESTADO.lock:
            ESTADO.t_base = time.perf_counter()
            ESTADO.amostras.clear()
            for v in ESTADO.pings.values():
                v.clear()
            ESTADO.eventos.clear()
            ESTADO.akm_leituras.clear()
            ESTADO.ultimo_conectado = None
            ESTADO.inicio_dt = datetime.now()
            ESTADO.fase = "caminhada"
        inicio_utc = datetime.now(timezone.utc) - timedelta(seconds=5)
        ESTADO.reler_akm.set()
        logger.info(f"CAMINHADA INICIADA — {DURACAO_CAMINHADA_S}s. Ande pelo escritorio para provocar trocas de AP.")

        fim_previsto = time.monotonic() + DURACAO_CAMINHADA_S
        ultimo_log = 0
        while time.monotonic() < fim_previsto:
            if ESTADO.pedido_fim.wait(1.0):
                logger.info("Caminhada encerrada pelo operador ('Encerrar agora').")
                break
            if time.monotonic() - ultimo_log >= 30:
                ultimo_log = time.monotonic()
                with ESTADO.lock:
                    c = dict(ESTADO.conexao)
                    n = len(ESTADO.roamings)
                logger.info(f"  Restam {int(fim_previsto - time.monotonic())}s | AP {c.get('ap')} {c.get('bssid')} "
                            f"RSSI {c.get('rssi')} dBm | roamings: {n}")

        with ESTADO.lock:
            ESTADO.fase = "processando"
            ESTADO.fim_dt = datetime.now()
        time.sleep(INTERVALO_AKM_S + 0.5)  # ultima leitura de AKM apos uma troca recente
        ESTADO.parar.set()
        ESTADO.reler_akm.set()
        for th in threads:
            th.join(timeout=5)

        logger.info("Processando resultados...")
        with ESTADO.lock:
            ESTADO.internet_ok = any(p[1] is not None for p in ESTADO.pings["internet"])
            avaliar_roamings()
        if not ESTADO.internet_ok:
            logger.warning(f"Ping para {HOST_INTERNET} sem resposta (bloqueado?). Metricas de internet = N/A.")
        for r in ESTADO.roamings:
            logger.info(f"  Roaming #{r['n']} {r['hora']}: {r['ap_origem']} -> {r['ap_destino']} | {r['classificacao']} | "
                        f"AKM {r['akm_nome']} | {r['duracao_ms']} ms ({r['fonte_duracao']}; reassociacao "
                        f"{r['reassociacao_ms']} ms, conclusao {r['conclusao_ms']} ms"
                        f"{', DEMORADA' if r['troca_demorada'] else ''}) | "
                        f"interrupcao gw {r['interrupcao_gateway_ms']} ms | desconexao {r['desconexao']}")

        codigo, motivo = decidir_resultado()
        ESTADO.resultado = "PASS" if codigo == 0 else "FAIL"
        ESTADO.motivo = motivo

        exportar_log_wlan(inicio_utc)
        gerar_wlanreport()

        aps = list(ESTADO.aps.values())
        achados = gerar_achados(compat, aps, conexao_inicial, ESTADO.roamings)
        compat["aps"] = aps
        compat["achados"] = achados
        compat_salvo = {k: v for k, v in compat.items() if not k.startswith("netsh_")}
        with open(os.path.join(OUTPUT_PATH, ARQ_COMPAT), "w", encoding="utf-8") as f:
            json.dump(compat_salvo, f, ensure_ascii=False, indent=2, default=str)

        resumo, gw, inet = calcular_resumo(compat, conexao_inicial)
        gravar_detalhes(ESTADO.inicio_dt)
        gravar_tematico(resumo)
        caminho = gerar_relatorio(compat, conexao_inicial, resumo, gw, inet, achados)
        logger.info(f"Relatorio: {caminho}")

        with ESTADO.lock:
            ESTADO.relatorio_html = caminho
            ESTADO.fase = "concluido"
        if codigo == 0:
            logger.info(f"SUCESSO: {motivo}")
        else:
            logger.error(f"FALHA: {motivo}")
        time.sleep(ESPERA_FINAL_PAINEL_S)
        return codigo
    finally:
        ESTADO.parar.set()
        if servidor is not None:
            try:
                servidor.shutdown()
            except OSError:
                pass
        if wlan is not None:
            wlan.fechar()


if __name__ == "__main__":
    inicio = datetime.now()
    try:
        _exit_code = main()
    except KeyboardInterrupt:
        logger.error("FALHA: teste interrompido (Ctrl+C).")
        _exit_code = 1
    except Exception as e:  # noqa: BLE001 — qualquer erro inesperado vira FAIL com traceback no log
        logger.exception(f"FALHA: erro inesperado: {e}")
        _exit_code = 1
    fim = datetime.now()
    logger.info(f"FIM: {'PASS' if _exit_code == 0 else 'FAIL'} — {fim - inicio}")
    sys.exit(_exit_code)
