"""Uma funcao por consulta, em vez de SQL cru espalhado por quem chama.

Antes disto o mesmo `SELECT * FROM servers WHERE id = ?` aparecia em oito lugares, e um
`UPDATE servers SET ...` com a lista de colunas escrita a mao em mais quatro. Nada disso
quebra ao renomear uma coluna: quebra na PRIMEIRA VISITA a tela que usa a copia que
ficou para tras, em runtime, sem lint nem teste acusando — foi assim que as migrations
de rename precisaram ser escritas com tanto cuidado.

**Toda funcao daqui recebe a conexao como PRIMEIRO parametro.** Nunca chama `db()`: a
conexao e por requisicao e mora no `g` do Flask, e um repositorio que a buscasse sozinho
nao serviria ao monitor nem ao agendador, que rodam em thread propria sem `g`. Passar a
conexao tambem e o que permite testar uma consulta sem subir aplicacao nenhuma.

**Nada aqui decide.** Sem `flash`, sem `abort`, sem traducao, sem regra de quem pode ver
o que: isso e de quem chama. O repositorio so sabe ler e escrever linha.
"""
