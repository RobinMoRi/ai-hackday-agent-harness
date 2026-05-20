.PHONY: build up down sh pi logs clean

build:
	docker compose build
	docker compose run --rm --no-deps api sh -c \
	  'rm -rf /workspace/pi/extensions/node_modules && \
	   cp -r /home/app/.cache/pi-extensions/node_modules /workspace/pi/extensions/node_modules'

up:
	docker compose up -d

down:
	docker compose down

sh:
	docker compose exec api bash

pi:
	docker compose exec api pi

logs:
	docker compose logs -f

clean:
	docker compose down -v --rmi local
