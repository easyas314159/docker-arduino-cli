import os
import re
import sys
import json
import time
import logging
import argparse
import subprocess

from itertools import product, chain
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone

import docker
import semver
import chevron
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

	parser_build.add_argument('-f', '--force', default=False, action='store_true')
	parser_build.add_argument('-q', '--quick', default=False, action='store_true')

	parser_build.add_argument('-r', '--repo', default='solarbotics/arduino-cli')
	parser_build.add_argument('-m', '--maintainer', default='support@solarbotics.com')

	subparser_build = parser_build.add_subparsers()
	subparser_build.required = True

	parser_base = subparser_build.add_parser('base')
	parser_base.set_defaults(command=build_base)

	parser_base.add_argument('--base', required=True)
	parser_base.add_argument('matrix')

	parser_core = subparser_build.add_parser('core')
	parser_core.set_defaults(command=build_core)

	parser_core.add_argument('--package', required=True)
	parser_core.add_argument('--platform', required=True)

	parser_core.add_argument('matrix')
	parser_core.add_argument('base_tags')


	parser_docs = subparser_build.add_parser('docs')
	parser_docs.set_defaults(command=build_docs)

	parser_docs.add_argument('-o', '--output', required=True)
	parser_docs.add_argument('matrix')

	parser_update = subparser.add_parser('update')
	parser_update.set_defaults(command=update)

	parser_update.add_argument('-t', '--token', required=True)
	parser_update.add_argument('-d', '--days', type=int, default=365)
	parser_update.add_argument('-l', '--limit', type=int, default=1)

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

def get_repository_tags(repo, retry_delay=1.0):
	while True:
		rsp = requests.get('https://registry.hub.docker.com/v1/repositories/%s/tags' % repo)
		if rsp.ok:
			return {t['name'] for t in rsp.json()}

		if rsp.status_code == 404:
			return set()

		if rsp.status_code == 502:
			time.sleep(retry_delay)
			continue

		rsp.raise_for_status()

def build_base(args):
	with open(args.matrix, 'r') as f:
		matrix = json.load(f)

	arduino_cli = matrix['arduino-cli']
	base = matrix['base'][args.base]

	arduino_cli_version_tags = version_tags(arduino_cli['versions'])
	base_version_tags = version_tags(base['versions'])

	# Get existing repo tags
	existing_tags = set() if args.force else get_repository_tags(args.repo)
	existing_base_tags = get_repository_tags(base['image'])

	client = docker.from_env()
	client.login(username=args.username, password=args.password, reauth=True)

	output_tags = {}
	for base_version_tag, arduino_cli_version_tag in product(base_version_tags, arduino_cli_version_tags):
		tags = [(t[0], args.base+t[1]) for t in product(
			arduino_cli_version_tags[arduino_cli_version_tag],
			base_version_tags[base_version_tag]
		)]
		tags = ['-'.join([f for f in t if f]) for t in tags]

		if not base_version_tag in existing_base_tags:
			logging.info(
				'Skipping %s due to missing base %s:%s',
				tags[0],
				base['image'],
				base_version_tag
			)
			continue

		if args.quick:
			tags = tags[:1]

		output_tags[tags[0]] = tags

		if tags[0] in existing_tags:
			logging.info('Skipping %s', tags[0])
			try:
				ensure_tags(client, args.repo, tags, existing_tags)
			except Exception as ex:
				logging.exception(ex)
				logging.error('Tagging %s failed', tags[0])
			continue

		if args.dryrun:
			logging.info('Building %s', tags[0])
			continue

		buildargs = {
			'MAINTAINER_EMAIL': args.maintainer,
			'ARDUINO_CLI_VERSION': arduino_cli_version_tag,
			'BASE_IMAGE': base['image'] + ':' + base_version_tag,
		}

		try:
			build_image(client, args.repo, buildargs, tags, path='base')
		except Exception as ex:
			logging.exception(ex)
			logging.error('Building %s failed', tags[0])
			del output_tags[tags[0]]

			subprocess.run('docker system prune -af', shell=True, check=True, stdout=subprocess.DEVNULL)

		client.containers.prune()
		client.volumes.prune()

	json.dump(output_tags, sys.stdout)

