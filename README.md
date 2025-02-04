# clockbot

Script para verificar (sim, infelizmente é necessário) se os registros de ponto foram feitos no sistema de ponto eletrônico.

A ideia é que esse script seja uma _function_ _triggada_ por um evento de _pub/sub_ que, por sua vez, seja usado por um _scheduler_ todo dia às 10am de segunda-feira à sexta-feira (use `0 10 * * 0-5` como _cron notation_).

> 10am foi o horário que eu entendi que seria (mais ou menos) o momento de sincronizar os registros nos relógios.

## Development

### Setup

* Copy and rename the `.env.example` file to `.env`

    > Fill the missing values with appropriate and valid credentials

### Testing

1. Start the function:

    ```bash
    functions-framework --target main --signature-type event
    ```

2. Use the `trigger.py` script to simulate a _pub/sub cloud event_:

    ```bash
    python trigger.py
    ```

### Export dependencies to `requirements.txt`

```bash
uv export \
    --format requirements-txt \
    --output-file ./requirements.txt \
    --no-hashes \
    --no-dev
```

### Docker

* Open a terminal inside container:

```bash
docker exec -it $(docker container ls -aqf 'name=vsc-*') bash
```

## References

* [discord.py](https://discordpy.readthedocs.io/en/stable/)
* [Clockify API](https://docs.clockify.me/#section/Introduction)
* [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/)
* [Pandas](https://pandas.pydata.org/docs/)
* [Docker](https://docs.docker.com/reference/)
* [functions-framework-python](https://github.com/GoogleCloudPlatform/functions-framework-python)
