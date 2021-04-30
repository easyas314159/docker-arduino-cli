import sys
import json
import logging
import argparse

from itertools import product
from collections import defaultdict

import docker
import semver
import pythonflow as pf

def get_cli_arguments():
	parser = argparse.ArgumentParser()

	parser.add_argument('-u', '--username', required=True)
	parser.add_argument('-p', '--password', required=True)

	parser.add_argument('-r', '--repo', required=True)
	parser.add_argument('-m', '--maintainer', required=True)

	parser.add_argument('--debug', default=False, action='store_true')
	parser.add_argument('--dryrun', default=False, action='store_true')

	parser.add_argument('matrix')

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

	with open(args.matrix, 'r') as f:
		matrix = json.load(f)

	with pf.Graph() as graph:
		docker_context_base = pf.constant('base')
		docker_context_core = pf.constant('core')

		repo = pf.constant(args.repo)
		maintainer = pf.constant(args.maintainer)
		dryrun = pf.constant(args.dryrun)
		username = pf.constant(args.username)
		password = pf.constant(args.password)

		client = pf.func_op(create_docker_client, username, password)

		base_repo = pf.placeholder('base_repo')
		base_version = pf.placeholder('base_version')
		base_tag = pf.func_op(fqt, base_repo, base_version)

		arduino_cli_version = pf.placeholder('arduino_cli_version')
		base_tags = pf.placeholder('tags')

		base_buildargs = pf.func_op(
			dict,
			MAINTAINER_EMAIL=maintainer,
			ARDUINO_CLI_VERSION=arduino_cli_version,
			BASE_IMAGE=base_tag,
		)
		base_builder = pf.func_op(build_image, client, repo, base_buildargs, base_tags, dryrun, path=docker_context_base)

		builds = [base_builder]

		for package, arch, additional_urls, core_tags in arduino_cli_core_tasks(matrix['core']):
			core_package = pf.constant(package)
			core_arch = pf.constant(arch)
			core_additional_urls = pf.constant(additional_urls)
			core_tags = pf.constant(core_tags)

			core_buildargs = pf.func_op(
				dict,
				MAINTAINER_EMAIL=maintainer,
				BASE_IMAGE=base_builder,
				ARDUINO_ADDITIONAL_URLS=pf.func_op('\n'.join, core_additional_urls),
				ARDUINO_CORE=pf.func_op(fqt, core_package, core_arch)
			)
			core_tags = pf.func_op(broadcast_tags, base_tags, core_tags)

			core_repo = pf.conditional(
				core_package == core_arch,
				core_package,
				pf.func_op('-'.join, [core_package, core_arch]),
			)
			core_repo = pf.func_op('-'.join, [repo, core_repo])

			core_builder = pf.func_op(
				build_image,
				client,
				core_repo,
				core_buildargs,
				core_tags,
				dryrun,
				path=docker_context_core
			)
			builds.append(core_builder)

		prune = pf.func_op(client_prune, client, dryrun, *builds)

		for context in arduino_cli_tasks(matrix['arduino-cli'], matrix['base']):
			graph([prune], context.copy())

def fqt(repo, tag):
	return ':'.join([f for f in [repo, tag] if f])

def create_docker_client(username, password):
	client = docker.from_env()
	client.login(username=username, password=password, reauth=True)

	return client

def build_image(client, repo, buildargs, tags, dryrun=False, **kwargs):
	name = fqt(repo, tags[0])

	logging.info('Building %s', name)
	logging.debug('buildargs: %s', buildargs)
	logging.debug('tags: %s', tags)

	if dryrun:
		return name

	try:
		rd = client.images.get_registry_data(name)
		logging.info('Skipping %s', name)
		return name
	except docker.errors.NotFound:
		pass

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
	logging.info(image.tags)

	return name

def client_prune(client, dryrun=False, *args):
	logging.info("Pruning")
	logging.debug(args)

	if not dryrun:
		client.containers.prune()
		client.volumes.prune()
		client.images.prune()

	return args

def arduino_cli_tasks(arduino_cli_versions, bases, target='arduino_cli'):
	arduino_cli_version_tags = version_tags(arduino_cli_versions)
	for arduino_cli_version in arduino_cli_version_tags:
		for base_tag in bases:
			base_version_tags = version_tags(bases[base_tag]['versions'])

			for base_version in base_version_tags:
				tags = [(t[0], base_tag+t[1]) for t in product(
					arduino_cli_version_tags[arduino_cli_version],
					base_version_tags[base_version]
				)]
				tags = ['-'.join([f for f in t if f]) for t in tags]

				yield {
					'arduino_cli_version': arduino_cli_version,
					'base_repo': bases[base_tag]['image'],
					'base_version': base_version,
					'tags': tags,
				}

def arduino_cli_core_tasks(cores):
	for base_name in cores:
		core_version_tags = version_tags(cores[base_name]['versions'])
		for core_version in core_version_tags:
			yield (
				cores[base_name]['package'],
				cores[base_name]['arch'],
				cores[base_name]['additional_urls'],
				core_version_tags[core_version],
			)

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

if __name__ == '__main__':
	main()
