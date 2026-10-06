# Lab prático de Docker Compose — E-mail Sender

Neste lab você monta, passo a passo, uma aplicação com **5 serviços**: um site, uma API, um banco de dados, uma fila e *workers* que "enviam" e-mails. A cada passo você roda o que foi explicado nos slides: serviços, volumes, bind mounts, redes, `depends_on`, healthchecks, restart, `.env` e múltiplos arquivos Compose.

```
              rede web              rede banco
 navegador ─▶ [ frontend ] ─────▶ [  app  ] ──────────────▶ [ db ]
  :8080        nginx    /api       Flask   │                  Postgres
                                           │  rede fila
                                           └────────────────▶ [ queue ] ◀───── [ worker ] × N
                                                               Redis
```

> O `app` participa das 3 redes (é a "ponte"). O `frontend` **não** enxerga o `db`, e o `db` **não** enxerga a fila. Isso é de propósito.

---

## Passo 0 — Preparação

Crie a pasta do projeto e entre nela. **Todos os comandos do lab são executados dentro dessa pasta**, onde ficará o `compose.yaml`.

```bash
mkdir email-sender
cd email-sender
mkdir scripts web nginx app worker
```

---

## Passo 1 — Primeiro serviço: o banco de dados

**Conceitos:** `services`, `image`, `environment`, comandos básicos.

Crie o arquivo `compose.yaml`:

```yaml
name: email-sender

services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: email_sender
```

- `name:` define o nome do projeto. Ele vira prefixo de containers, redes e volumes (ex.: `email-sender-db-1`).
- Não existe mais a linha `version:`. Ela é obsoleta, não use.

Rode:

```bash
docker compose config          # valida o arquivo e mostra o resultado final
docker compose up -d           # sobe em segundo plano
docker compose ps              # estado dos serviços
```

Espere aparecer `database system is ready to accept connections` (na primeira vez ele aparece **duas vezes**: o Postgres inicializa, reinicia e só então fica pronto). Depois:

```bash
docker compose exec db psql -U postgres -c "\l"
```

Você deve ver a lista de bancos, incluindo `email_sender`.


>`down` remove containers e redes. O `-v` também remove os **volumes** (os dados somem!). Usamos aqui só para começar do zero.

`docker compose up -d` sobe o `db`, `exec` consegue conversar com ele, e você sabe o que `down -v` faz.

---

## Passo 2 — Persistência: volume nomeado e bind mount

**Conceitos:** volume nomeado (dados), bind mount (arquivos do seu computador), a camada `volumes`.

Crie `scripts/init.sql`. A imagem do Postgres executa todo `.sql` da pasta `/docker-entrypoint-initdb.d/` **na primeira inicialização** (banco vazio), dentro do banco definido em `POSTGRES_DB`:

```sql
CREATE TABLE IF NOT EXISTS emails (
  id       SERIAL PRIMARY KEY,
  data     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  assunto  VARCHAR(100) NOT NULL,
  mensagem TEXT NOT NULL DEFAULT ''
);
```

Crie `scripts/check.sql` (um script de verificação para rodarmos quando quisermos):

```sql
\conninfo
\dt
\d emails
SELECT count(*) AS total_emails FROM emails;
```

Atualize o `compose.yaml`:

```yaml
name: email-sender

services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: email_sender
    volumes:
      - dados:/var/lib/postgresql/data                              # novo: volume nomeado
      - ./scripts:/scripts:ro                                       # novo: bind mount
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql:ro  # novo: bind mount

volumes:                                                            # novo: camada de volumes
  dados:
```

| | Volume nomeado (`dados`) | Bind mount (`./scripts`) |
|---|---|---|
| Quem gerencia | Docker | Você (pasta do seu computador) |
| Para quê | Dados que precisam sobreviver (banco) | Arquivos que você edita (código, config, scripts) |
| Declarado em `volumes:` no final? | Sim | Não |

O `:ro` significa *read-only*: o container só lê, não altera seus arquivos.

```bash
docker compose up -d
docker compose logs -f db      # espere ficar pronto; Ctrl+C
docker compose exec db psql -U postgres -d email_sender -f /scripts/check.sql
```

 o `check.sql` mostra a tabela `emails` com 0 registros.

**Experimento 1: os dados sobrevivem?**

