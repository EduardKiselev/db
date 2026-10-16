FROM python:3.11-slim

WORKDIR /app

# Копируем локальные пакеты
COPY packages/ ./packages/

# Копируем requirements.txt
COPY requirements.txt .

# Устанавливаем из локальных файлов
# RUN pip install --no-cache-dir --no-index --find-links=./packages -r requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Открываем порт
EXPOSE 5000

# Запускаем приложение
CMD ["python", "app.py"]