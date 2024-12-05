FROM python:3.11 AS build
RUN wget https://github.com/samtools/bcftools/releases/download/1.21/bcftools-1.21.tar.bz2; \
  tar -x -f bcftools-1.21.tar.bz2; cd bcftools-1.21; make

FROM python:3.11
WORKDIR /app
COPY ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY ./app /app
COPY ./data /data
COPY --from=build /bcftools-1.21/bcftools /usr/local/bin/
RUN mkdir -p /nfs/public/rw/enswbsites
ENV TMPDIR /nfs/public/rw/enswbsites
ENV PORT 8013
EXPOSE 8013
# CMD ["uvicorn", "main:app",  "--host", "0.0.0.0", "--port", "8013", "--reload"]
# CMD ["uvicorn", "main:app", "--proxy-headers", "--host", "0.0.0.0", "--port", "8013"]
