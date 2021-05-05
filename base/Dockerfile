ARG ARDUINO_CLI_VERSION
ARG BASE_IMAGE
ARG MAINTAINER_EMAIL

FROM circleci/golang:1.16 AS build
ARG ARDUINO_CLI_VERSION

USER root

RUN go install github.com/go-task/task/v3/cmd/task@latest
RUN git clone --depth 1 --branch $ARDUINO_CLI_VERSION https://github.com/arduino/arduino-cli.git /arduino-cli

WORKDIR /arduino-cli
RUN task build && task test-unit

FROM $BASE_IMAGE
ARG MAINTAINER_EMAIL
LABEL maintainer=$MAINTAINER_EMAIL
COPY --from=build /arduino-cli/arduino-cli /usr/local/bin
RUN arduino-cli config init
