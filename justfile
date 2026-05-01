REPO_ROOT := "$(git rev-parse --show-toplevel)" # Repo root
release TAG:
	$EDITOR {{REPO_ROOT}}/CHANGELOG.md
	git tag -a {{TAG}} -m "Tag update"
	git push origin {{TAG}}

test:
	python src/shadow_chat.py
