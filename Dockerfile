ARG ARDUINO_CLI_VERSION
ARG BASE_IMAGE
ARG ARDUINO_CORE_URL
ARG ARDUINO_CORE

FROM circleci/golang:1.16 AS build
ARG ARDUINO_CLI_VERSION

USER root

RUN go install github.com/go-task/task/v3/cmd/task@latest
RUN git clone --depth 1 --branch $ARDUINO_CLI_VERSION https://github.com/arduino/arduino-cli.git /arduino-cli

WORKDIR /arduino-cli
RUN task build && task test-unit

FROM $BASE_IMAGE AS arduino_cli
LABEL maintainer="support@solarbotics.com"
COPY --from=build /arduino-cli/arduino-cli /usr/local/bin
RUN arduino-cli config init

FROM arduino_cli AS arduino_cli_core
ARG ARDUINO_CORE_URL
ARG ARDUINO_CORE

RUN arduino-cli config add board_manager.additional_urls $ARDUINO_CORE_URL
RUN arduino-cli core install $ARDUINO_CORE