```bash
docker compose exec db psql -U postgres -d email_sender -c "INSERT INTO emails (assunto, mensagem) VALUES ('teste', 'ola');"
docker compose down            # sem -v
docker compose up -d
docker compose exec db psql -U postgres -d email_sender -c "SELECT id, assunto FROM emails;"
```

O registro continua lá: o volume `dados` sobreviveu ao `down`. Veja o volume com `docker volume ls` (nome `email-sender_dados`).

**Experimento 2: o `init.sql` roda de novo?**
Edite o `init.sql` (por exemplo, adicione a linha `status VARCHAR(20),` dentro do `CREATE TABLE`, antes de `mensagem`), rode `docker compose down` e `docker compose up -d`, e confira com o `check.sql`. A coluna **não** aparece, porque o banco já estava inicializado. Agora:

```bash
docker compose down -v
docker compose up -d
docker compose logs -f db      # espere ficar pronto; Ctrl+C
docker compose exec db psql -U postgres -d email_sender -f /scripts/check.sql
```

Agora a coluna aparece, e o registro de teste sumiu. **Este é o erro nº 1 de quem usa Postgres em Docker**: scripts de init só rodam com o volume vazio.

---

## Passo 3 — Front-end com nginx

**Conceitos:** novo serviço, `ports`, bind mount para desenvolver sem rebuild.

Crie `web/index.html`:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>E-mail Sender</title>
  <style>
    body { font-family: sans-serif; max-width: 480px; margin: 2rem auto; }
    label { display: block; margin-top: 1rem; }
    input, textarea { width: 100%; box-sizing: border-box; }
  </style>
</head>
<body>
  <h1>E-mail Sender</h1>
  <form action="/api/enviar" method="POST">
    <label for="assunto">Assunto</label>
    <input id="assunto" name="assunto" type="text" required>
    <label for="mensagem">Mensagem</label>
    <textarea id="mensagem" name="mensagem" rows="6"></textarea>
    <button type="submit">Enviar!</button>
  </form>
  <p><a href="/api/emails">Ver últimos e-mails registrados</a></p>
</body>
</html>
```

Adicione o serviço `frontend` ao `compose.yaml` (o `db` continua igual):

```yaml
name: email-sender

services:
  frontend:                                    # novo
    image: nginx:1.28-alpine
    ports:
      - "8080:80"                              # porta-do-seu-PC:porta-do-container
    volumes:
      - ./web:/usr/share/nginx/html:ro

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: email_sender
    volumes:
      - dados:/var/lib/postgresql/data
      - ./scripts:/scripts:ro
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql:ro

volumes:
  dados:
```

```bash
docker compose up -d
docker compose ps
docker compose logs -f -t frontend     # -t mostra a hora de cada linha
```

Observe na saída do `up -d`: o `db` **não** foi recriado, só o serviço novo. O Compose só mexe no que mudou.

Abra <http://localhost:8080>. A página aparece. Se clicar em **Enviar**, dá erro (`405`), e isso é esperado: ainda não existe nenhuma API.

**Experimento: bind mount em ação.**
Abra o `web/index.html`, mude o `<h1>` para outro texto, salve e recarregue o navegador. Mudou **sem reiniciar nada**, porque o container lê direto a sua pasta. Guarde essa sensação: no próximo passo, com `build`, vai ser diferente.

**Checkpoint:** o site abre em `localhost:8080` e acompanha suas edições.

---

## Passo 4 — A API: imagem própria com `build`

**Conceitos:** `build`, Dockerfile dentro do Compose, rebuild.

Crie `app/requirements.txt`:

```text
Flask==3.1.2
```

Crie `app/app.py` (versão inicial: só recebe o formulário e responde):

```python
from flask import Flask, request

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/enviar")
def enviar():
    assunto = request.form.get("assunto", "(sem assunto)")
    return f"Recebi o e-mail: {assunto}\n"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

Crie `app/Dockerfile`:

```dockerfile
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
USER appuser
EXPOSE 8080
CMD ["python", "app.py"]
```

> `PYTHONUNBUFFERED=1` faz os `print` aparecerem na hora em `docker compose logs`. Sem isso, o Python guarda a saída em buffer e você acha que o app "não loga nada".

Adicione o serviço `app` ao `compose.yaml`:

```yaml
  app:                                         # novo (dentro de "services:")
    build: ./app                               # em vez de "image:", constrói a partir do Dockerfile
    ports:
      - "8081:8080"                            # TEMPORÁRIO, só para testar direto
```

