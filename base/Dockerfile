ARG ARDUINO_CLI_VERSION
ARG BASE_IMAGE
ARG MAINTAINER_EMAIL

FROM circleci/golang:1.14.7 AS build

USER root
RUN env GO111MODULE=on go get -u github.com/go-task/task/v3/cmd/task@latest

FROM build as arduino_lint

WORKDIR /arduino-lint
RUN git clone --depth 1 --branch $(curl --silent https://api.github.com/repos/arduino/arduino-lint/releases/latest | jq -r ".tag_name") https://github.com/arduino/arduino-lint.git /arduino-lint
RUN task build

FROM build as arduino_cli
ARG ARDUINO_CLI_VERSION

WORKDIR /arduino-cli
RUN git clone --depth 1 --branch $ARDUINO_CLI_VERSION https://github.com/arduino/arduino-cli.git /arduino-cli
RUN task build

FROM $BASE_IMAGE
ARG MAINTAINER_EMAIL
LABEL maintainer=$MAINTAINER_EMAIL

COPY --from=arduino_lint /arduino-lint/arduino-lint /usr/local/bin
COPY --from=arduino_cli /arduino-cli/arduino-cli /usr/local/bin
