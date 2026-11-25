"""Calculos do teste de rede unificado (Testes/3_rede/3_teste_rede.py).

Funcoes puras, sem Selenium nem acesso a rede: configuracao, estatistica
(mediana, quartis, CV), status por fonte, exit code, leitura do ping e do
``netsh wlan`` (pt-BR e en-US), reparo dos nomes de servidor do fast.com e as
linhas dos CSVs. A CI importa este modulo direto
(.github/scripts/test_rede_estatistica.py).

Este arquivo nao e um teste: o hub o exclui do menu (Get-Scripts).
"""

import json
import os
import re
import statistics
import unicodedata
from collections import Counter

VERSAO_TESTE = "2.0"

FONTES = ("interno", "internet")
PREFIXO = {"interno": "Interno", "internet": "Internet"}

# Padroes do bloco "Rede" do config.json (cada chave pode ser sobrescrita la)
PADROES = {
    "Rodadas": 10,
    "Aquecimento": 1,
    "MinValidas": 8,
    "LimiteCV": 10.0,
    "MaxFalhasSeguidas": 3,
    "TimeoutInternoSeg": 120,
    "TimeoutInternetSeg": 120,
    "FastDuracaoSeg": 20,
    "FastConexoes": 8,
    "PingsICMP": 10,
    "JanelaFundoSeg": 5,
    "LimiteTrafegoFundoKbps": 1000,
}

# Metricas por fonte, na ordem em que aparecem no rede.csv
METRICAS = {
    "interno": [("Download", "Mbps"), ("Upload", "Mbps"), ("Ping", "ms"), ("Jitter", "ms"),
                ("Ping_ICMP", "ms"), ("Jitter_ICMP", "ms")],
    "internet": [("Download", "Mbps"), ("Upload", "Mbps"), ("Ping", "ms"), ("Latencia_Carga", "ms")],
}
ESTATISTICAS = [("Mediana", "mediana"), ("Media", "media"), ("P25", "p25"), ("P75", "p75"),
                ("CV", "cv"), ("Min", "min"), ("Max", "max")]

COLUNAS_RODADA = [
    "Fonte", "Rodada", "Aquecimento", "Status", "Motivo", "Data_Hora", "Duracao_s",
    "Download", "Upload", "Ping", "Jitter", "Latencia_Carga", "Ping_ICMP", "Jitter_ICMP",
    "Trafego_Fundo_Kbps", "Contaminada", "Interface", "Conexao_Tipo", "Link_Mbps",
    "Wifi_Banda", "Wifi_Canal", "Wifi_Sinal", "Wifi_BSSID",
    "Local_Cliente", "IP_Saida", "Servidores", "Config_Fast", "Print",
]
COLUNAS_NUMERICAS = {"Duracao_s", "Download", "Upload", "Ping", "Jitter", "Latencia_Carga",
                     "Ping_ICMP", "Jitter_ICMP", "Trafego_Fundo_Kbps", "Link_Mbps"}


# =============================================================================
# CONFIGURACAO
# =============================================================================
def carregar_config(raiz_hub, ambiente=None):
    """Bloco "Rede" do config.json mesclado aos padroes.

    HUB_REDE_RODADAS (ambiente) sobrescreve "Rodadas" para testes rapidos.
    MinValidas nunca passa de Rodadas.
    """
    ambiente = os.environ if ambiente is None else ambiente
    cfg = dict(PADROES)
    try:
        with open(os.path.join(raiz_hub, "config.json"), encoding="utf-8-sig") as f:
            bloco = json.load(f).get("Rede") or {}
    except (OSError, ValueError, AttributeError):
        bloco = {}
    if isinstance(bloco, dict):
        for chave, padrao in PADROES.items():
            if chave in bloco:
                try:
                    cfg[chave] = type(padrao)(bloco[chave])
                except (TypeError, ValueError):
                    pass
    rodadas = str(ambiente.get("HUB_REDE_RODADAS", "")).strip()
    if rodadas.isdigit() and int(rodadas) > 0:
        cfg["Rodadas"] = int(rodadas)
    cfg["Rodadas"] = max(1, cfg["Rodadas"])
    cfg["Aquecimento"] = max(0, cfg["Aquecimento"])
    cfg["MinValidas"] = max(1, min(cfg["MinValidas"], cfg["Rodadas"]))
    cfg["MaxFalhasSeguidas"] = max(1, cfg["MaxFalhasSeguidas"])
    return cfg


