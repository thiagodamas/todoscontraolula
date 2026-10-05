#!/usr/bin/env python3
"""Monta o mapa do voto para presidente em todo o Rio Grande do Sul.

O mapa abre focado no sul do estado: municípios cuja mediana de latitude
fica ao sul do paralelo 30,5°S.

Fontes (TSE):
- votacao_secao_2022_BR: votos por seção, 1º e 2º turnos de 2022
- eleitorado_local_votacao_2026: local, bairro, endereço e coordenadas
- boletins de urna do pleito 3220 (1º turno de 2026), eleição federal 6257
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import asn1tools

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "data"
MAPA = ROOT / "mapa"
ASN1 = Path(__file__).resolve().parent / "bu.asn1"
ZIPS = Path("/tmp/tsework/zips")

SUL_PARALELO = -30.5


def titulo_lugar(nome: str) -> str:
    particulas = {"de", "da", "do", "das", "dos", "e"}
    partes = []
    for indice, parte in enumerate(nome.strip().title().split()):
        if indice and parte.lower() in particulas:
            partes.append(parte.lower())
        else:
            partes.append(parte)
    return " ".join(partes)
CANDIDATOS_2026 = {
    13: "Lula",
    22: "Flávio Bolsonaro",
    70: "Augusto Cury",
    14: "Renan Santos",
    55: "Ronaldo Caiado",
    30: "Romeu Zema",
    80: "Samara",
    16: "Hertz Dias",
    27: "Clariana Barão",
    21: "Edmilson Costa",
    35: "Wilson Grassi",
    29: "Rui Costa Pimenta",
    95: "Branco",
    96: "Nulo",
}
BRANCO, NULO = 95, 96
UA = "mapa-voto-pelotas-riogrande/1.0"


def http_get(url: str, attempts: int = 4) -> bytes:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.4 * (i + 1))
    raise RuntimeError(f"{url} -> {last}")


def parse_tlv(blob: bytes, start: int = 0, end: int | None = None):
    if end is None:
        end = len(blob)
    items = []
    index = start
    while index < end:
        tag = blob[index]
        index += 1
        length_byte = blob[index]
        index += 1
        if length_byte < 128:
            length = length_byte
        else:
            nbytes = length_byte & 0x7F
            length = int.from_bytes(blob[index : index + nbytes], "big")
            index += nbytes
        chunk = blob[index : index + length]
        index += length
        if tag & 0x20:
            items.append((tag, parse_tlv(chunk)))
        else:
            items.append((tag, chunk))
    return items


def as_int(value: bytes) -> int:
    return int.from_bytes(value, "big") if value else 0


def find_eleicao(nodes, eleicao_id: int):
    for _tag, payload in nodes:
        if not isinstance(payload, list) or not payload:
            continue
        tag0, value0 = payload[0]
        if tag0 == 0x02 and isinstance(value0, bytes) and as_int(value0) == eleicao_id:
            return payload
        found = find_eleicao(payload, eleicao_id)
        if found:
            return found
    return None


def _eh_lista_de_votos(payload) -> bool:
    sequences = [child for tag, child in payload if tag == 0x30 and isinstance(child, list)]
    if not sequences:
        return False
    return all(any(tag == 0x82 and isinstance(value, bytes) for tag, value in item) for item in sequences)


def votos_presidente(eleicao_node) -> dict[int, int]:
    encontrados = []

    def walk(nodes) -> bool:
        for _tag, payload in nodes:
            if not isinstance(payload, list):
                continue
            codigos = [
                as_int(value)
                for tag, value in payload
                if tag == 0x81 and isinstance(value, bytes) and len(value) <= 2
            ]
            listas = [
                value
                for tag, value in payload
                if tag == 0x30 and isinstance(value, list) and _eh_lista_de_votos(value)
            ]
            if 1 in codigos and listas:
                encontrados.extend(listas)
                return True
            if walk(payload):
                return True
        return False

    walk(eleicao_node)
    votos: dict[int, int] = defaultdict(int)
    for lista in encontrados:
        for tag, payload in lista:
            if tag != 0x30 or not isinstance(payload, list):
                continue
            tipo = None
            quantidade = 0
            codigo = None
            for child_tag, child in payload:
                if child_tag == 0x81 and isinstance(child, bytes):
                    tipo = as_int(child)
                elif child_tag == 0x82 and isinstance(child, bytes):
                    quantidade = as_int(child)
                elif child_tag == 0xA3 and isinstance(child, list):
                    numeros = [as_int(value) for ctag, value in child if ctag == 0x02 and isinstance(value, bytes)]
                    if len(numeros) >= 2:
                        codigo = numeros[1]
                    elif numeros:
                        codigo = numeros[0]
            if tipo == 1 and codigo is not None:
                votos[codigo] += quantidade
            elif tipo == 2:
                votos[BRANCO] += quantidade
            elif tipo == 3:
                votos[NULO] += quantidade
            elif tipo == 4 and codigo is not None:
                votos[codigo] += quantidade
    return dict(votos)


def decode_bu(path: Path, conv) -> dict[int, int]:
    raw = path.read_bytes()
    try:
        envelope = conv.decode("EntidadeEnvelopeGenerico", raw)
        conteudo = bytes(envelope["conteudo"])
    except Exception:
        conteudo = raw
    arvore = parse_tlv(conteudo)
    eleicao = find_eleicao(arvore, 6257)
    if not eleicao:
        raise ValueError("eleição 6257 não encontrada")
    votos = votos_presidente(eleicao)
    if not votos:
        raise ValueError("votos de presidente não encontrados")
    return votos


def testar_parser(conv) -> None:
    amostra = Path("/tmp/tsework/sample.bu")
    votos = decode_bu(amostra, conv)
    if votos.get(13) != 115:
        raise SystemExit(f"parser da amostra falhou: {votos}")
    print("parser ok", dict(sorted(votos.items())))


def coordenada(texto: str):
    texto = (texto or "").strip().replace(",", ".")
    if texto in {"", "#NULO", "#NULO#", "-1", "0"}:
        return None
    try:
        valor = float(texto)
    except ValueError:
        return None
    return valor


def coordenada_valida(lat, lon) -> bool:
    return lat is not None and lon is not None and -35 < lat < -27 and -58 < lon < -49


def carregar_locais_2026():
    caminho = ZIPS / "eleitorado_2026.zip"
    locais = {}
    nomes_mun = {}
    with zipfile.ZipFile(caminho) as arquivo:
        with arquivo.open("eleitorado_local_votacao_2026_RS.csv") as bruto:
            leitor = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";")
            for linha in leitor:
                if linha["NR_TURNO"] != "1":
                    continue
                codigo = int(linha["CD_MUNICIPIO"])
                nomes_mun[codigo] = titulo_lugar(linha["NM_MUNICIPIO"])
                zona = int(linha["NR_ZONA"])
                secao = int(linha["NR_SECAO"])
                lat = coordenada(linha["NR_LATITUDE"])
                lon = coordenada(linha["NR_LONGITUDE"])
                principal = int(linha["NR_SECAO_PRINCIPAL"])
                locais[(codigo, zona, secao)] = {
                    "cidade": nomes_mun[codigo],
                    "zona": zona,
                    "secao": secao,
                    "local": int(linha["NR_LOCAL_VOTACAO"]),
                    "nome": linha["NM_LOCAL_VOTACAO"].strip(),
                    "bairro": linha["NM_BAIRRO"].strip() or "Sem bairro",
                    "endereco": linha["DS_ENDERECO"].strip(),
                    "cep": linha["NR_CEP"].strip(),
                    "lat": lat if coordenada_valida(lat, lon) else None,
                    "lon": lon if coordenada_valida(lat, lon) else None,
                    "aptos": int(linha["QT_ELEITOR_ELEICAO_FEDERAL"] or 0),
                    "principal": principal if principal > 0 else None,
                }
    # Único local sem coordenada oficial: Comunidade Rainha da Paz, 5º distrito.
    for meta in locais.values():
        if meta["nome"] == "COMUNIDADE RAINHA DA PAZ" and meta["lat"] is None:
            meta["lat"] = -31.5821764
            meta["lon"] = -52.4493401
            meta["aprox"] = True
        else:
            meta["aprox"] = False
    return locais, nomes_mun


def carregar_votos_2022(nomes_mun):
    caminho = ZIPS / "votacao_2022_br.zip"
    votos = defaultdict(lambda: defaultdict(int))
    nomes = defaultdict(dict)
    locais = {}
    with zipfile.ZipFile(caminho) as arquivo:
        with arquivo.open("votacao_secao_2022_BR.csv") as bruto:
            leitor = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";")
            for linha in leitor:
                if linha["SG_UF"] != "RS" or linha["CD_CARGO"] != "1":
                    continue
                codigo = int(linha["CD_MUNICIPIO"])
                nomes_mun.setdefault(codigo, titulo_lugar(linha["NM_MUNICIPIO"]))
                turno = int(linha["NR_TURNO"])
                zona = int(linha["NR_ZONA"])
                secao = int(linha["NR_SECAO"])
                numero = int(linha["NR_VOTAVEL"])
                quantidade = int(linha["QT_VOTOS"] or 0)
                votos[(turno, codigo, zona, secao)][numero] += quantidade
                nomes[turno][numero] = linha["NM_VOTAVEL"].strip()
                locais[(codigo, zona, secao)] = {
                    "local": int(linha["NR_LOCAL_VOTACAO"]),
                    "nome": linha["NM_LOCAL_VOTACAO"].strip(),
                    "endereco": linha["DS_LOCAL_VOTACAO_ENDERECO"].strip(),
                }
    return votos, nomes, locais


def secoes_com_urna():
    destino = CACHE / "rs-p003220-cs.json"
    if not destino.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        origem = Path("/tmp/rs-cs.json")
        if origem.exists():
            destino.write_bytes(origem.read_bytes())
        else:
            url = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3220/config/rs/rs-p003220-cs.json"
            destino.write_bytes(http_get(url))
    dados = json.loads(destino.read_text())
    saida = []
    for municipio in dados["abr"][0]["mu"]:
        codigo = int(municipio["cd"])
        for zona in municipio["zon"]:
            for secao in zona["sec"]:
                if "da" not in secao:
                    continue
                saida.append((codigo, int(zona["cd"]), int(secao["ns"])))
    return saida


def baixar_bu(item, conv):
    codigo, zona, secao = item
    destino = CACHE / "bu" / f"{codigo}-{zona}-{secao}.json"
    if destino.exists():
        return item, json.loads(destino.read_text()), None
    mun = f"{codigo:05d}"
    zon = f"{zona:04d}"
    sec = f"{secao:04d}"
    base = f"https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3220/dados/rs/{mun}/{zon}/{sec}"
    aux_url = f"{base}/p003220-rs-m{mun}-z{zon}-s{sec}-aux.json"
    try:
        aux = json.loads(http_get(aux_url))
        hashes = [item["hash"] for item in aux.get("hashes", []) if item.get("st") == "Totalizado"] or [
            item["hash"] for item in aux.get("hashes", [])
        ]
        if not hashes:
            raise RuntimeError("sem hash")
        bu_url = f"{base}/{hashes[-1]}/o03220rs{mun}{zon}{sec}-bu.dat"
        bruto = CACHE / "bu-raw"
        bruto.mkdir(parents=True, exist_ok=True)
        arquivo = bruto / f"{codigo}-{zona}-{secao}.bu"
        if not arquivo.exists():
            arquivo.write_bytes(http_get(bu_url))
        votos = decode_bu(arquivo, conv)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(votos))
        return item, votos, None
    except Exception as exc:  # noqa: BLE001
        return item, None, str(exc)


def baixar_todos(secoes, conv):
    votos = {}
    falhas = []
    pendentes = []
    for item in secoes:
        destino = CACHE / "bu" / f"{item[0]}-{item[1]}-{item[2]}.json"
        if destino.exists():
            votos[item] = {int(k): v for k, v in json.loads(destino.read_text()).items()}
        else:
            pendentes.append(item)
    print(f"urnas em cache: {len(votos)}; a baixar: {len(pendentes)}")
    if not pendentes:
        return votos, falhas
    with ThreadPoolExecutor(max_workers=12) as pool:
        futuros = [pool.submit(baixar_bu, item, conv) for item in pendentes]
        feitos = 0
        for futuro in as_completed(futuros):
            item, resultado, erro = futuro.result()
            feitos += 1
            if erro:
                falhas.append((item, erro))
            else:
                votos[item] = resultado
            if feitos % 200 == 0 or feitos == len(pendentes):
                print(f"  baixadas {feitos}/{len(pendentes)} falhas {len(falhas)}", flush=True)
    return votos, falhas


def oficial_municipio(codigo: int):
    url = f"https://resultados.tse.jus.br/oficial/ele2026/6257/dados/rs/rs{codigo:05d}-c0001-e006257-u.json"
    dados = json.loads(http_get(url))
    votos = {}
    for agrupamento in dados["carg"][0]["agr"]:
        for partido in agrupamento.get("par", []):
            for candidato in partido.get("cand", []):
                votos[int(candidato["n"])] = int(candidato["vap"])
    votos[BRANCO] = int(dados["v"]["vb"])
    votos[NULO] = int(dados["v"]["tvn"])
    return votos


def oficiais_2026(codigos):
    saida = {}
    falhas = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futuros = {pool.submit(oficial_municipio, codigo): codigo for codigo in codigos}
        for futuro in as_completed(futuros):
            codigo = futuros[futuro]
            try:
                saida[codigo] = futuro.result()
            except Exception as exc:  # noqa: BLE001
                falhas.append((codigo, str(exc)))
    if falhas:
        print("totais oficiais com falha", len(falhas), falhas[:5], flush=True)
    return saida


def somar(votos: dict) -> dict:
    total = defaultdict(int)
    for parcela in votos.values():
        for numero, quantidade in parcela.items():
            total[int(numero)] += int(quantidade)
    return dict(total)


def agregar(meta_2026, votos_2022, nomes_2022, locais_2022, votos_2026, nomes_mun):
    grupos = {}

    def garantir(chave, base):
        if chave not in grupos:
            grupos[chave] = {
                "id": f"{base['cidade']}-{base['zona']}-{base['local']}",
                "cidade": base["cidade"],
                "zona": base["zona"],
                "local": base["local"],
                "nome": base["nome"],
                "bairro": base.get("bairro") or "Sem bairro",
                "endereco": base.get("endereco") or "",
                "lat": base.get("lat"),
                "lon": base.get("lon"),
                "aprox": bool(base.get("aprox")),
                "aptos": 0,
                "secoes": [],
            }
        return grupos[chave]

    chaves = set(meta_2026) | {(c, z, s) for (_t, c, z, s) in votos_2022}
    for codigo, zona, secao in sorted(chaves):
        meta = meta_2026.get((codigo, zona, secao))
        antigo = locais_2022.get((codigo, zona, secao))
        if meta:
            base = meta
        elif antigo:
            base = {
                "cidade": nomes_mun.get(codigo, str(codigo)),
                "zona": zona,
                "local": antigo["local"],
                "nome": antigo["nome"],
                "bairro": "Sem bairro em 2026",
                "endereco": antigo["endereco"],
                "lat": None,
                "lon": None,
                "aprox": False,
            }
        else:
            continue
        grupo = garantir((base["cidade"], base["zona"], base["local"], base["nome"]), base)
        if meta and meta.get("lat") and grupo["lat"] is None:
            grupo["lat"] = meta["lat"]
            grupo["lon"] = meta["lon"]
            grupo["aprox"] = meta["aprox"]
        grupo["aptos"] += meta["aptos"] if meta else 0
        detalhe = {
            "secao": secao,
            "aptos": meta["aptos"] if meta else 0,
            "v": {},
        }
        for turno, eleicao in ((1, "2022-1"), (2, "2022-2")):
            parcela = votos_2022.get((turno, codigo, zona, secao))
            if parcela:
                detalhe["v"][eleicao] = {str(k): v for k, v in parcela.items()}
        parcela_2026 = votos_2026.get((codigo, zona, secao))
        if parcela_2026:
            detalhe["v"]["2026-1"] = {str(k): v for k, v in parcela_2026.items()}
        if detalhe["v"] or detalhe["aptos"]:
            grupo["secoes"].append(detalhe)

    locais = []
    for grupo in grupos.values():
        grupo["secoes"].sort(key=lambda item: item["secao"])
        acumulado = {"2022-1": defaultdict(int), "2022-2": defaultdict(int), "2026-1": defaultdict(int)}
        for secao in grupo["secoes"]:
            for eleicao, votos in secao["v"].items():
                for numero, quantidade in votos.items():
                    acumulado[eleicao][numero] += quantidade
        grupo["v"] = {eleicao: dict(votos) for eleicao, votos in acumulado.items() if votos}
        grupo["n_secoes"] = len(grupo["secoes"])
        locais.append(grupo)
    latitudes = defaultdict(list)
    for local in locais:
        if local["lat"] is not None:
            latitudes[local["cidade"]].append(local["lat"])
    cidades_sul = set()
    for cidade, valores in latitudes.items():
        valores.sort()
        if valores[len(valores) // 2] <= SUL_PARALELO:
            cidades_sul.add(cidade)
    for local in locais:
        local["sul"] = local["cidade"] in cidades_sul
    print("municípios no sul", len(cidades_sul), flush=True)
    locais.sort(key=lambda item: (item["cidade"], item["bairro"], item["nome"], item["zona"], item["local"]))
    nomes = {
        "2026-1": {str(k): v for k, v in CANDIDATOS_2026.items()},
        "2022-1": {str(k): v.title() for k, v in nomes_2022.get(1, {}).items()},
        "2022-2": {str(k): v.title() for k, v in nomes_2022.get(2, {}).items()},
    }
    for eleicao in nomes.values():
        eleicao.setdefault("95", "Branco")
        eleicao.setdefault("96", "Nulo")
        eleicao["13"] = "Lula"
        if eleicao is nomes["2026-1"]:
            eleicao["22"] = "Flávio Bolsonaro"
        else:
            eleicao["22"] = "Jair Bolsonaro"
    return locais, nomes


def escrever_csv(locais, nomes):
    resumo = OUT / "locais.csv"
    secoes = OUT / "secoes.csv"
    with resumo.open("w", encoding="utf-8-sig", newline="") as arquivo:
        colunas = [
            "cidade", "zona", "local", "nome", "bairro", "endereco", "latitude", "longitude",
            "coordenada_aproximada", "aptos_2026", "secoes",
            "lula_2022_1", "bolsonaro_2022_1", "validos_2022_1",
            "lula_2022_2", "bolsonaro_2022_2", "validos_2022_2",
            "lula_2026", "flavio_2026", "cury_2026", "renan_2026", "caiado_2026", "zema_2026",
            "outros_2026", "branco_2026", "nulo_2026", "validos_2026",
        ]
        escritor = csv.DictWriter(arquivo, colunas, delimiter=";")
        escritor.writeheader()
        for local in locais:
            def pegar(eleicao, numero):
                return int(local.get("v", {}).get(eleicao, {}).get(str(numero), 0))

            def validos(eleicao):
                return sum(
                    quantidade
                    for numero, quantidade in local.get("v", {}).get(eleicao, {}).items()
                    if numero not in {"95", "96"}
                )

            outros = validos("2026-1") - pegar("2026-1", 13) - pegar("2026-1", 22)
            escritor.writerow({
                "cidade": local["cidade"],
                "zona": local["zona"],
                "local": local["local"],
                "nome": local["nome"],
                "bairro": local["bairro"],
                "endereco": local["endereco"],
                "latitude": local["lat"] if local["lat"] is not None else "",
                "longitude": local["lon"] if local["lon"] is not None else "",
                "coordenada_aproximada": "sim" if local["aprox"] else "nao",
                "aptos_2026": local["aptos"],
                "secoes": " ".join(str(secao["secao"]) for secao in local["secoes"]),
                "lula_2022_1": pegar("2022-1", 13),
                "bolsonaro_2022_1": pegar("2022-1", 22),
                "validos_2022_1": validos("2022-1"),
                "lula_2022_2": pegar("2022-2", 13),
                "bolsonaro_2022_2": pegar("2022-2", 22),
                "validos_2022_2": validos("2022-2"),
                "lula_2026": pegar("2026-1", 13),
                "flavio_2026": pegar("2026-1", 22),
                "cury_2026": pegar("2026-1", 70),
                "renan_2026": pegar("2026-1", 14),
                "caiado_2026": pegar("2026-1", 55),
                "zema_2026": pegar("2026-1", 30),
                "outros_2026": outros,
                "branco_2026": pegar("2026-1", 95),
                "nulo_2026": pegar("2026-1", 96),
                "validos_2026": validos("2026-1"),
            })

    with secoes.open("w", encoding="utf-8-sig", newline="") as arquivo:
        colunas = [
            "cidade", "zona", "secao", "local", "nome", "bairro", "endereco",
            "latitude", "longitude", "aptos", "eleicao", "numero", "candidato", "votos",
        ]
        escritor = csv.DictWriter(arquivo, colunas, delimiter=";")
        escritor.writeheader()
        for local in locais:
            for secao in local["secoes"]:
                for eleicao, votos in secao["v"].items():
                    for numero, quantidade in sorted(votos.items(), key=lambda item: int(item[0])):
                        escritor.writerow({
                            "cidade": local["cidade"],
                            "zona": local["zona"],
                            "secao": secao["secao"],
                            "local": local["local"],
                            "nome": local["nome"],
                            "bairro": local["bairro"],
                            "endereco": local["endereco"],
                            "latitude": local["lat"] if local["lat"] is not None else "",
                            "longitude": local["lon"] if local["lon"] is not None else "",
                            "aptos": secao["aptos"],
                            "eleicao": eleicao,
                            "numero": numero,
                            "candidato": nomes.get(eleicao, {}).get(str(numero), numero),
                            "votos": quantidade,
                        })


def escrever_dados_js(locais, nomes, validacao):
    MAPA.mkdir(parents=True, exist_ok=True)
    pacote = {
        "atualizado": "2026-10-05",
        "eleicoes": [
            {"id": "2026-1", "rotulo": "2026 · 1º turno", "adversario": "Flávio Bolsonaro"},
            {"id": "2022-2", "rotulo": "2022 · 2º turno", "adversario": "Jair Bolsonaro"},
            {"id": "2022-1", "rotulo": "2022 · 1º turno", "adversario": "Jair Bolsonaro"},
        ],
        "nomes": nomes,
        "validacao": validacao,
        "locais": locais,
    }
    destino = MAPA / "dados.js"
    destino.write_text("window.DADOS = " + json.dumps(pacote, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("dados.js", destino.stat().st_size)


def main():
    conv = asn1tools.compile_files(str(ASN1), codec="ber")
    testar_parser(conv)
    meta, nomes_mun = carregar_locais_2026()
    print("seções no eleitorado 2026", len(meta), "municípios", len(nomes_mun), flush=True)
    votos_2022, nomes_2022, locais_2022 = carregar_votos_2022(nomes_mun)
    print("seções com voto em 2022", len({(c, z, s) for (_t, c, z, s) in votos_2022}), flush=True)
    secoes = secoes_com_urna()
    print("urnas 2026", len(secoes), flush=True)
    votos_2026, falhas = baixar_todos(secoes, conv)
    if falhas:
        print("nova tentativa para", len(falhas), flush=True)
        time.sleep(3)
        votos_retry, falhas = baixar_todos([item for item, _erro in falhas], conv)
        votos_2026.update(votos_retry)
    if falhas:
        (CACHE / "falhas.txt").write_text("\n".join(f"{a} {b}" for a, b in falhas))
        print("falhas", len(falhas), flush=True)
    codigos = sorted({codigo for codigo, _zona, _secao in votos_2026})
    oficiais = oficiais_2026(codigos)
    divergencias = []
    lula = flavio = lula_oficial = flavio_oficial = 0
    for codigo in codigos:
        cidade = nomes_mun.get(codigo, str(codigo))
        parcial = somar({chave: votos for chave, votos in votos_2026.items() if chave[0] == codigo})
        oficial = oficiais.get(codigo, {})
        lula += parcial.get(13, 0)
        flavio += parcial.get(22, 0)
        lula_oficial += oficial.get(13, 0)
        flavio_oficial += oficial.get(22, 0)
        if not oficial or parcial.get(13, 0) != oficial.get(13, 0) or parcial.get(22, 0) != oficial.get(22, 0):
            divergencias.append({
                "cidade": cidade,
                "lula": parcial.get(13, 0),
                "lula_oficial": oficial.get(13, 0),
                "flavio": parcial.get(22, 0),
                "flavio_oficial": oficial.get(22, 0),
            })
    validacao = {
        "municipios": len(codigos),
        "lula": lula,
        "flavio": flavio,
        "lula_oficial": lula_oficial,
        "flavio_oficial": flavio_oficial,
        "divergencias": divergencias,
    }
    print("RS Lula", lula, "oficial", lula_oficial, "Flávio", flavio, "oficial", flavio_oficial, "divergências", len(divergencias), flush=True)
    locais, nomes = agregar(meta, votos_2022, nomes_2022, locais_2022, votos_2026, nomes_mun)
    sem_coord = [f"{local['cidade']} · {local['nome']}" for local in locais if local["lat"] is None and local.get("v", {}).get("2026-1")]
    print("locais", len(locais), "sem coordenada", len(sem_coord), flush=True)
    if sem_coord:
        (CACHE / "sem_coordenada.txt").write_text("\n".join(sem_coord))
    OUT.mkdir(parents=True, exist_ok=True)
    escrever_csv(locais, nomes)
    escrever_dados_js(locais, nomes, validacao)
    print("csv", OUT / "locais.csv", OUT / "secoes.csv")


if __name__ == "__main__":
    main()
