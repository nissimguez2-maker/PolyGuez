FROM python:3.9

COPY . /home
WORKDIR /home

ENV PYTHONPATH=.

RUN pip3 install -r requirements.txt
