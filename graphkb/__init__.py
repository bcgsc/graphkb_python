import hashlib
import json
import requests
from typing import Dict, List

DEFAULT_URL = 'https://graphkb-api.bcgsc.ca/api'
DEFAULT_LIMIT = 1000


def join_url(base_url: str, *parts: List[str]) -> str:
    """
    Join parts of a URL into a full URL
    """
    if not parts:
        return base_url

    if base_url.endswith('/'):
        base_url = base_url[:-1]

    url = [base_url]

    for part in parts:
        if not part.startswith('/'):
            url.append('/')
        url.append(part)
    return ''.join(url)


class GraphKBConnection:
    def __init__(self, url: str = DEFAULT_URL):
        self.token = None
        self.url = url
        self.username = None
        self.password = None
        self.headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        self.cache = {}
        self.request_count = 0

    def request(self, endpoint: str, method: str = 'GET', **kwargs) -> Dict:
        """Request wrapper to handle adding common headers and logging

        Args:
            endpoint (string): api endpoint, excluding the base uri
            method (str, optional): the http method. Defaults to 'GET'.

        Returns:
            dict: the json response as a python dict
        """
        url = join_url(self.url, endpoint)
        self.request_count += 1
        resp = requests.request(method, url, headers=self.headers, **kwargs)

        if resp.status_code == 401 or resp.status_code == 403:
            # try to re-login if the token expired

            self.refresh_login()
            self.request_count += 1
            resp = requests.request(method, url, headers=self.headers, **kwargs)

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as err:
            # try to get more error details
            message = str(err)
            try:
                message += ' ' + resp.json()['message']
            except Exception:
                pass

            raise requests.exceptions.HTTPError(message)

        return resp.json()

    def post(self, uri: str, data: Dict = {}, **kwargs) -> Dict:
        """Convenience method for making post requests"""
        return self.request(uri, method='POST', data=json.dumps(data), **kwargs)

    def login(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

        # use requests package directly to avoid recursion loop on login failure
        self.request_count += 1
        resp = requests.request(
            url=f'{self.url}/token',
            method='POST',
            headers=self.headers,
            data=json.dumps({'username': username, 'password': password}),
        )
        resp.raise_for_status()
        content = resp.json()
        self.token = content['kbToken']
        self.headers['Authorization'] = self.token

    def refresh_login(self) -> None:
        self.login(self.username, self.password)

    def query(
        self,
        requestBody: Dict = {},
        paginate: bool = True,
        ignore_cache: bool = True,
        force_refresh: bool = False,
        limit: int = DEFAULT_LIMIT,
    ) -> List[Dict]:
        result = []
        hash_code = ""

        if not ignore_cache:
            body = json.dumps(requestBody, sort_keys=True)
            hash_code = hashlib.md5(f'/query{body}'.encode('utf-8')).hexdigest()
            if hash_code in self.cache and not force_refresh:
                return self.cache[hash_code]

        while True:
            content = self.post('query', data={**requestBody, 'limit': limit, 'skip': len(result)})
            records = content['result']
            result.extend(records)
            if len(records) < limit or not paginate:
                break

        if not ignore_cache:
            self.cache[hash_code] = result
        return result

    def parse(self, hgvs_string: str, requireFeatures: bool = False) -> Dict:
        content = self.post(
            'parse', data={'content': hgvs_string, 'requireFeatures': requireFeatures}
        )
        return content['result']

    def get_records_by_id(self, record_ids: List[str]) -> List[Dict]:
        if not record_ids:
            return []
        result = self.query({'target': record_ids})
        if len(record_ids) != len(result):
            raise AssertionError(
                f'The number of Ids given ({len(record_ids)}) does not match the number of records fetched ({len(result)})'
            )
        return result

    def get_record_by_id(self, record_id: str) -> Dict:
        result = self.get_records_by_id([record_id])
        return result[0]

    def get_source(self, name: str) -> Dict:
        source = self.query({'target': 'Source', 'filters': {'name': name}})
        if len(source) != 1:
            raise AssertionError(f'Unable to unqiuely identify source with name {name}')
        return source[0]
