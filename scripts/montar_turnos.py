#!/usr/bin/env python3
"""Inclui o 2º turno de 2026 e os aptos de cada turno em mapa/dados.js.

Os votos de 2022 e do 1º turno de 2026 já estão no arquivo. Este script
não baixa urna de novo e não edita o JSON à mão: lê o cache e regrava o arquivo.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
MAPA = ROOT / "mapa" / "dados.js"
ZIP_2022 = Path("/tmp/tsework/zips/detalhe_votacao_secao_2022.zip")
BRANCO, NULO = "95", "96"


def titulo_lugar(nome: str) -> str:
    particulas = {"de", "da", "do", "das", "dos", "e"}
    partes = []
    for indice, parte in enumerate(nome.strip().title().split()):
        if indice and parte.lower() in particulas:
            partes.append(parte.lower())
        else:
            partes.append(parte)
    return " ".join(partes)


def aptos_2022() -> dict[str, dict[str, int]]:
    destino = CACHE / "aptos_2022.json"
    if destino.exists():
        return json.loads(destino.read_text(encoding="utf-8"))
    saida: dict[str, dict[str, int]] = {}
    with zipfile.ZipFile(ZIP_2022) as arquivo:
        with arquivo.open("detalhe_votacao_secao_2022_RS.csv") as bruto:
            leitor = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";")
            for linha in leitor:
                # O detalhe por seção de 2022 não traz a linha de presidente.
                # Os aptos da seção se repetem no cargo de governador.
                if linha["CD_CARGO"] != "3":
                    continue
                turno = linha["NR_TURNO"]
                if turno not in {"1", "2"}:
                    continue
                chave = f"{int(linha['CD_MUNICIPIO'])}-{int(linha['NR_ZONA'])}-{int(linha['NR_SECAO'])}"
                saida.setdefault(chave, {})[f"2022-{turno}"] = int(linha["QT_APTOS"] or 0)
    destino.write_text(json.dumps(saida, separators=(",", ":")), encoding="utf-8")
    return saida


def codigos_municipio() -> dict[str, int]:
    config = json.loads((CACHE / "2t" / "rs-p003221-cs.json").read_text(encoding="utf-8"))
    return {titulo_lugar(municipio["nm"]): int(municipio["cd"]) for municipio in config["abr"][0]["mu"]}


def carregar_dados() -> dict:
    texto = MAPA.read_text(encoding="utf-8")
    prefixo = "window.DADOS = "
    if not texto.startswith(prefixo) or not texto.rstrip().endswith(";"):
        raise SystemExit("dados.js fora do formato esperado")
    return json.loads(texto[len(prefixo):].rstrip()[:-1])


def votos_2026_2() -> dict[str, dict[str, int]]:
    pasta = CACHE / "2t" / "bu"
    saida = {}
    for arquivo in pasta.glob("*.json"):
        bruto = json.loads(arquivo.read_text(encoding="utf-8"))
        saida[arquivo.stem] = {str(numero): int(quantidade) for numero, quantidade in bruto.items()}
    return saida


def somar(parcela: dict, destino: dict) -> None:
    for numero, quantidade in parcela.items():
        destino[numero] += int(quantidade)


def main() -> None:
    dados = carregar_dados()
    codigos = codigos_municipio()
    votos = votos_2026_2()
    aptos_novo = json.loads((CACHE / "aptos_2026.json").read_text(encoding="utf-8"))
    aptos_antigo = aptos_2022()
    sem_codigo = set()
    sem_voto = 0
    voto_sem_lugar = set(votos)
    totais = defaultdict(int)
    aptos_totais = defaultdict(int)
    for local in dados["locais"]:
        codigo = codigos.get(local["cidade"])
        if codigo is None:
            sem_codigo.add(local["cidade"])
        acumulado = defaultdict(int)
        aptos_local = defaultdict(int)
        for secao in local["secoes"]:
            chave = f"{codigo}-{local['zona']}-{secao['secao']}" if codigo is not None else ""
            bloco = {}
            bloco.update(aptos_antigo.get(chave, {}))
            bloco.update(aptos_novo.get(chave, {}))
            if bloco:
                secao["aptos"] = bloco
                for eleicao, quantidade in bloco.items():
                    aptos_local[eleicao] += quantidade
                    aptos_totais[eleicao] += quantidade
            parcela = votos.get(chave)
            if parcela:
                secao.setdefault("v", {})["2026-2"] = parcela
                somar(parcela, acumulado)
                voto_sem_lugar.discard(chave)
            elif codigo is not None:
                sem_voto += 1
        if acumulado:
            local.setdefault("v", {})["2026-2"] = {numero: quantidade for numero, quantidade in acumulado.items()}
            somar(acumulado, totais)
        if aptos_local:
            local["aptos"] = {eleicao: quantidade for eleicao, quantidade in aptos_local.items()}
    dados["eleicoes"] = [
        {"id": "2026-2", "rotulo": "2026 · 2º turno", "adversario": "Flávio Bolsonaro"},
        {"id": "2026-1", "rotulo": "2026 · 1º turno", "adversario": "Flávio Bolsonaro"},
        {"id": "2022-2", "rotulo": "2022 · 2º turno", "adversario": "Jair Bolsonaro"},
        {"id": "2022-1", "rotulo": "2022 · 1º turno", "adversario": "Jair Bolsonaro"},
    ]
    dados["nomes"]["2026-2"] = {
        "13": "Lula",
        "22": "Flávio Bolsonaro",
        "95": "Branco",
        "96": "Nulo",
    }
    dados["atualizado"] = "2026-10-26"
    dados["validacao"]["turno_2026_2"] = {
        "lula": totais["13"],
        "flavio": totais["22"],
        "branco": totais[BRANCO],
        "nulo": totais[NULO],
        "aptos": {eleicao: aptos_totais[eleicao] for eleicao in ("2022-1", "2022-2", "2026-1", "2026-2")},
        "sem_voto": sem_voto,
        "voto_sem_lugar": len(voto_sem_lugar),
        "cidades_sem_codigo": sorted(sem_codigo),
    }
    MAPA.write_text(
        "window.DADOS = " + json.dumps(dados, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(json.dumps(dados["validacao"]["turno_2026_2"], ensure_ascii=False), flush=True)
    print("dados.js", MAPA.stat().st_size, flush=True)
    esperado = {"13": 2824552, "22": 3874378, "95": 89463, "96": 101245}
    if any(totais[numero] != quantidade for numero, quantidade in esperado.items()):
        raise SystemExit(f"totais do 2º turno divergem: {dict(totais)}")
    if sem_codigo or voto_sem_lugar:
        raise SystemExit("seções do 2º turno sem encaixe")
    if aptos_totais["2026-2"] != 8522318 or aptos_totais["2026-1"] != 8522545:
        raise SystemExit(f"aptos de 2026 divergem: {dict(aptos_totais)}")


if __name__ == "__main__":
    main()
