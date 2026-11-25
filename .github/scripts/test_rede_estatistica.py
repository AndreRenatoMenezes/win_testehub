"""Teste de regressao: calculos do teste de rede unificado (Testes/_lib/rede_calc.py).

Cobre estatistica (mediana, quartis, CV, Estavel), exclusoes (aquecimento,
falha, contaminada), status por fonte, exit code, ordem intercalada, config,
leitura do ping e do netsh wlan (pt-BR/en-US), reparo dos servidores do
fast.com e as linhas dos CSVs. Nao abre navegador nem acessa a rede.
Rodar: python -I -X utf8 .github/scripts/test_rede_estatistica.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Testes" / "_lib"))
import rede_calc as rc  # noqa: E402

falhas = 0


def confere(cond, descricao):
    global falhas
    falhas += not cond
    print(f"  {'OK    ' if cond else 'FALHOU'}  {descricao}")


def perto(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


# --- Estatistica --------------------------------------------------------------
# Downloads da execucao de 24/11 23:17 (fast.com na DESKTOP-N3AUVKT)
s = rc.estatisticas([91, 73, 87, 65, 85])
confere(s["mediana"] == 85, "mediana de [91,73,87,65,85] = 85")
confere(perto(s["media"], 80.2), "media = 80,2")
confere(s["p25"] == 73 and s["p75"] == 87, "quartis inclusivos = 73 e 87")
confere(perto(s["cv"], 13.50), f"CV = 13,50% (obtido {s['cv']:.4f})")
confere(s["min"] == 65 and s["max"] == 91, "min 65 / max 91")
s1 = rc.estatisticas([42.0, None])
confere(s1["mediana"] == 42 and s1["p25"] is None and s1["cv"] is None, "1 valor: mediana, sem quartis nem CV")
confere(all(v is None for v in rc.estatisticas([]).values()), "sem valores: tudo None")
confere(rc.estatisticas([0, 0])["cv"] is None, "media zero: CV None (sem divisao por zero)")

confere(rc.estavel({"cv": 9.9}, {"cv": 10.0}, 10) == "sim", "Estavel=sim com CVs <= limite")
confere(rc.estavel({"cv": 9.9}, {"cv": 10.1}, 10) == "nao", "Estavel=nao com um CV acima")
confere(rc.estavel({"cv": None}, {"cv": 1}, 10) == "N/A", "Estavel=N/A sem CV")


# --- Rodadas, status e exit code ---------------------------------------------
def rod(n, status="ok", cont="nao", fonte="interno", down=100.0, up=50.0, **kw):
    return {"Fonte": fonte, "Rodada": n, "Status": status, "Contaminada": cont,
            "Download": down, "Upload": up, "Ping": 3.0, **kw}


confere(rc.rodada_valida(rod(1)), "rodada medida ok e limpa e valida")
confere(not rc.rodada_valida(rod(0)), "aquecimento nao entra")
confere(not rc.rodada_valida(rod(2, cont="sim")), "contaminada nao entra")
confere(not rc.rodada_valida(rod(3, status="falha")), "falha nao entra")

dez_ok = [rod(0)] + [rod(n) for n in range(1, 11)]
confere(rc.status_fonte(dez_ok, 8)[0] == "ok", "10 validas de 10 -> ok")
sete = [rod(n, status="falha" if n > 7 else "ok") for n in range(1, 11)]
st, mot = rc.status_fonte(sete, 8)
confere(st == "parcial" and "7 validas de 10" in mot, f"7 validas -> parcial ({mot})")
sete[-1]["Motivo"] = "speedtest interno nao concluiu em 120s"
st, mot = rc.status_fonte(sete, 8)
confere("ultima falha: speedtest interno nao concluiu em 120s" in mot, "parcial sem motivo_off traz a ultima falha")
cont = [rod(n, cont="sim") for n in range(1, 11)]
st, mot = rc.status_fonte(cont, 8)
confere(st == "off" and "contaminada" in mot, f"todas contaminadas -> off ({mot})")
st, mot = rc.status_fonte([], 8, "URL do speedtest interno nao configurada")
confere(st == "off" and mot == "URL do speedtest interno nao configurada", "sem rodadas -> off com o motivo")
st, mot = rc.status_fonte([rod(0), rod(1, status="bloqueio")], 8, "fast.com bloqueado: x")
confere(st == "off" and "fast.com bloqueado" in mot, "bloqueada -> off com o motivo")

confere(rc.exit_code({"interno": "ok", "internet": "off"}) == 0, "interno ok + internet off -> PASS")
confere(rc.exit_code({"interno": "off", "internet": "ok"}) == 0, "interno off + internet ok -> PASS")
confere(rc.exit_code({"interno": "parcial", "internet": "off"}) == 1, "parcial + off -> FAIL")
confere(rc.exit_code({"interno": "off", "internet": "off"}) == 1, "as duas off -> FAIL")

confere(rc.ordem_rodadas(2, 1) == [(0, "interno"), (0, "internet"), (1, "interno"), (1, "internet"),
                                   (2, "interno"), (2, "internet")], "ordem intercalada com aquecimento")
confere(rc.ordem_rodadas(1, 0) == [(1, "interno"), (1, "internet")], "sem aquecimento")

# --- Config -------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    cfg = rc.carregar_config(tmp, {})
    confere(cfg == {**rc.PADROES, "MinValidas": 8}, "sem config.json: padroes")
    Path(tmp, "config.json").write_text(json.dumps({"Rede": {"Rodadas": 4, "LimiteCV": "abc"}}), encoding="utf-8")
    cfg = rc.carregar_config(tmp, {})
    confere(cfg["Rodadas"] == 4 and cfg["MinValidas"] == 4 and cfg["LimiteCV"] == 10.0,
            "Rodadas do config, MinValidas limitado a Rodadas, valor invalido ignorado")
    cfg = rc.carregar_config(tmp, {"HUB_REDE_RODADAS": "2"})
    confere(cfg["Rodadas"] == 2 and cfg["MinValidas"] == 2, "HUB_REDE_RODADAS sobrescreve Rodadas")
    confere(rc.carregar_url_interna(tmp, {}) == "", "sem URL interna -> vazio")
    Path(tmp, "config.local.json").write_text('{"SpeedtestUrl": " https://speedtest.exemplo.local "}', encoding="utf-8")
    confere(rc.carregar_url_interna(tmp, {}) == "https://speedtest.exemplo.local", "URL do config.local.json")
    confere(rc.carregar_url_interna(tmp, {"HUB_SPEEDTEST_URL": "https://x"}) == "https://x", "HUB_SPEEDTEST_URL tem prioridade")

# --- Ping (saida localizada) ----------------------------------------------------
PING_PT = """
Disparando speedtest.exemplo.local com 32 bytes de dados:
Resposta de 127.0.0.1: bytes=32 tempo=3ms TTL=57
Resposta de 127.0.0.1: bytes=32 tempo=5ms TTL=57
Esgotado o tempo limite do pedido.
Resposta de 127.0.0.1: bytes=32 tempo=4ms TTL=57

