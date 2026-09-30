"""Qual gestor de mods vale para qual servidor.

A escolha e pelo NOME DO SERVICO (`ets2.service`): e a identidade que todo servidor do
painel tem, venha do broker, do deploy-game.ps1 ou do cadastro a mao - o painel nao guarda
"qual jogo e este" em outro lugar. Servidor sem perfil nao fica sem saida: a tela diz que o
jogo ainda nao tem gestor e manda para a tela Arquivos.

Perfil novo = uma entrada em `PROFILES`. Um teste cobra que dois perfis nao disputem o
mesmo servico (o primeiro venceria e o segundo viraria codigo morto calado).
"""
from __future__ import annotations

from dataclasses import dataclass

# O servidor LE os pacotes exportados do jogo; mod nenhum e copiado para ele.
KIND_PACKAGES = "packages"
# O servidor precisa do arquivo do mod numa pasta dele.
KIND_FOLDER = "folder"
# Mods do Thunderstore com o BepInEx: o CT baixa e instala (games/mods/thunderstore_remote.py).
KIND_THUNDERSTORE = "thunderstore"


@dataclass(frozen=True)
class ModProfile:
    key: str
    kind: str
    # Nomes de servico (sem o `.service`) que usam este perfil: o do catalogo curado e o que
    # a busca do painel sugere (LinuxGSM/Pterodactyl), que vira outro nome de servico.
    services: tuple[str, ...]
    # Pasta do container para onde o envio vai.
    folder: str
    # Chave de i18n do paragrafo que explica como os mods funcionam NESTE jogo.
    help_key: str
    # Envio aceito: nomes exatos (os pacotes do ETS2) ou extensoes (.pak). Um dos dois.
    upload_names: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    # App ID do JOGO na Steam, para o link da Workshop que vai para os jogadores.
    workshop_appid: int = 0
    # Thunderstore: a comunidade (parte da URL), o carregador (namespace, nome) e a memoria
    # que a PRIMEIRA subida com ele pede - medida, e nao chutada (ver VRISING).
    community: str = ""
    loader: tuple[str, str] = ("", "")
    min_memory_mb: int = 0

    def accepts(self, name: str) -> bool:
        """O nome de arquivo que pode entrar pela tela Mods deste jogo."""
        if self.upload_names:
            return name in self.upload_names
        # Sem extensao declarada (Thunderstore) nada entra por envio: `endswith(())` e False.
        return name.lower().endswith(self.extensions)


ETS2 = ModProfile(
    key="ets2",
    kind=KIND_PACKAGES,
    services=("ets2", "euro-truck-simulator-2"),
    # O wrapper do games/ets2.env liga a pasta padrao do servidor a esta (ele ignora o
    # -homedir): e aqui que os pacotes precisam estar.
    folder="/opt/game/server-home",
    help_key="mods.help_ets2",
    upload_names=("server_packages.sii", "server_packages.dat"),
    workshop_appid=227300,
)

PALWORLD = ModProfile(
    key="palworld",
    kind=KIND_FOLDER,
    services=("palworld",),
    # A Unreal carrega de ~mods os .pak que nao vieram com o jogo; o servidor e o cliente
    # tem cada um a sua copia, e mod de servidor so vale se estiver aqui.
    folder="/opt/game/Pal/Content/Paks/~mods",
    help_key="mods.help_palworld",
    extensions=(".pak",),
)

VRISING = ModProfile(
    key="vrising",
    kind=KIND_THUNDERSTORE,
    services=("vrising", "v-rising"),
    # A pasta do JOGO: o BepInExPack vai na raiz dele, e os plugins em BepInEx/plugins.
    folder="/opt/game",
    help_key="mods.help_vrising",
    community="v-rising",
    loader=("BepInEx", "BepInExPack_V_Rising"),
    # Medido num CT de teste: a primeira subida com o BepInEx gera o codigo do jogo inteiro
    # e chegou a 9,4 GB; com 6 GB o OOM killer derrubava o servidor em laco. O curado tem 8.
    min_memory_mb=10240,
)

PROFILES = (ETS2, PALWORLD, VRISING)


def service_stem(service: str) -> str:
    return (service or "").strip().removesuffix(".service")


def profile_for(service: str) -> ModProfile | None:
    stem = service_stem(service)
    return next((p for p in PROFILES if stem in p.services), None)
