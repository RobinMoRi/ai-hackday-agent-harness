.PHONY: build start up pi down clean nuke

WORKSPACE := $(CURDIR)

# Requires @devcontainers/cli: npm install -g @devcontainers/cli

build:
	devcontainer build --workspace-folder $(WORKSPACE)

start:
	devcontainer up --workspace-folder $(WORKSPACE)

up: start
	devcontainer exec --workspace-folder $(WORKSPACE) bash

pi: start
	devcontainer exec --workspace-folder $(WORKSPACE) pi

down:
	docker ps -q --filter "label=devcontainer.local_folder=$(WORKSPACE)" | xargs -r docker stop

clean: down
	docker ps -aq --filter "label=devcontainer.local_folder=$(WORKSPACE)" | xargs -r docker rm

nuke: clean
	docker images -q --filter "reference=vsc-ai-hackday-agent-harness-*" | xargs -r docker rmi -f
	docker volume rm -f pi-config pi-home