```bash
docker compose up -d --build
docker compose ps
docker compose logs app
```

Teste a API direto (sem passar pelo nginx):

```bash
curl http://localhost:8081/health
curl -X POST --data-urlencode "assunto=Oi" --data-urlencode "mensagem=Teste" http://localhost:8081/enviar
```

**Experimento: código novo exige rebuild.**
Troque o texto `"Recebi o e-mail: ..."` em `app.py` por outro, salve e rode só `docker compose up -d`. Teste de novo com o `curl`: **nada mudou**, porque o código está *dentro da imagem*, não numa pasta compartilhada. Agora:

```bash
docker compose up -d --build
```

Mudou. (Também funciona em dois tempos: `docker compose build app` e depois `docker compose up -d`.) No passo 11 você vai ver como evitar rebuild durante o desenvolvimento.

**Checkpoint:** `curl` na porta 8081 responde, e você entende a diferença entre editar um arquivo com bind mount (passo 3) e editar código que foi copiado para a imagem.

---

## Passo 5 — Proxy reverso: o nginx fala com a API

**Conceitos:** nome do serviço como endereço (DNS interno), `depends_on` simples, remover porta que não precisa ficar exposta.

O navegador só precisa falar com **uma** porta (a do nginx). O nginx repassa tudo que começa com `/api/` para o serviço `app`. Crie `nginx/default.conf`:

```nginx
server {
    listen 80;
    server_name localhost;

    location / {
        root /usr/share/nginx/html;
        index index.html;
    }

    location /api/ {
        resolver 127.0.0.11 valid=5s;
        set $app_upstream http://app:8080;
        rewrite ^/api/(.*)$ /$1 break;
        proxy_pass $app_upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

> **Por que `resolver` e `set $app_upstream`?** O nome `app` é resolvido pelo DNS interno do Docker (`127.0.0.11`). Por padrão o nginx consulta esse DNS **uma única vez**, ao iniciar. Se o container do `app` for recriado e ganhar outro IP, o nginx continuaria apontando para o IP velho e você veria `502 Bad Gateway`. Usando `resolver` + variável, ele reconsulta o DNS a cada poucos segundos. O `rewrite` remove o prefixo `/api`: `/api/enviar` chega no app como `/enviar`.

Atualize o `compose.yaml` completo:

```yaml
name: email-sender

services:
  frontend:
    image: nginx:1.28-alpine
    ports:
      - "8080:80"
    volumes:
      - ./web:/usr/share/nginx/html:ro
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro   # novo
    depends_on:                                                  # novo
      - app

  app:
    build: ./app                                                 # "ports" removido: agora só o nginx fala com o app

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: email_sender
    volumes:
      - dados:/var/lib/postgresql/data
      - ./scripts:/scripts:ro
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql:ro

volumes:
  dados:
```

```bash
docker compose up -d
docker compose ps
```

Repare: o `app` e o `frontend` foram **recriados** (a configuração deles mudou), o `db` não.

```bash
curl http://localhost:8080/api/health
curl -X POST --data-urlencode "assunto=Via proxy" --data-urlencode "mensagem=Teste" http://localhost:8080/api/enviar
curl http://localhost:8081/health      # deve FALHAR: a porta 8081 não existe mais
```

Agora abra <http://localhost:8080>, preencha o formulário e envie. Você deve ver a resposta em texto puro do app.

**Checkpoint:** o formulário funciona pela porta 8080, e a 8081 não responde mais. O `app` agora só é alcançável de dentro da rede do Compose.

---

## Passo 6 — Redes e o app falando com o banco

**Conceitos:** camada `networks`, isolamento, DNS por nome de serviço, `environment`, `depends_on` simples e **sua limitação**.

Primeiro, o código. Atualize `app/requirements.txt`:

```text
Flask==3.1.2
psycopg[binary]~=3.2.0
```

Substitua o `app/app.py` (agora grava no banco):

```python
import os

import psycopg
from flask import Flask, request

app = Flask(__name__)


def conectar_db():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "email_sender"),
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/enviar")
def enviar():
    assunto = request.form.get("assunto", "(sem assunto)")
    mensagem = request.form.get("mensagem", "")
    with conectar_db() as conn:
        conn.execute(
            "INSERT INTO emails (assunto, mensagem) VALUES (%s, %s)",
            (assunto, mensagem),
        )
    return f"Mensagem registrada no banco! Assunto: {assunto}\n"


