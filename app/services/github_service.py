from github import Github
from github.Repository import Repository

g = Github()

def get_projects() -> list[Repository]:
    repos = g.get_organization('itd-sdk').get_repos().get_page(0) # bruh how can i sort by stars stupid lib
    repos.sort(key=lambda repo: repo.stargazers_count, reverse=True)
    try:
        repos.remove(next((repo for repo in repos if repo.name == '.github')))
    except StopIteration:
        pass
    return repos

def get_analogs() -> list[Repository]:
    return [g.get_repo('gam5510/itdpy'), g.get_repo('EpsilonRationes/aioitd'), g.get_repo('IRRatium/itdirr')]