REPO_ROOT := "$(git rev-parse --show-toplevel)" # Repo root

test:
    python src/shadow_chat.py

[confirm("Do you want to release a new version with tag: " + TAG + "?")]
release TAG:
    $EDITOR {{ REPO_ROOT }}/CHANGELOG.md
    git commit CHANGELOG.md -m 'Push changes for next release'
    git tag -a {{ TAG }} -m "Tag update"
    git push origin {{ TAG }}