@app.get("/emails")
def listar():
    with conectar_db() as conn:
        linhas = conn.execute(
            "SELECT id, data, assunto FROM emails ORDER BY id DESC LIMIT 10"
        ).fetchall()
    return {"emails": [{"id": i, "data": d.isoformat(), "assunto": a} for i, d, a in linhas]}


if __name__ == "__main__":
    # Testa a conexão ao iniciar: se o banco não estiver pronto, o app cai de propósito.
    conectar_db().close()
    app.run(host="0.0.0.0", port=8080)
```

Agora o `compose.yaml`: criamos duas redes, `web` (frontend ↔ app) e `banco` (app ↔ db):

```yaml
name: email-sender

services:
  frontend:
    image: nginx:1.28-alpine
    ports:
      - "8080:80"
    volumes:
      - ./web:/usr/share/nginx/html:ro
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    networks:                          # novo
      - web
    depends_on:
      - app

  app:
    build: ./app
    environment:                       # novo: o app descobre onde está o banco
      DB_HOST: db                      # "db" é o nome do serviço = nome na rede
      DB_USER: postgres
      DB_PASSWORD: postgres
      DB_NAME: email_sender
    networks:                          # novo: o app está nas duas redes
      - web
      - banco
    depends_on:                        # novo
      - db

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: email_sender
    volumes:
      - dados:/var/lib/postgresql/data
      - ./scripts:/scripts:ro
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:                          # novo
      - banco

networks:                              # novo: camada de redes
  web:
  banco:

volumes:
  dados:
```

```bash
docker compose up -d --build
docker compose ps
```

Teste pelo navegador (<http://localhost:8080>) ou:

```bash
curl -X POST --data-urlencode "assunto=Meu primeiro e-mail" --data-urlencode "mensagem=Gravado no Postgres" http://localhost:8080/api/enviar
curl http://localhost:8080/api/emails
docker compose exec db psql -U postgres -d email_sender -c "SELECT id, assunto FROM emails;"
```

**Checkpoint:** o e-mail aparece em `/api/emails` e no `psql`.

**Experimento 1: o isolamento é real.**

```bash
docker compose exec frontend ping -c 1 db
docker compose exec app python -c "import socket; print(socket.gethostbyname('db'))"
docker network ls
```

- O `frontend` **não consegue** resolver `db` (`bad address 'db'`): estão em redes diferentes.
- O `app` resolve `db` e mostra um IP: ele está na rede `banco`.
- Em `docker network ls` você vê `email-sender_web` e `email-sender_banco` (nome do projeto + nome da rede).

**Experimento 2: o limite do `depends_on` simples.**
Comece do zero (apaga os dados!):

```bash
docker compose down -v
docker compose up -d
docker compose ps -a
docker compose logs app
```

Muito provavelmente o `app` **não sobe** (você verá `Exited (1)` ou um erro `dependency failed to start`), e nos logs aparece `Connection refused`. Por quê? O `depends_on` simples só garante que o container do `db` foi **iniciado** antes, não que o Postgres já está **pronto** para aceitar conexões (na primeira vez ele ainda está rodando o `init.sql`). Espere alguns segundos e rode `docker compose up -d` de novo: agora funciona. No **passo 9** vamos resolver isso direito.

---

## Passo 7 — Fila e workers

**Conceitos:** mais serviços, terceira rede, comunicação assíncrona.

Fluxo: o `app` grava no banco **e** coloca a mensagem numa fila (Redis). Os `worker` pegam mensagens da fila e "enviam" (aqui, só simulamos com uma espera).

Atualize `app/requirements.txt`:

```text
Flask==3.1.2
psycopg[binary]~=3.2.0
redis==5.2.1
```

Substitua o `app/app.py`:

```python
import json
import os

import psycopg
import redis
from flask import Flask, request

app = Flask(__name__)

fila = redis.Redis(host=os.getenv("REDIS_HOST", "queue"), port=6379, decode_responses=True)


def conectar_db():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "email_sender"),
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/enviar")
def enviar():
    assunto = request.form.get("assunto", "(sem assunto)")
    mensagem = request.form.get("mensagem", "")
    with conectar_db() as conn:
        conn.execute(
            "INSERT INTO emails (assunto, mensagem) VALUES (%s, %s)",
            (assunto, mensagem),
        )
    fila.rpush("sender", json.dumps({"assunto": assunto, "mensagem": mensagem}))
    print(f"Mensagem registrada e enfileirada: {assunto}")
    return f"Mensagem enfileirada! Assunto: {assunto}\n"


