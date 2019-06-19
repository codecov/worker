def get_repo_yaml(repository):
    return merge_repo_and_owner_yamls(repository.owner.yaml, repository.yaml)


def merge_repo_and_owner_yamls(owner_yaml, repo_yaml, commit_yaml=None):
    if commit_yaml is not None:
        return commit_yaml
    if repo_yaml is None:
        return owner_yaml
    if owner_yaml is None:
        return repo_yaml
    return {**owner_yaml, **repo_yaml}


def set_repo_yaml_if_needed(repository, current_branch, new_yaml):
    pass
