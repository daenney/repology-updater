# Copyright (C) 2016-2019 Dmitry Marakasov <amdmi3@amdmi3.ru>
#
# This file is part of repology
#
# repology is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# repology is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with repology.  If not, see <http://www.gnu.org/licenses/>.

import bz2
import functools
import gzip
import lzma
import tempfile
import time
from json import dumps
from typing import Any, Callable

import requests

from repology.config import config

USER_AGENT = 'repology-fetcher/0 (+{}/bots)'.format(config['REPOLOGY_HOME'])
STREAM_CHUNK_SIZE = 10240


class PoliteHTTP:
    def __init__(self, timeout=5, delay=None):
        self.do_http = functools.partial(do_http, timeout=timeout)
        self.delay = delay
        self.had_requests = False

    def __call__(self, *args, **kwargs):
        if self.had_requests and self.delay:
            time.sleep(self.delay)

        self.had_requests = True
        return self.do_http(*args, **kwargs)


# XXX: post argument is a compatibility shim
def do_http(url, method=None, check_status=True, timeout=5, data=None, json=None, post=None, headers=None, stream=False) -> requests.Response:
    headers = headers.copy() if headers else {}
    headers['User-Agent'] = USER_AGENT

    if post and not data:
        data = post
    if json and not data:
        data = dumps(json)

    request: Callable[..., requests.Response] = requests.get

    if method == 'POST' or (method is None and data):
        request = requests.post
    elif method == 'DELETE':
        request = requests.delete
    elif method == 'PUT':
        request = requests.put

    response = request(url, headers=headers, timeout=timeout, data=data, stream=stream)

    if check_status:
        response.raise_for_status()

    return response


class NotModifiedException(requests.RequestException):
    pass


def save_http_stream(url, outfile, compression=None, **kwargs) -> requests.Response:
    # TODO: we should really decompress stream on the fly or
    # (better) store it as is and decompress when reading.

    kwargs = kwargs.copy()
    kwargs.update(stream=True)

    response = do_http(url, **kwargs)

    if response.status_code == 304:
        raise NotModifiedException(response=response)

    # no compression, just save to output
    if compression is None:
        for chunk in response.iter_content(STREAM_CHUNK_SIZE):
            outfile.write(chunk)
        return response

    # choose decompressor
    decompressor_module: Any[gzip, lzma, bz2]
    if compression == 'gz':
        decompressor_module = gzip
    elif compression == 'xz':
        decompressor_module = lzma
    elif compression == 'bz2':
        decompressor_module = bz2
    else:
        raise ValueError('Unsupported compression {}'.format(compression))

    # read into temp file, then decompress into output
    with tempfile.NamedTemporaryFile() as temp:
        for chunk in response.iter_content(STREAM_CHUNK_SIZE):
            temp.write(chunk)

        temp.seek(0)

        with decompressor_module.open(temp) as decompressor:
            while True:
                chunk = decompressor.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                outfile.write(chunk)

    return response
