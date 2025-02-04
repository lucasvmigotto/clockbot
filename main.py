from datetime import datetime as dt
from datetime import timedelta as td
from io import StringIO
from logging import DEBUG, INFO, Logger, basicConfig, getLogger
from os import getenv
from typing import Any

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

NOTIFY_ANYWAY: bool = getenv("NOTIFY_ANYWAY", None) is not None

USERNAME: str = getenv("PONTO_USERNAME")
PASSWORD: str = getenv("PONTO_PASSWORD")
DISCORD_TOKEN: str = getenv("DISCORD_TOKEN")
DISCORD_USER_ID: str = getenv("DISCORD_USER_ID")
URL_BASE: str = getenv("URL_BASE")

REQUIRED_ENVS: list[bool] = [
    USERNAME,
    PASSWORD,
    DISCORD_TOKEN,
    DISCORD_USER_ID,
    URL_BASE,
]
if not all(REQUIRED_ENVS):
    logger.error("Some required env var not provied")
    exit(1)

HOLIDAYS_COUNTRY: str = getenv("HOLIDAYS_COUNTRY", "BR")
HOLIDAYS_SUBDIV: str = getenv("HOLIDAYS_SUBDIV", "SP")


URL_LOGIN: str = f"{URL_BASE}/Paginas/pgLogin.aspx"
URL_DATA: str = f"{URL_BASE}/Paginas/pgCalculos.aspx"

HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0"
}

SKIP_ROWS: int = 2
DF_COLUMNS: list[str] = ["date", "clockin", "breakin", "breakout", "clockout"]
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
    clean.columns = DF_COLUMNS

    clean["date"] = pd_to_datetime(
        clean["date"].apply(lambda date: date.split(" - ")[0].strip()),
        format=DATE_FORMAT,
    )

    clean = clean.set_index("date")

    return clean


def get_hours_as_dataframe(
    username: str, password: str, start_interval: dt, end_interval: dt
) -> DataFrame:
    with Session() as session:
        session.headers.update(HEADERS)

        login_page = BeautifulSoup(
            session.get(URL_LOGIN).content, features="html.parser"
        )

        session.post(
            url=URL_LOGIN,
            data=(base_fields(login_page) | login_form(username, password)),
        )

        data_page_get: Response = session.get(URL_DATA)

        if not data_page_get.text.find("Cálculos"):
            error_message: str = "Login has failed"
            logger.error(error_message)
            raise Exception(error_message)

        data_page: Response = session.post(
            url=URL_DATA,
            data=(
                base_fields(
                    BeautifulSoup(data_page_get.content, features="html.parser")
                )
                | date_interval_form(date_mask(start_interval), date_mask(end_interval))
            ),
        )

        if (
            table := BeautifulSoup(data_page.content, features="html.parser").select(
                "table"
            )
        ) is None:
            error_message: str = "Hours tables could not be generated"
            logger.error(error_message)
            raise Exception(error_message)

        hours: DataFrame = pd_read_html(StringIO(table[-1].decode()))[-1]

        return clean_hours_dataframe(hours)


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
        clock = get_hours_as_dataframe(USERNAME, PASSWORD, LAST_DAY, LAST_DAY)
        logger.debug("Hours retrieved")

        missing = clock.isna().sum(axis=1)

        message_to_send: str = None

        if missing.sum() != 0:
            logger.debug(f"Missing hours: {missing}")
            message_to_send = "\n".join(
                [
                    "* **{date}**: {missing}".format(
                        date=date.strftime("%d/%m/%Y"), missing=hours
                    )
                    for date, hours in missing[missing != 0].reset_index().values
                ]
            )

        else:
            logger.debug("No missing hours")
            message_to_send = (
                f":white_check_mark: - {date_mask(LAST_DAY)}" if NOTIFY_ANYWAY else None
            )

        if message_to_send is not None:
            logger.info(f"Message to send:\n{message_to_send}")
            user: DiscordUser = await client.fetch_user(DISCORD_USER_ID)
            await user.send(message_to_send)

    except Exception as err:
        logger.exception(f"An error occurred: {err}", exc_info=True)

    finally:
        logger.info("Closing Discord client")

        await client.close()

        logger.info("Discord client disconnected")


@cloud_event
def main(_: CloudEvent):
    client.run(DISCORD_TOKEN)
