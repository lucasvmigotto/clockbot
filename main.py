from abc import ABC
from calendar import monthrange
from datetime import datetime as dt
from datetime import timedelta as td
from functools import partial
from io import StringIO
from logging import DEBUG, INFO, Logger, basicConfig, getLogger
from os import getenv
from types import NoneType
from typing import Any, Callable, Self
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from cloudevents.http.event import CloudEvent
from discord import Client as DiscordClient
from discord import Intents as DiscordIntents
from discord.user import User as DiscordUser
from functions_framework import cloud_event
from holidays import country_holidays
from pandas import (
    DataFrame,
)
from pandas import (
    read_html as pd_read_html,
)
from pandas import (
    to_datetime as pd_to_datetime,
)
from requests import Response, Session

basicConfig(
    level=DEBUG if getenv("DEBUG_MODE") else INFO,
    format="{asctime} {levelname:<8} {name}.{funcName}.{lineno}: {message}",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="{",
)
logger: Logger = getLogger(__name__)

CLOCKBOT_AUTH: str = getenv("CLOCKBOT_AUTH")
CLOCKBOT_DISCORD_TOKEN: str = getenv("CLOCKBOT_DISCORD_TOKEN")
DISCORD_USER_ID: str = getenv("DISCORD_USER_ID")
RECIPIENT: str = getenv("RECIPIENT")
SENDER: str = getenv("SENDER")
URL_BASE: str = getenv("URL_BASE")

REQUIRED_ENVS: list[bool] = [
    CLOCKBOT_AUTH,
    CLOCKBOT_DISCORD_TOKEN,
    DISCORD_USER_ID,
    RECIPIENT,
    SENDER,
    URL_BASE,
]

if not all(REQUIRED_ENVS):
    logger.error("Some required env var not provied")
    exit(1)

USERNAME, PASSWORD = None, None
try:
    USERNAME, PASSWORD = CLOCKBOT_AUTH.split(":")
except ValueError:
    logger.exception("Malformed CLOCKBOT_AUTH secret. Should be <username>:<password>")

URL_EMAIL: str = getenv("URL_EMAIL", "https://mail.google.com/mail")
SUBJECT_TEMPLATE: str = "{date} - Falha de sincronização de ponto eletrônico"
EMAIL_TEMPLATE: str = """Bom dia,

Notei que houve {errors_len} falha{is_more_than_one} no ponto eletrônico do dia {date}.
Seguem em anexo o relatório extraído do sistema de ponto eletrônico com a falha detectada, bem como o{is_more_than_one} comprovante{is_more_than_one} do{is_more_than_one} ponto{is_more_than_one} faltante{is_more_than_one}.

At.te, {sender}.
"""

MESSAGE_TEMPLATE: str = """
{errors}

[Enviar Email]({email_link})
"""

HOLIDAYS_COUNTRY: str = getenv("HOLIDAYS_COUNTRY", "BR")
HOLIDAYS_SUBDIV: str = getenv("HOLIDAYS_SUBDIV", "SP")

DATE_MASK_PATTERN: str = getenv("DATE_MASK_PATTERN", "%d/%m/%Y")
SKIP_ROWS: int = (
    int(skip_rows_env) if (skip_rows_env := getenv("WEBSCRAP_TABLE_SKIP_ROWS")) else 2
)

URL_LOGIN: str = f"{URL_BASE}/Paginas/pgLogin.aspx"
URL_DATA: str = f"{URL_BASE}/Paginas/pgCalculos.aspx"
LOGIN_SUCCESS_MATCH: str = "Cálculos"

HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0"
}

DF_COLUMNS: dict[str] = {
    "date": "Data",
    "clockin": "Entrada 1",
    "breakin": "Saída 1",
    "breakout": "Entrada 2",
    "clockout": "Saída 2",
}

LOCAL_HOLIDAYS = country_holidays(HOLIDAYS_COUNTRY, subdiv=HOLIDAYS_SUBDIV)

LAST_DAY_TIMEDELTA = td(days=1 if dt.now().weekday() != 0 else 3)
LAST_DAY: dt = (
    dt.now().replace(hour=0, minute=0, second=0, microsecond=0) - LAST_DAY_TIMEDELTA
)


def base_fields(soup: BeautifulSoup) -> dict[str, Any]:
    return {
        field["name"]: field.get("value", "") for field in soup.select("input[name]")
    }


def login_form(username: str, password: str) -> dict[str, str]:
    return {
        "txtUsuario": username,
        "txtSenha": password,
        "cboModoLogin": "0",
        "ScriptManager1": "updPanel|lnkLogin",
        "__EVENTTARGET": "lnkLogin",
        "__ASYNCPOST": "true",
    }


def date_interval_form(start: str, end: str) -> dict[str, str]:
    return {
        "ctl00$ContentPlaceHolder1$txtPeriodoIni": start,
        "ctl00$ContentPlaceHolder1$txtPeriodoFim": end,
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$lnkAtualizar",
    }


def get_month_interval(date_ref: dt) -> tuple[dt, dt]:
    _, last = monthrange(date_ref.year, date_ref.month)

    return (date_ref.replace(day=1), date_ref.replace(day=last))


def count_errors(df: DataFrame) -> list[tuple[dt, list[str]]]:
    return list(
        filter(
            lambda el: len(el[-1]) > 0,
            [
                (idx.to_pydatetime(), row.index[row.isna()].to_list())
                for idx, row in df.iterrows()
            ],
        )
    )


