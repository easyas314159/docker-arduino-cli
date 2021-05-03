# Arduino CLI Docker Images

Pre-built [`arduino-cli`](https://arduino.github.io/arduino-cli/) docker images with support for [CircleCI](https://circleci.com/) maintained by [Solarbotics](https://solarbotics.com).

None of the tags in this repository include any Arduino cores. To bootstrap your development consider using one of our other repositories with [preinstalled cores](#images-with-preinstalled-cores)

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