def build_core(args):
	with open(args.matrix, 'r') as f:
		matrix = json.load(f)

	with open(args.base_tags, 'r') as f:
		base_version_tags = json.load(f)

	for core in matrix['core']:
		if core['package'] == args.package and core['arch'] == args.platform:
			break
	else:
		logging.error('Unable to locate package %s', args.package)
		sys.exit(1)

	platform_version_tags = version_tags(core['versions'])

	repo_core = args.repo + '-' + args.package
	if args.package != args.platform:
		repo_core += '-' + args.platform
	existing_tags = set() if args.force else get_repository_tags(repo_core)

	client = docker.from_env()
	client.login(username=args.username, password=args.password, reauth=True)

	output_tags = {}
	for base_version_tag in base_version_tags:
		for platform_version_tag in platform_version_tags:
			tags = broadcast_tags(
				platform_version_tags[platform_version_tag],
				base_version_tags[base_version_tag]
			)

			if args.quick:
				tags = tags[:1]

			output_tags[tags[0]] = tags

			if tags[0] in existing_tags:
				logging.info('Skipping %s', tags[0])
				try:
					ensure_tags(client, repo_core, tags, existing_tags)
				except Exception as ex:
					logging.exception(ex)
					logging.error('Tagging %s failed', tags[0])
				continue

			if args.dryrun:
				logging.info('Building %s', tags[0])
				continue

			buildargs = {
				'MAINTAINER_EMAIL': args.maintainer,
				'BASE_IMAGE': args.repo + ':' + base_version_tag,
				'ARDUINO_CORE': args.package + ':' + args.platform + '@' + platform_version_tag,
			}

			if core['index_url'] != ARDUINO_PACKAGE_URL:
				buildargs['ARDUINO_ADDITIONAL_URLS'] = core['index_url']

			try:
				build_image(client, repo_core, buildargs, tags, path='core')
			except Exception as ex:
				logging.exception(ex)
				logging.error('Building %s failed', tags[0])
				del output_tags[tags[0]]

				subprocess.run('docker system prune -af', shell=True, check=True, stdout=subprocess.DEVNULL)

			client.containers.prune()
			client.volumes.prune()

	json.dump(output_tags, sys.stdout)

def version_tags(versions):
	tags = {}
	max_versions = OrderedDict()
	for v in sorted(versions, key=semver.VersionInfo.parse, reverse=True):
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

		while True:
			logging.info('Pushing %s:%s', repo, tag)
			try:
				output = client.images.push(repo, tag=tag, stream=False)
				logging.debug(output)
				break
			except Exception as ex:
				logging.exception(ex)
				time.sleep(10.0)

	image.reload()
	logging.debug(image.tags)

def ensure_tags(client, repo, tags, existing):
	missing = {t for t in tags[1:] if not t in existing}

	if not missing:
		return

	logging.info('Pulling %s:%s', repo, tags[0])
	image = client.images.pull(repo, tag=tags[0])

	for tag in missing:
		if not image.tag(repo, tag=tag):
			logging.warn('Failed to tag %s with %s', image.short_id, tag)
			continue

		while True:
			logging.info('Pushing %s:%s', repo, tag)
			try:
				output = client.images.push(repo, tag=tag, stream=False)
				logging.debug(output)
				break
			except Exception as ex:
				logging.exception(ex)
				time.sleep(10.0)

def build_docs(args):
	with open(args.matrix, 'r') as f:
		matrix = json.load(f)

	arduino_cli = matrix['arduino-cli']
	arduino_cli_versions = version_tags(arduino_cli['versions'])
	max_arduino_cli_version = first(arduino_cli_versions)

	base_tags = OrderedDict()
	max_base_versions = []
	for name, base in matrix['base'].items():
		base['name'] = name
		base_tags[base['name']] = version_tags(base['versions'])
		max_base_versions.append(base['name'] + first(base_tags[base['name']]))

		base['tags'] = mustache_map(base_tags[base['name']])

	for core in matrix['core']:
		core['repo'] = args.repo + '-' + core['package']
		if core['package'] != core['arch']:
			core['repo'] += '-' + core['arch']

		core['tags'] = version_tags(core['versions'])
		core['max_version'] = first(core['tags'])

		core['tags'] = mustache_map(core['tags'])

	render_template(
		'templates/base.md',
		os.path.join(args.output, 'base.md'),
		{
			'repo': args.repo,
			'max_base_versions': max_base_versions,
			'max_arduino_cli_version': max_arduino_cli_version,
			'arduino_cli_versions': mustache_map(arduino_cli_versions),
			'base': mustache_map(matrix['base']),
			'core': matrix['core'],
		}
	)

	for core in matrix['core']:
		filename = '%s-%s.md' % (core['package'], core['arch'])

		render_template(
			'templates/core.md',
			os.path.join(args.output, filename),
			{
				'repo': args.repo,
				'max_base_versions': max_base_versions,
				'max_arduino_cli_version': max_arduino_cli_version,
				'core': core,
			}
		)