@app.get("/emails")
def listar():
    with conectar_db() as conn:
        linhas = conn.execute(
            "SELECT id, data, assunto FROM emails ORDER BY id DESC LIMIT 10"
        ).fetchall()
    return {"emails": [{"id": i, "data": d.isoformat(), "assunto": a} for i, d, a in linhas]}


if __name__ == "__main__":
    conectar_db().close()
    app.run(host="0.0.0.0", port=8080)
```

Crie o worker. `worker/requirements.txt`:

```text
redis==5.2.1
```

`worker/worker.py`:

```python
import json
import os
import time

import redis

fila = redis.Redis(host=os.getenv("REDIS_HOST", "queue"), port=6379, decode_responses=True)
espera = int(os.getenv("WORKER_DELAY", "5"))

print("Aguardando mensagens...")

while True:
    _, bruto = fila.blpop("sender")          # bloqueia até chegar uma mensagem
    msg = json.loads(bruto)
    print(f"Enviando: {msg['assunto']}")
    time.sleep(espera)                       # simula o tempo de envio
    print(f"Enviada: {msg['assunto']}")
```

`worker/Dockerfile`:

```dockerfile
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /worker
RUN useradd --create-home appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker.py .
USER appuser
CMD ["python", "worker.py"]
```

Atualize o `compose.yaml` completo (a rede `fila` é nova):

```yaml
name: email-sender

services:
  frontend:
    image: nginx:1.28-alpine
    ports:
      - "8080:80"
    volumes:
      - ./web:/usr/share/nginx/html:ro
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - web
    depends_on:
      - app

  app:
    build: ./app
    environment:
      DB_HOST: db
      DB_USER: postgres
      DB_PASSWORD: postgres
      DB_NAME: email_sender
      REDIS_HOST: queue                # novo
    networks:
      - web
      - banco
      - fila                           # novo
    depends_on:
      - db
      - queue                          # novo

  worker:                              # novo
    build: ./worker
    environment:
      REDIS_HOST: queue
      WORKER_DELAY: "5"                # segundos que cada "envio" demora
    networks:
      - fila
    depends_on:
      - queue

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: email_sender
    volumes:
      - dados:/var/lib/postgresql/data
      - ./scripts:/scripts:ro
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - banco

  queue:                               # novo
    image: redis:7.4-alpine
    networks:
      - fila

networks:
  web:
  banco:
  fila:                                # novo

volumes:
  dados:
```

```bash
docker compose up -d --build
docker compose ps
```

Se o `app` falhar por causa da corrida com o banco (passo 6), rode `docker compose up -d` mais uma vez.

**Experimento: acompanhe uma mensagem passando pelo sistema.**
Em um terminal, deixe os logs abertos:

```bash
docker compose logs -f app worker
```

Em outro terminal (ou pelo formulário no navegador), envie uma mensagem:

```bash
curl -X POST --data-urlencode "assunto=Msg 1" --data-urlencode "mensagem=Teste" http://localhost:8080/api/enviar
```

Você vê: o `app` registra e enfileira → o `worker` pega → 5 segundos depois "envia".

🔬 **Experimento: a fila acumulando.** Mande 5 mensagens seguidas e olhe o tamanho da fila:

```bash
for i in 1 2 3 4 5; do curl -s -X POST --data-urlencode "assunto=Msg $i" --data-urlencode "mensagem=Teste" http://localhost:8080/api/enviar; done
docker compose exec queue redis-cli LLEN sender
```

O número mostra quantas mensagens ainda esperam. Com um único worker, as 5 levam cerca de 25 segundos para esvaziar. Dá para melhorar. 

**Checkpoint:** as mensagens aparecem no banco (`/api/emails`) **e** são processadas pelo worker.

---

## Passo 8 — Escalando os workers

**Conceitos:** réplicas de um serviço, `--scale`, `deploy.replicas`.

```bash
docker compose up -d --scale worker=3
docker compose ps
```

Há 3 containers do `worker` (`email-sender-worker-1`, `-2`, `-3`). Reabra os logs do worker e mande 9 mensagens:

```bash
docker compose logs -f worker
```

```bash
for i in 1 2 3 4 5 6 7 8 9; do curl -s -X POST --data-urlencode "assunto=Lote $i" --data-urlencode "mensagem=Teste" http://localhost:8080/api/enviar; done
```

No log, o prefixo `worker-1`, `worker-2`, `worker-3` mostra o trabalho sendo **dividido**: 9 mensagens em cerca de 15 s em vez de 45 s. Ninguém precisou mudar código: todos os workers consomem da mesma fila.

`--scale` vale só para aquele comando. Se você rodar `docker compose up -d` de novo sem a flag, volta para 1 worker. Para deixar a escala **no arquivo**, use `deploy.replicas` (vamos usar no passo 11):

```yaml
  worker:
    deploy:
      replicas: 3
