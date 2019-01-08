build.prod:
	docker build -f Dockerfile.prod -t codecov/worker .

build.dev:
	docker build -f Dockerfile.dev -t codecov/workerdev .

