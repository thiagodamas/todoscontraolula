#!/usr/bin/env python3
"""Lê qtdEleitoresAptos dos boletins já baixados do RS, 1º e 2º turno de 2026."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import baixar_bu_2t as bu  # noqa: E402

CACHE = ROOT / "data" / "cache"
PASTAS = {
    "2026-1": (CACHE / "bu-raw", 6257),
    "2026-2": (CACHE / "2t" / "bu-raw", 6258),
}


def ler(tarefa: tuple[str, int, str]) -> tuple[str, str, int | None, str | None]:
    eleicao, codigo_eleicao, caminho = tarefa
    bruto = Path(caminho).read_bytes()
    try:
        arvore = bu.parse_tlv(bu.conteudo_do_envelope(bruto))
        bloco = bu.find_eleicao(arvore, codigo_eleicao)
        if not bloco or bloco[1][0] != 0x02:
            return eleicao, Path(caminho).stem, None, "sem aptos"
        return eleicao, Path(caminho).stem, bu.as_int(bloco[1][1]), None
    except Exception as exc:  # noqa: BLE001
        return eleicao, Path(caminho).stem, None, str(exc)


def main() -> None:
    tarefas = []
    for eleicao, (pasta, codigo) in PASTAS.items():
        for arquivo in pasta.glob("*.bu"):
            tarefas.append((eleicao, codigo, str(arquivo)))
    print(f"boletins: {len(tarefas)}", flush=True)
    saida: dict[str, dict[str, int]] = {}
    falhas = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        futuros = [pool.submit(ler, tarefa) for tarefa in tarefas]
        feitos = 0
        for futuro in as_completed(futuros):
            eleicao, chave, aptos, erro = futuro.result()
            feitos += 1
            if erro or aptos is None:
                falhas.append(f"{eleicao} {chave} {erro}")
            else:
                saida.setdefault(chave, {})[eleicao] = aptos
            if feitos % 5000 == 0 or feitos == len(tarefas):
                print(f"  lidos {feitos}/{len(tarefas)} falhas {len(falhas)}", flush=True)
    destino = CACHE / "aptos_2026.json"
    destino.write_text(json.dumps(saida, separators=(",", ":")), encoding="utf-8")
    if falhas:
        (CACHE / "aptos_2026_falhas.txt").write_text("\n".join(falhas) + "\n", encoding="utf-8")
    print(f"chaves {len(saida)} falhas {len(falhas)} bytes {destino.stat().st_size}", flush=True)
    if falhas:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
