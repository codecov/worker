def get_repo_yaml(repository):
    return merge_repo_and_owner_yamls(repository.owner.yaml, repository.yaml)


def merge_repo_and_owner_yamls(owner_yaml, repo_yaml):
    if repo_yaml is None:
        return owner_yaml
    if owner_yaml is None:
        return repo_yaml
    return {**owner_yaml, **repo_yaml}