```

**Experimento: por que o `worker` escala e o `frontend` não?**

```bash
docker compose up -d --scale frontend=2
```

Vai dar erro de porta em uso (`port is already allocated`): duas réplicas não podem publicar a mesma porta `8080` do seu computador. Serviços **sem** `ports` (como o worker) escalam à vontade. Para escalar o app/nginx de verdade você colocaria um balanceador na frente. Volte ao normal:

```bash
docker compose up -d
```

(Isso também volta o worker para 1 réplica.)

**Checkpoint:** você viu 3 workers dividindo a fila e sabe por que só alguns serviços escalam com facilidade.

---

## Passo 9 — Robustez: healthchecks, `depends_on` com condição e restart

**Conceitos:** `healthcheck`, `depends_on: condition: service_healthy`, `restart`.

Vamos corrigir o problema do passo 6 de forma correta (nada de `sleep`!) e fazer o sistema se recuperar de falhas.

Primeiro, adicione uma rota que **derruba o app de propósito**, só para o laboratório. No `app/app.py`, logo depois da rota `/health`:

```python
@app.get("/crash")
def crash():
    # SOMENTE PARA O LABORATÓRIO: mata o processo para testarmos o restart
    os._exit(1)
```

Agora o `compose.yaml` completo:

```yaml
name: email-sender

