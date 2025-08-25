# app/models/sql_types.py
from sqlalchemy.types import UserDefinedType


class TiDBVector(UserDefinedType):
    """
    Minimal VECTOR(n) column type for TiDB that works with SQLAlchemy 2.x.
    Avoids custom @compiles so we don't hit unexpected kwargs like 'type_expression'.
    """
    cache_ok = True

    def __init__(self, dim: int):
        self.dim = int(dim)

    def get_col_spec(self, **kw) -> str:
        # Emits: VECTOR(1536) or VECTOR(3072), etc.
        return f"VECTOR({self.dim})"
