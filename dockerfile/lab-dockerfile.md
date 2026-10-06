# Lab prático de Dockerfile — Construindo suas próprias imagens

Neste lab você escreve 4 Dockerfiles, cada um um pouco maior que o anterior. A cada passo você constrói a imagem, roda um container e confere o resultado, praticando o que foi explicado nos slides: `FROM`, `RUN`, `LABEL`, `ARG`, `ENV`, `COPY`, `USER`, `VOLUME`, `WORKDIR`, `EXPOSE`, `ENTRYPOINT` e `CMD`.

```
  Dockerfile ────── docker build ──────▶ Imagem ────── docker run ──────▶ Container
  (a receita)     cada instrução vira    (somente leitura,               (a imagem + uma
                  uma camada              reutilizável)                   camada gravável)
```

---

## Passo 0 — Preparação

Crie a pasta do lab, com uma subpasta por passo:

```bash
mkdir dockerfile-lab
cd dockerfile-lab
mkdir 01-primeiro-build 02-arg-env 03-copy 04-servidor
```

---

## Passo 1 — Seu primeiro build

**Conceitos:** `Dockerfile`, `FROM`, `RUN`, `docker build`, tag (`-t`), contexto de build.

Entre na pasta do passo e crie o arquivo `Dockerfile` (esse é o nome padrão, sem extensão):

```bash
cd 01-primeiro-build
```

```dockerfile
FROM nginx:1.28-alpine
RUN echo '<h1>Hello World !</h1>' > /usr/share/nginx/html/index.html
```

- `FROM` escolhe a **imagem base**. Todo Dockerfile começa por ela.
- `RUN` executa um comando durante o build, dentro da imagem. O resultado (aqui, a página criada) fica gravado nela.

Construa a imagem e confira que ela existe:

```bash
docker build -t ex-simple-build .
docker images
```

- `-t ex-simple-build` dá um **nome (tag)** à imagem.
- O `.` no final é o **contexto de build**: a pasta atual, onde o Docker procura o `Dockerfile` e os arquivos que o build pode usar. Não esqueça o ponto.

Na saída do build, observe os passos `[1/2] FROM` e `[2/2] RUN`: um por instrução. Agora rode um container a partir da imagem:

```bash
docker run --rm -p 8080:80 ex-simple-build
```

- `-p 8080:80` publica a porta (porta-do-seu-PC:porta-do-container).
- `--rm` remove o container quando ele terminar.

Abra <http://localhost:8080>. Aparece "Hello World !", e o terminal mostra o log de acesso do nginx. Use `Ctrl+C` para parar.

**As camadas da imagem.**

```bash
docker history ex-simple-build
```

Cada linha é uma **camada**. A mais recente fica no topo: é o seu `RUN`, e ocupa só alguns bytes. As de baixo vêm da imagem base do nginx.

**O conteúdo está dentro da imagem.**
Mude o texto do `echo` no `Dockerfile` (por exemplo, para `<h1>Versão 2</h1>`), reconstrua com o mesmo `-t` e rode de novo:

```bash
docker build -t ex-simple-build .
docker run --rm -p 8080:80 ex-simple-build
```

A página mudou, mas só porque você reconstruiu a imagem. Guarde essa ideia: o que foi colocado na imagem só muda com um novo build.

**Checkpoint:** o site abre em `localhost:8080` e você sabe explicar o que fazem o `-t` e o `.` no `docker build`.

---

## Passo 2 — Configurando o build: `LABEL`, `ARG` e `ENV`

**Conceitos:** metadados (`LABEL`), argumento de build (`ARG`), variável de ambiente (`ENV`), `--build-arg`, `docker inspect`.

```bash
cd ..
cd 02-arg-env
```

Crie o `Dockerfile`:

```dockerfile
FROM debian:13-slim
LABEL maintainer="seu-nome <seu-email@exemplo.com>"

ARG S3_BUCKET=files
ENV S3_BUCKET=${S3_BUCKET}
```

| Instrução | Para que serve | Valor disponível |
|---|---|---|
| `LABEL` | Metadados da imagem (mantenedor, versão...) | Na imagem (consultável com `docker inspect`) |
| `ARG` | Valor que você informa na hora do `docker build` (`--build-arg`) | Só enquanto a imagem está sendo construída |
| `ENV` | Variável de ambiente | Durante o build e também depois, com o container rodando |

Ou seja, o `ARG` existe em um único momento (o build), enquanto o `ENV` existe nos dois: o build e a execução do container. O padrão `ARG` + `ENV` serve para receber um valor no build e deixá-lo disponível para o programa que vai rodar dentro do container.

Construa e confira o valor dentro do container:

```bash
docker build -t ex-build-arg .
docker run --rm ex-build-arg bash -c 'echo $S3_BUCKET'
```

Saída esperada: `files` (o valor padrão do `ARG`).

> Repare nas aspas simples: elas impedem que o seu terminal expanda o `$S3_BUCKET`. Quem expande a variável é o `bash` de dentro do container.

Agora informe outro valor no build:

```bash
docker build --build-arg S3_BUCKET=myapp -t ex-build-arg .
docker run --rm ex-build-arg bash -c 'echo $S3_BUCKET'
```

Saída esperada: `myapp`.

Os `LABEL` podem ser lidos depois, direto da imagem:

```bash
docker inspect --format '{{ index .Config.Labels "maintainer" }}' ex-build-arg
```

Deve aparecer o texto que você colocou no `LABEL`.

**O `ARG` sozinho não chega ao container.**
Apague a linha `ENV S3_BUCKET=${S3_BUCKET}` do `Dockerfile` e reconstrua:

```bash
docker build --build-arg S3_BUCKET=myapp -t ex-build-arg .
docker run --rm ex-build-arg bash -c 'echo $S3_BUCKET'
```

A saída vem vazia: o `ARG` só existe durante o build. Coloque a linha do `ENV` de volta e reconstrua.

**O `ENV` pode ser trocado na hora de rodar.**

```bash
docker run --rm -e S3_BUCKET=outro ex-build-arg bash -c 'echo $S3_BUCKET'
```

Aparece `outro`. Resumindo: o `ARG` é decidido no build, e o `ENV` pode ser sobrescrito no `docker run` (`-e`).

> Segredos: não coloque senhas em `ARG` nem em `ENV`. Ambos ficam visíveis em `docker history` e `docker inspect`.

**Checkpoint:** você mostrou `files` e `myapp` com o mesmo Dockerfile e explica por que o `ARG` sozinho deu vazio.

---

## Passo 3 — Colocando arquivos na imagem: `COPY` e `RUN`

**Conceitos:** `COPY`, ordem das camadas, cache de build.

```bash
cd ..
cd 03-copy
```

Crie o `index.html`:

```html
<meta charset="utf-8">
<a href="conteudo.html">Conteúdo do site</a>
```

Crie o `Dockerfile`:

```dockerfile
FROM nginx:1.28-alpine
LABEL maintainer="seu-nome <seu-email@exemplo.com>"

RUN echo '<meta charset="utf-8"><h1>Sem conteúdo</h1>' > /usr/share/nginx/html/conteudo.html
COPY *.html /usr/share/nginx/html/
```

- `COPY` copia arquivos da sua pasta (o contexto de build) para dentro da imagem. Aqui, todo `*.html`.
- O `RUN` cria um `conteudo.html` "de reserva" dentro da imagem.

> Existe também o `ADD`, que faz o mesmo que o `COPY` e ainda aceita URLs e descompacta arquivos. Use `COPY` sempre que possível; o `ADD` só quando precisar desses extras.

```bash
docker build -t ex-build-copy .
docker run --rm -p 8080:80 ex-build-copy
```

Abra <http://localhost:8080> e clique no link "Conteúdo do site". Aparece "Sem conteúdo", o texto criado pelo `RUN`. Pare com `Ctrl+C`.

**Quem vence, o `RUN` ou o `COPY`?**
Crie na pasta o arquivo `conteudo.html`:

```html
<meta charset="utf-8">
<h1>Agora sim, conteúdo de verdade!</h1>
```

Reconstrua e rode de novo:

```bash
docker build -t ex-build-copy .
docker run --rm -p 8080:80 ex-build-copy
```

Clique no link outra vez: agora aparece o seu texto. As instruções rodam em ordem, e o `COPY` (depois do `RUN`) sobrescreveu o arquivo que o `RUN` tinha criado. Pare com `Ctrl+C`.

**O cache de build.**
Rode o build de novo, sem mudar nada:

```bash
docker build -t ex-build-copy .
```

Os passos aparecem como `CACHED` e o build termina quase na hora: o Docker reaproveitou as camadas que não mudaram, o chamado **cache de build**. Agora edite o `conteudo.html` (qualquer mudança) e reconstrua:

```bash
docker build -t ex-build-copy .
```

O `FROM` e o `RUN` continuam em cache, e só o `COPY` (e o que vem depois dele) é refeito. Cada instrução é uma camada, e o Docker só refaz a partir da primeira camada que mudou. Por isso, em Dockerfiles reais, o que muda pouco vai no começo e o que muda muito (o seu código) vai no final.

**Checkpoint:** você viu os dois textos ("Sem conteúdo" e o seu) e entende por que o segundo build foi mais rápido.

---

## Passo 4 — Preparando a imagem para rodar: `USER`, `VOLUME`, `WORKDIR`, `EXPOSE`, `ENTRYPOINT` e `CMD`

**Conceitos:** usuário sem privilégios, volume declarado na imagem, `ENTRYPOINT` + `CMD`, `EXPOSE`, containers compartilhando volume.

```bash
cd ..
cd 04-servidor
```

Aqui o container roda um pequeno servidor web em Python. Crie o `index.html`:

```html
<p>Hello from python</p>
```

Crie o `run.py` (um servidor HTTP que também grava um arquivo de log):