services:
  frontend:
    image: nginx:1.28-alpine
    ports:
      - "8080:80"
    volumes:
      - ./web:/usr/share/nginx/html:ro
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - web
    depends_on:
      app:
        condition: service_healthy     # mudou: espera o app ficar saudável
    restart: unless-stopped            # novo

  app:
    build: ./app
    environment:
      DB_HOST: db
      DB_USER: postgres
      DB_PASSWORD: postgres
      DB_NAME: email_sender
      REDIS_HOST: queue
    networks:
      - web
      - banco
      - fila
    depends_on:
      db:
        condition: service_healthy     # mudou
      queue:
        condition: service_healthy     # mudou
    healthcheck:                       # novo
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
    restart: unless-stopped            # novo

  worker:
    build: ./worker
    environment:
      REDIS_HOST: queue
      WORKER_DELAY: "5"
    networks:
      - fila
    depends_on:
      queue:
        condition: service_healthy     # mudou
    restart: unless-stopped            # novo

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: email_sender
    volumes:
      - dados:/var/lib/postgresql/data
      - ./scripts:/scripts:ro
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - banco
    healthcheck:                       # novo
      test: ["CMD-SHELL", "pg_isready -U postgres -d email_sender"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped            # novo

  queue:
    image: redis:7.4-alpine
    networks:
      - fila
    healthcheck:                       # novo
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped            # novo

networks:
  web:
  banco:
  fila:

volumes:
  dados:
```

> Cada healthcheck é um comando que roda **dentro** do container. Se ele termina com código 0, o container está `healthy`. Aqui o `app` usa o próprio Python para consultar `/health`, porque a imagem `slim` não tem `curl`.

**Experimento 1: a corrida acabou.** Repita exatamente o experimento do passo 6:

```bash
docker compose down -v
docker compose up -d --build --wait
docker compose ps
```

O `--wait` faz o comando só terminar quando tudo estiver rodando e saudável. Em outro terminal, rode `docker compose ps` durante a subida e veja o `db` em `(health: starting)` enquanto `app` e `frontend` ficam **esperando**. Depois todos viram `(healthy)`. Desta vez o `app` não cai.

**Experimento 2: o restart em ação.**

```bash
curl -i http://localhost:8080/api/crash
docker compose ps
```

O `curl` recebe `502 Bad Gateway` (o app morreu no meio da requisição). Segundos depois, o `docker compose ps` mostra o `app` de volta, com tempo de `Up` bem curto. Confira quantas vezes ele reiniciou:

```bash
docker inspect --format "{{.RestartCount}}" $(docker compose ps -q app)
```

**Experimento 3: parar manualmente não reinicia.**

```bash
docker compose stop app
docker compose ps -a        # app fica Exited e NÃO volta sozinho
docker compose start app
```

Com `unless-stopped`, o Docker reinicia quando o processo **morre**, mas respeita quando **você** mandou parar.

> Um container `unhealthy` **não** é reiniciado automaticamente pelo Compose: o healthcheck informa o estado e controla o `depends_on`; quem reinicia é a política `restart` (quando o processo morre).

**Checkpoint:** `down -v` + `up -d --wait` sobe tudo na ordem certa, sem erro, e o `/api/crash` é recuperado sozinho.

---

## Passo 10 — Tirando configuração do YAML: `.env` e variáveis

**Conceitos:** arquivo `.env`, interpolação `${VAR}`, valor padrão `:-`, variável obrigatória `:?`, escapar `$$`.

Hoje a senha do banco está escrita em 3 lugares do `compose.yaml`. Vamos centralizar. Crie o arquivo `.env` (o Compose lê esse arquivo automaticamente, na mesma pasta do `compose.yaml`):

```env
WEB_PORT=8080
POSTGRES_USER=postgres
POSTGRES_PASSWORD=troque-esta-senha
POSTGRES_DB=email_sender
WORKER_DELAY=5
```

Crie também um `.env.example` (mesma estrutura, **sem segredos reais**; é o que vai para o Git) e um `.gitignore`:

```env
WEB_PORT=8080
POSTGRES_USER=postgres
POSTGRES_PASSWORD=defina-uma-senha
POSTGRES_DB=email_sender
WORKER_DELAY=5
```

```text
.env
```

A senha do Postgres só é aplicada **na primeira inicialização do volume**. Como mudamos a senha, apague o volume antigo antes de subir (senão o app dará `password authentication failed`):

```bash
docker compose down -v
```

Atualize o `compose.yaml` completo, trocando valores fixos por variáveis:

```yaml
name: email-sender

services:
  frontend:
    image: nginx:1.28-alpine
    ports:
      - "${WEB_PORT:-8080}:80"                                    # variável com valor padrão
    volumes:
      - ./web:/usr/share/nginx/html:ro
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - web
    depends_on:
      app:
        condition: service_healthy
    restart: unless-stopped

  app:
    build: ./app
    environment:
      DB_HOST: db
      DB_USER: ${POSTGRES_USER:-postgres}                         # <-
      DB_PASSWORD: ${POSTGRES_PASSWORD:?defina POSTGRES_PASSWORD no .env}   # obrigatória
      DB_NAME: ${POSTGRES_DB:-email_sender}                       # <-
      REDIS_HOST: queue
    networks:
      - web
      - banco
      - fila
    depends_on:
      db:
        condition: service_healthy
      queue:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
    restart: unless-stopped

  worker:
    build: ./worker
    environment:
      REDIS_HOST: queue
      WORKER_DELAY: ${WORKER_DELAY:-5}                            # <-
    networks:
      - fila
    depends_on:
      queue:
        condition: service_healthy
    restart: unless-stopped

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}                   # <-
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?defina POSTGRES_PASSWORD no .env}   # <-
      POSTGRES_DB: ${POSTGRES_DB:-email_sender}                   # <-
    volumes:
      - dados:/var/lib/postgresql/data
      - ./scripts:/scripts:ro
      - ./scripts/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - banco
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]   # note o $$
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

  queue:
    image: redis:7.4-alpine
    networks:
      - fila
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

networks:
  web:
  banco:
  fila:

volumes:
  dados:
