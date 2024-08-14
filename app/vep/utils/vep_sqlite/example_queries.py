import sqlite3
import json

from db_details import DATABASE_NAME

def serialize_variants(rows):
    results = []
    for row in rows:
        variant = {}
        variant["id"] = row["variant_id"]
        variant["name"] = row["name"]
        variant["region_name"] = row["region_name"]
        variant["start"] = row["start"]
        results.append(variant)
    return json.dumps(results, indent=2)

# takes about 40ms to run
def get_first_page_of_variants():
    sql = """
        SELECT * FROM variants
        JOIN consequences USING(variant_id)
        LIMIT 100
    """
    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.row_factory = sqlite3.Row
    cursor = db_connection.cursor()
    cursor.execute(sql)
    results = serialize_variants(cursor.fetchall())
    print(results)

# takes about 50ms to run
def get_page_of_variants_with_offset():
    sql = """
        SELECT * FROM variants
        JOIN consequences USING(variant_id)
        LIMIT 100
        OFFSET 80000
    """
    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.row_factory = sqlite3.Row
    cursor = db_connection.cursor()
    cursor.execute(sql)
    results = serialize_variants(cursor.fetchall())
    print(results)

# takes about 150ms to run
def get_variants_with_one_filter():
    sql = """
        SELECT * FROM variants
        JOIN consequences USING(variant_id)
        WHERE biotype="retained_intron"
        AND variants.variant_id in (
            SELECT DISTINCT variants.variant_id
            FROM variants JOIN consequences USING(variant_id)
            WHERE biotype="retained_intron"
            limit 100
            offset 10000
        );
    """
    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.row_factory = sqlite3.Row
    cursor = db_connection.cursor()
    cursor.execute(sql)
    results = serialize_variants(cursor.fetchall())
    print(results)


# get_first_page_of_variants()
# get_page_of_variants_with_offset()
get_variants_with_one_filter()