def carregar_url_interna(raiz_hub, ambiente=None):
    """URL do speedtest interno: HUB_SPEEDTEST_URL ou SpeedtestUrl do config.local.json."""
    ambiente = os.environ if ambiente is None else ambiente
    url = str(ambiente.get("HUB_SPEEDTEST_URL", "")).strip()
    if url:
        return url
    try:
        with open(os.path.join(raiz_hub, "config.local.json"), encoding="utf-8-sig") as f:
            return str(json.load(f).get("SpeedtestUrl", "")).strip()
    except (OSError, ValueError, AttributeError):
        return ""


def ordem_rodadas(rodadas, aquecimento, fontes=FONTES):
    """[(n, fonte)] intercalado; n <= 0 e aquecimento."""
    return [(n, f) for n in range(1 - aquecimento, rodadas + 1) for f in fontes]


# =============================================================================
# ESTATISTICA
# =============================================================================
def estatisticas(valores):
    """Mediana, media, quartis (inclusivos), CV % (desvio amostral), min e max.

    Valores None sao ignorados. Sem valores: tudo None. Com 1 valor: quartis e
    CV ficam None.
    """
    vals = [float(v) for v in valores if v is not None]
    vazio = {k: None for _, k in ESTATISTICAS}
    if not vals:
        return vazio
    res = dict(vazio)
    res["mediana"] = statistics.median(vals)
    res["media"] = statistics.fmean(vals)
    res["min"] = min(vals)
    res["max"] = max(vals)
    if len(vals) >= 2:
        q = statistics.quantiles(vals, n=4, method="inclusive")
        res["p25"], res["p75"] = q[0], q[2]
        media = res["media"]
        res["cv"] = statistics.stdev(vals) / media * 100 if media else None
    return res


def rodada_valida(r):
    """Entra na estatistica: medida (n >= 1), ok e nao contaminada."""
    return r.get("Rodada", 0) >= 1 and r.get("Status") == "ok" and r.get("Contaminada") != "sim"


def estavel(stats_down, stats_up, limite_cv):
    """'sim' quando o CV do download e o do upload ficam <= limite; 'N/A' sem CV."""
    cvs = [s.get("cv") for s in (stats_down, stats_up)]
    if any(c is None for c in cvs):
        return "N/A"
    return "sim" if all(c <= limite_cv for c in cvs) else "nao"


def status_fonte(rodadas, min_validas, motivo_off=""):
    """(status, motivo) de uma fonte a partir das rodadas medidas dela.

    ok: validas >= min_validas; parcial: alguma valida; off: nenhuma.
    motivo_off: por que a fonte parou (nao configurada, bloqueada, falhas).
    """
    medidas = [r for r in rodadas if r.get("Rodada", 0) >= 1]
    validas = sum(1 for r in medidas if rodada_valida(r))
    contaminadas = sum(1 for r in medidas if r.get("Contaminada") == "sim")
    if validas >= min_validas:
        return "ok", motivo_off
    partes = []
    if medidas or validas:
        partes.append(f"{validas} validas de {len(medidas)} (minimo {min_validas})")
    if contaminadas:
        partes.append(f"{contaminadas} contaminada(s) por trafego de fundo")
    if motivo_off:
        partes.append(motivo_off)
    else:
        falhas = [r for r in medidas if r.get("Status") not in (None, "ok") and r.get("Motivo")]
        if falhas:
            partes.append(f"ultima falha: {falhas[-1]['Motivo']}")
    motivo = "; ".join(partes) or "nenhuma rodada medida"
    return ("parcial" if validas > 0 else "off"), motivo


def exit_code(status_por_fonte):
    """0 (PASS) quando pelo menos uma fonte terminou ok; 1 caso contrario."""
    return 0 if any(s == "ok" for s in status_por_fonte.values()) else 1


