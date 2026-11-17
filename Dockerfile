FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py adapters.py restore_catalog.py pins.py readiness.py .
COPY templates templates
COPY static static
CMD ["python","-m","flask","--app","app","run","--host=0.0.0.0","--port=8000"]
