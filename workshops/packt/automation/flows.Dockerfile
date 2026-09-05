FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY ./automation/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Source code is bind-mounted into /app at runtime via the compose file so
# attendees can edit flows live without rebuilding the image. We still copy
# it here so the image works standalone too.
COPY ./automation/ /app/

CMD ["python", "/app/serve.py"]
