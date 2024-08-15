# Description

This attempt is to transform a vcf source into a sqlite database, and query variants back from it. It uses 2 tables: `variants`, and `consequences`, of which the `consequences` table contains denormalized data (e.g. alternative alleles, transcripts, the actual consequences).


## Instructions

NOTE: because of problems with imports in my setup, I ran all files from inside this current directory

### Create a sqlite database
To transform a vcf file into a sqlite database:
- change the `path_to_file` variable in the `parse_vcf` file to a correct string
- run `python vcf_to_sqlite.py`

A `test.db` database file will appear inside of the `denormalized` directory

### Run queries against the database
There are some example queries in the `example_queries.py` file. They describe common scenarios:
- Get the first page of variants
- Get a page of variants with an offset (simulate pagination queries)
- Get a page of variants using a filter (simulate paginated filter query)

To execute an example query, run `python vcf_to_sqlite.py` (one query function will be uncommented, and will run)
