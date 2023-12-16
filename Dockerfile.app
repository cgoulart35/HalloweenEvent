FROM python:3.9.7 AS stage

WORKDIR /HalloweenEvent

RUN apt-get update
RUN apt-get install -y openssl

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

RUN openssl genrsa -des3 -passout pass:app -out server.pass.key 2048
RUN openssl rsa -passin pass:app -in server.pass.key -out server.key
RUN rm server.pass.key
RUN openssl req -new -key server.key -out server.csr -subj "/C=US/CN=HalloweenEventWebApp"
RUN openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt

##########################
# develop
##########################

FROM stage AS dev

ENTRYPOINT ["python3", "-m", "debugpy", "--wait-for-client", "--listen", "0.0.0.0:5678", "app.py"]

##########################
# production
##########################

FROM stage AS prod

ENTRYPOINT ["python3", "-m", "debugpy", "--listen", "0.0.0.0:5678", "app.py"]