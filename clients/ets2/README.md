# Euro Truck Simulator 2 - controles do Logitech G923

Dois `controls.sii` de perfil do ETS2 para o G923 **versao PlayStation/PC** (id de hardware
`046D:C266`; a versao Xbox numera os botoes de outro jeito e nao serve). As teclas do teclado
continuam valendo nos dois: os botoes do volante foram SOMADOS a elas.

| Arquivo | Para quem |
|---|---|
| `g923-controls.sii` | volante + cambio H (Driving Force Shifter) |
| `g923-no-shifter-controls.sii` | so o volante: seta nas borboletas, marcha no R2/L2 |

## Os botoes

| Botao | Com cambio H | Sem cambio |
|---|---|---|
| Borboleta esquerda / direita | Seta esquerda / direita | Seta esquerda / direita |
| Cambio H | Marchas (`joy.b13`-`b19`) | - |
| R2 / L2 | Retarder + / - | Marcha + / - |
| D-pad esquerda / direita | Olhar para os lados | Olhar para os lados |
| D-pad cima / baixo | Freio motor / trava do diferencial | Retarder + / - |
| X | Engatar/soltar reboque | igual |
| Quadrado | Farois (alterna os modos) | igual |
| Circulo | Farol alto | igual |
| Triangulo | Freio de estacionamento | igual |
| Share | Camera interna | igual |
| Options | Limpador | igual |
| R3 | Buzina | igual |
| L3 | Radio do comboio (falar no multiplayer) | igual |
| + / - | Piloto automatico: aumentar / diminuir | igual |
| Enter do disco vermelho | Piloto automatico liga/desliga | igual |
| Disco horario / anti-horario | Troca de camera / piscar farol | igual |
| PS | Motor liga/desliga | **Pisca-alerta** (motor so na tecla E) |

Por que a versao sem cambio e assim:

- **Marcha em R2/L2, e nao nas borboletas**: as borboletas continuam sendo seta, que se usa
  em toda curva. No automatico o R2/L2 so troca D/N/R, entao gasta-se pouco.
- **O retarder desceu para o D-pad** e o freio motor e a trava do diferencial ficaram no
  teclado (B e V). Ligue "freio motor automatico" em Opcoes > Gameplay e o B quase nao faz
  falta.
- **Pisca-alerta no PS**: e o botao do centro, que se acha sem olhar - o mesmo lugar do botao
  de alerta num painel de verdade. O motor saiu dali porque se liga uma vez por viagem, com o
  caminhao parado; o alerta e usado andando, quando o transito trava na estrada.

Na versao sem cambio, escolha **Transmissao: automatica** (o R2/L2 so passa entre D, N e
R) ou **sequencial** (o R2/L2 troca cada marcha) em Opcoes > Gameplay. Com "manual H" o
jogo espera um cambio que nao existe.

## Aplicar num perfil

Com o jogo FECHADO (ele regrava o arquivo ao sair):

1. Copie o arquivo por cima de
   `Documentos\Euro Truck Simulator 2\steam_profiles\<perfil>\controls.sii`
   (guarde o original antes).
2. Troque a terceira linha (`input_config : _nameless.XXX {`) pela do arquivo original:
   e o identificador interno daquele perfil, e nao pode ser o mesmo em dois perfis.
3. A linha `device joy` tem o GUID de instancia do volante do computador onde o arquivo
   foi gerado. Em outra maquina o jogo pode nao reconhecer o volante: escolha-o de novo em
   Opcoes > Controles e os botoes continuam onde estao.

O perfil fica no Steam Cloud: se ao abrir o jogo a Steam avisar de conflito, escolha a
versao LOCAL, senao ela devolve o arquivo antigo.
