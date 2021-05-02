import re
import sys
import json
import logging
import argparse

from itertools import product
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import docker
import semver
import requests
import dateutil.parser

PATTERN_SEMVER = re.compile('^v?(\d+\.\d+\.\d+)$')
ARDUINO_PACKAGE_URL = 'http://downloads.arduino.cc/packages/package_index.json'

def get_cli_arguments():
	parser = argparse.ArgumentParser()

	parser.add_argument('--debug', default=False, action='store_true')
	parser.add_argument('--dryrun', default=False, action='store_true')

	subparser = parser.add_subparsers()
	subparser.required = True

	parser_build = subparser.add_parser('build')

	parser_build.add_argument('-u', '--username', required=True)
	parser_build.add_argument('-p', '--password', required=True)

	parser_build.add_argument('-r', '--repo', default='solarbotics/arduino-cli')
	parser_build.add_argument('-m', '--maintainer', default='support@solarbotics.com')

	subparser_build = parser_build.add_subparsers()
	subparser_build.required = True

	parser_base = subparser_build.add_parser('base')
	parser_base.set_defaults(command=build_base)

	parser_base.add_argument('matrix')

	parser_core = subparser_build.add_parser('core')
	parser_core.set_defaults(command=build_core)

	parser_core.add_argument('--index-url', required=True)
	parser_core.add_argument('--package', required=True)
	parser_core.add_argument('--platform', required=True)

	parser_core.add_argument('base_tags')

	parser_update = subparser.add_parser('update')
	parser_update.set_defaults(command=update)

	parser_update.add_argument('-t', '--token', required=True)

	parser_update.add_argument('matrix')

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

	args.command(args)

def get_repository_tags(repo):
	try:
		return {t['name'] for t in requests.get('https://registry.hub.docker.com/v1/repositories/%s/tags' % repo).json()}
	except:
		return set()

def build_base(args):
	# Get existing repo tags
	existing_tags = get_repository_tags(args.repo)

	with open(args.matrix, 'r') as f:
		matrix = json.load(f)

	arduino_cli_version_tags = version_tags(matrix['arduino-cli'])
	base_versions = matrix['base']

	client = docker.from_env()
	client.login(username=args.username, password=args.password, reauth=True)

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

			if args.dryrun:
				logging.info('Building %s', tags[0])
				continue

			buildargs = {
				'MAINTAINER_EMAIL': args.maintainer,
				'ARDUINO_CLI_VERSION': arduino_cli_version_tag,
				'BASE_IMAGE': base_version['image'] + ':' + base_version_tag,
			}

			build_image(client, args.repo, buildargs, tags, path='base')

			client.containers.prune()
			client.volumes.prune()

		if not args.dryrun:
			client.images.prune()

	json.dump(output_tags, sys.stdout)

def build_core(args):
	with open(args.base_tags, 'r') as f:
		base_version_tags = json.load(f)

	packages = requests.get(args.index_url).json()['packages']

	for package in packages:
		if package['name'] == args.package:
			break
	else:
		logging.error('Unable to locate package %s', args.package)
		sys.exit(1)

	platform_version_tags = version_tags([p['version'] for p in package['platforms'] if p['architecture'] == args.platform])

	repo_core = args.repo + '-' + args.package
	if args.package != args.platform:
		repo_core += '-' + args.platform
	existing_tags = get_repository_tags(repo_core)

	client = docker.from_env()
	client.login(username=args.username, password=args.password, reauth=True)

	output_tags = {}
	for base_version_tag in base_version_tags:
		for platform_version_tag in platform_version_tags:
			tags = broadcast_tags(
				platform_version_tags[platform_version_tag],
				base_version_tags[base_version_tag]
			)

			output_tags[tags[0]] = tags

			if tags[0] in existing_tags:
				logging.info('Skipping %s', tags[0])
				# TODO: Double check other tags exist
				continue

			if args.dryrun:
				logging.info('Building %s', tags[0])
				continue

			buildargs = {
				'MAINTAINER_EMAIL': args.maintainer,
				'BASE_IMAGE': args.repo + ':' + base_version_tag,
				'ARDUINO_CORE': args.package + ':' + args.platform + '@' + platform_version_tag,
			}

			if args.index_url != ARDUINO_PACKAGE_URL:
				buildargs['ARDUINO_ADDITIONAL_URLS'] = args.index_url

			build_image(client, repo_core, buildargs, tags, path='core')

			client.containers.prune()
			client.volumes.prune()

		if not args.dryrun:
			client.images.prune()

	json.dump(output_tags, sys.stdout)

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

def update(args):
	with open(args.matrix, 'r') as f:
		matrix = json.load(f, object_pairs_hook=OrderedDict)

	now = datetime.now(timezone.utc)
	after = now - timedelta(days=365)

	arduino_cli_versions = get_version_targets(args.token, 'arduino', 'arduino-cli', after)

	matrix['arduino-cli'], changed = update_versions(matrix['arduino-cli'], arduino_cli_versions)
	if not changed:
		base_versions = {
			'node': get_version_targets(args.token, 'nodejs', 'node', after),
			'python': get_version_targets(args.token, 'python', 'cpython', after)
		}

		for base in matrix['base']:
			if not base['name'] in base_versions:
				continue

			base['versions'], changed = update_versions(base['versions'], base_versions[base['name']])
			if changed:
				break

	if not changed:
		sys.exit(1)

	if args.dryrun:
		json.dump(matrix, sys.stdout, indent=4)
	else:
		with open(args.matrix, 'w') as f:
			json.dump(matrix, f, indent=2)

def get_version_targets(token, owner, name, after, limit=100):
	headers = {'Authorization': 'bearer %s' % token}
	query = '''{{
		repository(name: "{name}", owner: "{owner}") {{
			refs(refPrefix: "refs/tags/", orderBy: {{field: TAG_COMMIT_DATE, direction: DESC}}, first: {limit:d}) {{
				nodes {{
					name
					target {{
						... on Tag {{
							target {{
								... on Commit {{
									authoredDate
									committedDate
									pushedDate
								}}
							}}
						}}
					}}
				}}
	        }}
		}}
	}}'''.format(owner=owner, name=name, limit=limit)

	available = set()

	results = requests.post('https://api.github.com/graphql', json={'query': query}, headers=headers).json()
	for node in results['data']['repository']['refs']['nodes']:
		m = PATTERN_SEMVER.match(node['name'])
		if not m:
			continue

		try:
			target = node['target']['target']
			for key in ['pushedDate', 'committedDate', 'authoredDate']:
				if not key in target:
					continue

				if not target[key]:
					continue

				pushed = dateutil.parser.parse(target[key])
				break
			else:
				continue
		except:
			continue

		if pushed < after:
			continue

		available.add(m.group(1))

	return available

def update_versions(current, desired):
	changed = False

	updated = {v for v in current if v in desired}
	if len(current) != len(updated):
		changed = True

	desired = list(sorted(desired - updated, key=semver.VersionInfo.parse))
	if desired:
		updated.add(desired[-1])
		changed = True

	return list(sorted(updated, key=semver.VersionInfo.parse)), changed

if __name__ == '__main__':
	main()
