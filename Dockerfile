FROM python:3.11-slim

WORKDIR /app

RUN pip install flask gunicorn

COPY update_server.py .
COPY manifest.json .
RUN mkdir -p packages logs

EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "update_server:app"]