Estat�sticas do Ping para 127.0.0.1:
    Aproximar um n�mero redondo de vezes em milissegundos:
    M�nimo = 3ms, M�ximo = 5ms, M�dia = 4ms
"""
PING_EN = """
Pinging speedtest.example with 32 bytes of data:
Reply from 127.0.0.1: bytes=32 time<1ms TTL=64
Reply from 127.0.0.1: bytes=32 time=2ms TTL=64
Request timed out.
"""
confere(rc.tempos_ping(PING_PT) == [3.0, 5.0, 4.0], "ping pt-BR: 3 respostas, ignora estatisticas")
confere(rc.tempos_ping(PING_EN) == [0.5, 2.0], "ping en-US: '<1ms' vira 0,5")
confere(rc.tempos_ping("Esgotado o tempo limite do pedido.\n" * 3) == [], "sem respostas")
confere(rc.ping_e_jitter([3.0, 5.0, 4.0]) == (4.0, 1.5), "mediana 4 e jitter 1,5 (|5-3|, |4-5|)")
confere(rc.ping_e_jitter([3.0]) == (3.0, None), "1 resposta: sem jitter")
confere(rc.ping_e_jitter([]) == (None, None), "nenhuma resposta: N/A")

# --- netsh wlan -----------------------------------------------------------------
WLAN_PT = """
Há 1 interface no sistema:

    Nome                   : Wi-Fi
    Descrição              : Intel(R) Wi-Fi 6E AX211 160MHz
    GUID                   : 1b2c3d4e-0000-0000-0000-000000000000
    Endereço físico        : aa:bb:cc:dd:ee:ff
    Estado                 : conectado
    SSID                   : LAB-CORP
    AP BSSID               : 70:3a:0e:12:34:56
    Banda                  : 5 GHz
    Canal                  : 44
    Tipo de rádio          : 802.11ax
    Sinal                  : 92%
