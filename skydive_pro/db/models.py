"""
db/models.py — Stockage persistant SQLite pour SkyDive Pro.

Remplace le dict en mémoire JOBS_STATE de api/serveur_api.py.
Utilise SQLAlchemy 2.0+ (DeclarativeBase, mapped_column) avec scoped_session
pour la compatibilité Flask multi-thread.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, DateTime, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    scoped_session,
    sessionmaker,
)
from sqlalchemy.engine import Engine

from core.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# DB path
# ---------------------------------------------------------------------------

_DB_DIR = Path(__file__).resolve().parent
_DB_PATH = _DB_DIR / "skydive.db"

# ---------------------------------------------------------------------------
# Engine + Session factory
# ---------------------------------------------------------------------------

_engine: Optional[Engine] = None
_SessionFactory: Optional[scoped_session] = None


def get_engine() -> Engine:
    """Retourne (ou crée) l'engine SQLite."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{_DB_PATH}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
        log.debug("SQLAlchemy engine créé : %s", _DB_PATH)
    return _engine


def get_session() -> Session:
    """Retourne une session threadlocale (scoped_session)."""
    global _SessionFactory
    if _SessionFactory is None:
        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        _SessionFactory = scoped_session(factory)
    return _SessionFactory()


# ---------------------------------------------------------------------------
# Base déclarative
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prenom: Mapped[str] = mapped_column(String, nullable=False)
    nom: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    telephone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    sauts: Mapped[list["Saut"]] = relationship("Saut", back_populates="client")

    def __repr__(self) -> str:
        return f"<Client id={self.id} {self.prenom} {self.nom}>"


class Saut(Base):
    __tablename__ = "sauts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    client_id: Mapped[int] = mapped_column(Integer, ForeignKey("clients.id"), nullable=False)

    # Infos saut
    date_saut: Mapped[str] = mapped_column(String, nullable=False)
    lieu: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    moniteur: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Statut traitement
    statut: Mapped[str] = mapped_column(String, default="en_cours", nullable=False)
    etape: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    progression: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Source
    dossier_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    nb_fichiers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confiance_ordre: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Résultats
    fichier_montage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    taille_montage_mb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reels: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # JSON list

    # Télémétrie
    altitude_max_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vitesse_max_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duree_chute_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Livraison
    email_envoye: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qr_code_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Timing
    duree_traitement_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Erreurs
    erreurs: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # JSON list

    # Relation
    client: Mapped["Client"] = relationship("Client", back_populates="sauts")

    def __repr__(self) -> str:
        return f"<Saut job_id={self.job_id} statut={self.statut}>"


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Crée les tables si elles n'existent pas encore."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    log.info("Base de données initialisée : %s", _DB_PATH)


# ---------------------------------------------------------------------------
# Helpers CRUD
# ---------------------------------------------------------------------------


def create_client(
    prenom: str,
    nom: str,
    email: str,
    telephone: str = "",
    session: Optional[Session] = None,
) -> Client:
    """Crée et persiste un nouveau client."""
    _own = session is None
    s = session or get_session()
    try:
        client = Client(
            prenom=prenom,
            nom=nom,
            email=email,
            telephone=telephone or None,
            created_at=datetime.utcnow(),
        )
        s.add(client)
        s.commit()
        s.refresh(client)
        log.debug("Client créé : %s", client)
        return client
    except Exception:
        s.rollback()
        raise
    finally:
        if _own:
            s.close()


def get_or_create_client(
    prenom: str,
    nom: str,
    email: str,
    telephone: str = "",
    session: Optional[Session] = None,
) -> Client:
    """Retourne le client existant (par email) ou en crée un nouveau."""
    _own = session is None
    s = session or get_session()
    try:
        client = s.query(Client).filter_by(email=email).first()
        if client is None:
            client = Client(
                prenom=prenom,
                nom=nom,
                email=email,
                telephone=telephone or None,
                created_at=datetime.utcnow(),
            )
            s.add(client)
            s.commit()
            s.refresh(client)
            log.debug("Nouveau client créé via get_or_create : %s", client)
        else:
            log.debug("Client existant trouvé : %s", client)
        return client
    except Exception:
        s.rollback()
        raise
    finally:
        if _own:
            s.close()


