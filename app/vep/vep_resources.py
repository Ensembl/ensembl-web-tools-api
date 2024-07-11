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

import logging

from typing import Annotated
from fastapi import Request, HTTPException, status, APIRouter

from core.logging import InterceptHandler
from vep.models.upload_vcf_files import Streamer, MaxBodySizeException
from vep.models.pipeline_model import ConfigIniParams, VEPConfigParams
import json
logging.getLogger().handlers = [InterceptHandler()]

router = APIRouter()


@router.post("/submissions", name="submit_vep")
async def submit_vep(request : Request):
    try:
        stream_obj = Streamer(request=request)
        stream_result = await stream_obj.stream()
        parameters = stream_obj.parameters.value.decode()
        genome_id = stream_obj.genome_id.value.decode()

        parameters_dict = json.loads(parameters)
        ini_parameters = ConfigIniParams(**parameters_dict)
        inifile = ini_parameters.create_config_ini_file(stream_obj.temp_dir)
        vep_config_parameters = VEPConfigParams(vcf=stream_obj.filepath,vep_config=inifile.name)
        if stream_result:
            return {"message": f"Successfully uploaded{stream_obj.filepath}"}
        else:
            raise Exception
    except MaxBodySizeException:
        return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                             detail='Maximum file size limit exceeded.')
    except Exception as e:
        print(e)
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail='There was an error uploading the file.')


