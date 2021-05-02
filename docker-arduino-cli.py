import sys
import json
import logging
import argparse

from itertools import product

import docker
import semver
import requests

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

	logging.basicConfig(
		stream=sys.stderr,
		level=logging.DEBUG if args.debug else logging.INFO,
		format="%(asctime)s %(name)s %(levelname)s - %(message)s"
	)
	logging.getLogger('py.warnings').setLevel(logging.ERROR)
	logging.captureWarnings(True)

	client = docker.from_env()
	client.login(username=args.username, password=args.password, reauth=True)

	args.command(client, args)

def get_repository_tags(repo):
	try:
		return {t['name'] for t in requests.get('https://registry.hub.docker.com/v1/repositories/%s/tags' % repo).json()}
	except:
		return set()

def build_base(client, args):
	# Get existing repo tags
	existing_tags = get_repository_tags(args.repo)

	with open(args.arduino_cli_versions, 'r') as f:
		arduino_cli_versions = json.load(f)
	arduino_cli_version_tags = version_tags(arduino_cli_versions)

	with open(args.base_versions, 'r') as f:
		base_versions = json.load(f)

	output_tags = {}

	for base_version in base_versions:
		base_version_tags = version_tags(base_version['versions'])

		for base_version_tag, arduino_cli_version_tag in product(base_version_tags, arduino_cli_version_tags):
			tags = [(t[0], base_version['name']+t[1]) for t in product(
				arduino_cli_version_tags[arduino_cli_version_tag],
				base_version_tags[base_version_tag]
			)]
			tags = ['-'.join([f for f in t if f]) for t in tags]

			output_tags[tags[0]] = tags

			if tags[0] in existing_tags:
				logging.info('Skipping %s', tags[0])
				# TODO: Double check other tags exist
				continue

			buildargs = {
				'MAINTAINER_EMAIL': args.maintainer,
				'ARDUINO_CLI_VERSION': arduino_cli_version_tag,
				'BASE_IMAGE': base_version['image'] + ':' + base_version_tag,
			}

			if args.dryrun:
				logging.info('Building %s', tags[0])
				continue

			build_image(client, args.repo, buildargs, tags, path='base')

		if not args.dryrun:
			prune(client)

	json.dump(output_tags, sys.stdout)

def build_core(client, args):
	pass

def version_tags(versions):
	tags = {}
	max_versions = {}
	for v in versions:
		tags[v] = [v]

		parent = v
		while parent:
			parent, _, _ = parent.rpartition('.')
			if not parent or parent == '0':
				continue

			if parent in max_versions:
				max_versions[parent] = semver.max_ver(max_versions[parent], v)
			else:
				max_versions[parent] = v

	for key, value in max_versions.items():
		tags[value].append(key)

	return tags

def broadcast_tags(*args):
	return ['-'.join(t) for t in product(*args)]

def build_image(client, repo, buildargs, tags, **kwargs):
	logging.info('Building %s', tags[0])
	logging.debug('buildargs: %s', buildargs)
	logging.debug('tags: %s', tags)

	image, logs = client.images.build(buildargs=buildargs, **kwargs)
	for l in logs:
		logging.debug(l)

	for tag in tags:
		if not image.tag(repo, tag=tag):
			logging.warn('Failed to tag %s with %s', image.short_id, tag)
			continue

		logging.info('Pushing %s:%s', repo, tag)
		output = client.images.push(repo, tag=tag, stream=False)
		logging.debug(output)

	image.reload()
	logging.debug(image.tags)

def prune(client):
	client.containers.prune()
	client.volumes.prune()
	client.images.prune()

if __name__ == '__main__':
	main()
