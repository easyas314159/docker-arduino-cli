import argparse

import docker
import semver

def get_cli_arguments():
	parser = argparse.ArgumentParser()

	parser.add_argument('-u', '--username', required=True)
	parser.add_argument('-p', '--password', required=True)

	parser.add_argument('--debug', default=False, action='store_true')
	parser.add_argument('--dryrun', default=False, action='store_true')

	subparser = parser.add_subparsers()
	subparser.required = True

	parser_build = subparser.add_parser('build')
	parser_build.add_argument('-r', '--repo', default='solarbotics/arduino-cli')
	parser_build.add_argument('-m', '--maintainer', default='support@solarbotics.com')

	subparser_build = parser_build.add_subparsers()
	subparser_build.required = True

	parser_base = subparser_build.add_parser('base')
	parser_base.set_defaults(command=build_base)

	parser_base.add_argument('arduino_cli_versions')
	parser_base.add_argument('base_versions')

	parser_core = subparser_build.add_parser('core')
	parser_core.set_defaults(command=build_core)

	return parser.parse_args()

def main():
	args = get_cli_arguments()

	client = docker.from_env()
	client.login(username=args.username, password=args.password, reauth=True)

	args.command(client, args)

def build_base(client, args):
	pass

def build_core(client, args):
	pass

if __name__ == '__main__':
	main()
