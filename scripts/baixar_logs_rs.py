"""Baixa só os logs das urnas do 1º turno de 2026 no Rio Grande do Sul.

O zip oficial também traz boletim, RDV e assinaturas (4,9 GB). Aqui entram
apenas os membros ``*-log.jez`` (cerca de 2,9 GB), por HTTP Range. Cada log é
lido na hora e reduzido a uma linha em ``data/cache/logs_rs.jsonl``. Rodar de
novo continua dos registros que já estão no arquivo.
"""

from __future__ import annotations

import http.client
import io
import json
import struct
import sys
import threading
import time
import zlib
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CACHE = RAIZ / "data" / "cache"
SAIDA = CACHE / "logs_rs.jsonl"
STATUS = CACHE / "logs_rs_status.txt"
INDICE = CACHE / "logs_rs_indice.json"
HOST = "cdn.tse.jus.br"
CAMINHO = (
    "/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/"
    "bu_imgbu_logjez_rdv_vscmr_2026_1t_RS.zip"
)
TRABALHOS = 16
MSG_VOTO = "O voto do eleitor foi computado"
MSG_PRONTA = (
    "Aguardando digitação do título",
    "Aguardando digitação do identificador do eleitor",
)
MSG_BIO = "Tipo de habilitação do eleitor [biométrica]"
MSG_SEM = "O eleitor não possui biometria"
MSG_ANO = "Ano de nascimento digitado é igual ao do cadastro"
MSG_MANUAL = "Solicitação de dado pessoal do eleitor para habilitação manual"
HAB_OUTRO, HAB_BIO, HAB_SEM, HAB_MANUAL = 0, 1, 2, 3
AMOSTRA = (87912, 34, 2, 270, 243, 8, 19)

_local = threading.local()
_escrita = threading.Lock()
_estranhos = Counter()
_estranhos_trava = threading.Lock()


def status(texto: str) -> None:
    STATUS.write_text(texto + "\n", encoding="utf-8")
    print(texto, flush=True)


def conexao() -> http.client.HTTPSConnection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(HOST, timeout=90)
        _local.conn = conn
    return conn


def fechar_conexao() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def baixar_intervalo(inicio: int, fim: int) -> bytes:
    ultimo = None
    for tentativa in range(5):
        try:
            conn = conexao()
            conn.request(
                "GET",
                CAMINHO,
                headers={
                    "Range": f"bytes={inicio}-{fim}",
                    "User-Agent": "todoscontraolula/1.0",
                    "Connection": "keep-alive",
                },
            )
            resposta = conn.getresponse()
            corpo = resposta.read()
            if resposta.status == 206 and len(corpo) == fim - inicio + 1:
                return corpo
            ultimo = f"HTTP {resposta.status} bytes {len(corpo)}"
            fechar_conexao()
        except Exception as exc:  # noqa: BLE001
            ultimo = f"{type(exc).__name__}: {exc}"
            fechar_conexao()
        time.sleep(0.4 * (tentativa + 1))
    raise RuntimeError(ultimo or "falha no intervalo")


