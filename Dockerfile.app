FROM python:3.12 AS stage

WORKDIR /HalloweenEvent
ENV PYTHONPATH=/HalloweenEvent

RUN apt-get update \
    && apt-get install -y openssl \
    && apt-get install libgl1 -y

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY . .

RUN openssl genrsa -des3 -passout pass:app -out server.pass.key 2048
RUN openssl rsa -passin pass:app -in server.pass.key -out server.key
RUN rm server.pass.key
RUN openssl req -new -key server.key -out server.csr -subj "/C=US/CN=HalloweenEventWebApp"
RUN openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt

# Build-stamped version: short SHA in CI (via build-arg), "dev" for local/QA builds.
# Kept last in the shared stage so a new SHA doesn't bust the pip/cert layer cache.
ARG APP_VERSION=dev
ENV VERSION=$APP_VERSION

##########################
# develop
##########################

FROM stage AS dev

ENTRYPOINT ["python3", "-m", "debugpy", "--wait-for-client", "--listen", "0.0.0.0:5678", "src/app/app.py"]

##########################
# production
##########################

FROM stage AS prod

ENTRYPOINT ["python3", "src/app/app.py"]