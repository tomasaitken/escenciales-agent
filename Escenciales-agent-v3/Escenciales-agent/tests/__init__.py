import os

# Las pruebas nunca deben escribir una base de datos dentro de la entrega.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "development")
