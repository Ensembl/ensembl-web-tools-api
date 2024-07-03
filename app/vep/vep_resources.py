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
<<<<<<< HEAD
See the License for the specific language governing permissions and
limitations under the License.

"""
import logging
from typing import Annotated

from fastapi import APIRouter, responses, UploadFile, Form
import logging
import tempfile
import os

import typing
from typing import Annotated, Optional

from fastapi import APIRouter, responses, UploadFile, Form, Depends, File
from starlette.datastructures import UploadFile as StarletteUploadFile


from core.logging import InterceptHandler

logging.getLogger().handlers = [InterceptHandler()]

router = APIRouter()


class NamedTemporaryUploadFile(StarletteUploadFile):
    def __init__(self, filename: str,  file: Optional[object] = None):
        super().__init__(filename=filename,  file=file)
        if filename.lower().endswith(''):
                pass
        self._temp_file = tempfile.NamedTemporaryFile(delete=False, dir="/tmpdir", suffix=filename)
        self.file = self._temp_file

    async def write(self, data: bytes) -> None:
        self.file.write(data)

    async def read(self, size: int = -1) -> bytes:
        self.file.seek(0)
        return self.file.read(size)

    async def close(self) -> None:
        self.file.close()

    def __getattr__(self, name: str):
        return getattr(self.file, name)

    def __del__(self):
        try:
            self.file.close()
        except:
            pass

async def named_tempfile_upload(input_file: UploadFile = File(...)) -> NamedTemporaryUploadFile:
    return NamedTemporaryUploadFile(filename=input_file.filename, file=input_file.file)

@router.post("/submissions", name="submit_vep")
def submit_vep(genome_id: Annotated[str, Form()], input_file: NamedTemporaryUploadFile = Depends(named_tempfile_upload)):
    try:
        return {"genome_id": genome_id, "filename": input_file.filename}

    except Exception as e:
        logging.info(e)
