FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY data data
RUN python data/generate_data.py
ENV PORT=8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port $PORT
