FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install -U uv && uv pip install -r requirements.txt

CMD ["python", "bot.py"]