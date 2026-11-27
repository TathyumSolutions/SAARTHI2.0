"""Connection and model settings for the regression run, read from the
environment so nothing here is tied to one machine."""
import os
from dataclasses import dataclass
from urllib.parse import urlparse

# Server + credentials only; the database name comes from each question bank.
DEFAULT_DEMO_DB_URL = "postgresql://saarthi:password@localhost:5432/postgres"


@dataclass(frozen=True)
class DbTarget:
    host: str
    port: int
    user: str
    password: str
    dbname: str

    def as_psycopg2(self) -> dict:
        return {"host": self.host, "port": self.port, "user": self.user,
                "password": self.password, "dbname": self.dbname}


def demo_db_target(dbname: str) -> DbTarget:
    """REGRESSION_DB_URL (falls back to LENDING_/MANUFACTURING_DATABASE_URL,
    then the demo generators' own default) with `dbname` swapped in."""
    url = (os.getenv("REGRESSION_DB_URL")
           or os.getenv("LENDING_DATABASE_URL")
           or os.getenv("MANUFACTURING_DATABASE_URL")
           or DEFAULT_DEMO_DB_URL)
    p = urlparse(url)
    return DbTarget(host=p.hostname or "localhost", port=p.port or 5432,
                    user=p.username or "", password=p.password or "", dbname=dbname)


def pipeline_model() -> str:
    """Model the pipeline runs on, in Saarthi's own model-id syntax:
    "api://claude-sonnet-4-5", "api://gpt-4o", or an Ollama model name
    such as "llama3"."""
    return os.getenv("REGRESSION_MODEL", "api://claude-sonnet-4-5")


def pipeline_api_key() -> str:
    """Key for an api:// model. Empty lets the provider SDK read its own
    variable (ANTHROPIC_API_KEY, OPENAI_API_KEY, ...)."""
    return os.getenv("REGRESSION_API_KEY", "")


def ollama_url() -> str:
    return os.getenv("REGRESSION_OLLAMA_URL", "http://localhost:11434")
