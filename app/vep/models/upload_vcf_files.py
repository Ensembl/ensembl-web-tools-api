"""
See the NOTICE file distributed with this work for additional information
regarding copyright ownership.


Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""
import os
import logging
import tempfile
import shutil

from starlette.requests import ClientDisconnect

from streaming_form_data import StreamingFormDataParser
from streaming_form_data.targets import FileTarget, ValueTarget

from core.config import VCF_UPLOAD_DIRECTORY

MAX_FILE_SIZE = 260 * 1024 * 1024  # 250 MB
MAX_REQUEST_BODY_SIZE = MAX_FILE_SIZE + 1024

class MaxBodySizeException(Exception):
    def __init__(self, body_len: str):
        self.body_len = body_len


class MaxBodySizeValidator:
    def __init__(self, max_size: int):
        self.body_len = 0
        self.max_size = max_size

    def __call__(self, chunk: bytes):
        self.body_len += len(chunk)
        if self.body_len > self.max_size:
            raise MaxBodySizeException(body_len=self.body_len)


class Streamer:
    def __init__(self, request):
        self.request = request
        self.filename = self.request.headers.get('Filename', None)
        self.file_name_validator(self.filename)
        self.temp_dir = tempfile.mkdtemp(dir=VCF_UPLOAD_DIRECTORY)
        self.filepath = os.path.join(str(self.temp_dir), os.path.basename(self.filename))
        self._input_file = FileTarget(self.filepath)

        self.parser = StreamingFormDataParser(headers=self.request.headers)
        self.parameters = ValueTarget()
        self.genome_id = ValueTarget()

    @staticmethod
    def file_name_validator(file_name: str = None):
        if not file_name:
            raise Exception

    async def stream(self):
        body_validator =MaxBodySizeValidator(MAX_REQUEST_BODY_SIZE)
        try:
            self.parser.register('input_file', self._input_file)
            self.parser.register('parameters', self.parameters)
            self.parser.register('genome_id', self.genome_id)

            async for chunk in self.request.stream():
                body_validator(chunk)
                self.parser.data_received(chunk)
            return True
        except (Exception, ClientDisconnect) as e:
            print(e)
            logging.info(e)
            shutil.rmtree(self.temp_dir)
            raise Exception
