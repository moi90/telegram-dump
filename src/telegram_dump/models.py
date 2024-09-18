from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column
from sqlalchemy.sql.sqltypes import String, Integer, DateTime
import telethon.tl.custom.message

Base = declarative_base()


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    dialog_id = Column(Integer, primary_key=True)
    date = Column(DateTime)
    message = Column(String)
    filename = Column(String)
    media_type = Column(String)
    json = Column(String)

    @staticmethod
    def from_telethon(msg: telethon.tl.custom.message.Message, **kwargs):
        return Message(
            id=msg.id, date=msg.date, message=msg.message, json=msg.to_json(), **kwargs
        )
