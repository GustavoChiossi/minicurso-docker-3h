from flask import Flask
import os

app = Flask(__name__)

@app.route("/")
def home():
    nome = os.getenv("NOME", "Docker")
    return f"Olá, {nome}! Aplicação rodando dentro do Docker."

@app.route("/status")
def status():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)