def kbps(bytes_delta, segundos):
    return bytes_delta * 8 / 1000 / segundos if segundos > 0 else 0.0


def mais_frequente(valores):
    valores = [v for v in valores if v]
    return Counter(valores).most_common(1)[0][0] if valores else "N/A"


# =============================================================================
# PING (saida localizada do ping.exe)
# =============================================================================
# "Resposta de x: bytes=32 tempo=3ms TTL=57" / "Reply from x: bytes=32 time<1ms TTL=57"
_RE_PING = re.compile(r"(?:tempo|time)\s*([=<])\s*(\d+(?:[.,]\d+)?)\s*ms", re.I)


def tempos_ping(texto):
    """Tempos (ms) das respostas; '<1ms' vira 0.5."""
    tempos = []
    for linha in (texto or "").splitlines():
        if "TTL" not in linha.upper():
            continue
        m = _RE_PING.search(linha)
        if m:
            v = float(m.group(2).replace(",", "."))
            tempos.append(v / 2 if m.group(1) == "<" else v)
    return tempos


def ping_e_jitter(tempos):
    """(mediana, jitter) — jitter = media de |t[i] - t[i-1]|; None se faltar dado."""
    if not tempos:
        return None, None
    jitter = (sum(abs(b - a) for a, b in zip(tempos, tempos[1:])) / (len(tempos) - 1)
              if len(tempos) >= 2 else None)
    return statistics.median(tempos), jitter


# =============================================================================
# NETSH WLAN (rotulos em pt-BR e en-US)
# =============================================================================
def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


_RE_CAMPO = re.compile(r"^\s*([^:\r\n]+?)\s*:\s?(.*?)\s*$")
_RE_MAC = re.compile(r"\b([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b", re.I)
_ROTULOS_WLAN = {
    "nome": "nome", "name": "nome",
    "ssid": "ssid", "ap bssid": "bssid", "bssid": "bssid",
    "banda": "banda", "band": "banda", "canal": "canal", "channel": "canal",
    "sinal": "sinal", "signal": "sinal", "estado": "estado", "state": "estado",
}


def parse_wlan(texto, interface=None):
    """Campos da interface Wi-Fi no 'netsh wlan show interfaces'.

    Com varias interfaces, escolhe a de Nome == interface (sem diferenciar
    maiusculas); sem ela, a primeira. Retorna {} quando nao ha nenhum bloco
    (ex.: netsh sem permissao de Localizacao no Windows 11).
    """
    blocos, atual = [], None
    for linha in (texto or "").replace("\r\n", "\n").splitlines():
        m = _RE_CAMPO.match(linha)
        if not m:
            continue
        chave = _ROTULOS_WLAN.get(normalizar(m.group(1)))
        if not chave:
            continue
        if chave == "nome":
            atual = {}
            blocos.append(atual)
        if atual is not None and chave not in atual:
            atual[chave] = m.group(2).strip()
    if not blocos:
        return {}
    escolhido = blocos[0]
    if interface:
        for b in blocos:
            if normalizar(b.get("nome")) == normalizar(interface):
                escolhido = b
                break
    out = dict(escolhido)
    if out.get("bssid"):
        mm = _RE_MAC.search(out["bssid"])
        out["bssid"] = mm.group(1).lower() if mm else None
    if out.get("sinal"):
        ms = re.search(r"(\d{1,3})\s*%", out["sinal"])
        out["sinal"] = int(ms.group(1)) if ms else None
    return out


def tipo_por_meio(meio, nome=""):
    """'wifi' / 'cabo' pelo PhysicalMediaType do Get-NetAdapter (ou pelo nome)."""
    meio = (meio or "").lower()
    if "802.11" in meio or "wireless" in meio:
        return "wifi"
    if "802.3" in meio:
        return "cabo"
    nome = normalizar(nome)
    if any(p in nome for p in ("wi-fi", "wifi", "wlan", "wireless", "sem fio")):
        return "wifi"
    if "ethernet" in nome:
        return "cabo"
    return "desconhecido"


