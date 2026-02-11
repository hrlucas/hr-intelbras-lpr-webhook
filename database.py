from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from models import Base, EntradaLPR

logger = logging.getLogger("DATABASE")

try:
    from dotenv import load_dotenv

    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STORAGE_DIR = os.path.join(_BASE_DIR, "storage")
_SQLITE_FILE = os.path.join(_STORAGE_DIR, "lpr_local.db")

_DB_LOCK = threading.RLock()

URL_BANCO = None
engine = None
SessaoBanco = None

engine_sqlite = None
engine_postgres = None
_modo_banco = "desconhecido"
_aviso_senha_exemplo_emitido = False


def _obter_url_postgres():
    global _aviso_senha_exemplo_emitido
    full_url = os.getenv("DATABASE_URL", "").strip()
    if full_url:
        if full_url.startswith("postgresql"):
            return full_url
        logger.error("DATABASE_URL informado, mas não é PostgreSQL")
        return None

    host = os.getenv("POSTGRES_HOST", "").strip()
    port = os.getenv("POSTGRES_PORT", "").strip()
    database_name = os.getenv("POSTGRES_DB", "").strip()
    user = os.getenv("POSTGRES_USER", "").strip()
    password = os.getenv("POSTGRES_PASSWORD", "")

    if host and port and database_name and user:
        if password and password.strip().lower() in {"senha_aqui", "sua_senha_aqui", "changeme", "change_me"}:
            if not _aviso_senha_exemplo_emitido:
                logger.info(
                    "POSTGRES_PASSWORD ainda está com valor de exemplo. "
                    "Defina a senha real para conectar ao PostgreSQL."
                )
                _aviso_senha_exemplo_emitido = True
            return None

        user_encoded = quote_plus(user)
        db_encoded = quote_plus(database_name)
        if password:
            password_encoded = quote_plus(password)
            return f"postgresql://{user_encoded}:{password_encoded}@{host}:{port}/{db_encoded}"
        return f"postgresql://{user_encoded}@{host}:{port}/{db_encoded}"

    return None


def obter_url_banco():
    return _obter_url_postgres()


def caminho_sqlite_local():
    return _SQLITE_FILE


def modo_banco_ativo():
    with _DB_LOCK:
        return _modo_banco


def validar_conexao_postgres():
    return bool(_obter_url_postgres())


def _criar_engine_sqlite():
    os.makedirs(_STORAGE_DIR, exist_ok=True)
    sqlite_url = f"sqlite:///{_SQLITE_FILE}"
    return create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        echo=False,
    )


def _criar_engine_postgres(url):
    return create_engine(
        url,
        connect_args={"options": "-c client_encoding=UTF8"},
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=False,
    )


def _testar_engine(alvo_engine):
    with alvo_engine.connect() as connection:
        connection.execute(text("SELECT 1")).fetchone()


def _formatar_erro(exc):
    def _decodificar_bytes_erro(payload):
        if not isinstance(payload, (bytes, bytearray)):
            return None
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                return bytes(payload).decode(encoding)
            except Exception:
                continue
        return None

    def _mensagem_amigavel_postgres(texto_erro):
        if not texto_erro:
            return None

        texto = texto_erro.lower()
        if (
            "autenticação do tipo senha falhou" in texto
            or "authentication failed" in texto
            or "password authentication failed" in texto
        ):
            return (
                "falha de autenticação no PostgreSQL "
                "(verifique POSTGRES_USER e POSTGRES_PASSWORD no .env)."
            )
        if "connection refused" in texto or "não foi possível conectar" in texto:
            return "não foi possível conectar ao PostgreSQL (verifique host/porta e se o serviço está ativo)."
        if "database" in texto and "does not exist" in texto:
            return "o banco de dados configurado não existe (verifique POSTGRES_DB)."
        if "no pg_hba.conf entry" in texto:
            return "acesso ao PostgreSQL negado por regra de pg_hba.conf para este host/usuário."
        return None

    if isinstance(exc, UnicodeDecodeError):
        decoded = _decodificar_bytes_erro(getattr(exc, "object", None))
        friendly = _mensagem_amigavel_postgres(decoded)
        if friendly:
            return friendly
        if decoded:
            return decoded.strip()

    try:
        texto = str(exc)
    except Exception:
        try:
            texto = repr(exc)
        except Exception:
            texto = f"{exc.__class__.__name__} (mensagem indisponível)"

    friendly = _mensagem_amigavel_postgres(texto)
    if friendly:
        return friendly

    if "utf-8" in texto and "codec can't decode" in texto:
        return "falha ao decodificar resposta do PostgreSQL."
    return texto


def testar_conexao_postgres(alvo_engine=None):
    try:
        if alvo_engine is None:
            if engine_postgres is None:
                return False
            _testar_engine(engine_postgres)
        else:
            _testar_engine(alvo_engine)
        return True
    except Exception as exc:
        logger.warning(f"Falha ao testar conexão PostgreSQL: {_formatar_erro(exc)}")
        return False


def _definir_banco_ativo(novo_engine, modo):
    global engine, SessaoBanco, _modo_banco
    with _DB_LOCK:
        engine = novo_engine
        SessaoBanco = sessionmaker(autocommit=False, autoflush=False, bind=novo_engine)
        _modo_banco = modo


