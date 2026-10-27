const LULA = "#c41e2a";
const ADV = "#1565c0";
const cicloEl = document.querySelector("#ciclo");
const cidadeEl = document.querySelector("#cidade");
const buscaEl = document.querySelector("#busca");
const D = window.DADOS;

const mapa = L.map("mapa", { scrollWheelZoom: true, zoomControl: false, preferCanvas: true });
L.control.zoom({ position: "bottomleft" }).addTo(mapa);
const atr = "Tiles &copy; Esri";
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 18,
  maxNativeZoom: 16,
  attribution: atr
}).addTo(mapa);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {
  maxZoom: 18,
  maxNativeZoom: 16
}).addTo(mapa);
const camada = L.layerGroup().addTo(mapa);
let selecionado = null;
let tela = "mapa";
let linhasRanking = [];
let ordemRanking = null;

function turno(qual) {
  return cicloEl.value + "-" + qual;
}
function nomeAzul() {
  return cicloEl.value === "2022" ? "Jair Bolsonaro" : "Flávio Bolsonaro";
}
function nomeCurto() {
  return cicloEl.value === "2022" ? "Jair" : "Flávio";
}
function votosDe(entidade, eleicao) {
  return (entidade.v && entidade.v[eleicao]) || {};
}
function aptosDe(entidade, eleicao) {
  const bloco = entidade.aptos;
  if (!bloco || typeof bloco !== "object" || !Object.prototype.hasOwnProperty.call(bloco, eleicao)) return null;
  return bloco[eleicao];
}
function numero(valor) {
  return Math.round(valor || 0).toLocaleString("pt-BR");
}
function sinal(valor) {
  if (valor == null || Number.isNaN(valor)) return "–";
  const texto = numero(Math.abs(valor));
  if (valor > 0) return "+" + texto;
  if (valor < 0) return "−" + texto;
  return "0";
}
function percentual(parte, total) {
  if (!total) return "–";
  return (100 * parte / total).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
}
function pontosTexto(valor) {
  if (valor == null || Number.isNaN(valor)) return "–";
  const texto = Math.abs(valor * 100).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (valor > 0) return "+" + texto + " p.p.";
  if (valor < 0) return "−" + texto + " p.p.";
  return "0,0 p.p.";
}
function casaDecimal(valor) {
  if (valor == null || Number.isNaN(valor)) return "–";
  const texto = Math.abs(valor).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (valor > 0) return "+" + texto;
  if (valor < 0) return "−" + texto;
  return "0,0";
}
function escapar(texto) {
  return String(texto).replace(/[&<>"]/g, (caractere) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[caractere]));
}
function resumo(votos) {
  const lula = votos["13"] || 0;
  const adv = votos["22"] || 0;
  let validos = 0;
  let outros = 0;
  Object.entries(votos).forEach(([numeroCandidato, quantidade]) => {
    if (numeroCandidato === "95" || numeroCandidato === "96") return;
    validos += quantidade;
    if (numeroCandidato !== "13" && numeroCandidato !== "22") outros += quantidade;
  });
  const duelo = lula + adv;
  return {
    lula, adv, outros, validos, duelo,
    branco: votos["95"] || 0,
    nulo: votos["96"] || 0,
    lulaNoDuelo: duelo ? lula / duelo : null
  };
}
function contaDe(entidade, eleicao) {
  const base = resumo(votosDe(entidade, eleicao));
  const aptos = aptosDe(entidade, eleicao);
  const comparecimento = base.validos + base.branco + base.nulo;
  const abstencao = aptos == null ? null : aptos - comparecimento;
  return Object.assign(base, { aptos, comparecimento, abstencao });
}
function saldoDe(t1, t2) {
  const pontos = t1.lulaNoDuelo == null || t2.lulaNoDuelo == null
    ? null
    : (1 - t2.lulaNoDuelo) - (1 - t1.lulaNoDuelo);
  return {
    lula: t2.lula - t1.lula,
    adv: t2.adv - t1.adv,
    branco: t2.branco - t1.branco,
    nulo: t2.nulo - t1.nulo,
    abstencao: t1.abstencao == null || t2.abstencao == null ? null : t2.abstencao - t1.abstencao,
    aptos: t1.aptos == null || t2.aptos == null ? null : t2.aptos - t1.aptos,
    outros: t1.outros,
    pontos
  };
}
function comparavel(t1, t2) {
  return t1.duelo >= 80 && t2.duelo >= 80 && t1.lulaNoDuelo != null && t2.lulaNoDuelo != null;
}
function sobraDe(t1) {
  return t1.outros + t1.branco + t1.nulo + (t1.abstencao == null ? 0 : Math.max(0, t1.abstencao));
}
function identidade(saldo) {
  if (saldo.abstencao == null || saldo.aptos == null) return null;
  return saldo.lula + saldo.adv + saldo.branco + saldo.nulo + saldo.abstencao - saldo.aptos;
}
function corSwing(pontos) {
  const papel = [243, 244, 245];
  const destino = pontos == null ? papel : pontos >= 0 ? [21, 101, 192] : [196, 30, 42];
  const peso = pontos == null ? 0 : Math.min(1, Math.abs(pontos) / 0.12);
  const rgb = papel.map((canal, indice) => Math.round(canal + (destino[indice] - canal) * peso));
  return "rgb(" + rgb.join(",") + ")";
}
function raio(validos, maximo) {
  if (!maximo) return 6;
  return 5 + 16 * Math.sqrt(validos / maximo);
}
function noRecorte(local) {
  const cidade = cidadeEl.value;
  if (cidade === "sul") return !!local.sul;
  if (cidade) return local.cidade === cidade;
  return true;
}
function preencherCidades() {
  const cidades = [...new Set(D.locais.map((local) => local.cidade))].sort((a, b) => a.localeCompare(b, "pt"));
  cidadeEl.innerHTML = "";
  [["sul", "Sul do estado"], ["", "Todo o Rio Grande do Sul"]].concat(cidades.map((cidade) => [cidade, cidade])).forEach(([valor, rotulo]) => {
    const option = document.createElement("option");
    option.value = valor;
    option.textContent = rotulo;
    cidadeEl.appendChild(option);
  });
  cidadeEl.value = "sul";
}
function locaisDoRecorte() {
  const busca = buscaEl.value.trim().toLowerCase();
  return D.locais.filter((local) => {
    if (!noRecorte(local)) return false;
    if (!busca) return true;
    return (local.cidade + " " + local.nome + " " + local.bairro + " " + local.endereco).toLowerCase().includes(busca);
  });
}
function somarVotos(locais, eleicao) {
  const totais = {};
  let aptos = 0;
  let comAptos = false;
  locais.forEach((local) => {
    Object.entries(votosDe(local, eleicao)).forEach(([numeroCandidato, quantidade]) => {
      totais[numeroCandidato] = (totais[numeroCandidato] || 0) + quantidade;
    });
    const quantidade = aptosDe(local, eleicao);
    if (quantidade != null) {
      aptos += quantidade;
      comAptos = true;
    }
  });
  const base = resumo(totais);
  const comparecimento = base.validos + base.branco + base.nulo;
  const abstencao = comAptos ? Math.max(0, aptos - comparecimento) : null;
  return Object.assign(base, { aptos: comAptos ? aptos : null, comparecimento, abstencao });
}
function fraseSwing(pontos) {
  if (pontos == null) return "Este recorte ainda não tem os dois turnos.";
  const texto = Math.abs(pontos * 100).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  if (pontos > 0) return texto + " p.p. a mais na fatia de " + nomeAzul() + ".";
  if (pontos < 0) return texto + " p.p. a mais na fatia de Lula.";
  return "A fatia do duelo ficou igual.";
}
function pintarRotulos() {
  const nome = nomeAzul();
  document.querySelector("#frase-cor").textContent = "Do 1º para o 2º turno. Azul: a fatia de " + nome + " sobe. Vermelho: a fatia de Lula sobe.";
  document.querySelector("#legenda-adv").textContent = nomeCurto() + " sobe";
  document.querySelector("#nota-cor").textContent = "O boletim soma o local. O saldo é a diferença de votos entre os turnos. Azul é a fatia de " + nome + " subindo. Vermelho é a fatia de Lula subindo. O tamanho do círculo acompanha os votos válidos do 2º turno.";
}
function desenhar(ajustar) {
  camada.clearLayers();
  const lista = locaisDoRecorte().filter((local) => local.lat != null && local.lon != null);
  const maximo = Math.max(...lista.map((local) => contaDe(local, turno(2)).validos), 1);
  const limites = [];
  lista.forEach((local) => {
    const t1 = contaDe(local, turno(1));
    const t2 = contaDe(local, turno(2));
    if (!t1.comparecimento && !t2.comparecimento) return;
    const saldo = saldoDe(t1, t2);
    const circulo = L.circleMarker([local.lat, local.lon], {
      radius: raio(t2.validos || t1.validos, maximo),
      color: saldo.pontos == null ? "#8aa" : saldo.pontos >= 0 ? ADV : LULA,
      weight: selecionado === local.id ? 3 : 1,
      fillColor: corSwing(saldo.pontos),
      fillOpacity: 0.9
    });
    circulo.on("click", () => abrirLocal(local, false));
    circulo.bindTooltip(local.nome + " · " + local.bairro, { direction: "top" });
    circulo.addTo(camada);
    limites.push([local.lat, local.lon]);
  });
  if (ajustar !== false && limites.length) {
    const caixaBarra = document.querySelector(".barra-topo").getBoundingClientRect();
    const topo = caixaBarra.height ? Math.ceil(caixaBarra.bottom) + 16 : 140;
    let direita = 24;
    if (document.body.classList.contains("painel-aberto")) {
      const painel = document.querySelector("aside").getBoundingClientRect();
      if (painel.width < window.innerWidth * 0.7) direita = Math.ceil(painel.width) + 28;
    }
    mapa.fitBounds(limites, {
      paddingTopLeft: [16, topo],
      paddingBottomRight: [direita, 36],
      maxZoom: 14
    });
  }
  pintarRotulos();
  pintarResumo();
  pintarBairros();
  if (tela !== "mapa") pintarRanking();
}
function pintarResumo() {
  const locais = locaisDoRecorte();
  const t1 = somarVotos(locais, turno(1));
  const t2 = somarVotos(locais, turno(2));
  const saldo = saldoDe(t1, t2);
  const rotulo = cidadeEl.value === "sul" ? "Sul do estado" : (cidadeEl.value || "Rio Grande do Sul");
  const nome = nomeAzul();
  document.querySelector("#resumo").innerHTML =
    "<div class='cartao'><strong>" + rotulo + " · " + cicloEl.value + "</strong>" +
    "<div class='numeros'><span>1º turno</span><span class='lula'>Lula " + percentual(t1.lula, t1.duelo) + "</span><span class='adv'>" + nome + " " + percentual(t1.adv, t1.duelo) + "</span></div>" +
    "<div class='numeros'><span>2º turno</span><span class='lula'>Lula " + percentual(t2.lula, t2.duelo) + "</span><span class='adv'>" + nome + " " + percentual(t2.adv, t2.duelo) + "</span></div>" +
    "<div class='nota'>" + fraseSwing(saldo.pontos) + "</div></div>";
}
function linhaTurno(rotulo, conta) {
  return "<tr><td>" + rotulo + "</td><td class='lula'>" + numero(conta.lula) + "</td><td class='adv'>" + numero(conta.adv) +
    "</td><td>" + numero(conta.outros) + "</td><td>" + numero(conta.branco) + "</td><td>" + numero(conta.nulo) +
    "</td><td>" + (conta.abstencao == null ? "–" : numero(conta.abstencao)) + "</td><td>" +
    (conta.aptos == null ? "–" : numero(conta.aptos)) + "</td></tr>";
}
function mostrarFicha(local) {
  const t1 = contaDe(local, turno(1));
  const t2 = contaDe(local, turno(2));
  const saldo = saldoDe(t1, t2);
  const nome = nomeAzul();
  const nomes = D.nomes[turno(1)] || {};
  const aviso = local.aprox ? "<p class='aviso'>Coordenada aproximada: o TSE não informou a latitude deste local. O ponto está no distrito de Cordeiro de Farias.</p>" : "";
  const outros = Object.entries(votosDe(local, turno(1)))
    .filter(([numeroCandidato, quantidade]) => quantidade && numeroCandidato !== "13" && numeroCandidato !== "22" && numeroCandidato !== "95" && numeroCandidato !== "96")
    .sort((a, b) => b[1] - a[1]);
  const listaOutros = outros.length
    ? "<div class='rola'><table><thead><tr><th>Candidato no 1º turno</th><th>Votos</th></tr></thead><tbody>" +
      outros.map(([numeroCandidato, quantidade]) => "<tr class='estatica'><td>" + escapar(nomes[numeroCandidato] || numeroCandidato) + "</td><td>" + numero(quantidade) + "</td></tr>").join("") +
      "</tbody></table></div><p class='nota'>A soma desses votos neste local é " + numero(t1.outros) + ". O saldo da tabela acima vale para essa soma.</p>"
    : "<p class='nota'>Este local não teve voto em outros candidatos no 1º turno.</p>";
  const secoes = local.secoes.map((secao) => {
    const a = contaDe(secao, turno(1));
    const b = contaDe(secao, turno(2));
    if (!a.comparecimento && !b.comparecimento) return "";
    const saldoSecao = saldoDe(a, b);
    return "<tr class='estatica'><td>" + secao.secao + "</td><td class='lula'>" + numero(a.lula) + "</td><td class='adv'>" + numero(a.adv) +
      "</td><td class='lula'>" + numero(b.lula) + "</td><td class='adv'>" + numero(b.adv) +
      "</td><td class='lula'>" + sinal(saldoSecao.lula) + "</td><td class='adv'>" + sinal(saldoSecao.adv) + "</td></tr>";
  }).join("");
  const tetoLula = t2.aptos == null ? null : t2.aptos - t2.adv;
  const tetoAdv = t2.aptos == null ? null : t2.aptos - t2.lula;
  const folga = t2.abstencao == null ? null : t2.branco + t2.nulo + t2.abstencao;
  document.querySelector("#ficha").innerHTML =
    "<h3>" + escapar(local.nome) + "</h3>" +
    "<div class='meta'>" + escapar(local.cidade) + " · Zona " + local.zona + " · " + escapar(local.bairro) + "<br>" + escapar(local.endereco) +
    "<br>" + local.n_secoes + (local.n_secoes === 1 ? " seção" : " seções") + "</div>" + aviso +
    "<p class='nota'>" + fraseSwing(saldo.pontos) + " A queda de um candidato é o mínimo que saiu dele. O destino dessa queda fica repartido no outro nome, no branco, no nulo e na abstenção.</p>" +
    "<div class='rola'><table><thead><tr><th></th><th class='lula'>Lula</th><th class='adv'>" + escapar(nomeCurto()) + "</th><th>Outros</th><th>Branco</th><th>Nulo</th><th>Abstenção</th><th>Aptos</th></tr></thead><tbody>" +
    linhaTurno("1º turno", t1) + linhaTurno("2º turno", t2) +
    "<tr><td>Saldo</td><td class='lula'>" + sinal(saldo.lula) + "</td><td class='adv'>" + sinal(saldo.adv) + "</td><td>" + sinal(-t1.outros) +
    "</td><td>" + sinal(saldo.branco) + "</td><td>" + sinal(saldo.nulo) + "</td><td>" + sinal(saldo.abstencao) + "</td><td>" + sinal(saldo.aptos) + "</td></tr>" +
    "</tbody></table></div>" +
    "<h2>Sobra do 1º turno</h2><p class='nota'>A sobra reúne outros candidatos, branco, nulo e abstenção: " + numero(sobraDe(t1)) +
    " votos. Os outros candidatos, sozinhos, somam " + numero(t1.outros) + " e a conta dos saldos chega a " +
    (identidade(saldo) == null ? "–" : numero(identidade(saldo))) + ".</p>" +
    "<h2>Teto no 2º turno</h2><p class='nota'>" + (t2.abstencao != null && t2.abstencao < 0
      ? "Neste local o comparecimento de presidente passou dos aptos da seção. A abstenção fica negativa e o teto fica de fora da conta."
      : "Lula teve " + numero(t2.lula) + " e o teto, se o branco, o nulo e a abstenção fossem dele, era " +
        (tetoLula == null ? "–" : numero(tetoLula)) + ". " + nome + " teve " + numero(t2.adv) + " e o teto era " +
        (tetoAdv == null ? "–" : numero(tetoAdv)) + ". A folga, quem não escolheu nenhum dos dois, foi " +
        (folga == null ? "–" : numero(folga)) + ". A rejeição revelada de Lula é " + percentual(t2.adv, t2.aptos) +
        " dos aptos. A de " + nome + " é " + percentual(t2.lula, t2.aptos) + ".") + "</p>" +
    "<h2>Outros candidatos no 1º turno</h2>" + listaOutros +
    "<h2>Seções neste local</h2><div class='rola'><table><thead><tr><th>Seção</th><th class='lula'>Lula 1º</th><th class='adv'>" + escapar(nomeCurto()) +
    " 1º</th><th class='lula'>Lula 2º</th><th class='adv'>" + escapar(nomeCurto()) + " 2º</th><th class='lula'>Saldo Lula</th><th class='adv'>Saldo " + escapar(nomeCurto()) + "</th></tr></thead><tbody>" + secoes + "</tbody></table></div>";
}
function pintarBairros() {
  const porMunicipio = cidadeEl.value === "sul" || !cidadeEl.value;
  document.querySelector("#titulo-bairros").textContent = porMunicipio ? "Por município" : "Por bairro";
  const grupos = new Map();
  locaisDoRecorte().forEach((local) => {
    const chave = porMunicipio ? local.cidade : local.bairro;
    if (!grupos.has(chave)) grupos.set(chave, []);
    grupos.get(chave).push(local);
  });
  const linhas = [...grupos.entries()].map(([nome, locais]) => {
    const t1 = somarVotos(locais, turno(1));
    const t2 = somarVotos(locais, turno(2));
    return { nome, t2, pontos: saldoDe(t1, t2).pontos };
  }).filter((item) => item.t2.duelo > 0)
    .sort((a, b) => Math.abs(b.pontos || 0) - Math.abs(a.pontos || 0));
  document.querySelector("#bairros").innerHTML = "<div class='rola'><table><thead><tr><th>" + (porMunicipio ? "Município" : "Bairro") +
    "</th><th class='lula'>Lula no 2º</th><th class='adv'>" + escapar(nomeAzul()) + "</th><th>Saldo do duelo</th></tr></thead><tbody>" +
    linhas.map((item) => "<tr class='estatica'><td>" + escapar(item.nome) + "</td><td class='lula'>" + percentual(item.t2.lula, item.t2.duelo) +
      "</td><td class='adv'>" + percentual(item.t2.adv, item.t2.duelo) + "</td><td>" + pontosTexto(item.pontos) + "</td></tr>").join("") +
    "</tbody></table></div>";
}
function celulaLocal(item) {
  return "<td>" + escapar(item.local.nome) + "</td><td>" + escapar(item.local.cidade) + "</td><td>" + escapar(item.local.bairro) + "</td>";
}
function valorVazio(valor) {
  return valor == null || valor === "" || (typeof valor === "number" && Number.isNaN(valor));
}
function ordenarPar(a, b, direcao) {
  if (valorVazio(a) && valorVazio(b)) return 0;
  if (valorVazio(a)) return 1;
  if (valorVazio(b)) return -1;
  if (typeof a === "number" && typeof b === "number") return direcao * (a - b);
  return direcao * String(a).localeCompare(String(b), "pt", { sensitivity: "base", numeric: true });
}
function direcaoInicial(itens, coluna, chave) {
  for (let i = 0; i < itens.length; i += 1) {
    const valor = chave(itens[i])[coluna];
    if (valorVazio(valor)) continue;
    return typeof valor === "number" ? -1 : 1;
  }
  return 1;
}
function cabecalhoOrdenavel(colunas) {
  return colunas.map((coluna, indice) => {
    let marca = "";
    let aria = "none";
    if (ordemRanking && ordemRanking.coluna === indice) {
      const desc = ordemRanking.direcao < 0;
      marca = desc ? " ordem-desc" : " ordem-asc";
      aria = desc ? "descending" : "ascending";
    }
    return "<th class='ordena" + marca + "' data-col='" + indice + "' aria-sort='" + aria + "' title='Ordenar por esta coluna'>" + escapar(coluna) + "</th>";
  }).join("");
}
const listas = {
  diferenca: {
    titulo: "Maior diferença",
    texto() {
      return "Locais em que a fatia do duelo mais mudou do 1º para o 2º turno. Entram locais com pelo menos 80 votos no duelo de cada turno. O sinal positivo é a fatia de " + nomeAzul() + " subindo. O sinal negativo é a fatia de Lula subindo.";
    },
    itens(locais) {
      return locais.map((local) => {
        const t1 = contaDe(local, turno(1));
        const t2 = contaDe(local, turno(2));
        if (!comparavel(t1, t2)) return null;
        return { local, t1, t2, saldo: saldoDe(t1, t2) };
      }).filter(Boolean).sort((a, b) => Math.abs(b.saldo.pontos) - Math.abs(a.saldo.pontos));
    },
    colunas() {
      const curto = nomeCurto();
      return ["Local", "Município", "Bairro", "Lula 1º", "Lula 2º", curto + " 1º", curto + " 2º", "Saldo do duelo", "Branco 2º", "Nulo 2º", "Abstenção 2º"];
    },
    chave(item) {
      return [item.local.nome, item.local.cidade, item.local.bairro, item.t1.lula, item.t2.lula, item.t1.adv, item.t2.adv, item.saldo.pontos, item.t2.branco, item.t2.nulo, item.t2.abstencao];
    },
    linha(item) {
      return celulaLocal(item) + "<td class='lula'>" + numero(item.t1.lula) + "</td><td class='lula'>" + numero(item.t2.lula) +
        "</td><td class='adv'>" + numero(item.t1.adv) + "</td><td class='adv'>" + numero(item.t2.adv) + "</td><td>" + pontosTexto(item.saldo.pontos) +
        "</td><td>" + numero(item.t2.branco) + "</td><td>" + numero(item.t2.nulo) + "</td><td>" + numero(item.t2.abstencao) + "</td>";
    }
  },
  sobra: {
    titulo: "Sobra",
    texto: "A sobra do 1º turno é outros candidatos, branco, nulo e abstenção. Ao lado está o saldo de cada candidato do 2º turno. O saldo positivo é voto que chegou de fora do que esse candidato já tinha. A queda é o mínimo que saiu dele, sem um destino único.",
    itens(locais) {
      return locais.map((local) => {
        const t1 = contaDe(local, turno(1));
        const t2 = contaDe(local, turno(2));
        if (!comparavel(t1, t2)) return null;
        const saldo = saldoDe(t1, t2);
        return { local, t1, t2, saldo, sobra: sobraDe(t1), chegada: Math.max(saldo.lula, saldo.adv, 0) };
      }).filter(Boolean).sort((a, b) => b.chegada - a.chegada || b.sobra - a.sobra);
    },
    colunas() {
      return ["Local", "Município", "Bairro", "Sobra", "Saldo de Lula", "Saldo de " + nomeCurto(), "Branco 2º", "Nulo 2º", "Abstenção 2º"];
    },
    chave(item) {
      return [item.local.nome, item.local.cidade, item.local.bairro, item.sobra, item.saldo.lula, item.saldo.adv, item.t2.branco, item.t2.nulo, item.t2.abstencao];
    },
    linha(item) {
      return celulaLocal(item) + "<td>" + numero(item.sobra) + "</td><td class='lula'>" + sinal(item.saldo.lula) +
        "</td><td class='adv'>" + sinal(item.saldo.adv) + "</td><td>" + numero(item.t2.branco) + "</td><td>" + numero(item.t2.nulo) +
        "</td><td>" + numero(item.t2.abstencao) + "</td>";
    }
  },
  teto: {
    titulo: "Teto e rejeição",
    texto() {
      return "No 2º turno, o piso é o voto que o candidato teve. O teto é o que ele teria se o branco, o nulo e a abstenção fossem dele. A folga é quem não escolheu nenhum dos dois. A rejeição revelada é o voto no outro candidato do duelo dividido pelos aptos. A lista começa pela rejeição mais alta. Local em que o comparecimento passou dos aptos fica de fora.";
    },
    itens(locais) {
      return locais.map((local) => {
        const t2 = contaDe(local, turno(2));
        const t1 = contaDe(local, turno(1));
        if (!comparavel(t1, t2) || !t2.aptos || t2.abstencao < 0) return null;
        const rejeicaoLula = t2.adv / t2.aptos;
        const rejeicaoAdv = t2.lula / t2.aptos;
        return {
          local, t1, t2,
          rejeicaoLula, rejeicaoAdv,
          rejeitado: rejeicaoLula >= rejeicaoAdv ? "Lula" : nomeAzul(),
          maior: Math.max(rejeicaoLula, rejeicaoAdv)
        };
      }).filter(Boolean).sort((a, b) => b.maior - a.maior);
    },
    colunas() {
      const nome = nomeAzul();
      return ["Local", "Município", "Bairro", "Rejeição maior", "Rejeição de Lula", "Rejeição de " + nome, "Piso de Lula", "Teto de Lula", "Piso de " + nome, "Teto de " + nome, "Folga"];
    },
    chave(item) {
      return [
        item.local.nome, item.local.cidade, item.local.bairro, item.maior, item.rejeicaoLula, item.rejeicaoAdv,
        item.t2.lula, item.t2.aptos - item.t2.adv, item.t2.adv, item.t2.aptos - item.t2.lula,
        item.t2.branco + item.t2.nulo + item.t2.abstencao
      ];
    },
    linha(item) {
      const folga = item.t2.branco + item.t2.nulo + item.t2.abstencao;
      return celulaLocal(item) + "<td>" + escapar(item.rejeitado) + " " + percentual(item.maior, 1) + "</td><td class='lula'>" +
        percentual(item.rejeicaoLula, 1) + "</td><td class='adv'>" + percentual(item.rejeicaoAdv, 1) + "</td><td class='lula'>" +
        numero(item.t2.lula) + "</td><td class='lula'>" + numero(item.t2.aptos - item.t2.adv) + "</td><td class='adv'>" +
        numero(item.t2.adv) + "</td><td class='adv'>" + numero(item.t2.aptos - item.t2.lula) + "</td><td>" + numero(folga) + "</td>";
    }
  }
};
function outrosDoRecorte(locais) {
  const nomes = D.nomes[turno(1)] || {};
  const acc = new Map();
  const totais = { votos: 0, lula: 0, adv: 0, branco: 0, nulo: 0, abstencao: 0, aptos: 0 };
  locais.forEach((local) => {
    const t1 = contaDe(local, turno(1));
    const saldo = saldoDe(t1, contaDe(local, turno(2)));
    Object.entries(votosDe(local, turno(1))).forEach(([numeroCandidato, quantidade]) => {
      if (!quantidade || !t1.aptos || numeroCandidato === "13" || numeroCandidato === "22" || numeroCandidato === "95" || numeroCandidato === "96") return;
      if (!acc.has(numeroCandidato)) {
        acc.set(numeroCandidato, { numero: numeroCandidato, nome: nomes[numeroCandidato] || numeroCandidato, votos: 0, lula: 0, adv: 0, branco: 0, nulo: 0, abstencao: 0 });
      }
      const item = acc.get(numeroCandidato);
      const peso = quantidade / t1.aptos;
      item.votos += quantidade;
      item.lula += peso * saldo.lula;
      item.adv += peso * saldo.adv;
      item.branco += peso * saldo.branco;
      item.nulo += peso * saldo.nulo;
      item.abstencao += peso * (saldo.abstencao || 0);
    });
    totais.votos += t1.outros;
    totais.lula += saldo.lula;
    totais.adv += saldo.adv;
    totais.branco += saldo.branco;
    totais.nulo += saldo.nulo;
    totais.abstencao += saldo.abstencao || 0;
    totais.aptos += saldo.aptos || 0;
  });
  const lista = [...acc.values()].filter((item) => item.votos >= 5000).sort((a, b) => b.votos - a.votos);
  return { lista, totais };
}
function porCem(acumulado, votos) {
  if (!votos) return null;
  return 100 * acumulado / votos;
}
function pintarOutros(locais) {
  const { lista, totais } = outrosDoRecorte(locais);
  const fecha = totais.lula + totais.adv + totais.branco + totais.nulo + totais.abstencao - totais.aptos;
  document.querySelector("#dados-titulo").textContent = "Outros candidatos";
  document.querySelector("#explicacao").textContent = "Cada número do candidato é o saldo do 2º turno a cada 100 aptos do local em que o voto dele estava. O local pesa pelo tamanho desse voto. A soma, em votos, fica no texto acima e fecha pela diferença dos turnos. Candidato com menos de 5.000 votos no recorte fica de fora.";
  document.querySelector("#dados-contagem").textContent = lista.length
    ? "A soma dos outros neste recorte é " + numero(totais.votos) + " votos. O saldo foi Lula " + sinal(totais.lula) + ", " + nomeAzul() + " " + sinal(totais.adv) + ", branco " + sinal(totais.branco) + ", nulo " + sinal(totais.nulo) + " e abstenção " + sinal(totais.abstencao) + ". A conta chega a " + numero(fecha) + "."
    : "Nenhum outro candidato chegou a 5.000 votos neste recorte.";
  const nome = nomeCurto();
  const cabeca = ["Candidato", "Votos no 1º", "Lula", nome, "Branco", "Nulo", "Abstenção"].map((coluna) => "<th>" + coluna + "</th>").join("");
  const corpo = lista.map((item) => "<tr class='estatica'><td>" + escapar(item.nome) + "</td><td>" + numero(item.votos) +
    "</td><td class='lula'>" + casaDecimal(porCem(item.lula, item.votos)) + "</td><td class='adv'>" + casaDecimal(porCem(item.adv, item.votos)) +
    "</td><td>" + casaDecimal(porCem(item.branco, item.votos)) + "</td><td>" + casaDecimal(porCem(item.nulo, item.votos)) +
    "</td><td>" + casaDecimal(porCem(item.abstencao, item.votos)) + "</td></tr>").join("");
  document.querySelector("#ranking").innerHTML = "<table><thead><tr>" + cabeca + "</tr></thead><tbody>" + corpo + "</tbody></table>";
  linhasRanking = [];
}
function pintarRanking() {
  if (tela === "outros") {
    pintarOutros(locaisDoRecorte());
    return;
  }
  const lista = listas[tela];
  document.querySelector("#dados-titulo").textContent = lista.titulo;
  document.querySelector("#explicacao").textContent = typeof lista.texto === "function" ? lista.texto() : lista.texto;
  linhasRanking = lista.itens(locaisDoRecorte());
  if (ordemRanking) {
    const coluna = ordemRanking.coluna;
    const direcao = ordemRanking.direcao;
    linhasRanking.sort((a, b) => ordenarPar(lista.chave(a)[coluna], lista.chave(b)[coluna], direcao));
  }
  const quantidade = linhasRanking.length;
  document.querySelector("#dados-contagem").textContent = quantidade
    ? (quantidade === 1 ? "1 local neste recorte." : numero(quantidade) + " locais neste recorte.") + " Clique numa linha para abrir o local no mapa. Clique no título da coluna para ordenar."
    : "Nenhum local neste recorte.";
  document.querySelector("#ranking").innerHTML = "<table><thead><tr>" +
    cabecalhoOrdenavel(lista.colunas()) +
    "</tr></thead><tbody>" +
    linhasRanking.map((item, indice) => "<tr data-i='" + indice + "'>" + lista.linha(item) + "</tr>").join("") +
    "</tbody></table>";
}
function pintarValidacao() {
  const bloco = D.validacao && D.validacao.turno_2026_2;
  if (!bloco) return;
  document.querySelector("#validacao").textContent = "2º turno de 2026 no Rio Grande do Sul: Lula " + numero(bloco.lula) +
    " e Flávio Bolsonaro " + numero(bloco.flavio) + ". A soma dos boletins bate com o TSE. Aptos nesse turno: " + numero(bloco.aptos["2026-2"]) + ".";
}
function abrirLocal(local, ajustarMapa) {
  selecionado = local.id;
  mostrarFicha(local);
  abrirPainel();
  if (local.lat != null) {
    if (ajustarMapa) mapa.setView([local.lat, local.lon], 16);
    manterPontoVisivel(local);
  }
  desenhar(false);
  document.querySelector("#ficha").scrollIntoView({ block: "start" });
}
document.querySelector("#ranking").addEventListener("click", (evento) => {
  const titulo = evento.target.closest("th");
  if (titulo && titulo.dataset.col != null && listas[tela]) {
    const coluna = Number(titulo.dataset.col);
    if (ordemRanking && ordemRanking.coluna === coluna) ordemRanking.direcao *= -1;
    else ordemRanking = { coluna, direcao: direcaoInicial(linhasRanking, coluna, (item) => listas[tela].chave(item)) };
    pintarRanking();
    return;
  }
  const linha = evento.target.closest("tr");
  if (!linha || linha.dataset.i == null) return;
  const item = linhasRanking[Number(linha.dataset.i)];
  if (!item) return;
  mostrarTela("mapa");
  mapa.invalidateSize();
  abrirLocal(item.local, true);
});
document.querySelectorAll("#menu button[data-tela]").forEach((botao) => {
  botao.addEventListener("click", () => mostrarTela(botao.dataset.tela));
});
function mostrarTela(id) {
  if (id !== tela) ordemRanking = null;
  tela = id;
  document.body.classList.toggle("tela-dados", id !== "mapa");
  document.querySelectorAll("#menu button[data-tela]").forEach((botao) => {
    botao.classList.toggle("ativa", botao.dataset.tela === id);
  });
  if (id === "mapa") {
    mapa.invalidateSize();
    desenhar(false);
    return;
  }
  pintarRanking();
  document.querySelector("#dados").scrollTop = 0;
}
function encaixarMapa() {
  const altura = document.querySelector("#menu").offsetHeight;
  document.documentElement.style.setProperty("--menu-altura", altura + "px");
  mapa.invalidateSize();
}
function definirPainel(aberto) {
  document.body.classList.toggle("painel-aberto", aberto);
  const botao = document.querySelector("#abrir-painel");
  botao.setAttribute("aria-expanded", aberto ? "true" : "false");
  botao.textContent = aberto ? "Ocultar detalhes" : "Detalhes";
}
function alternarPainel() {
  definirPainel(!document.body.classList.contains("painel-aberto"));
}
function abrirPainel() {
  definirPainel(true);
}
function manterPontoVisivel(local) {
  const painel = document.querySelector("aside").getBoundingClientRect();
  if (painel.width >= window.innerWidth * 0.7) return;
  const ponto = mapa.latLngToContainerPoint([local.lat, local.lon]);
  const limite = painel.left - mapa.getContainer().getBoundingClientRect().left - 28;
  if (ponto.x > limite) mapa.panBy([ponto.x - limite, 0]);
}
document.querySelector("#abrir-painel").addEventListener("click", alternarPainel);
document.querySelector("#fechar-painel").addEventListener("click", alternarPainel);
cicloEl.addEventListener("change", () => {
  desenhar();
  const local = D.locais.find((item) => item.id === selecionado);
  if (local) mostrarFicha(local);
});
cidadeEl.addEventListener("change", desenhar);
buscaEl.addEventListener("input", desenhar);
window.addEventListener("resize", encaixarMapa);
preencherCidades();
pintarValidacao();
encaixarMapa();
desenhar();
