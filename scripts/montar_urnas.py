"""Cruza os logs das urnas com a abstenção oficial e grava mapa/urnas.js.

Cada seção é comparada com o próprio município. O desvio usa a taxa do
município e a variação que sobra depois do acaso esperado pelo tamanho da
seção. Município com menos de 8 seções comparáveis usa a taxa do estado.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CACHE = RAIZ / "data" / "cache"
MAPA = RAIZ / "mapa"
LIMITE = 3.0
BITS = {"abs": 1, "man": 2, "sem": 4, "bio": 8, "apos": 16}


def titulo_lugar(nome: str) -> str:
    particulas = {"de", "da", "do", "das", "dos", "e"}
    partes = []
    for indice, parte in enumerate(nome.strip().title().split()):
        if indice and parte.lower() in particulas:
            partes.append(parte.lower())
        else:
            partes.append(parte)
    return " ".join(partes)


def estimar(linhas: list[dict], chave_k: str, chave_n: str) -> tuple[float, float]:
    total_k = sum(item[chave_k] for item in linhas)
    total_n = sum(item[chave_n] for item in linhas)
    p = total_k / total_n if total_n else 0.0
    if len(linhas) < 2:
        return p, 0.0
    taxas = [item[chave_k] / item[chave_n] for item in linhas]
    media = sum(taxas) / len(taxas)
    variancia = sum((taxa - media) ** 2 for taxa in taxas) / (len(taxas) - 1)
    binomial = sum(p * (1 - p) / item[chave_n] for item in linhas) / len(linhas)
    return p, max(0.0, variancia - binomial)


def zscore(k: int, n: int, p: float, tau2: float) -> float:
    den = math.sqrt(max(p * (1 - p) / n + tau2, 0.0))
    if den < 1e-9:
        return 0.0
    return max(-99.0, min(99.0, (k / n - p) / den))


def carregar_logs() -> list[dict]:
    linhas = []
    with (CACHE / "logs_rs.jsonl").open(encoding="utf-8") as arquivo:
        for linha in arquivo:
            if linha.strip():
                linhas.append(json.loads(linha))
    return linhas


def carregar_mapa() -> tuple[dict, dict]:
    texto = (MAPA / "dados.js").read_text(encoding="utf-8")
    dados = json.loads(texto[texto.index("{") : texto.rindex("}") + 1])
    indice = {}
    for local in dados["locais"]:
        for secao in local["secoes"]:
            votos = secao.get("v", {}).get("2026-1", {})
            indice[(local["cidade"], int(local["zona"]), int(secao["secao"]))] = {
                "loc": int(local["local"]),
                "n": local["nome"],
                "b": local["bairro"],
                "e": local["endereco"],
                "lat": local["lat"],
                "lon": local["lon"],
                "apx": 1 if local["aprox"] else 0,
                "sul": 1 if local["sul"] else 0,
                "aptos": int(secao["aptos"]),
                "comp": int(sum(votos.values())),
            }
    return dados, indice


def nomes_municipio() -> dict[int, str]:
    bruto = json.loads((CACHE / "rs-p003220-cs.json").read_text(encoding="utf-8"))
    return {int(municipio["cd"]): titulo_lugar(municipio["nm"]) for municipio in bruto["abr"][0]["mu"]}


def aplicar(registros: list[dict], chave_k: str, chave_n: str, minimo: int, nome: str, municipios: dict, aceita=None) -> None:
    por_cidade = defaultdict(list)
    for registro in registros:
        if registro[chave_n] >= minimo and (aceita is None or aceita(registro)):
            por_cidade[registro["c"]].append(registro)
    estado = [registro for lista in por_cidade.values() for registro in lista]
    if len(estado) < 2:
        return
    p_estado, tau_estado = estimar(estado, chave_k, chave_n)
    for cidade, lista in por_cidade.items():
        if len(lista) >= 8:
            p, tau2 = estimar(lista, chave_k, chave_n)
            base = "municipio"
        else:
            p, tau2 = p_estado, tau_estado
            base = "estado"
        info = municipios[cidade]
        info[nome] = round(p, 4)
        info["base_" + nome] = base
        for registro in lista:
            z = zscore(registro[chave_k], registro[chave_n], p, tau2)
            registro["z" + nome] = round(z, 2)
            if abs(z) >= LIMITE and max(registro[chave_k], registro[chave_n] * p) >= 5:
                registro["f"] |= BITS[nome]


def contexto(registros: list[dict], chave_z: str, bit: int, destino: str) -> None:
    grupos = defaultdict(list)
    for registro in registros:
        grupos[(registro["c"], registro["z"], registro.get("loc"))].append(registro)
    for grupo in grupos.values():
        uteis = [item for item in grupo if item.get(chave_z) is not None]
        for registro in grupo:
            z = registro.get(chave_z)
            if not uteis or z is None or not (registro["f"] & bit):
                registro[destino] = 0
                continue
            mesmo = [
                item for item in uteis
                if item is not registro and item[chave_z] * z > 0 and abs(item[chave_z]) >= 2
            ]
            outros = len(uteis) - 1
            if outros <= 0:
                registro[destino] = 0
            elif len(mesmo) / outros >= 0.7:
                registro[destino] = 2
            elif not mesmo:
                registro[destino] = 1
            else:
                registro[destino] = 3


def main() -> None:
    nomes = nomes_municipio()
    _, indice = carregar_mapa()
    registros = []
    dias = defaultdict(int)
    sem_cadastro_geo = 0
    for log in carregar_logs():
        cidade = nomes.get(log["mun"], str(log["mun"]))
        base = indice.get((cidade, log["zona"], log["secao"]))
        if base is None:
            sem_cadastro_geo += 1
            base = {
                "loc": None, "n": "", "b": "", "e": "", "lat": None, "lon": None,
                "apx": 0, "sul": 0, "aptos": 0, "comp": 0,
            }
        aptos = base["aptos"]
        comp = base["comp"]
        faltaram = max(0, aptos - comp) if aptos else 0
        cadastrados = log["bio"] + log["man"]
        dias[log["dia"]] += 1
        registros.append({
            "c": cidade,
            "z": log["zona"],
            "s": log["secao"],
            "loc": base["loc"],
            "n": base["n"],
            "b": base["b"],
            "e": base["e"],
            "lat": None if base["lat"] is None else round(base["lat"], 5),
            "lon": None if base["lon"] is None else round(base["lon"], 5),
            "apx": base["apx"],
            "sul": base["sul"],
            "aptos": aptos,
            "comp": comp,
            "falt": faltaram,
            "votos": log["votos"],
            "bio": log["bio"],
            "sem": log["sem"],
            "man": log["man"],
            "out": log["out"],
            "apos": log["apos"],
            "seq": log["seq"],
            "h": log.get("h") or [0] * 24,
            "cad": cadastrados,
            "f": 0,
            "dif": abs(log["votos"] - comp) if aptos or comp else 0,
        })

    municipios = defaultdict(dict)
    for registro in registros:
        municipios[registro["c"]]["n"] = municipios[registro["c"]].get("n", 0) + 1
    def log_fecha(registro: dict) -> bool:
        return registro["dif"] <= 5

    aplicar(registros, "falt", "aptos", 50, "abs", municipios)
    aplicar(registros, "man", "cad", 40, "man", municipios, log_fecha)
    aplicar(registros, "sem", "votos", 80, "sem", municipios, log_fecha)
    aplicar(registros, "bio", "votos", 80, "bio", municipios, log_fecha)
    aplicar(registros, "apos", "votos", 80, "apos", municipios, log_fecha)
    contexto(registros, "zabs", BITS["abs"], "ca")
    for registro in registros:
        melhor = None
        for nome, bit in (("man", BITS["man"]), ("sem", BITS["sem"]), ("bio", BITS["bio"]), ("apos", BITS["apos"])):
            z = registro.get("z" + nome)
            if registro["f"] & bit and z is not None and (melhor is None or abs(z) > abs(melhor)):
                melhor = z
                registro["_sit"] = nome
        registro["zsmax"] = None if melhor is None else round(melhor, 2)
    contexto_situacao(registros)

    situacao = BITS["man"] | BITS["sem"] | BITS["bio"] | BITS["apos"]
    divergem = [item for item in registros if item["f"] & BITS["abs"] and item["f"] & situacao]
    saida = []
    for registro in registros:
        registro.pop("_sit", None)
        saida.append(registro)
    saida.sort(key=lambda item: (item["c"], item["z"], item["s"]))

    votos = sum(item["votos"] for item in registros)
    totais = {
        "secoes": len(registros),
        "votos": votos,
        "bio": sum(item["bio"] for item in registros),
        "sem": sum(item["sem"] for item in registros),
        "man": sum(item["man"] for item in registros),
        "out": sum(item["out"] for item in registros),
        "apos": sum(item["apos"] for item in registros),
        "aptos": sum(item["aptos"] for item in registros),
        "faltaram": sum(item["falt"] for item in registros),
        "divergem": len(divergem),
        "situacao": sum(1 for item in registros if item["f"] & situacao),
        "abstencao": sum(1 for item in registros if item["f"] & BITS["abs"]),
        "sem_coord": sum(1 for item in registros if item["lat"] is None),
        "log_difere": sum(1 for item in registros if item["dif"] > 5),
        "sem_lugar": sem_cadastro_geo,
    }
    pacote = {
        "gerado": "2026-10-12",
        "limite": LIMITE,
        "totais": totais,
        "municipios": municipios,
        "secoes": saida,
    }
    destino = MAPA / "urnas.js"
    destino.write_text(
        "window.URNAS = " + json.dumps(pacote, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    bio_h = sem_h = man_h = out_h = 0
    for item in registros:
        for celula in item["h"]:
            if isinstance(celula, list):
                bio_h += celula[0]
                sem_h += celula[1] if len(celula) > 1 else 0
                man_h += celula[2] if len(celula) > 2 else 0
                out_h += celula[3] if len(celula) > 3 else 0
    if registros and isinstance(registros[0]["h"][0], list):
        if (bio_h, sem_h, man_h, out_h) != (totais["bio"], totais["sem"], totais["man"], totais["out"]):
            raise SystemExit(f"horas não fecham com os totais: {bio_h, sem_h, man_h, out_h}")
    print("dias", dict(dias))
    print("totais", json.dumps(totais))
    print("horas", bio_h, sem_h, man_h, out_h)
    print("urnas.js", destino.stat().st_size)
    print("divergem sul", sum(1 for item in divergem if item["sul"]))


def contexto_situacao(registros: list[dict]) -> None:
    grupos = defaultdict(list)
    for registro in registros:
        grupos[(registro["c"], registro["z"], registro.get("loc"))].append(registro)
    bits = {"man": BITS["man"], "sem": BITS["sem"], "bio": BITS["bio"], "apos": BITS["apos"]}
    for grupo in grupos.values():
        for registro in grupo:
            nome = registro.get("_sit")
            if not nome:
                registro["cs"] = 0
                continue
            chave = "z" + nome
            z = registro.get(chave)
            uteis = [item for item in grupo if item.get(chave) is not None]
            mesmo = [
                item for item in uteis
                if item is not registro and item[chave] * z > 0 and abs(item[chave]) >= 2
            ]
            outros = len(uteis) - 1
            if outros <= 0:
                registro["cs"] = 0
            elif mesmo and len(mesmo) / outros >= 0.7:
                registro["cs"] = 2
            elif not mesmo:
                registro["cs"] = 1
            else:
                registro["cs"] = 3
            registro["sit"] = nome


if __name__ == "__main__":
    main()
