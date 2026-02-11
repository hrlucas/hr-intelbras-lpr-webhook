from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class EntradaLPR(Base):
    __tablename__ = "lpr_webhook"

    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String, index=True, nullable=False)
    cor_placa = Column(String, nullable=True)
    cor_veiculo = Column(String, nullable=True)
    caminho_imagem = Column(String, nullable=True)
    confianca = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<EntradaLPR(id={self.id}, placa={self.placa})>"
