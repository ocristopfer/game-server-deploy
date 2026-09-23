"""O que um campo de configuracao de jogo E: tipo, limite, unidade e rotulo.

Aqui nao ha jogo nenhum. O `config_format.py` sabe LER e GRAVAR os arquivos (ini, json,
serverDZ.cfg) sem conhecer jogo — e isso e proposital: arquivo novo continua editavel
sem tocar no codigo. O que falta la e SEMANTICA: que um campo e booleano, que outro e
uma porcentagem, que `dayTimeDuration` esta em nanossegundos e tem minimo de 2 minutos.

Esta camada acrescenta so isso, e cada jogo a preenche no seu `adapters/`:

* nada e obrigatorio — campo sem descricao continua aparecendo como texto livre;
* o catalogo nunca esconde campo: se o jogo ganhar uma chave nova numa atualizacao,
  ela aparece na tela mesmo sem estar mapeada.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Um segundo em nanossegundos. O Enshrouded grava duracao nessa unidade, e e a origem
# do erro mais comum no arquivo dele: quem digita "120" achando que sao segundos
# escreve 120 nanossegundos, e o jogo silenciosamente usa o minimo.
NS = 1_000_000_000

# Rotulos que aparecem em varios jogos com nomes tecnicos diferentes (`ServerName`,
# `SessionName`, `hostname`, `name`). O nome do CAMPO muda de jogo para jogo; o que a
# pessoa procura na tela, nao - e e justamente por isso que ele precisa sair igual nos
# quatro. Escritos a mao, um deles viraria "Nome de servidor" numa atualizacao e a
# busca por nome deixaria de achar aquele campo naquele jogo.
LABEL_NAME = "Nome do servidor"
# Rotulo de campo na tela, nao segredo - o analisador confunde por causa do nome da constante.
LABEL_JOIN_PASSWORD = "Senha de entrada"  # noqa: S105  # NOSONAR
LABEL_ADMIN_PASSWORD = "Senha de admin"  # noqa: S105  # NOSONAR


@dataclass
class FieldSpec:
    """Como um campo deve aparecer na tela e o que vale nele."""

    label: str = ""
    help: str = ""
    kind: str = "text"          # text | bool | number | factor | duration | enum | password
    options: dict[str, str] = field(default_factory=dict)   # valor gravado -> rotulo na tela
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ""              # sufixo mostrado ao lado do campo
    # Para kind="duration": o arquivo guarda nanossegundos, a tela mostra minutos.
    scale: int = 1

    def to_display(self, raw: str) -> str:
        """Valor do arquivo -> valor mostrado na tela."""
        text = (raw or "").strip()
        if self.kind != "duration" or not text:
            return text
        try:
            minutes = float(text) / self.scale
        except ValueError:
            return text
        return f"{minutes:g}"

    def from_display(self, text: str) -> str:
        """Valor digitado na tela -> valor gravado no arquivo."""
        text = (text or "").strip()
        if self.kind != "duration" or not text:
            return text
        return str(round(float(text) * self.scale))

    def validate(self, text: str) -> str:
        """Devolve mensagem de erro, ou string vazia quando o valor serve.

        A conferencia e feita na unidade da TELA (minutos, multiplicador), que e onde
        a pessoa erra - reportar limite em nanossegundos nao ajudaria ninguem.

        Campo vazio nunca e erro: o jogo tem um padrao para a chave ausente, e apagar
        o valor e uma forma legitima de voltar para ele.
        """
        text = (text or "").strip()
        if not text:
            return ""
        if self.kind == "enum" and self.options:
            return self._validate_enum(text)
        if self.kind in ("number", "factor", "duration"):
            return self._validate_number(text)
        return ""

    def _validate_enum(self, text: str) -> str:
        if text in self.options:
            return ""
        return f"valor invalido; use um de: {', '.join(sorted(self.options))}"

    def _validate_number(self, text: str) -> str:
        try:
            value = float(text)
        except ValueError:
            return "precisa ser um numero"
        if self.minimum is not None and value < self.minimum:
            return f"minimo {self._with_unit(self.minimum)}"
        if self.maximum is not None and value > self.maximum:
            return f"maximo {self._with_unit(self.maximum)}"
        return ""

    def _with_unit(self, value: float) -> str:
        """"2 min", "0.25 x", ou so "16" quando o campo nao tem unidade."""
        return f"{value:g}{self.unit and ' ' + self.unit}"


def factor(label: str, help_text: str, minimum: float = 0.25, maximum: float = 4.0) -> FieldSpec:
    """Multiplicador: 1 = padrao do jogo, 0,5 = metade, 2 = dobro."""
    return FieldSpec(label=label, help=help_text, kind="factor", minimum=minimum,
                     maximum=maximum, step=0.05, unit="x")


def duration(label: str, help_text: str, min_minutes: float, max_minutes: float) -> FieldSpec:
    """Duracao gravada em nanossegundos, editada em minutos."""
    return FieldSpec(label=label, help=help_text, kind="duration", scale=60 * NS,
                     minimum=min_minutes, maximum=max_minutes, step=1, unit="min")


def enum_of(label: str, help_text: str, options: dict[str, str]) -> FieldSpec:
    return FieldSpec(label=label, help=help_text, kind="enum", options=options)


def flag(label: str, help_text: str) -> FieldSpec:
    return FieldSpec(label=label, help=help_text, kind="bool")