```

Entenda as três sintaxes:

| Sintaxe | Significado |
|---|---|
| `${WEB_PORT:-8080}` | usa `WEB_PORT`; se não existir, usa `8080` |
| `${POSTGRES_PASSWORD:?mensagem}` | **obrigatória**: se faltar, o Compose para e mostra a mensagem |
| `$${POSTGRES_USER}` | `$$` "escapa" o cifrão: o Compose **não** interpola, e quem expande a variável é o shell **dentro do container** |

```bash
docker compose config            # veja o arquivo com tudo já substituído
docker compose up -d --wait
```

**Checkpoint:** `docker compose config` mostra a senha e a porta vindas do `.env`, e o sistema funciona como antes.

**Experimento 1: mude a porta sem tocar no YAML.** Troque `WEB_PORT=8080` por `WEB_PORT=8090` no `.env` e rode `docker compose up -d`. Só o `frontend` é recriado; o site agora está em <http://localhost:8090>. Volte para 8080 depois.

**Experimento 2: variável do terminal vence o `.env`.**

```bash
WEB_PORT=9000 docker compose config | grep published
```

Aparece `published: "9000"`: a variável do shell tem prioridade sobre o `.env`. (Por isso, em máquinas diferentes, o mesmo projeto pode se comportar diferente sem você perceber.)

**Experimento 3: variável obrigatória faltando.** Renomeie o `.env` para `.env.bak` e rode `docker compose config`. O Compose para com a sua mensagem `defina POSTGRES_PASSWORD no .env`. Renomeie de volta.

---

## Passo 11 — Múltiplos arquivos: dev × produção

**Conceitos:** `compose.override.yaml`, `-f`, regras de mesclagem, `docker compose config` para conferir.

O Compose junta arquivos na ordem. Se existir um **`compose.override.yaml`** ao lado do `compose.yaml`, ele é carregado **automaticamente**. Ótimo para ajustes de desenvolvimento.

Crie `compose.override.yaml`:

```yaml
# Carregado automaticamente por "docker compose up" (ambiente de desenvolvimento)
services:
  app:
    environment:
      APP_DEBUG: "1"          # liga o recarregamento automático do Flask
    volumes:
      - ./app:/app            # bind mount: edite o código sem rebuild
  worker:
    environment:
      WORKER_DELAY: "2"       # envios mais rápidos para testar
  db:
    ports:
      - "127.0.0.1:5432:5432" # permite conectar um cliente SQL do seu PC
```

Para o `APP_DEBUG` fazer efeito, ajuste a última linha do `app/app.py`:

```python
    app.run(host="0.0.0.0", port=8080, debug=os.getenv("APP_DEBUG") == "1")
```

E crie `compose.prod.yaml` (será usado **explicitamente**):

```yaml
# Uso: docker compose -f compose.yaml -f compose.prod.yaml up -d
services:
  app:
    environment:
      APP_DEBUG: "0"
  worker:
    deploy:
      replicas: 3             # a escala agora fica registrada no arquivo
```

Compare o que cada combinação produz **sem subir nada**:

```bash
docker compose config                                          # base + override (automático)
docker compose -f compose.yaml config                          # só a base
docker compose -f compose.yaml -f compose.prod.yaml config     # base + produção
```

Procure em cada saída: `APP_DEBUG`, `WORKER_DELAY`, as `ports` do `db` e as `replicas` do `worker`.

**Regras de mesclagem:**

| Tipo | O que acontece |
|---|---|
| Mapas (`environment`) | são mesclados chave a chave; se a chave repete, **o último arquivo vence** (`WORKER_DELAY` vira `2`) |
| Listas (`ports`, `volumes`) | são **somadas** |
| Valores simples (`image`, `command`) | o último arquivo substitui |

Ao usar `-f`, o `compose.override.yaml` **não** é carregado automaticamente. Por isso, o ambiente de produção não expõe a porta do banco.

**Experimento: desenvolver sem rebuild.**

```bash
docker compose up -d --build
docker compose logs -f app
```

Em outro terminal, edite a mensagem de retorno em `app/app.py` e salve. O log mostra o Flask detectando a mudança e recarregando. Teste com `curl` na hora, **sem** `--build`. Compare com o passo 4: lá o código estava dentro da imagem; aqui o override monta a sua pasta por cima.

**Experimento: subir como "produção".**

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d
docker compose -f compose.yaml -f compose.prod.yaml ps
```

Você deve ver 3 workers e nenhuma porta do banco publicada.

**Checkpoint:** você sabe prever o resultado da mesclagem e conferir com `config` antes de subir.

---

## Passo 12 — Encerramento

Desmonte tudo: containers, redes, volumes e as imagens construídas por você.

```bash
docker compose -f compose.yaml -f compose.prod.yaml down -v --rmi local --remove-orphans
docker compose down -v --rmi local --remove-orphans
```

---