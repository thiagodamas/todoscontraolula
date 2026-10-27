#!/usr/bin/env python3
"""Baixa os boletins de urna do 2º turno de 2026 no Rio Grande do Sul.

Pleito 3221, eleição federal 6258, votação de 25/10/2026.
O bruto fica em data/cache/2t/bu-raw/ e os votos de presidente em data/cache/2t/bu/.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "2t"
BRUTO = CACHE / "bu-raw"
JSONS = CACHE / "bu"
OFICIAIS = CACHE / "oficial"
CONFIG = CACHE / "rs-p003221-cs.json"
UA = "mapa-voto-pelotas-riogrande/1.0"
PLEITO = 3221
ELEICAO = 6258
BRANCO, NULO = 95, 96


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


def parse_tlv(blob: bytes):
    items = []
    index = 0
    end = len(blob)
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


def conteudo_do_envelope(raw: bytes) -> bytes:
    for _tag, payload in parse_tlv(raw):
        achado = _octet_longo(payload if isinstance(payload, list) else [])
        if achado:
            return achado
    return raw


def _octet_longo(nodes) -> bytes | None:
    for tag, payload in nodes:
        if tag == 0x04 and isinstance(payload, bytes) and len(payload) > 200:
            return payload
        if isinstance(payload, list):
            achado = _octet_longo(payload)
            if achado:
                return achado
    return None


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
                    numeros = [
                        as_int(value) for ctag, value in child if ctag == 0x02 and isinstance(value, bytes)
                    ]
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


def decode_bu(raw: bytes) -> dict[int, int]:
    arvore = parse_tlv(conteudo_do_envelope(raw))
    eleicao = find_eleicao(arvore, ELEICAO)
    if not eleicao:
        raise ValueError(f"eleição {ELEICAO} não encontrada")
    votos = votos_presidente(eleicao)
    if not votos:
        raise ValueError("votos de presidente não encontrados")
    return votos


def carregar_config() -> dict:
    if not CONFIG.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        url = (
            "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/"
            f"{PLEITO}/config/rs/rs-p{PLEITO:06d}-cs.json"
        )
        CONFIG.write_bytes(http_get(url))
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def secoes_com_urna(config: dict) -> list[tuple[int, int, int]]:
    saida = []
    for municipio in config["abr"][0]["mu"]:
        codigo = int(municipio["cd"])
        for zona in municipio["zon"]:
            for secao in zona["sec"]:
                if "da" not in secao:
                    continue
                saida.append((codigo, int(zona["cd"]), int(secao["ns"])))
    return saida


def baixar_bu(item: tuple[int, int, int]):
    codigo, zona, secao = item
    destino = JSONS / f"{codigo}-{zona}-{secao}.json"
    if destino.exists():
        return item, json.loads(destino.read_text()), None
    mun = f"{codigo:05d}"
    zon = f"{zona:04d}"
    sec = f"{secao:04d}"
    base = (
        "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/"
        f"{PLEITO}/dados/rs/{mun}/{zon}/{sec}"
    )
    aux_url = f"{base}/p{PLEITO:06d}-rs-m{mun}-z{zon}-s{sec}-aux.json"
    try:
        aux = json.loads(http_get(aux_url))
        hashes = [parte["hash"] for parte in aux.get("hashes", []) if parte.get("st") == "Totalizado"] or [
            parte["hash"] for parte in aux.get("hashes", [])
        ]
        if not hashes:
            raise RuntimeError("sem hash")
        bu_url = f"{base}/{hashes[-1]}/o{PLEITO:05d}rs{mun}{zon}{sec}-bu.dat"
        BRUTO.mkdir(parents=True, exist_ok=True)
        arquivo = BRUTO / f"{codigo}-{zona}-{secao}.bu"
        if not arquivo.exists() or arquivo.stat().st_size == 0:
            arquivo.write_bytes(http_get(bu_url))
        votos = decode_bu(arquivo.read_bytes())
        JSONS.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(".json.tmp")
        temporario.write_text(json.dumps(votos))
        temporario.replace(destino)
        return item, votos, None
    except Exception as exc:  # noqa: BLE001
        return item, None, str(exc)


def baixar_todos(secoes: list[tuple[int, int, int]], workers: int):
    votos = {}
    falhas = []
    pendentes = []
    for item in secoes:
        destino = JSONS / f"{item[0]}-{item[1]}-{item[2]}.json"
        if destino.exists():
            votos[item] = {int(k): v for k, v in json.loads(destino.read_text()).items()}
        else:
            pendentes.append(item)
    print(f"urnas em cache: {len(votos)}; a baixar: {len(pendentes)}", flush=True)
    if not pendentes:
        return votos, falhas
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = [pool.submit(baixar_bu, item) for item in pendentes]
        feitos = 0
        for futuro in as_completed(futuros):
            item, resultado, erro = futuro.result()
            feitos += 1
            if erro:
                falhas.append((item, erro))
            else:
                votos[item] = resultado
            if feitos % 250 == 0 or feitos == len(pendentes):
                print(
                    f"  baixadas {feitos}/{len(pendentes)} falhas {len(falhas)}",
                    flush=True,
                )
    return votos, falhas


def oficial_municipio(codigo: int) -> dict[int, int]:
    destino = OFICIAIS / f"{codigo}.json"
    if destino.exists():
        dados = json.loads(destino.read_text())
    else:
        url = (
            "https://resultados.tse.jus.br/oficial/ele2026/"
            f"{ELEICAO}/dados/rs/rs{codigo:05d}-c0001-e{ELEICAO:06d}-u.json"
        )
        bruto = http_get(url)
        OFICIAIS.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(bruto)
        dados = json.loads(bruto)
    votos = {}
    for agrupamento in dados["carg"][0]["agr"]:
        for partido in agrupamento.get("par", []):
            for candidato in partido.get("cand", []):
                votos[int(candidato["n"])] = int(candidato["vap"])
    votos[BRANCO] = int(dados["v"]["vb"])
    votos[NULO] = int(dados["v"]["tvn"])
    return votos


def somar(votos: dict) -> dict[int, int]:
    total = defaultdict(int)
    for parcela in votos.values():
        for numero, quantidade in parcela.items():
            total[int(numero)] += int(quantidade)
    return dict(total)


def conferir(votos: dict) -> dict:
    codigos = sorted({codigo for codigo, _zona, _secao in votos})
    oficiais = {}
    falhas = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futuros = {pool.submit(oficial_municipio, codigo): codigo for codigo in codigos}
        for futuro in as_completed(futuros):
            codigo = futuros[futuro]
            try:
                oficiais[codigo] = futuro.result()
            except Exception as exc:  # noqa: BLE001
                falhas.append((codigo, str(exc)))
    divergencias = []
    totais = defaultdict(int)
    oficiais_totais = defaultdict(int)
    for codigo in codigos:
        parcial = somar({chave: parcela for chave, parcela in votos.items() if chave[0] == codigo})
        oficial = oficiais.get(codigo, {})
        for numero, quantidade in parcial.items():
            totais[numero] += quantidade
        for numero, quantidade in oficial.items():
            oficiais_totais[numero] += quantidade
        if not oficial or any(parcial.get(numero, 0) != oficial.get(numero, 0) for numero in (13, 22, BRANCO, NULO)):
            divergencias.append(
                {
                    "municipio": codigo,
                    "bu": {str(numero): parcial.get(numero, 0) for numero in (13, 22, BRANCO, NULO)},
                    "oficial": {str(numero): oficial.get(numero, 0) for numero in (13, 22, BRANCO, NULO)},
                }
            )
    return {
        "municipios": len(codigos),
        "secoes": len(votos),
        "lula": totais[13],
        "flavio": totais[22],
        "branco": totais[BRANCO],
        "nulo": totais[NULO],
        "lula_oficial": oficiais_totais[13],
        "flavio_oficial": oficiais_totais[22],
        "branco_oficial": oficiais_totais[BRANCO],
        "nulo_oficial": oficiais_totais[NULO],
        "divergencias": len(divergencias),
        "oficiais_falhos": len(falhas),
        "amostra_divergencias": divergencias[:8],
    }


def main() -> None:
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    config = carregar_config()
    secoes = secoes_com_urna(config)
    print(f"seções com boletim: {len(secoes)}", flush=True)
    if limite:
        secoes = secoes[:limite]
        print(f"amostra: {len(secoes)}", flush=True)
    votos, falhas = baixar_todos(secoes, workers=16)
    if falhas:
        print(f"nova tentativa para {len(falhas)}", flush=True)
        time.sleep(3)
        votos_retry, falhas = baixar_todos([item for item, _erro in falhas], workers=8)
        votos.update(votos_retry)
    if falhas:
        (CACHE / "falhas.txt").write_text(
            "\n".join(f"{codigo} {zona} {secao} {erro}" for (codigo, zona, secao), erro in falhas) + "\n",
            encoding="utf-8",
        )
        print(f"FAILED falhas {len(falhas)}", flush=True)
    else:
        print("boletins completos", flush=True)
    if limite:
        print("amostra", somar(votos), flush=True)
        return
    resumo = conferir(votos)
    resumo["falhas"] = len(falhas)
    (CACHE / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in resumo.items() if k != "amostra_divergencias"}), flush=True)
    if falhas or resumo["divergencias"] or resumo["oficiais_falhos"]:
        print("FAILED conferencia", flush=True)
        raise SystemExit(1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
