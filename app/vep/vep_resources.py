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

from core.logging import InterceptHandler
from vep.models.upload_vcf_files import Streamer

from fastapi import Request, HTTPException, status, APIRouter

logging.getLogger().handlers = [InterceptHandler()]

router = APIRouter()


@router.post("/submissions", name="submit_vep")
async def submit_vep(request : Request):
    try:
        test_obj = Streamer(request=request)
        stream_result = await test_obj.stream()
        print(test_obj.parameters.value.decode())
        print(test_obj.genome_id.value.decode())
        if stream_result:
            return {"message": f"Successfully uploaded{test_obj.filepath}"}
        else:
            raise Exception

    except Exception as e:
        print(e)
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail='There was an error uploading the file')

