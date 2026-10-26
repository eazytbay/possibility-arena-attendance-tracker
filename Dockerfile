FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -r app && chown -R app /srv
USER app
EXPOSE 8000
CMD ["sh","-c","flask --app app:create_app db upgrade && gunicorn -w 2 -b 0.0.0.0:8000 'app:create_app()'"]