def mustache_map(m):
	return [{'key': k, 'value': v} for k,v in m.items()]

def render_template(src, dst, data):
	with open(src, 'r') as f_in, open(dst, 'w') as f_out:
		f_out.write(chevron.render(f_in, data))

def update(args):
	with open(args.matrix, 'r') as f:
		matrix = json.load(f, object_pairs_hook=OrderedDict)

	now = datetime.now(timezone.utc)
	after = now - timedelta(days=args.days)

	arduino_cli_versions = get_version_targets(args.token, 'arduino', 'arduino-cli', after)
	base_filters = {
		'node': lambda x: only_max_versions(x, max_minor, limit=3),
		'python': lambda x: only_max_versions(x, max_patch, limit=3),
	}

	message = []

	# Update Arduino CLI

	arduino_cli = matrix['arduino-cli']

	## Remove stale versions
	arduino_cli['versions'], removed = remove_versions(arduino_cli['versions'], arduino_cli_versions)
	for v in removed:
		message.append('Removed `arduino-cli@%s`' % v)

	## Add new versions
	arduino_cli['versions'], added = add_versions(arduino_cli['versions'], arduino_cli_versions, limit=args.limit)
	for v in added:
		message.append('Added `arduino-cli@%s`' % v)

	should_update_core = False
	should_update_base = len(added) == 0

	# Update base images

	for name, base in matrix['base'].items():
		repo = base['repo']
		existing_tags = get_repository_tags(base['image'])

		versions = get_version_targets(args.token, repo['owner'], repo['name'], after)
		versions = set.intersection(versions, existing_tags)

		if name in base_filters:
			versions = base_filters[name](versions)

		## Remove stale versions
		base['versions'], removed = remove_versions(base['versions'], versions)
		for v in removed:
			message.append('Removed base `%s@%s`' % (name, v))

		## Add new versions
		if should_update_base:
			base['versions'], added = add_versions(base['versions'], versions, limit=args.limit)
			for v in added:
				message.append('Added base `%s@%s`' % (name, v))
			should_update_core = should_update_core and len(added) == 0

	# Update cores

	index_cache = {}

	for core in matrix['core']:
		index_url = core['index_url']
		if not index_url in index_cache:
			index_cache[index_url] = requests.get(index_url).json()['packages']

		for package in index_cache[index_url]:
			if package['name'] == core['package']:
				break
		else:
			logging.warn("Failed to find package %s at %s", core['platform'], index_url)
			continue

		core_versions = {p['version'] for p in package['platforms'] if p['architecture'] == core['arch']}

		## Remove stale versions
		core['versions'], removed = remove_versions(core['versions'], core_versions)
		for v in removed:
			message.append('Removed core `%s:%s@%s`' % (core['package'], core['arch'], v))

		## Add new versions
		if should_update_core:
			core['versions'], added = add_versions(core['versions'], core_versions, limit=None)
			for v in added:
				message.append('Added core `%s:%s@%s`' % (core['package'], core['arch'], v))

	if not message:
		return

	if args.dryrun:
		print('\n'.join(message))
		json.dump(matrix, sys.stdout, indent=4)
	else:
		with open('message.txt', 'w') as f:
			f.writelines('\n'.join(message))

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

def only_max_versions(versions, key, limit=1):
	major_minor_versions = defaultdict(list)
	for v in versions:
		bin = key(semver.VersionInfo.parse(v))
		major_minor_versions[bin].append(v)

	versions = [version_list(v)[::-1][:limit] for v in major_minor_versions.values()]

	return set(chain(*versions))

def max_patch(v):
	return v.to_tuple()[:2]

def max_minor(v):
	return v.to_tuple()[:1]

def version_list(iter):
	return list(sorted(iter, key=semver.VersionInfo.parse))

def remove_versions(current, desired):
	removed = set()
	updated = set()

	for v in current:
		if v in desired:
			updated.add(v)
		else:
			removed.add(v)

	return version_list(updated), version_list(removed)

def add_versions(current, desired, limit=None):
	if limit == 0:
		return version_list(current), []

	updated = set(current)
	added = version_list(desired - updated)
	if not limit is None:
		added = added[-limit:]

	updated.update(added)

	return version_list(updated), added

def first(iter):
	for i in iter:
		return i

if __name__ == '__main__':
	main()
