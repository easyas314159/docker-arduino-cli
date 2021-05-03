# Arduino CLI with `{{core.package}}:{{core.arch}}` Preinstalled

For more details on using these images see [{{repo}}](https://hub.docker.com/r/{{repo}})

## Tags

Tags use the following format:

```
[core_version]-[arduino_cli_tag]
```
* `core_version` - The version of the core
* `arduino_cli_tag` - The [{{repo}}](https://hub.docker.com/r/{{repo}}) base tag

### Example Tags
{{#max_base_versions}}

#### Version `{{core.package}}:{{core.arch}}@{{core.max_version}}` with `{{max_arduino_cli_version}}-{{.}}`
```
{{core.repo}}:{{core.max_version}}-{{max_arduino_cli_version}}-{{.}}
```
{{/max_base_versions}}

## Supported `{{core.package}}:{{core.arch}}` Versions

Core Version | Core Version Tag
--- | ---
{{#core.tags}}
`{{core.package}}:{{core.arch}}@{{key}}` |{{#value}} `{{.}}`{{/value}}
{{/core.tags}}
