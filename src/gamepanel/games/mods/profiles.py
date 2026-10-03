"""Qual gestor de mods vale para qual servidor.

A escolha e pelo NOME DO SERVICO (`ets2.service`): e a identidade que todo servidor do
painel tem, venha do broker, do deploy-game.ps1 ou do cadastro a mao - o painel nao guarda
"qual jogo e este" em outro lugar. Servidor sem perfil nao fica sem saida: a tela diz que o
jogo ainda nao tem gestor e manda para a tela Arquivos.

Perfil novo = uma entrada em `PROFILES`. Um teste cobra que dois perfis nao disputem o
mesmo servico (o primeiro venceria e o segundo viraria codigo morto calado).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# O servidor LE os pacotes exportados do jogo; mod nenhum e copiado para ele.
KIND_PACKAGES = "packages"
# O servidor precisa do arquivo do mod numa pasta dele.
KIND_FOLDER = "folder"
# Mods do Thunderstore com o BepInEx: o CT baixa e instala (games/mods/thunderstore_remote.py).
KIND_THUNDERSTORE = "thunderstore"
# Carregador nativo do Enshrouded (Shroudtopia): o CT baixa o carregador, o Wine passa a usar
# o winmm.dll dele, e os mods sao DLLs que entram pela tela (games/mods/shroudtopia_remote.py).
KIND_SHROUDTOPIA = "shroudtopia"
# UE4SS (jogo Unreal cujo servidor e o .exe de Windows sob o Proton): o CT baixa o carregador, o
# Wine passa a usar o dwmapi.dll dele, e os mods moram em Mods/ ao lado do executavel
# (games/mods/ue4ss_remote.py). A pasta do perfil e a Mods/; o carregador mora na de cima.
KIND_UE4SS = "ue4ss"
# Satisfactory: SML e os mods do ficsit.app, pela API dele (games/mods/sml_remote.py).
KIND_SML = "sml"
# Rust: o Oxide (uMod) sobrescreve DLLs do jogo e os plugins sao .cs (games/mods/oxide_remote.py).
KIND_OXIDE = "oxide"
# So o guia (onde achar, como instalar), sem acao: o caminho existe mas ainda nao foi provado
# num servidor de verdade, e botao que "instala" sem prova e pior que instrucao clara.
KIND_GUIDE = "guide"

# Onde se acha mod de cada jogo. O Nexus Mods fica como LINK, nunca como download automatico:
# a API dele so entrega arquivo para conta Premium, e automatizar sem ela viola os termos de
# uso. Quem baixa do Nexus e a pessoa; o painel recebe o arquivo pela tela.
NEXUS = "https://www.nexusmods.com/"


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
    # (chave de i18n do rotulo, URL) de onde os mods deste jogo sao encontrados.
    sources: tuple[tuple[str, str], ...] = ()
    # O que o "Verificar mods instalados" passa pelo antivirus, quando nao e so `folder`: o
    # carregador mora fora da pasta de mods, e na pasta do jogo inteira (V Rising) seriam gigas
    # de arquivo do proprio jogo para nada.
    audit_paths: tuple[str, ...] = ()
    # Carregador nativo: a pasta do executavel do jogo, onde o carregador entra. Vazio = um nivel
    # acima da pasta de mods (Shroudtopia); o UE4SS experimental poe os mods DOIS niveis abaixo.
    loader_dir: str = ""
    # False = o instalador existe mas ainda nao rodou num servidor de verdade: a tela avisa.
    # Quem provar num CT real troca para True, com o que foi medido escrito no perfil.
    proven: bool = True
    # Thunderstore num servidor Linux NATIVO (Valheim): o BepInEx entra por drop-in do systemd
    # (LD_PRELOAD do doorstop), e nao pelo winhttp do Wine.
    linux_bepinex: bool = False

    @property
    def scan_paths(self) -> tuple[str, ...]:
        return self.audit_paths or (self.folder,)

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
    audit_paths=("/opt/game/server-home/server_packages.sii", "/opt/game/server-home/server_packages.dat"),
    workshop_appid=227300,
    sources=(("mods.source_workshop", "https://steamcommunity.com/app/227300/workshop/"),),
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
    sources=(("mods.source_nexus", NEXUS + "palworld/mods/"),),
)

DRAGONWILDS = ModProfile(
    key="dragonwilds",
    kind=KIND_FOLDER,
    services=("dragonwilds",),
    # O servidor e Unreal 5 nativo Linux: le de ~mods o que nao veio com o jogo. Conferido no
    # CT de producao (os proprios arquivos do jogo em Paks/ sao .pak + .ucas + .utoc).
    folder="/opt/game/RSDragonwilds/Content/Paks/~mods",
    help_key="mods.help_dragonwilds",
    # Unreal 5 (IoStore): um mod costuma vir em TRES arquivos com o mesmo nome, e o .pak sozinho
    # nao carrega. Os tres entram juntos.
    extensions=(".pak", ".utoc", ".ucas"),
    sources=(("mods.source_nexus", NEXUS + "runescapedragonwilds/mods/"),),
)

ENSHROUDED = ModProfile(
    key="enshrouded",
    kind=KIND_SHROUDTOPIA,
    services=("enshrouded",),
    # A pasta dos MODS; o carregador mora na de cima, ao lado do enshrouded_server.exe. Provado
    # no CT 303 (Proton GE 11) em 2026-10-03: com winmm=n,b o Shroudtopia sobe, carrega a DLL
    # de mods/ e o servidor segue respondendo a A2S. Ver shroudtopia_remote.py.
    folder="/opt/game/mods",
    help_key="mods.help_enshrouded",
    extensions=(".dll",),
    audit_paths=("/opt/game/mods", "/opt/game/winmm.dll", "/opt/game/shroudtopia.dll"),
    sources=(("mods.source_shroudtopia", "https://github.com/s0t7x/shroudtopia/releases"),
             ("mods.source_nexus", NEXUS + "enshrouded/mods/")),
)

ICARUS = ModProfile(
    key="icarus",
    kind=KIND_UE4SS,
    services=("icarus",),
    # O servidor e o IcarusServer-Win64-Shipping.exe sob o Proton (UE 4.27): o proxy do UE4SS
    # (dwmapi.dll) entra ao lado dele, e o resto - mods inclusive - em ue4ss/ (layout da
    # experimental, a que nao quebra a Steam: ver ue4ss_remote.py). Provado num Icarus de teste.
    folder="/opt/game/Icarus/Binaries/Win64/ue4ss/Mods",
    loader_dir="/opt/game/Icarus/Binaries/Win64",
    help_key="mods.help_icarus",
    audit_paths=("/opt/game/Icarus/Binaries/Win64/ue4ss", "/opt/game/Icarus/Binaries/Win64/dwmapi.dll"),
    sources=(("mods.source_ue4ss", "https://github.com/UE4SS-RE/RE-UE4SS/releases"),
             ("mods.source_nexus", NEXUS + "icarus/mods/")),
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
    # O BepInEx inteiro (core, plugins, a pasta do .NET) e o winhttp.dll do doorstop.
    audit_paths=("/opt/game/BepInEx", "/opt/game/winhttp.dll", "/opt/game/dotnet"),
    # Medido num CT de teste: a primeira subida com o BepInEx gera o codigo do jogo inteiro
    # e chegou a 9,4 GB; com 6 GB o OOM killer derrubava o servidor em laco. O curado tem 8.
    min_memory_mb=10240,
    sources=(("mods.source_thunderstore", "https://thunderstore.io/c/v-rising/"),),
)

SATISFACTORY = ModProfile(
    key="satisfactory",
    kind=KIND_SML,
    services=("satisfactory",),
    # Servidor Linux nativo: cada mod numa pasta em FactoryGame/Mods, o SML inclusive.
    folder="/opt/game/FactoryGame/Mods",
    loader_dir="/opt/game",
    help_key="mods.help_satisfactory",
    audit_paths=("/opt/game/FactoryGame/Mods",),
    sources=(("mods.source_ficsit", "https://ficsit.app/mods"),),
    proven=False,
)

VALHEIM = ModProfile(
    key="valheim",
    kind=KIND_THUNDERSTORE,
    services=("valheim",),
    folder="/opt/game",
    help_key="mods.help_valheim",
    community="valheim",
    loader=("denikson", "BepInExPack_Valheim"),
    # Chute, nao medida: o Valheim pede bem menos que o V Rising. Medir ao provar.
    min_memory_mb=4096,
    audit_paths=("/opt/game/BepInEx", "/opt/game/doorstop_libs"),
    sources=(("mods.source_thunderstore", "https://thunderstore.io/c/valheim/"),),
    proven=False,
    linux_bepinex=True,
)

RUST = ModProfile(
    key="rust",
    kind=KIND_OXIDE,
    services=("rust",),
    # A pasta dos PLUGINS (.cs); o Oxide entra na do jogo (RustDedicated_Data/Managed).
    folder="/opt/game/oxide/plugins",
    loader_dir="/opt/game",
    help_key="mods.help_rust",
    extensions=(".cs",),
    audit_paths=("/opt/game/oxide/plugins", "/opt/game/.gamepanel-oxide/package"),
    sources=(("mods.source_umod", "https://umod.org/plugins?page=1&categories=rust"),),
    proven=False,
)

PROFILES = (ETS2, PALWORLD, VRISING, DRAGONWILDS, ENSHROUDED, ICARUS, SATISFACTORY, VALHEIM, RUST)


def service_stem(service: str) -> str:
    return (service or "").strip().removesuffix(".service")


def profile_for(service: str) -> ModProfile | None:
    stem = service_stem(service)
    return next((p for p in PROFILES if stem in p.services), None)


# Referencia de mod do ficsit.app, solta ou dentro do link da pagina (ficsit.app/mod/<ref>).
# A mesma forma que o sml_remote confere de novo no CT: ela vira nome de pasta.
_FICSIT_REF = re.compile(r"^(?:https?://(?:www\.)?ficsit\.app/mod/)?([A-Za-z0-9_]{1,64})/?(?:[?#].*)?$", re.ASCII)


def ficsit_ref(text: str) -> str:
    found = _FICSIT_REF.match((text or "").strip())
    return found.group(1) if found else ""