def houve_roaming(bssids):
    """[(n, bssid)] -> lista de rodadas n em que o BSSID mudou (ignora vazios)."""
    trocas, anterior = [], None
    for n, b in bssids:
        if not b:
            continue
        if anterior is not None and b != anterior:
            trocas.append(n)
        anterior = b
    return trocas


# =============================================================================
# FAST.COM
# =============================================================================
FATOR_MBPS = {"kbps": 0.001, "mbps": 1.0, "gbps": 1000.0}
FATOR_MS = {"ms": 1.0, "s": 1000.0}

# O fast.com as vezes exibe o nome do servidor ja corrompido na origem
# ("Sao Joao de Meriti, BR" aparece com U+FFFD no lugar do "a" na propria pagina): o acento
# se perdeu antes do navegador e nao ha como recupera-lo do DOM. Cada U+FFFD
# casa com UMA letra; o nome so e restaurado quando bate exatamente com uma
# cidade conhecida. Fora da lista, o texto fica como veio (com U+FFFD).
CIDADES_ACENTUADAS = [
    "São João de Meriti", "São Paulo", "São Luís", "São José",
    "São José dos Campos", "São José do Rio Preto", "São Bernardo do Campo",
    "São Gonçalo", "São Leopoldo", "Brasília", "Belém", "Goiânia",
    "Florianópolis", "Vitória", "Maceió", "João Pessoa", "Cuiabá",
    "Ribeirão Preto", "Uberlândia", "Niterói", "Jundiaí", "Maringá",
    "Londrina", "Paraná", "Ceará", "Pará", "Amapá", "Piauí",
    "Espírito Santo", "Rondônia", "Goiás", "Macapá", "Teresina",
    "Aracaju", "Contagem", "Betim", "Petrópolis", "Volta Redonda",
    "Bogotá", "México", "Medellín", "Asunción", "Belém do Pará",
]


def reparar_texto(texto):
    """Restaura nomes conhecidos em que o acento virou U+FFFD na origem."""
    if not texto or "�" not in texto:
        return texto
    for nome in sorted(CIDADES_ACENTUADAS, key=len, reverse=True):
        padrao = "".join(r"[^\s|,]" if not c.isascii() else re.escape(c) for c in nome)
        # Ancorado nos separadores do fast.com (inicio, espaco, "|", ",", "-"):
        # nao casa dentro de nomes maiores (ex.: "Ita?na" com U+FFFD nao vira "Itaina").
        padrao = r"(?<![^\s|,-])" + padrao + r"(?![^\s|,-])"
        texto = re.sub(padrao, lambda m, n=nome: n if "�" in m.group(0) else m.group(0), texto)
    return texto


def parse_numero(texto):
    if texto is None:
        return None
    try:
        return float(str(texto).strip().replace(",", "."))
    except ValueError:
        return None


def converter(valor, unidade, fatores, unidade_padrao):
    """valor+unidade -> unidade padrao; unidade vazia = padrao; None se invalido."""
    numero = parse_numero(valor)
    if numero is None:
        return None
    fator = fatores.get((unidade or unidade_padrao).strip().lower())
    return None if fator is None else numero * fator


def config_fast_aplicada(ls, duracao, conexoes):
    """True quando o localStorage do fast.com tem duracao e conexoes fixas pedidas."""
    ls = ls or {}
    alvo = {"minDuration": duracao, "maxDuration": duracao,
            "minConnections": conexoes, "maxConnections": conexoes}
    return all(str(ls.get(k, "")).strip() == str(v) for k, v in alvo.items())


# =============================================================================
# SAIDA (CSVs)
# =============================================================================
def fmt_br(v):
    """Numero -> '140,00'; None -> 'N/A' (CSV por rodada, separador ';')."""
    return f"{v:.2f}".replace(".", ",") if isinstance(v, (int, float)) else "N/A"


def fmt_ponto(v):
    """Numero -> '140.00'; None -> 'N/A' (rede.csv)."""
    return f"{v:.2f}" if isinstance(v, (int, float)) else "N/A"