def nova_sessao():
    with _DB_LOCK:
        if SessaoBanco is None:
            raise RuntimeError("Sessão de banco não inicializada")
        factory = SessaoBanco
    return factory()


def inicializar_banco():
    global URL_BANCO, engine_sqlite, engine_postgres

    URL_BANCO = _obter_url_postgres()
    engine_sqlite = _criar_engine_sqlite()
    Base.metadata.create_all(bind=engine_sqlite)

    if URL_BANCO:
        try:
            engine_postgres = _criar_engine_postgres(URL_BANCO)
            _testar_engine(engine_postgres)
            _definir_banco_ativo(engine_postgres, "postgres")
            logger.info("Banco ativo inicial: PostgreSQL")
            return engine_postgres
        except Exception as exc:
            logger.warning(f"PostgreSQL indisponível na inicialização: {_formatar_erro(exc)}")

    _definir_banco_ativo(engine_sqlite, "sqlite")
    logger.info(f"Banco ativo inicial: SQLite local ({_SQLITE_FILE})")
    return engine_sqlite


def criar_tabelas():
    with _DB_LOCK:
        if engine is None:
            raise RuntimeError("Engine ativa não inicializada")
        Base.metadata.create_all(bind=engine)


def _ajustar_sequence_postgres(pg_session):
    pg_session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('lpr_webhook','id'), "
            "COALESCE((SELECT MAX(id) FROM lpr_webhook), 1), true)"
        )
    )


def _migrar_sqlite_para_postgres(sqlite_engine, postgres_engine):
    sqlite_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)
    pg_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=postgres_engine)

    sqlite_session = sqlite_session_factory()
    pg_session = pg_session_factory()

    try:
        sqlite_rows = sqlite_session.query(EntradaLPR).order_by(EntradaLPR.id.asc()).all()
        if not sqlite_rows:
            return 0

        existing_ids = {row_id for (row_id,) in pg_session.query(EntradaLPR.id).all()}
        migrated = 0

        for row in sqlite_rows:
            target_id = row.id if row.id not in existing_ids else None
            new_record = EntradaLPR(
                id=target_id,
                placa=row.placa,
                cor_placa=row.cor_placa,
                cor_veiculo=row.cor_veiculo,
                caminho_imagem=row.caminho_imagem,
                confianca=row.confianca,
                timestamp=row.timestamp,
            )
            pg_session.add(new_record)
            pg_session.flush()
            existing_ids.add(new_record.id)
            migrated += 1

        _ajustar_sequence_postgres(pg_session)
        pg_session.commit()

        sqlite_session.query(EntradaLPR).delete()
        sqlite_session.commit()

        logger.info(f"Migração SQLite -> PostgreSQL concluída: {migrated} registro(s)")
        return migrated

    except Exception as exc:
        pg_session.rollback()
        sqlite_session.rollback()
        logger.error(f"Erro durante migração SQLite -> PostgreSQL: {_formatar_erro(exc)}")
        return 0

    finally:
        sqlite_session.close()
        pg_session.close()


def tentar_promover_para_postgres_e_migrar():
    global URL_BANCO, engine_postgres

    if URL_BANCO is None:
        URL_BANCO = _obter_url_postgres()

    if not URL_BANCO:
        return False, 0

    if engine_postgres is None:
        try:
            engine_postgres = _criar_engine_postgres(URL_BANCO)
        except Exception as exc:
            logger.warning(f"Falha ao criar engine PostgreSQL: {_formatar_erro(exc)}")
            return False, 0

    try:
        _testar_engine(engine_postgres)
    except Exception as exc:
        logger.warning(f"PostgreSQL ainda indisponível: {_formatar_erro(exc)}")
        return False, 0

    Base.metadata.create_all(bind=engine_postgres)

    migrated = 0
    if engine_sqlite is not None:
        migrated = _migrar_sqlite_para_postgres(engine_sqlite, engine_postgres)

    promoted = False
    if modo_banco_ativo() != "postgres":
        _definir_banco_ativo(engine_postgres, "postgres")
        promoted = True
        logger.info("Banco ativo alterado para PostgreSQL")

    return promoted, migrated


def obter_registros_filtrados(
    sessao,
    placa: Optional[str] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
):
    consulta = sessao.query(EntradaLPR)

    if placa and placa.strip():
        placa_normalizada = placa.replace("-", "").replace(" ", "").upper().strip()
        if placa_normalizada:
            consulta = consulta.filter(
                func.replace(func.upper(EntradaLPR.placa), "-", "").like(f"%{placa_normalizada}%")
            )

    has_date_filter = (data_inicio and data_inicio.strip()) or (data_fim and data_fim.strip())

    if has_date_filter:
        if data_inicio and data_inicio.strip():
            try:
                dt_inicio = datetime.strptime(data_inicio.strip(), "%Y-%m-%d")
                consulta = consulta.filter(EntradaLPR.timestamp >= dt_inicio)
            except ValueError:
                pass

        if data_fim and data_fim.strip():
            try:
                dt_fim = datetime.strptime(data_fim.strip(), "%Y-%m-%d") + timedelta(days=1)
                consulta = consulta.filter(EntradaLPR.timestamp < dt_fim)
            except ValueError:
                pass

    return consulta.order_by(EntradaLPR.timestamp.desc()).all()