```python
import getpass
import http.server
import logging
import socketserver

PORT = 8000


class MyHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        logging.info(
            "%s - - [%s] %s",
            self.client_address[0],
            self.log_date_time_string(),
            format % args,
        )


logging.basicConfig(
    filename="/log/http-server.log",
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger().addHandler(logging.StreamHandler())

logging.info("inicializando...")
with socketserver.TCPServer(("", PORT), MyHTTPHandler) as httpd:
    logging.info("escutando a porta: %s", PORT)
    logging.info("usuário: %s", getpass.getuser())
    httpd.serve_forever()
```

O log vai para dois lugares: a saída do container (`docker logs`) e o arquivo `/log/http-server.log`.

Crie o `Dockerfile`:

```dockerfile
FROM python:3.13-slim
LABEL maintainer="seu-nome <seu-email@exemplo.com>"

RUN useradd www && \
    mkdir /app && \
    mkdir /log && \
    chown www /log

USER www
VOLUME /log
WORKDIR /app
EXPOSE 8000

ENTRYPOINT ["python"]
CMD ["run.py"]
```

| Instrução | O que faz neste Dockerfile |
|---|---|
| `RUN useradd ...` | Cria o usuário `www`, as pastas `/app` e `/log` e entrega o `/log` ao `www` |
| `USER www` | A partir daqui, o `RUN` do build e o processo do container não rodam como root (boa prática de segurança) |
| `VOLUME /log` | Faz o container criar um volume para `/log`, que pode ser compartilhado com outros containers |
| `WORKDIR /app` | Define a pasta onde o processo principal executa (é por isso que ele acha o `run.py`) |
| `EXPOSE 8000` | Documenta a porta que o servidor usa. Não publica nada |
| `ENTRYPOINT ["python"]` | O programa fixo do container |
| `CMD ["run.py"]` | O argumento padrão do programa (pode ser trocado no `docker run`) |

> O `run.py` não é copiado para a imagem: ele chega ao container por **bind mount** (próximo comando). Assim você edita o código na sua máquina e só reinicia o container, sem rebuild.

Construa a imagem e suba o container:

```bash
docker build -t ex-servidor .
docker run -d --name servidor -v "$(pwd)":/app -p 8080:8000 ex-servidor
```

- `-d` roda em segundo plano e `--name servidor` dá um nome ao container (vamos usá-lo adiante).
- `-v "$(pwd)":/app` monta a pasta atual em `/app`. No PowerShell, use `-v "${PWD}:/app"`.

Abra <http://localhost:8080>. Aparece "Hello from python". Veja o log do container:

```bash
docker logs servidor
```

Você deve ver `inicializando...`, `escutando a porta: 8000`, `usuário: www` e as requisições que o navegador fez.

**O container não roda como root (`USER`).**
O log já mostrou `usuário: www`. Confirme por dentro do container:

```bash
docker exec servidor whoami
```

Resposta: `www`. Sem a linha `USER www`, a resposta seria `root`.

**Outro container lê o log do primeiro (`VOLUME`).**

```bash
docker run --rm --volumes-from servidor debian:13-slim cat /log/http-server.log
```

O `cat` mostra o mesmo log do servidor, lido por um container totalmente diferente: o `--volumes-from` herda o volume do `/log`. Veja de onde cada pasta vem:

```bash
docker inspect servidor --format '{{ range .Mounts }}{{ .Type }} -> {{ .Destination }}{{ "\n" }}{{ end }}'
```

Saída esperada: `bind -> /app` (sua pasta) e `volume -> /log` (criado pelo `VOLUME`).

**`ENTRYPOINT` fixo, `CMD` trocável.**
O que você escrever depois do nome da imagem substitui o `CMD`, e o `ENTRYPOINT` continua `python`:

```bash
docker run --rm ex-servidor --version
docker run --rm ex-servidor -c "print('oi do container')"
```

O primeiro mostra a versão do Python e o segundo imprime `oi do container`. Nenhum dos dois sobe o servidor, porque o `run.py` (o `CMD`) foi substituído.

**O `EXPOSE` só documenta.**
Suba outro container sem usar `-p` e com `-P` (maiúsculo), que publica as portas declaradas no `EXPOSE` em portas aleatórias:

```bash
docker run -d --rm --name teste -v "$(pwd)":/app -P ex-servidor
docker port teste
```

A saída mostra algo como `8000/tcp -> 0.0.0.0:32768`. Abra `http://localhost:` com a porta que apareceu. Depois pare o container:

```bash
docker stop teste
```

**Bônus: edite o HTML sem reiniciar.**
Edite o `index.html` na sua máquina e atualize o navegador em `localhost:8080`. Mudou na hora, porque a pasta está montada em `/app` (bind mount).

**Checkpoint:** o servidor responde, `whoami` retorna `www`, e o `--volumes-from` mostrou o log do servidor em outro container.

---

## Passo 5 — Encerramento

Remova o container do servidor, as imagens que você construiu e os volumes anônimos que sobraram (o do `/log`):

```bash
docker rm -f servidor
docker rmi ex-simple-build ex-build-arg ex-build-copy ex-servidor
docker volume prune
```

> O `docker volume prune` pede confirmação e lista o que vai apagar. Leia a lista antes de confirmar.