FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt
COPY pixoo/ pixoo/
EXPOSE 9100
CMD ["python", "-m", "pixoo.server", "--http", "--port", "9100"]
