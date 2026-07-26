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
import re
import tempfile
import shutil

from starlette.requests import ClientDisconnect

from streaming_form_data import StreamingFormDataParser
from streaming_form_data.targets import FileTarget, ValueTarget
from streaming_form_data.validators import ValidationError

from core.config import NF_WORK_DIR

MAX_FILE_SIZE = 1024 * 1024 * 1024 * 2  # 2GB
MAX_REQUEST_BODY_SIZE = MAX_FILE_SIZE + 1024

# What a client may call its upload. Deliberately a strict allowlist rather than
# a denylist of dangerous characters: this name becomes a real path, that path is
# handed to bcftools, and it round-trips through the pipeline before coming back
# to us on the status response — so it is worth being able to say what it can
# contain rather than guessing at what it cannot. Covers every real VCF name
# (`sample_1.vcf.gz`, `NA12878.chr1-22.vcf`).
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


class UnsafeFileNameException(Exception):
    """The client's `Filename` header is not a plain file name."""

    def __init__(self, file_name: str):
        self.file_name = file_name
        super().__init__(f"unacceptable file name: {file_name!r}")


class MaxBodySizeException(Exception):
    def __init__(self, body_len: int):
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
        self.filename = self.request.headers.get("Filename", "temp_name")
        self.file_name_validator(self.filename)
        self.temp_dir = tempfile.mkdtemp(dir=NF_WORK_DIR)
        self.filepath = os.path.join(
            str(self.temp_dir), os.path.basename(self.filename)
        )
        self._input_file = FileTarget(self.filepath)

        self.parser = StreamingFormDataParser(headers=self.request.headers)
        self.parameters = ValueTarget()
        self.genome_id = ValueTarget()

    @staticmethod
    def file_name_validator(file_name: str | None = None):
        """Reject anything that is not a plain, safe file name.

        `os.path.basename` alone is not enough — it strips directories but
        leaves shell metacharacters, so `a$(...).vcf` reaches the shell intact.
        The command interpolations it fed are now argument lists, but the name
        also becomes a path and travels through the pipeline, so it is checked
        at the door as well.
        """
        if not file_name:
            raise Exception
        if not SAFE_FILENAME.fullmatch(file_name):
            raise UnsafeFileNameException(file_name)

    async def stream(self):
        body_validator = MaxBodySizeValidator(MAX_REQUEST_BODY_SIZE)
        try:
            self.parser.register("input_file", self._input_file)
            self.parser.register("parameters", self.parameters)
            self.parser.register("genome_id", self.genome_id)

            async for chunk in self.request.stream():
                body_validator(chunk)
                self.parser.data_received(chunk)

            if self.filename == "temp_name":
                # A second, independent source of the name: the multipart part's
                # own filename, used when the client sent no `Filename` header.
                # It gets the same gate — validating only the header would leave
                # the door open next to the lock.
                multipart_name = os.path.basename(
                    self._input_file.multipart_filename or ""
                )
                self.file_name_validator(multipart_name)
                os.rename(
                    self.filepath,
                    os.path.join(self.temp_dir, multipart_name),
                )
                self.filename = multipart_name
                self.filepath = os.path.join(self.temp_dir, self.filename)
            return True

        except (MaxBodySizeException, ValidationError):
            shutil.rmtree(self.temp_dir)
            raise MaxBodySizeException(MAX_FILE_SIZE)
        except (ClientDisconnect, Exception):
            shutil.rmtree(self.temp_dir)
            raise
