FROM python:3.10
WORKDIR /app
COPY ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY ./app /app
COPY ./data /data
RUN mkdir -p /nfs/public/rw/enswbsites
RUN mkdir /tmpdir
ENV TMPDIR /tmpdir
ENV PORT 8013
EXPOSE 8013
# CMD ["uvicorn", "main:app", "--proxy-headers", "--host", "0.0.0.0", "--port", "8013"]
