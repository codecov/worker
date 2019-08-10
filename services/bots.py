def get_repo_appropriate_bot(repo):
    if repo.bot is not None and repo.bot.oauth_token is not None:
        return repo.bot
    if repo.owner.bot is not None and repo.owner.bot.oauth_token is not None:
        return repo.owner.bot
    return repo.owner
