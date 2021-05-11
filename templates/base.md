# Arduino CLI Docker Images

Pre-built [`arduino-cli`](https://arduino.github.io/arduino-cli/) docker images with support for [CircleCI](https://circleci.com/) maintained by [Solarbotics](https://solarbotics.com).

None of the tags in this repository include any Arduino cores. To bootstrap your development consider using one of our other repositories with [preinstalled cores](#images-with-preinstalled-cores)

## Usage

### Building locally

#### Starting the docker container

```
docker run --rm -it -w ~/project -v $(pwd):~/project solarbotics/arduino-cli:{{max_arduino_cli_version}}-python3 bash
```

#### Using the `arduino-cli`

The `arduino-cli` has published an excellent [Getting Started](https://arduino.github.io/arduino-cli/latest/getting-started/) document with detailed examples, and provides documentation pages for all available [`arduino-cli` sub commands](https://arduino.github.io/arduino-cli/latest/commands/arduino-cli/)

### With CircleCI

#### Example Project

Consider an example project `MySketch` that run on the Arduino Uno and depends on the `Servo` library. The git repository would look like this:

* .circleci
  * config.yml
* MySketch
  * MySketch.ino

##### Example `.circleci/config.yml`

```
version: 2.1

jobs:
  build:
    docker:
      - image: solarbotics/arduino-cli:{{max_arduino_cli_version}}-python3

    steps:
      - checkout

      - run:
          name: Install core
          command: arduino-cli core install arduino:avr

      - run:
          name: Install library
          command: arduino-cli lib install Servo

      - run:
          name: Build sketch
          command: arduino-cli compile --output-dir build --fqbn arduino:avr:uno MySketch

      - store_artifacts:
          path: build
```

## Available Versions

### With preinstalled cores

Additional docker repositories are available with preinstalled versions of the latest cores.

{{#core}}
* `{{package}}:{{arch}}` - [{{repo}}](https://hub.docker.com/r/{{repo}})
{{/core}}

### `arduino-cli`

Arduino CLI Version | Version Tags
--- | ---
{{#arduino_cli_versions}}
{{key}} |{{#value}} `{{.}}`{{/value}}
{{/arduino_cli_versions}}

### Base Images
{{#base}}

#### `{{name}}`

Repository: [{{image}}](https://hub.docker.com/r/{{image}})

{{name}} Version | Version Tags
--- | ---
{{#tags}}
{{key}} |{{#value}} `{{name}}{{.}}`{{/value}}
{{/tags}}
{{/base}}
