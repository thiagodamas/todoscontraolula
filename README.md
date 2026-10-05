# Todos contra o Lula

Mapa dos votos para presidente no Rio Grande do Sul, por local de votação. O recorte inicial é o sul do estado, nos municípios ao sul do paralelo 30,5°S.

Site: https://todoscontraolula.pages.dev

Vermelho é Lula. Azul é Flávio Bolsonaro no 1º turno de 2026 e Jair Bolsonaro nos dois turnos de 2022. O tamanho do círculo acompanha os votos válidos da eleição escolhida.

## Fonte

- 2022: TSE, votação por seção eleitoral, 1º e 2º turnos.
- 2026: soma dos boletins de urna do 1º turno, pleito 3220, eleição federal 6257, conferida com o total municipal do TSE.

O site é a pasta `mapa/`: `index.html` e `dados.js`. O Cloudflare Pages publica essa pasta, sem build.

## Atualizar

O 2º turno de 2026 é em 25 de outubro. Com o cache local em `data/cache/` e os zips do TSE em `/tmp/tsework/zips`:

```
/tmp/tsework/venv/bin/python -u scripts/build_mapa.py
```

O script regrava `mapa/dados.js`. Commit desse arquivo e push em `main`. O Pages republica sozinho.