def clean_hours_dataframe(
    df: DataFrame, skip_rows: int, columns: list[str], date_format: str
) -> DataFrame:
    clean = df.iloc[skip_rows:, : len(columns)].copy()

    clean.columns = columns

    clean["date"] = pd_to_datetime(
        clean["date"].apply(lambda date: date.split(" - ")[0].strip()),
        format=date_format,
    )

    return clean.set_index("date")


f_clean_hours_dataframe: Callable = partial(
    clean_hours_dataframe,
    skip_rows=SKIP_ROWS,
    columns=DF_COLUMNS.keys(),
    date_format="%d/%m/%y",
)


def mask_date(date: dt, pattern: str):
    return date.strftime(pattern)


f_mask_date: Callable = partial(mask_date, pattern=DATE_MASK_PATTERN)


def build_errors_list(
    errors: list[tuple[dt, list[str]]], labels: dict[str, str], func_mask: Callable
) -> str:
    return "\n".join(
        [
            f"* {func_mask(date)}:\n" + "\n".join([f"  * {labels[occ]}" for occ in err])
            for date, err in errors
        ]
    )


f_build_errors_list: Callable = partial(build_errors_list, func_mask=f_mask_date)


def build_gmail_link(base: str, recipient: str, subject: str, content: str) -> str:
    return f"{base}?" + urlencode(
        {"tf": "cm", "fs": 1, "to": recipient, "su": subject, "body": content}
    )


class Clock(ABC):
    _LOGIN_SUCCESS_MATCH: str = LOGIN_SUCCESS_MATCH
    _HEADERS: dict[str, str] = HEADERS
    _URL_BASE: str = URL_BASE
    URL_LOGIN: str = URL_LOGIN
    URL_DATA: str = URL_DATA


class ClockSession(Clock):
    def __init__(self: Self, username: str, password: str):
        self._username = username
        self._password = password
        self.session: Session = None

    def __enter__(self: Self) -> Self:
        with Session() as session:
            session.headers.update(self._HEADERS)

            login_page = BeautifulSoup(
                session.get(self.URL_LOGIN).content, features="lxml"
            )

            session.post(
                url=self.URL_LOGIN,
                data=(
                    base_fields(login_page) | login_form(self._username, self._password)
                ),
            )

            if not session.get(self.URL_DATA).text.find(self._LOGIN_SUCCESS_MATCH):
                raise Exception("Login failed")

            self.session = session

            return self

    def __exit__(self: Self, *errors: Any):
        if any(errors):
            logger.error(f"Errors: {errors}")

        self.session.close()


def check_for_errors(
    start_interval: dt,
    end_interval: dt,
    username: str,
    password: str,
) -> list[tuple[dt, list[str]]] | NoneType:
    with ClockSession(username, password) as clock:
        data_page_get = clock.session.get(clock.URL_DATA)

        data_page: Response = clock.session.post(
            url=clock.URL_DATA,
            data=(
                base_fields(BeautifulSoup(data_page_get.content, features="lxml"))
                | date_interval_form(
                    f_mask_date(start_interval), f_mask_date(end_interval)
                )
            ),
        )

        if (
            table := BeautifulSoup(data_page.content, features="lxml").select("table")
        ) is None:
            raise Exception("Table not found")

        errors_at: list[tuple[dt, list[str]]] = count_errors(
            f_clean_hours_dataframe(pd_read_html(StringIO(table[-1].decode()))[-1])
        )

        return errors_at


f_check_for_errors: Callable = partial(
    check_for_errors, username=USERNAME, password=PASSWORD
)


class ClockBot(DiscordClient):
    def __init__(
        self: Self, start_period: dt = None, end_period: dt = None, *args, **kwargs
    ):
        super(ClockBot, self).__init__(*args, **kwargs)
        self._start_period = start_period or LAST_DAY
        self._end_period = end_period or LAST_DAY

    async def on_ready(self: Self) -> NoneType:
        try:
            if LAST_DAY in LOCAL_HOLIDAYS:
                logger.info(
                    f"{str(LAST_DAY.date())} holiday: {LOCAL_HOLIDAYS.get(LAST_DAY)}"
                )
                return

            logger.info("Discord client connected")

            logger.debug("Retrieving hours")

            errors = f_check_for_errors(self._start_period, self._end_period)

            logger.debug("Hours retrieved")

            message_to_send: str = None
            date_masked: str = f_mask_date(self._start_period)

            if (errors_len := len(errors)) > 0:
                logger.debug(f"{errors_len} Missing hours: {errors}")

                message_to_send = MESSAGE_TEMPLATE.format(
                    errors=build_errors_list(errors=errors, labels=DF_COLUMNS),
                    email_link=build_gmail_link(
                        base=URL_EMAIL,
                        recipient=RECIPIENT,
                        subject=SUBJECT_TEMPLATE.format(date=date_masked),
                        content=EMAIL_TEMPLATE.format(
                            errors_len=errors_len,
                            is_more_than_one="s" if errors_len > 1 else "",
                            date=date_masked,
                            sender=SENDER,
                        ),
                    ),
                )

            else:
                logger.debug("No missing hours")
                message_to_send = f":white_check_mark: {date_masked}"

            logger.info(f"Message to send:\n{message_to_send}")

            user: DiscordUser = await self.fetch_user(DISCORD_USER_ID)

            await user.send(message_to_send)

        except Exception as err:
            error_message: str = f"An error occurred: {err}"
            logger.exception(error_message, exc_info=True)

        finally:
            logger.info("Closing Discord client")

            await self.close()

            logger.info("Discord client disconnected")


@cloud_event
def main(_: CloudEvent) -> dict[str, bool]:
    _intentes = DiscordIntents.default()
    _intentes.messages = True

    ClockBot(intents=_intentes).run(CLOCKBOT_DISCORD_TOKEN)

    return {"success": True}
