.PHONY: deploy deploy-dry-run deploy-local rollback test

deploy:
	./scripts/deploy.sh

deploy-dry-run:
	./scripts/deploy.sh --dry-run

deploy-local:
	./scripts/deploy.sh --local-only

rollback:
	@test -n "$(ROLLBACK_ID)" || (echo "ROLLBACK_ID is required" >&2; exit 2)
	./scripts/deploy.sh --rollback "$(ROLLBACK_ID)"

test:
	python3 -m unittest discover -s tests -v
