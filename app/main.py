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

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from blast.blast import app as blast_app
from vep.routes import router as vep_router
from core.config import API_PREFIX, ALLOWED_HOSTS, VERSION, PROJECT_NAME, DEBUG


class GZipExceptAlreadyCompressed(GZipMiddleware):
    """gzip, except for the responses that are already compressed bytes.

    A results page is ~1.17MB of JSON that gzips to 134KB for 4ms of CPU at
    level 1 — worth little on a LAN and worth seconds on a slow connection.

    The downloads are the exception: they stream a `.gz` already, and Starlette
    excludes only `text/event-stream`, so they would be compressed a second
    time. That is not wrong — the client strips the transport encoding and
    still saves the `.gz` — but it is a whole extra pass over a potentially
    large file for no reduction at all, since the bytes are incompressible.
    """

    def __init__(self, app, minimum_size: int = 500, compresslevel: int = 1):
        super().__init__(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path", "").endswith("/download"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def get_application() -> FastAPI:
    application = FastAPI(title=PROJECT_NAME, debug=DEBUG, version=VERSION)

    # Level 1 deliberately: measured on a results page it gives 9x for 4ms,
    # where level 6 gives 11x for 9ms and level 9 gives 11x for 14ms. The extra
    # compression is not worth two to three times the CPU per request.
    application.add_middleware(GZipExceptAlreadyCompressed, compresslevel=1)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_HOSTS or ["*"],
        allow_credentials=True,
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )

    application.include_router(vep_router, prefix=API_PREFIX)

    return application


app = get_application()
app.mount("/api/tools/blast", blast_app)
