"""Modello comune di un avviso ANAC, già appiattito."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Avviso:
    id: str                      # idAvviso ANAC, stabile: è la chiave anti-spam
    momento: str                 # manifestazione | preavviso | gara | esito | modifica | altro
    titolo: str
    descrizione: str = ""
    ente: str | None = None
    cf_ente: str | None = None
    cig: str | None = None
    categorie: list[str] = field(default_factory=list)   # etichette CPV (testo, non codici)
    natura: str | None = None    # servizi | forniture | lavori
    valore: float | None = None  # stima a base d'asta (somma dei lotti)
    valore_aggiudicato: float | None = None
    aggiudicatari: list[dict] = field(default_factory=list)
    luogo: str | None = None     # NUTS o ISTAT o testo, come arriva da ANAC
    regione: str | None = None   # ricavata da luogo (vedi filters.regione_di)
    pubblicazione: str | None = None   # AAAA-MM-GG
    scadenza: str | None = None        # AAAA-MM-GG
    url: str = ""                # scheda sulla piattaforma ANAC
    link_gara: str | None = None # documenti sul portale dell'ente
    punteggio: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Avviso":
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})
