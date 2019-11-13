from collections import Counter
from urllib.parse import parse_qs, urlparse

import requests
from django.conf import settings

GITHUB_API_URL = 'https://api.github.com'


class GitHubError(Exception):
    """GitHub error."""


class NoContributorsError(GitHubError):
    """A repository has no contributors."""


class ContributorNotFoundError(GitHubError):
    """A particular contributor was not found."""


def get_headers():
    """Returns headers to use in a request."""
    return {'Authorization': f'token {settings.GITHUB_AUTH_TOKEN}'}


def get_one_item_at_a_time(url, additional_params=None):
    """Returns data from all pages (one instance at a time)."""
    query_params = {'page': 1}
    query_params.update(additional_params or {})
    response = requests.get(url, headers=get_headers(), params=query_params)
    response.raise_for_status()
    yield from response.json()

    pages_count = get_pages_count(response.links)
    while query_params['page'] < pages_count:
        query_params['page'] += 1
        response = requests.get(url, headers=get_headers(), params=query_params)
        response.raise_for_status()
        yield from response.json()


def get_whole_response_as_json(url):
    """Returns data as given by GitHub (a batch)."""
    response = requests.get(url, headers=get_headers())
    response.raise_for_status()
    return response.json()


def get_org_data(org):
    """Returns an organization's data."""
    url = f'{GITHUB_API_URL}/orgs/{org}'
    return get_whole_response_as_json(url)


def get_user_data(user):
    """Returns a user's data."""
    url = f'{GITHUB_API_URL}/users/{user}'
    return get_whole_response_as_json(url)


def get_user_name(url):
    """Returns a user's name."""
    return get_whole_response_as_json(url)['name']


def get_org_repos(org):
    """Returns repositories of an organization."""
    url = f'{GITHUB_API_URL}/orgs/{org}/repos'
    return get_one_item_at_a_time(url)


def get_repo_contributors(owner, repo):
    """Returns contributors for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/stats/contributors'
    return get_whole_response_as_json(url)


def get_repo_commits(owner, repo):
    """Returns all commits for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/commits'
    return get_one_item_at_a_time(url)


def get_repo_prs(owner, repo):
    """Returns all pull requests for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/pulls'
    query_params = {'state': 'all'}
    return get_one_item_at_a_time(url, query_params)


def get_repo_issues(owner, repo):
    """
    Returns all issues for a repository.

    Every pull request is an issue, but not every issue is a pull request.
    Identify pull requests by the `pull_request` key.
    [issue for issue in issues if 'pull_request' not in issue]
    """
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/issues'
    query_params = {'state': 'all'}
    return get_one_item_at_a_time(url, query_params)


def get_comments_for_issue(owner, repo, issue_number):
    """Returns all comments for an issue."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{issue_number}/comments'
    return get_one_item_at_a_time(url)


def get_repo_comments(owner, repo):
    """Returns all comments for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/issues/comments'
    return get_one_item_at_a_time(url)


def get_review_comments_for_pr(owner, repo, pr_number):
    """Returns all review comments for a pull request."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/comments'
    return get_one_item_at_a_time(url)


def get_repo_review_comments(owner, repo):
    """Returns all review comments for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/comments'
    return get_one_item_at_a_time(url)


def get_total_contributions_per_user(contributions, author_field_name):
    """Returns total numbers of contributions of a specific type per user."""
    users_contributions_totals = {}
    for contribution in contributions:
        author = contribution.get(author_field_name)
        if not author:  # Deleted user
            continue
        login = author.get('login')
        users_contributions_totals[login] = (
            users_contributions_totals.get(login, 0) + 1
        )
    return users_contributions_totals


def get_total_changes_per_user(contributors, change_type):
    """Returns total numbers of changes of `type` made by each user."""
    total_changes_per_user = {}
    for contribution in contributors:
        login = contribution['author']['login']
        total_changes_per_user[login] = sum(
            week[change_type] for week in contribution['weeks']
        )
    return total_changes_per_user


def get_total_prs_per_user(prs):
    """Returns total numbers of pull requests per user."""
    return get_total_contributions_per_user(prs, 'user')


def get_total_commits_per_user(commits):
    """Returns total numbers of commits per user."""
    return get_total_contributions_per_user(commits, 'author')


def get_total_commits_per_user_excluding_merges(owner, repo):
    """Returns total numbers of commits per user excluding merge commits."""
    contributors = get_repo_contributors(owner, repo)
    return {contributor['author']['login']: contributor['total'] for contributor in contributors}


def get_total_issues_per_user(issues):
    """Returns total numbers of issues per user."""
    return get_total_contributions_per_user(issues, 'user')


def get_total_comments_per_user(comments):
    """Returns total numbers of comments per user."""
    return get_total_contributions_per_user(comments, 'user')


def get_total_additions_per_user(contributors):
    """Returns total numbers of additions per user."""
    return get_total_changes_per_user(contributors, 'a')


def get_total_deletions_per_user(contributors):
    """Returns total numbers of deletions per user."""
    return get_total_changes_per_user(contributors, 'd')


def get_pages_count(link_headers):
    """Returns a number of pages for a resource."""
    if 'last' in link_headers:
        return int(
            parse_qs(urlparse(link_headers['last']['url']).query)['page'][0],
        )
    return 1


def merge_dicts(*dicts):
    """Merges several dictionaries into one."""
    counter = Counter()
    for dict_ in dicts:
        counter.update(dict_)
    return counter


def get_commit_stats_for_contributor(repo_full_name, contributor_id):
    """Returns numbers of commits, additions, deletions of a contributor."""
    url = f'{GITHUB_API_URL}/repos/{repo_full_name}/stats/contributors'
    response = requests.get(url, headers=get_headers())
    response.raise_for_status()
    if response.status_code == requests.codes.no_content:
        raise NoContributorsError(
            "Nobody has contributed to this repository yet.",
        )

    try:
        contributor_stats = [
            stats for stats in response.json()
            if stats['author']['id'] == contributor_id
        ][0]
    except IndexError:
        raise ContributorNotFoundError(
            "No such contributor in this repository.",
        )

    totals = merge_dicts(*contributor_stats['weeks'])

    return totals['c'], totals['a'], totals['d']