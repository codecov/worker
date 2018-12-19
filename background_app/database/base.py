from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class CodecovBaseModel(Base):

    __abstract__ = True
