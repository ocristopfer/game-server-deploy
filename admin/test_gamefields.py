#!/usr/bin/env python3
"""Testes do catalogo de campos por jogo.

Rodar:  python3 /opt/gamepanel/test_gamefields.py

O que estes testes protegem e a promessa do recurso: o valor que a pessoa digita na
tela (minutos, multiplicador) e o valor que vai para o arquivo (nanossegundos) sao
unidades diferentes, e a conversao tem que ser reversivel. Um erro aqui grava
silenciosamente uma noite de 1 segundo - foi exatamente o que motivou o recurso.
"""
import gamefields

falhas = []


def checa(rotulo, obtido, esperado):
    if obtido == esperado:
        print("  ok   %s" % rotulo)
    else:
        falhas.append(rotulo)
        print("  FALHA %s: obtido %r, esperado %r" % (rotulo, obtido, esperado))


print("Duracao: arquivo em nanossegundos, tela em minutos")
dia = gamefields.describe("enshrouded_server.json", "dayTimeDuration")
checa("30 min viram 1800000000000 ns", dia.from_display("30"), "1800000000000")
checa("1800000000000 ns viram 30 min", dia.to_display("1800000000000"), "30")
checa("ida e volta preserva", dia.to_display(dia.from_display("2")), "2")
checa("minimo de 2 min recusa 1", bool(dia.validate("1")), True)
checa("2 min passa", dia.validate("2"), "")
checa("60 min passa", dia.validate("60"), "")
checa("61 min recusa", bool(dia.validate("61")), True)

print()
print("O caso real que motivou tudo: noite de 1 segundo no arquivo")
noite = gamefields.describe("enshrouded_server.json", "nightTimeDuration")
# 1000000000 ns = 1 segundo = 0,0167 min -> abaixo do minimo de 2 min
checa("1e9 ns aparecem como fracao de minuto", noite.to_display("1000000000"), "0.0166667")
checa("e sao recusados ao salvar", bool(noite.validate("0.0166667")), True)

print()
print("Enum: so aceita valor que o jogo entende")
tumba = gamefields.describe("enshrouded_server.json", "tombstoneMode")
checa("AddBackpackMaterials passa", tumba.validate("AddBackpackMaterials"), "")
checa("NoTombstone passa", tumba.validate("NoTombstone"), "")
checa("valor inventado recusa", bool(tumba.validate("PerdeTudo")), True)
checa("tem os tres modos", len(tumba.options), 3)

print()
print("Fator: multiplicador com limite")
vida = gamefields.describe("enshrouded_server.json", "playerHealthFactor")
checa("1 passa", vida.validate("1"), "")
checa("4 passa", vida.validate("4"), "")
checa("5 recusa", bool(vida.validate("5")), True)
checa("0 recusa", bool(vida.validate("0")), True)
checa("texto recusa", bool(vida.validate("muito")), True)
# Fator nao converte unidade: o que se digita e o que vai para o arquivo.
checa("fator nao converte", vida.from_display("1.5"), "1.5")

print()
print("Reciclagem de perk vai de 0 a 1 (fracao devolvida)")
rec = gamefields.describe("enshrouded_server.json", "perkUpgradeRecyclingFactor")
checa("0.5 passa", rec.validate("0.5"), "")
checa("1 passa", rec.validate("1"), "")
checa("2 recusa", bool(rec.validate("2")), True)

print()
print("Outros jogos e campos nao mapeados")
checa("Palworld conhece ServerPlayerMaxNum",
      gamefields.describe("PalWorldSettings.ini", "ServerPlayerMaxNum").kind, "number")
checa("Icarus conhece ShutdownIfEmptyFor",
      gamefields.describe("ServerSettings.ini", "ShutdownIfEmptyFor").unit, "s")
checa("DayZ conhece steamQueryPort",
      gamefields.describe("serverDZ.cfg", "steamQueryPort").kind, "number")
checa("chave desconhecida devolve None",
      gamefields.describe("enshrouded_server.json", "campoQueNaoExiste"), None)
checa("arquivo desconhecido devolve None",
      gamefields.describe("qualquer.ini", "name"), None)
checa("caminho completo funciona",
      gamefields.describe("/opt/game/enshrouded_server.json", "slotCount").kind, "number")

print()
print("Campo sem catalogo nao pode ser alterado por engano")
vazio = gamefields.FieldSpec()
checa("texto livre nao valida", vazio.validate("qualquer coisa"), "")
checa("texto livre nao converte", vazio.from_display("123"), "123")

print()
if falhas:
    print("FALHARAM %d teste(s): %s" % (len(falhas), ", ".join(falhas)))
    raise SystemExit(1)
print("todos os testes passaram")
