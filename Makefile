.PHONY: build up down sh pi logs clean

build:
	docker compose build

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