def create_saut(
    job_id: str,
    client_id: int,
    date_saut: str,
    lieu: str = "",
    moniteur: str = "",
    statut: str = "en_cours",
    etape: str = "",
    progression: int = 0,
    dossier_source: str = "",
    nb_fichiers: int = 0,
    session: Optional[Session] = None,
) -> Saut:
    """Crée et persiste un nouveau saut (job)."""
    _own = session is None
    s = session or get_session()
    try:
        now = datetime.utcnow()
        saut = Saut(
            job_id=job_id,
            client_id=client_id,
            date_saut=date_saut,
            lieu=lieu or None,
            moniteur=moniteur or None,
            statut=statut,
            etape=etape or None,
            progression=progression,
            dossier_source=dossier_source or None,
            nb_fichiers=nb_fichiers,
            created_at=now,
            updated_at=now,
        )
        s.add(saut)
        s.commit()
        s.refresh(saut)
        log.debug("Saut créé : %s", saut)
        return saut
    except Exception:
        s.rollback()
        raise
    finally:
        if _own:
            s.close()


def update_saut(
    job_id: str,
    session: Optional[Session] = None,
    **fields,
) -> Optional[Saut]:
    """Met à jour les champs d'un saut existant. Retourne None si introuvable."""
    _own = session is None
    s = session or get_session()
    try:
        saut = s.query(Saut).filter_by(job_id=job_id).first()
        if saut is None:
            log.warning("update_saut : job_id=%s introuvable", job_id)
            return None
        for key, value in fields.items():
            if hasattr(saut, key):
                setattr(saut, key, value)
            else:
                log.warning("update_saut : champ inconnu '%s' ignoré", key)
        saut.updated_at = datetime.utcnow()
        s.commit()
        s.refresh(saut)
        log.debug("Saut mis à jour : %s fields=%s", job_id, list(fields.keys()))
        return saut
    except Exception:
        s.rollback()
        raise
    finally:
        if _own:
            s.close()


def get_saut(job_id: str, session: Optional[Session] = None) -> Optional[Saut]:
    """Retourne un saut par son job_id, ou None."""
    _own = session is None
    s = session or get_session()
    try:
        return s.query(Saut).filter_by(job_id=job_id).first()
    finally:
        if _own:
            s.close()


def list_sauts(
    limit: int = 50,
    statut: Optional[str] = None,
    session: Optional[Session] = None,
) -> list[Saut]:
    """Liste les sauts, optionnellement filtrés par statut."""
    _own = session is None
    s = session or get_session()
    try:
        q = s.query(Saut)
        if statut is not None:
            q = q.filter_by(statut=statut)
        return q.order_by(Saut.created_at.desc()).limit(limit).all()
    finally:
        if _own:
            s.close()


def list_clients(limit: int = 50, session: Optional[Session] = None) -> list[Client]:
    """Liste les clients (ordre alphabétique nom)."""
    _own = session is None
    s = session or get_session()
    try:
        return s.query(Client).order_by(Client.nom, Client.prenom).limit(limit).all()
    finally:
        if _own:
            s.close()


def saut_to_dict(saut: Saut) -> dict:
    """Convertit un Saut en dict JSON-sérialisable pour l'API."""
    reels = []
    if saut.reels:
        try:
            reels = json.loads(saut.reels)
        except (json.JSONDecodeError, TypeError):
            reels = []

    erreurs = []
    if saut.erreurs:
        try:
            erreurs = json.loads(saut.erreurs)
        except (json.JSONDecodeError, TypeError):
            erreurs = []

    return {
        "job_id": saut.job_id,
        "client_id": saut.client_id,
        "date_saut": saut.date_saut,
        "lieu": saut.lieu,
        "moniteur": saut.moniteur,
        "statut": saut.statut,
        "etape": saut.etape,
        "progression": saut.progression,
        "dossier_source": saut.dossier_source,
        "nb_fichiers": saut.nb_fichiers,
        "confiance_ordre": saut.confiance_ordre,
        "fichier_montage": saut.fichier_montage,
        "taille_montage_mb": saut.taille_montage_mb,
        "reels": reels,
        "altitude_max_m": saut.altitude_max_m,
        "vitesse_max_kmh": saut.vitesse_max_kmh,
        "duree_chute_s": saut.duree_chute_s,
        "email_envoye": saut.email_envoye,
        "qr_code_path": saut.qr_code_path,
        "duree_traitement_s": saut.duree_traitement_s,
        "created_at": saut.created_at.isoformat() if saut.created_at else None,
        "updated_at": saut.updated_at.isoformat() if saut.updated_at else None,
        "erreurs": erreurs,
    }


# ---------------------------------------------------------------------------
# Auto-init à l'import
# ---------------------------------------------------------------------------

init_db()
