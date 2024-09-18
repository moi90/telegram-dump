import collections
import datetime
import itertools
import os
import shutil
from typing import Optional, Union

import configargparse
from telethon.hints import Username
import telethon.tl.custom.message
from telethon.tl.types import Channel, Chat, User
import telethon.utils
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.expression import func
from telethon.sync import TelegramClient

from telegram_dump.models import Base, Message
import tqdm
import telethon.errors.rpcerrorlist
import exif

from slugify import slugify


def set_exif(filename: str, msg: telethon.tl.custom.message.Message):
    ext = os.path.splitext(filename)[1]

    if ext not in (".jpg",):
        return

    image = exif.Image(filename)

    image.datetime_original = msg.date.strftime(exif.DATETIME_STR_FORMAT)

    with open(filename, "wb") as f:
        f.write(image.get_file())


def list(api_id, api_hash, max_n, **kwargs):
    print("Dialogs:")
    # print(args)

    with TelegramClient("telegram-dump", api_id, api_hash) as client:
        n_dialogs = 0
        for dialog in client.iter_dialogs(max_n):
            print(dialog.id, dialog.name, dialog.date)
            n_dialogs += 1

        print(f"{n_dialogs} dialogs total.")


def _mirror(
    session,
    client: TelegramClient,
    dialog_id: int,
    max_n_dialog: Optional[int],
    max_n_total: Optional[int],
    exclude_types,
    n_processed: int,
) -> int:
    dialog: Union[User, Chat, Channel] = client.get_entity(dialog_id)

    if isinstance(dialog, User):
        dialog_name = (
            dialog.username
            if dialog.username is not None
            else " ".join(filter(None, (dialog.first_name, dialog.last_name)))
        )
    else:
        dialog_name = dialog.title

    if not dialog_name:
        dialog_name = str(dialog_id)

    slug = slugify(dialog_name)

    max_n_str = "all" if max_n_dialog is None else f"up to {max_n_dialog}"

    print(
        f"Mirroring {max_n_str} messages from {dialog_name} ({dialog_id}) to {slug}..."
    )

    max_id = session.query(func.max(Message.id)).filter_by(dialog_id=dialog_id).scalar()
    min_id = session.query(func.min(Message.id)).filter_by(dialog_id=dialog_id).scalar()

    n_retries = 2

    media_type_counter = collections.Counter()

    try:
        if None in (max_id, min_id):
            print(f"Initial mirror")
            messages = client.iter_messages(dialog_id, max_n_dialog, wait_time=1.0)
        else:
            print(f"Incremental mirror after ID {max_id} and before ID {min_id}")
            messages = itertools.chain(
                # Fetch messages newer than newest message in DB (oldest to newest)
                client.iter_messages(
                    dialog_id, max_n_dialog, wait_time=1.0, min_id=max_id, reverse=True
                ),
                # Fetch messages older than oldest message in DB (newest to oldest)
                client.iter_messages(
                    dialog_id, max_n_dialog, wait_time=1.0, max_id=min_id
                ),
            )

        message_progress = tqdm.tqdm(
            messages,
            desc=f"Messages",
            unit="",
            initial=n_processed,
            total=max_n_total,
            leave=False,
        )
        for message in message_progress:
            message: telethon.tl.custom.message.Message

            message_progress.set_description(f"Messages {message.date:%Y-%m-%d %H:%M}")

            media_type = type(message.media).__name__
            db_message = Message.from_telethon(
                message, media_type=media_type, dialog_id=dialog_id
            )

            session.add(db_message)
            session.flush()

            file_path = os.path.join(slug, message.date.strftime("%Y-%m"))

            if message.media is not None and media_type not in exclude_types:
                os.makedirs(file_path, exist_ok=True)
                with tqdm.tqdm(
                    desc=media_type,
                    leave=False,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                ) as progress_bar:

                    def progress_callback(received, total):
                        progress_bar.total = total
                        progress_bar.n = received
                        progress_bar.update(0)

                    for _ in range(n_retries):
                        try:
                            db_message.filename = client.download_media(  # type: ignore
                                message,  # type: ignore
                                file_path,
                                progress_callback=progress_callback,
                            )
                            break
                        except telethon.errors.rpcerrorlist.TimeoutError:
                            print("Timeout, retrying...")
                            continue

                    if db_message.filename is not None:
                        set_exif(db_message.filename, message)

                media_type_counter[media_type] += 1

            session.commit()
            n_processed += 1
    finally:
        for k, v in sorted(media_type_counter.items()):
            print(k, v)

    return n_processed


def mirror(api_id, api_hash, dialog_ids, max_n, exclude_types, **kwargs):
    try:
        shutil.copy(
            "messages.sqlite", f"messages.sqlite.{datetime.datetime.now():%Y-%m-%d}"
        )
    except OSError:
        # File most likely does not exist
        pass

    engine = create_engine("sqlite:///messages.sqlite", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    if not dialog_ids:
        dialog_ids = [
            m.dialog_id for m in session.query(Message.dialog_id).distinct().all()
        ]

    with TelegramClient("telegram-dump", api_id, api_hash) as client:
        n_processed = 0
        for i, dialog_id in enumerate(dialog_ids, start=1):
            n_processed = _mirror(
                session,
                client,
                dialog_id,
                (
                    max(1, round(max_n / len(dialog_ids) * i) - n_processed)
                    if max_n is not None
                    else None
                ),
                max_n,
                exclude_types,
                n_processed,
            )
            if max_n is not None and n_processed >= max_n:
                break


def telegram_dump():
    parser = configargparse.ArgParser(
        default_config_files=[
            "~/.telegram-dump/telegram-dump.conf",
            "telegram-dump.conf",
        ]
    )

    parser.add_argument("--api-id", type=int, required=True)
    parser.add_argument("--api-hash", required=True)
    parser.set_defaults(func=None)

    subparsers = parser.add_subparsers(title="Commands")

    parser_list = subparsers.add_parser("list")
    parser_list.set_defaults(func=list)
    parser_list.add_argument("--max-n", type=int)

    parser_mirror = subparsers.add_parser("mirror")
    parser_mirror.set_defaults(func=mirror)
    parser_mirror.add_argument("dialog_ids", type=int, nargs="*")
    parser_mirror.add_argument("--max-n", type=int)
    parser_mirror.add_argument(
        "--exclude-type",
        "-x",
        dest="exclude_types",
        action="append",
        default=[],
    )

    args = parser.parse_args()

    if args.func is not None:
        return args.func(**args.__dict__)

    parser.print_help()
