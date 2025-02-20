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

## Deploy

* Preparação do ambiente com criação de tópico _pub/sub_ e _scheduler_:

    ```bash
    REGION="<Região GCP>"
    SCHEDULE="<Expressão Cron>"
    FUNCTION="<Nome da função>"
    TIMEZONE="America/Sao_Paulo" # Usar padrão https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List
    MESSAGE_BODY="Foo Bar"

    # Criar tópico para pub/sub
    gcloud pubsub topics create "${FUNCTION}"

    # Criar job para publicar no tópico seguindo um agendamento
    gcloud scheduler job create pubsub "${FUNCTION}" \
        --location="${REGION}" \
        --schedule="${SCHEDULE}" \
        --topic="${FUNCTION}" \
        --time-zone="${TIMEZONE}" \
        --message-body="${MESSAGE_BODY}"
    ```

> Todas os comandos consideram que o diretório atual é o mesmo do projeto.

* Exportar as dependências em um arquivo `requirements.txt`:

    ```bash
    uv export \
        --format requirements-txt \
        --output-file ./requirements.txt \
        --no-hashes \
        --no-dev
    ```

* Criar a _function_:

    ```bash
    # Valores para serem usados no comando de deploy
    REGION="<Região GCP>"
    FUNCTION="<Nome da função>"
    RUNTIME="python312"
    SOURCE="$(pwd)"
    ENTRYPOINT="main"
    TRIGGER_TOPIC="<Nome do tópico>"
    SERVICE_ACCOUNT="<Email de service account>"

    # Definição de variávies de ambiente
    DISCORD_USER_ID_VALUE=<User ID do Discord>
    URL_BASE_VALUE=<URL Base do sistema de ponto>
    SENDER_VALUE="<Nome do remetente do email>"
    RECIPIENT_VALUE="<Destinatário do Email>"
    GCP_ENV_VARS="DISCORD_USER_ID=${DISCORD_USER_ID_VALUE}"
    GCP_ENV_VARS="${GCP_ENV_VARS},URL_BASE=${URL_BASE_VALUE}"
    GCP_ENV_VARS="${GCP_ENV_VARS},SENDER=${SENDER_VALUE}"
    GCP_ENV_VARS="${GCP_ENV_VARS},RECIPIENT=${RECIPIENT_VALUE}"
    GCP_ENV_VARS="${GCP_ENV_VARS},LOG_EXECUTION_ID=true"

    # Definir os secrets que serão disponibilizados para a function
    GCP_SECRETS="CLOCKBOT_AUTH=CLOCKBOT_AUTH:latest"
    GCP_SECRETS="${GCP_SECRETS},CLOCKBOT_DISCORD_TOKEN=CLOCKBOT_DISCORD_TOKEN:latest"

    # Máximo de instâncias que podem ser criadas
    MAX_INTANCES=10

    gcloud functions deploy "${FUNCTION}" \
        --gen2 \
        --region="${REGION}" \
        --runtime="${RUNTIME}" \
        --source="${SOURCE}" \
        --entry-point="${ENTRYPOINT}" \
        --trigger-topic="${TRIGGER}" \
        --run-service-account="${SERVICE_ACCOUNT}" \
        --service-account="${SERVICE_ACCOUNT}" \
        --set-env-vars="${GCP_ENV_VARS}" \
        --set-secrets="${GCP_SECRETS}" \
        --max-instances=$MAX_INTANCES

    # Redirecionar tráfego para a nova revisão
    # gcloud run services update-traffic clockbot --to-latest
    ```

* Listar as revisões desativadas:

    ```bash
    INACTIVE_REVISIONS=$(gcloud run revisions list \
        --region="${REGION}" \
        --service="${FUNCTION_NAME}" \
        --filter='status.conditions.type.Active:False' \
        --format='value(metadata.name)') \
        && echo "${INACTIVE_REVISIONS}"
    ```

* Remover as revisões desativadas:

    ```bash
    gcloud run revisions delete \
        --region="${REGION}" \
        "${INACTIVE_REVISIONS}"
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
