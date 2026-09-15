from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    No tables are defined in Phase 0. Academic domain models are added
    starting in a later phase.
    """