def ler_zip64(extra: bytes, comp: int, uncomp: int, offset: int) -> tuple[int, int, int]:
    pos = 0
    while pos + 4 <= len(extra):
        ident, tamanho = struct.unpack_from("<HH", extra, pos)
        bloco = extra[pos + 4 : pos + 4 + tamanho]
        pos += 4 + tamanho
        if ident != 1:
            continue
        valores = list(struct.unpack("<" + "Q" * (len(bloco) // 8), bloco))
        cursor = iter(valores)
        if uncomp == 0xFFFFFFFF:
            uncomp = next(cursor)
        if comp == 0xFFFFFFFF:
            comp = next(cursor)
        if offset == 0xFFFFFFFF:
            offset = next(cursor)
    return comp, uncomp, offset


def indice_logs() -> list[dict]:
    if INDICE.exists():
        return json.loads(INDICE.read_text(encoding="utf-8"))
    status("Lendo o índice do zip oficial")
    cauda = baixar_intervalo(4917940986 - 200, 4917940986 - 1)
    marca = cauda.rfind(b"PK\x06\x07")
    deslocamento = struct.unpack_from("<Q", cauda, marca + 8)[0]
    cabeca = baixar_intervalo(deslocamento, deslocamento + 80)
    tamanho, inicio = struct.unpack_from("<QQ", cabeca, 40)
    central = baixar_intervalo(inicio, inicio + tamanho - 1)
    logs = []
    pos = 0
    while pos + 46 <= len(central):
        if central[pos : pos + 4] != b"PK\x01\x02":
            raise RuntimeError(f"índice ilegível na posição {pos}")
        metodo = struct.unpack_from("<H", central, pos + 10)[0]
        comp, uncomp = struct.unpack_from("<II", central, pos + 20)
        nlen, elen, clen = struct.unpack_from("<HHH", central, pos + 28)
        offset = struct.unpack_from("<I", central, pos + 42)[0]
        nome = central[pos + 46 : pos + 46 + nlen].decode("utf-8")
        extra = central[pos + 46 + nlen : pos + 46 + nlen + elen]
        if comp == 0xFFFFFFFF or uncomp == 0xFFFFFFFF or offset == 0xFFFFFFFF:
            comp, uncomp, offset = ler_zip64(extra, comp, uncomp, offset)
        if nome.endswith("-log.jez"):
            logs.append({"n": nome, "c": comp, "o": offset, "m": metodo})
        pos += 46 + nlen + elen + clen
    INDICE.write_text(json.dumps(logs), encoding="utf-8")
    status(f"Índice com {len(logs)} logs")
    return logs


def inflar(nome: str, comp: int, offset: int, metodo: int) -> bytes:
    folga = 30 + len(nome) + 80
    bloco = baixar_intervalo(offset, offset + folga + comp - 1)
    if bloco[:4] != b"PK\x03\x04":
        raise RuntimeError("cabeçalho local inválido")
    nlen, elen = struct.unpack_from("<HH", bloco, 26)
    metodo_local = struct.unpack_from("<H", bloco, 8)[0]
    inicio = 30 + nlen + elen
    if inicio + comp > len(bloco):
        dados = baixar_intervalo(offset + inicio, offset + inicio + comp - 1)
    else:
        dados = bloco[inicio : inicio + comp]
    if metodo_local == 0:
        return dados
    if metodo_local != 8 and metodo != 8:
        raise RuntimeError(f"compressão {metodo_local}")
    return zlib.decompress(dados, -15)


def texto_log(bruto: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(bruto)) as arquivo:
        nome = next(n for n in arquivo.namelist() if n.lower().endswith("logd.dat"))
        return arquivo.read(nome).decode("latin-1")


def resumir(nome: str, texto: str) -> dict:
    codigo = int(nome[8:13])
    zona = int(nome[13:17])
    secao = int(nome[17:21])
    eventos = []
    dias = Counter()
    for linha in texto.splitlines():
        partes = linha.split("\t")
        if len(partes) < 5 or partes[3] != "VOTA":
            continue
        dia, hora = partes[0][:10], partes[0][11:19]
        mensagem = partes[4]
        if mensagem == MSG_VOTO:
            dias[dia] += 1
        eventos.append((dia, hora, mensagem))
    if not dias:
        raise RuntimeError("log sem voto")
    dia_eleicao = dias.most_common(1)[0][0]
    votos = bio = sem = manual = outro = apos = manual_apos = sem_apos = 0
    sequencia = maior = 0
    ultimo = 0
    hab = HAB_OUTRO
    for dia, hora, mensagem in eventos:
        if dia != dia_eleicao:
            continue
        if mensagem in MSG_PRONTA:
            hab = HAB_OUTRO
            continue
        if mensagem == MSG_BIO:
            hab = HAB_BIO
            continue
        if mensagem == MSG_SEM:
            hab = HAB_SEM
            continue
        if mensagem == MSG_ANO and hab == HAB_OUTRO:
            hab = HAB_SEM
            continue
        if mensagem == MSG_MANUAL:
            hab = HAB_MANUAL
            continue
        if mensagem.startswith("Tipo de habilitação do eleitor") and mensagem != MSG_BIO:
            with _estranhos_trava:
                _estranhos[mensagem] += 1
            hab = HAB_OUTRO
            continue
        if mensagem != MSG_VOTO:
            continue
        h, m, s = (int(p) for p in hora.split(":"))
        instante = h * 3600 + m * 60 + s
        votos += 1
        ultimo = max(ultimo, instante)
        tarde = instante >= 17 * 3600
        if tarde:
            apos += 1
        if hab == HAB_BIO:
            bio += 1
            sequencia = 0
        elif hab == HAB_SEM:
            sem += 1
            sequencia = 0
            if tarde:
                sem_apos += 1
        elif hab == HAB_MANUAL:
            manual += 1
            sequencia += 1
            maior = max(maior, sequencia)
            if tarde:
                manual_apos += 1
        else:
            outro += 1
            sequencia = 0
        hab = HAB_OUTRO
    return {
        "mun": codigo,
        "zona": zona,
        "secao": secao,
        "votos": votos,
        "bio": bio,
        "sem": sem,
        "man": manual,
        "out": outro,
        "apos": apos,
        "man_apos": manual_apos,
        "sem_apos": sem_apos,
        "seq": maior,
        "ultimo": ultimo,
        "dia": dia_eleicao,
    }


def processar(item: dict) -> dict:
    bruto = inflar(item["n"], item["c"], item["o"], item["m"])
    return resumir(item["n"], texto_log(bruto))


def prontos() -> set[tuple[int, int, int]]:
    feitos = set()
    if not SAIDA.exists():
        return feitos
    with SAIDA.open(encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue
            item = json.loads(linha)
            feitos.add((item["mun"], item["zona"], item["secao"]))
    return feitos


def conferir_amostra(logs: list[dict]) -> None:
    nome = f"o03220rs{AMOSTRA[0]:05d}{AMOSTRA[1]:04d}{AMOSTRA[2]:04d}-log.jez"
    item = next(registro for registro in logs if registro["n"] == nome)
    resumo = processar(item)
    esperado = {
        "votos": AMOSTRA[3],
        "bio": AMOSTRA[4],
        "sem": AMOSTRA[5],
        "man": AMOSTRA[6],
    }
    obtido = {chave: resumo[chave] for chave in esperado}
    if obtido != esperado:
        raise SystemExit(f"amostra divergiu: {obtido} != {esperado}")
    print(
        f"AMOSTRA_OK Pelotas zona {AMOSTRA[1]} seção {AMOSTRA[2]} "
        f"votos {resumo['votos']} digital {resumo['bio']} sem cadastro {resumo['sem']} "
        f"manual {resumo['man']} após 17h {resumo['apos']}",
        flush=True,
    )


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    logs = indice_logs()
    if len(logs) != 27547:
        raise SystemExit(f"esperava 27547 logs e o índice tem {len(logs)}")
    conferir_amostra(logs)
    feitos = prontos()
    fila = []
    for item in logs:
        chave = (int(item["n"][8:13]), int(item["n"][13:17]), int(item["n"][17:21]))
        if chave not in feitos:
            fila.append(item)
    status(f"RUN 0/{len(fila)} já={len(feitos)}")
    if not fila:
        status(f"DONE secoes={len(feitos)}")
        return 0
    arquivo = SAIDA.open("a", encoding="utf-8")
    concluidos = 0
    falhas: list[str] = []
    inicio = time.time()

    def guardar(resumo: dict) -> None:
        arquivo.write(json.dumps(resumo, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(max_workers=TRABALHOS) as pool:
        futuros = {pool.submit(processar, item): item for item in fila}
        for futuro in as_completed(futuros):
            item = futuros[futuro]
            try:
                resumo = futuro.result()
            except Exception as exc:  # noqa: BLE001
                falhas.append(f"{item['n']} {type(exc).__name__}: {exc}")
            else:
                with _escrita:
                    guardar(resumo)
                concluidos += 1
            if (concluidos + len(falhas)) % 200 == 0:
                arquivo.flush()
                ritmo = concluidos / max(time.time() - inicio, 1)
                status(
                    f"RUN {concluidos}/{len(fila)} falhas={len(falhas)} "
                    f"{ritmo:.0f}/s já={len(feitos)}"
                )
    arquivo.flush()
    arquivo.close()
    if falhas:
        (CACHE / "logs_rs_falhas.txt").write_text("\n".join(falhas), encoding="utf-8")
        status(f"FAILED faltam={len(falhas)} lidos={concluidos}")
        return 1
    extras = ", ".join(f"{k}={v}" for k, v in _estranhos.most_common(8)) or "nenhuma"
    status(f"DONE secoes={len(feitos) + concluidos} habilitacoes_novas={extras}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
