# clockbot

Script para verificar (sim, infelizmente é necessário) se os registros de ponto foram feitos no sistema de ponto eletrônico.

A ideia é que esse script seja uma _function_ _triggada_ por um evento de _pub/sub_ que, por sua vez, seja usado por um _scheduler_ todo dia às 10:30am de segunda-feira à sexta-feira (use `30 10 * * 0-5` como _cron notation_).

> 10am-10:30am foi o horário que eu entendi que seria (mais ou menos) o momento de sincronizar os registros nos relógios.

## Development

### Setup

1. Crie um projeto Google Cloud, caso já não tenha um, e defina dois _secrets_ no [Secret Manager](https://console.cloud.google.com/security/secret-manager):

    * `CLOCKBOT_AUTH`: Devem ser suas credenciais usadas para fazer login no formato `<usuário>:<senha>`

    * `CLOCKBOT_DISCORD_TOKEN`: Deve ser o token de acesso do bot do Discord.

    > Esses valores serão acessados como variáveis de ambiente no ambiente Cloud Run. Para testar localmente, exporte as variáveis, com os mesmos nomes, com valores válidos.

2. Clone o projeto:

    * _SSH_:

        ```bash
        git clone git@github.com:lucasvmigotto/clockbot.git
        ```

    * _HTTPS_:

        ```bash
        git clone https://github.com/lucasvmigotto/clockbot.git
        ```

3. Crie uma cópia do arquivo `.env.example` e renomeie para `.env`.

    > Preencha os campos faltantes com valores válidos

### Testes

1. Inicie a _function_:

    ```bash
    functions-framework --target main --signature-type event
    ```

2. Use o script `trigger.py` para simular uma chamada _pub/sub cloud event_:

    ```bash
    python trigger.py
    ```

### Comandos úteis

* Exportar as dependências para `requirements.txt`

    ```bash
    uv export \
        --format requirements-txt \
        --output-file ./requirements.txt \
        --no-hashes \
        --no-dev
    ```

* Abrir um terminal dentro do _devcontainer_:

    ```bash
    docker exec -it $(docker container ls -aqf 'name=clockbot') bash
    ```

## TODO

* Adicionar instruções e comandos para deploy com `gcloud`;
* Enviar, quando houverem erros, o relatório em PDF exportado dentro do sistema;
* Criar storage para receber espelhos de ponto e, caso haja erros, criar PDF para anexo com comprovantes;
  * Definir política de limpeza e deleção de arquivos dado determinado período transcorrido;

## References

* [Google Cloud: Cloud Functions](https://cloud.google.com/functions?hl=en)
* [Google Cloud: Secret Manager](https://cloud.google.com/security/products/secret-manager?hl=en)
* [Docker](https://docs.docker.com/reference/)
* [functions-framework-python](https://github.com/GoogleCloudPlatform/functions-framework-python)
* [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/)
* [Pandas](https://pandas.pydata.org/docs/)
* [discord.py](https://discordpy.readthedocs.io/en/stable/)