"""
WLAN_EN = """
There are 2 interfaces on the system:

    Name                   : Wi-Fi 2
    State                  : disconnected

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : LAB-CORP
    BSSID                  : 70:3A:0E:AB:CD:EF
    Band                   : 6 GHz
    Channel                : 37
    Signal                 : 71%
"""
w = rc.parse_wlan(WLAN_PT, "Wi-Fi")
confere(w.get("bssid") == "70:3a:0e:12:34:56" and w.get("banda") == "5 GHz" and w.get("canal") == "44"
        and w.get("sinal") == 92, f"netsh pt-BR: {w}")
w = rc.parse_wlan(WLAN_EN, "wi-fi")
confere(w.get("bssid") == "70:3a:0e:ab:cd:ef" and w.get("banda") == "6 GHz" and w.get("sinal") == 71,
        "netsh en-US com 2 interfaces: escolhe a ativa pelo nome")
SEM_LOCAL = ("Há 1 interface no sistema: \nOs comandos do shell de rede precisam de permissão de local "
             "para acessar as informações da WLAN.\n")
confere(rc.parse_wlan(SEM_LOCAL, "Wi-Fi") == {}, "netsh sem permissao de Localizacao: {}")
confere(rc.parse_wlan("", None) == {}, "saida vazia: {}")

confere(rc.tipo_por_meio("Native 802.11", "Wi-Fi") == "wifi", "PhysicalMediaType 802.11 -> wifi")
confere(rc.tipo_por_meio("802.3", "Ethernet") == "cabo", "PhysicalMediaType 802.3 -> cabo")
confere(rc.tipo_por_meio("", "Ethernet 2") == "cabo", "sem meio: nome Ethernet -> cabo")
confere(rc.tipo_por_meio("", "Conexão Sem Fio") == "wifi", "sem meio: nome 'sem fio' -> wifi")
confere(rc.tipo_por_meio("", "vEthernet (WSL)") == "cabo", "vEthernet (nome) -> cabo")
confere(rc.tipo_por_meio("Unspecified", "Loopback") == "desconhecido", "meio desconhecido")

confere(rc.houve_roaming([(1, "a"), (2, None), (3, "a"), (4, "b"), (5, "b")]) == [4], "roaming na rodada 4")
confere(rc.houve_roaming([(1, None), (2, None)]) == [], "sem BSSID: sem roaming")

# --- fast.com ----------------------------------------------------------------------
LS = {"minDuration": "20", "maxDuration": "20", "minConnections": "8", "maxConnections": "8"}
confere(rc.config_fast_aplicada(LS, 20, 8), "config fixa reconhecida no localStorage")
confere(not rc.config_fast_aplicada({**LS, "maxDuration": "30"}, 20, 8), "duracao diferente -> padrao")
confere(not rc.config_fast_aplicada({}, 20, 8), "localStorage vazio -> padrao")
confere(rc.converter("1,2", "Gbps", rc.FATOR_MBPS, "mbps") == 1200, "1,2 Gbps -> 1200 Mbps")
confere(rc.converter("850", "Kbps", rc.FATOR_MBPS, "mbps") == 0.85, "850 Kbps -> 0,85 Mbps")
confere(rc.converter("", "Mbps", rc.FATOR_MBPS, "mbps") is None, "valor vazio -> None")

R = "�"
CASOS_REPARO = [
    (f"S{R}o Jo{R}o de Meriti, BR | Campos dos Goytacazes, BR | Rio de Janeiro, BR",
     "São João de Meriti, BR | Campos dos Goytacazes, BR | Rio de Janeiro, BR"),
    (f"Bras{R}lia, BR", "Brasília, BR"),
    (f"S{R}o Jos{R}, BR", "São José, BR"),
    (f"S{R}o Jos{R} dos Campos, BR", "São José dos Campos, BR"),
    (f"S{R}o Jos{R} dos Pinhais, BR", "São José dos Pinhais, BR"),  # prefixo conhecido (aceitavel)
    (f"Ita{R}na, BR", f"Ita{R}na, BR"),                              # nao casa dentro de nomes maiores
    (f"Ita{R}ba, BR", f"Ita{R}ba, BR"),
    (f"S{R}o Jo{R}o del-Rei, BR", f"S{R}o Jo{R}o del-Rei, BR"),      # fora da lista
    ("São João de Meriti, BR", "São João de Meriti, BR"),
    ("Rio De Janeiro, BR", "Rio De Janeiro, BR"),
    ("", ""),
    (None, None),
]
for entrada, esperado in CASOS_REPARO:
    confere(rc.reparar_texto(entrada) == esperado, f"reparar_texto({ascii(entrada)})")

# --- CSVs -----------------------------------------------------------------------------
CFG = rc.carregar_config(tempfile.gettempdir(), {"HUB_REDE_RODADAS": "3"})
CFG.update(Rodadas=3, MinValidas=3, Aquecimento=1)
rodadas = [
    rod(0, fonte="interno", down=60, Wifi_BSSID="aa", Conexao_Tipo="wifi"),
    rod(0, fonte="internet", status="bloqueio", down=None, up=None, Wifi_BSSID="aa", Conexao_Tipo="wifi"),
    rod(1, fonte="interno", down=100, up=200, Wifi_BSSID="aa", Conexao_Tipo="wifi"),
    rod(2, fonte="interno", down=104, up=204, Wifi_BSSID="bb", Conexao_Tipo="wifi"),
    rod(3, fonte="interno", down=900, up=900, cont="sim", Wifi_BSSID="bb", Conexao_Tipo="wifi"),
]
linhas = {m: (v, u) for m, v, u in rc.linhas_rede_csv(rodadas, CFG, {"internet": "fast.com bloqueado: x"})}
confere(linhas["Interno_Status"][0] == "parcial", "interno com 2 validas de 3 (minimo 3) -> parcial")
confere(linhas["Interno_Rodadas_Contaminadas"][0] == 1, "contaminada contada")
confere(linhas["Interno_Download_Mediana"] == ("102.00", "Mbps"), "mediana ignora aquecimento e contaminada")
confere(linhas["Interno_Download_CV"][1] == "%", "CV em %")
confere(linhas["Internet_Status"][0] == "off" and "bloqueado" in linhas["Internet_Motivo"][0], "internet off com motivo")
confere(linhas["Internet_Download_Mediana"][0] == "N/A", "sem validas: N/A")
confere(linhas["Conexao_Tipo"][0] == "wifi" and linhas["Roaming"][0] == "sim", "wifi e roaming no rede.csv")
confere(linhas["Roaming_Rodadas"][0] == "Interno 2", f"rodada do roaming ({linhas['Roaming_Rodadas'][0]})")
confere(rc.nome_rodada({"Fonte": "internet", "Rodada": 0}, 1) == "Internet A1", "nome da rodada de aquecimento")
confere(linhas["Versao_Teste"][0] == rc.VERSAO_TESTE, "Versao_Teste")
linha = rc.linha_rodada_csv(rodadas[0], 1)
confere(linha["Rodada"] == "A1" and linha["Download"] == "60,00" and linha["Jitter"] == "N/A",
        "CSV por rodada: aquecimento A1, decimal com virgula, N/A")
confere(list(linha) == rc.COLUNAS_RODADA, "colunas na ordem")

print()
if falhas:
    print(f"  {falhas} verificacao(oes) falharam.")
    sys.exit(1)
print("  Todas as verificacoes passaram.")
