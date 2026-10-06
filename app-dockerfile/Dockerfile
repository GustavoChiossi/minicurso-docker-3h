# Imagem base
FROM python:3.12-slim

# Diretório de trabalho
WORKDIR /app

# Variável de ambiente
ENV NOME=Docker

# Copia primeiro as dependências
COPY requirements.txt .

# Instala as dependências
RUN pip install -r requirements.txt

# Cria um usuário para executar a aplicação
RUN useradd --create-home appuser

# Copia o restante da aplicação
COPY app.py .

# Executa o container como usuário comum
USER appuser

# Documenta a porta usada pela aplicação
EXPOSE 5000

# Define o programa principal
ENTRYPOINT ["python"]

# Define o argumento padrão
CMD ["app.py"]