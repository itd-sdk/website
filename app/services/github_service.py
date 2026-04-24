from github import Github
from github.Repository import Repository

g = Github()

def get_projects() -> list[Repository]:
    return g.get_organization('itd-sdk').get_repos(sort='updated').get_page(0) # bruh how can i sort by stars stupid lib

def get_analogs() -> list[Repository]:
    return [g.get_repo('gam5510/itdpy'), g.get_repo('EpsilonRationes/aioitd'), g.get_repo('IRRatium/itdirr')]