def linha_rodada_csv(r, aquecimento):
    """Dict pronto para o resultado_afericoes.csv (rodada <= 0 vira A1, A2...)."""
    out = {}
    for c in COLUNAS_RODADA:
        v = r.get(c)
        if c in COLUNAS_NUMERICAS:
            out[c] = fmt_br(v)
        elif c == "Rodada":
            out[c] = v if v >= 1 else f"A{v + aquecimento}"
        else:
            out[c] = "N/A" if v in (None, "") else v
    return out


def resumo_fontes(rodadas, cfg, motivos_off):
    """{fonte: {status, motivo, executadas, validas, contaminadas, stats, estavel}}."""
    res = {}
    for f in FONTES:
        rf = [r for r in rodadas if r.get("Fonte") == f]
        medidas = [r for r in rf if r.get("Rodada", 0) >= 1]
        validas = [r for r in medidas if rodada_valida(r)]
        status, motivo = status_fonte(rf, cfg["MinValidas"], motivos_off.get(f, ""))
        stats = {m: estatisticas(r.get(m) for r in validas) for m, _ in METRICAS[f]}
        res[f] = {
            "status": status, "motivo": motivo,
            "executadas": len(medidas), "validas": len(validas),
            "contaminadas": sum(1 for r in medidas if r.get("Contaminada") == "sim"),
            "stats": stats,
            "estavel": estavel(stats["Download"], stats["Upload"], cfg["LimiteCV"]),
        }
    return res


def nome_rodada(r, aquecimento):
    """'Interno 3' / 'Internet A1' — para logs e avisos."""
    n = r.get("Rodada", 0)
    return f"{PREFIXO.get(r.get('Fonte'), r.get('Fonte'))} {n if n >= 1 else f'A{n + aquecimento}'}"


def tipo_conexao_geral(rodadas):
    tipos = {r.get("Conexao_Tipo") for r in rodadas if r.get("Conexao_Tipo") not in (None, "", "desconhecido")}
    if not tipos:
        return "desconhecido"
    return tipos.pop() if len(tipos) == 1 else "misto"


def linhas_rede_csv(rodadas, cfg, motivos_off):
    """Linhas [Metrica, Valor, Unidade] do rede.csv (sem o cabecalho)."""
    resumo = resumo_fontes(rodadas, cfg, motivos_off)
    trocas = houve_roaming([(i, r.get("Wifi_BSSID")) for i, r in enumerate(rodadas)])
    linhas = [
        ["Versao_Teste", VERSAO_TESTE, "texto"],
        ["Rodadas_Configuradas", cfg["Rodadas"], "un"],
        ["Aquecimento_Por_Fonte", cfg["Aquecimento"], "un"],
        ["Conexao_Tipo", tipo_conexao_geral(rodadas), "texto"],
        ["Roaming", "sim" if trocas else "nao", "texto"],
        ["Roaming_Rodadas", "; ".join(nome_rodada(rodadas[i], cfg["Aquecimento"]) for i in trocas) or "N/A", "texto"],
    ]
    for f in FONTES:
        p, s = PREFIXO[f], resumo[f]
        linhas += [
            [f"{p}_Status", s["status"], "texto"],
            [f"{p}_Motivo", s["motivo"] or "N/A", "texto"],
            [f"{p}_Rodadas_Executadas", s["executadas"], "un"],
            [f"{p}_Rodadas_Validas", s["validas"], "un"],
            [f"{p}_Rodadas_Contaminadas", s["contaminadas"], "un"],
            [f"{p}_Estavel", s["estavel"], "texto"],
        ]
        for metrica, unidade in METRICAS[f]:
            for rotulo, chave in ESTATISTICAS:
                linhas.append([f"{p}_{metrica}_{rotulo}", fmt_ponto(s["stats"][metrica][chave]),
                               "%" if chave == "cv" else unidade])
        if f == "internet":
            medidas = [r for r in rodadas if r.get("Fonte") == f and r.get("Rodada", 0) >= 1]
            for campo in ("Config_Fast", "Local_Cliente", "IP_Saida", "Servidores"):
                linhas.append([f"{p}_{campo}", mais_frequente(r.get(campo) for r in medidas), "texto"])
    return linhas
