# Euro Truck Simulator 2 - controles do Logitech G923

`g923-controls.sii` e o `controls.sii` de um perfil do ETS2 com o G923 (versao
PlayStation/PC, id de hardware `046D:C266`) mapeado inteiro: pedais, cambio H, setas nas
borboletas e os botoes do volante para as funcoes do caminhao. As teclas do teclado
continuam valendo; os botoes do volante foram SOMADOS a elas.

| Botao | Funcao |
|---|---|
| Borboleta esquerda / direita | Seta esquerda / direita |
| Cambio H | Marchas (`joy.b13`-`b19`) |
| D-pad esquerda / direita | Olhar para os lados |
| D-pad cima | Freio motor |
| D-pad baixo | Trava do diferencial |
| X | Engatar/soltar reboque |
| Quadrado | Farois (alterna os modos) |
| Circulo | Farol alto |
| Triangulo | Freio de estacionamento |
| R2 / L2 | Retarder + / - |
| Share | Camera interna |
| Options | Limpador |
| R3 | Buzina |
| L3 | Pisca-alerta |
| + / - | Piloto automatico: aumentar / diminuir |
| Enter do disco vermelho | Piloto automatico liga/desliga |
| Disco horario / anti-horario | Troca de camera / piscar farol |
| PS | Motor liga/desliga |

## Aplicar num perfil

Com o jogo FECHADO (ele regrava o arquivo ao sair):

1. Copie este arquivo por cima de
   `Documentos\Euro Truck Simulator 2\steam_profiles\<perfil>\controls.sii`
   (guarde o original antes).
2. Troque a terceira linha (`input_config : _nameless.XXX {`) pela do arquivo original:
   e o identificador interno daquele perfil, e nao pode ser o mesmo em dois perfis.
3. A linha `device joy` tem o GUID de instancia do volante NESTE computador. Em outra
   maquina o jogo pode nao reconhecer o volante: escolha-o de novo em Opcoes > Controles
   e os botoes continuam onde estao.

O perfil fica no Steam Cloud: se ao abrir o jogo a Steam avisar de conflito, escolha a
versao LOCAL, senao ela devolve o arquivo antigo.
