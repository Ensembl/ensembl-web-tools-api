import logging
import tempfile
import aiofiles

import typing
from starlette import status

from fastapi import UploadFile, File, HTTPException

from core.config import VCF_UPLOAD_DIRECTORY

ALLOWED_FILE_TYPES = ("vcf", "vcf.gz", ".txt")  # Allowed file types
MAX_FILE_SIZE = 240 * 1024 * 1024  # 250 MB


async def validate_file(input_file: UploadFile = File(...), allowed_types: typing.Tuple[str] = ALLOWED_FILE_TYPES,
                        max_size: int = MAX_FILE_SIZE) -> bool:
    # Check file type
    if not input_file.filename.endswith(ALLOWED_FILE_TYPES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type: {input_file.content_type}. Allowed types are: {', '.join(allowed_types)}."
        )

    # Check file size
    input_file.file.seek(0, 2)
    file_size = input_file.file.tell()
    input_file.file.seek(0)

    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the maximum limit of {(max_size / (1024 * 1024)) + 10} MB."
        )


async def custom_file_upload(input_file: UploadFile = File(...)) -> UploadFile:
    await validate_file(input_file=input_file)
    temp_file = tempfile.NamedTemporaryFile(delete=False, dir=VCF_UPLOAD_DIRECTORY, suffix=input_file.filename)
    try:
        CHUNK_SIZE = 1024 * 1024  # 1MB
        async with aiofiles.open(temp_file.name, 'wb') as f:
            while chunk := await input_file.read(CHUNK_SIZE):
                await f.write(chunk)

    except Exception as e:
        logging.info(e)

    return input_file
