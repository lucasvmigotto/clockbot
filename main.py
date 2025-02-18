from abc import ABC
from calendar import monthrange
from datetime import datetime as dt
from datetime import timedelta as td
from io import StringIO
from logging import DEBUG, INFO, Logger, basicConfig, getLogger
from os import getenv
from types import NoneType
from typing import Any, Self
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

DEBUG_MODE: bool = getenv("DEBUG_MODE", None) is not None

basicConfig(
    level=DEBUG if DEBUG_MODE else INFO,
    format="{levelname:<8} {name}: {message}",
    datefmt="%Y-%m-%d %H:%M:%S",
    style="{",
)
logger: Logger = getLogger(__name__)

DISCORD_TOKEN: str = getenv("DISCORD_TOKEN")
DISCORD_USER_ID: str = getenv("DISCORD_USER_ID")
PASSWORD: str = getenv("PONTO_PASSWORD")
RECIPIENT: str = getenv("RECIPIENT")
SENDER: str = getenv("SENDER")
URL_BASE: str = getenv("URL_BASE")
URL_EMAIL: str = getenv("URL_EMAIL")
USERNAME: str = getenv("PONTO_USERNAME")

REQUIRED_ENVS: list[bool] = [
    DISCORD_TOKEN,
    DISCORD_USER_ID,
    PASSWORD,
    RECIPIENT,
    SENDER,
    URL_BASE,
    URL_EMAIL,
    USERNAME,
]

if not all(REQUIRED_ENVS):
    logger.error("Some required env var not provied")
    exit(1)

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


URL_LOGIN: str = f"{URL_BASE}/Paginas/pgLogin.aspx"
URL_DATA: str = f"{URL_BASE}/Paginas/pgCalculos.aspx"

HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0"
}

SKIP_ROWS: int = 2
DF_COLUMNS: dict[str] = {
    "date": "Data",
    "clockin": "Entrada 1",
    "breakin": "Saída 1",
    "breakout": "Entrada 2",
    "clockout": "Saída 2",
}
DATE_FORMAT: str = "%d/%m/%y"

LOCAL_HOLIDAYS = country_holidays(HOLIDAYS_COUNTRY, subdiv=HOLIDAYS_SUBDIV)

LAST_DAY_TIMEDELTA = td(days=1 if dt.now().weekday() != 0 else 3)
LAST_DAY: dt = (
    dt.now().replace(hour=0, minute=0, second=0, microsecond=0) - LAST_DAY_TIMEDELTA
)

__intents = DiscordIntents.default()
__intents.messages = True

client = DiscordClient(intents=__intents)


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


def date_mask(date: dt):
    return date.strftime("%d/%m/%Y")


def date_interval_form(start: str, end: str) -> dict[str, str]:
    return {
        "ctl00$ContentPlaceHolder1$txtPeriodoIni": start,
        "ctl00$ContentPlaceHolder1$txtPeriodoFim": end,
        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$lnkAtualizar",
    }


def clean_hours_dataframe(df: DataFrame) -> DataFrame:
    clean: DataFrame = df.copy()

    clean = clean.iloc[SKIP_ROWS:, : len(DF_COLUMNS)]
    clean.columns = DF_COLUMNS.keys()

    clean["date"] = pd_to_datetime(
        clean["date"].apply(lambda date: date.split(" - ")[0].strip()),
        format=DATE_FORMAT,
    )

    return clean.set_index("date")


def get_month_interval(date_ref: dt) -> tuple[dt, dt]:
    _, last = monthrange(date_ref.year, date_ref.month)

    return (date_ref.replace(day=1), date_ref.replace(day=last))


def count_errors(df: DataFrame) -> list[tuple[dt, list[str]]]:
    return list(
        filter(
            lambda errors: len(errors) > 0,
            [
                (idx.to_pydatetime(), row.index[row.isna()].to_list())
                for idx, row in df.iterrows()
            ],
        )
    )


def build_errors_list(
    errors: list[tuple[dt, list[str]]], labels: dict[str, str]
) -> str:
    return "\n".join(
        [
            f"* **{date_mask(date)}**:\n"
            + "\n".join([f"  * {labels[occ]}" for occ in err])
            for date, err in errors
        ]
    )


def build_gmail_link(base: str, recipient: str, subject: str, content: str) -> str:
    return f"{base}?" + urlencode(
        {"tf": "cm", "fs": 1, "to": recipient, "su": subject, "body": content}
    )


class Clock(ABC):
    def __init__(self: Self):
        self._URL_BASE: str = URL_BASE
        self.URL_LOGIN: str = URL_LOGIN
        self.URL_DATA: str = URL_DATA


class ClockSession(Clock):
    def __init__(self: Self, username: str, password: str):
        super(ClockSession, self).__init__()
        self._username = username
        self._password = password
        self.session: Session = None

    def __enter__(self: Self):
        with Session() as session:
            session.headers.update(HEADERS)

            login_page = BeautifulSoup(session.get(self.URL_LOGIN).content)

            session.post(
                url=self.URL_LOGIN,
                data=(
                    base_fields(login_page) | login_form(self._username, self._password)
                ),
            )

            if not session.get(self.URL_DATA).text.find("Cálculos"):
                raise Exception("Login failed")

            self.session = session

            return self

    def __exit__(self: Self, *errors: Any):
        if errors:
            logger.error(errors)

        self.session.close()


def check_for_errors(
    username: str, password: str, start_interval: dt, end_interval: dt
) -> list[tuple[dt, list[str]]] | NoneType:
    with ClockSession(username, password) as clock:
        data_page_get = clock.session.get(clock.URL_DATA)

        data_page: Response = clock.session.post(
            url=clock.URL_DATA,
            data=(
                base_fields(BeautifulSoup(data_page_get.content))
                | date_interval_form(date_mask(start_interval), date_mask(end_interval))
            ),
        )

        if (table := BeautifulSoup(data_page.content).select("table")) is None:
            raise Exception("Table not found")

        errors_at: list[tuple[dt, list[str]]] = count_errors(
            clean_hours_dataframe(pd_read_html(StringIO(table[-1].decode()))[-1])
        )

        return errors_at


@client.event
async def on_ready():
    try:
        if LAST_DAY in LOCAL_HOLIDAYS:
            logger.info(
                f"{str(LAST_DAY.date())} holiday: {LOCAL_HOLIDAYS.get(LAST_DAY)}"
            )
            return

        logger.info("Discord client connected")

        logger.debug("Retrieving hours")
        errors = check_for_errors(USERNAME, PASSWORD, LAST_DAY, LAST_DAY)
        logger.debug("Hours retrieved")

        message_to_send: str = None
        date_masked: str = date_mask(LAST_DAY)

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

        user: DiscordUser = await client.fetch_user(DISCORD_USER_ID)

        await user.send(message_to_send)

    except Exception as err:
        error_message: str = f"An error occurred: {err}"
        logger.exception(error_message, exc_info=True)

    finally:
        logger.info("Closing Discord client")

        await client.close()

        logger.info("Discord client disconnected")


@cloud_event
def main(_: CloudEvent):
    client.run(DISCORD_TOKEN)
