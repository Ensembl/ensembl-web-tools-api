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

def get_first_page_of_variants():
    sql = """
        WITH joint_table AS (
            SELECT variants.*, consequences.*
            FROM variants JOIN consequences USING(variant_id)
        ) SELECT * FROM joint_table WHERE variant_id IN (
            SELECT DISTINCT variant_id from joint_table
            LIMIT 100
        )
    """
    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.row_factory = sqlite3.Row
    cursor = db_connection.cursor()
    cursor.execute(sql)
    results = serialize_variants(cursor.fetchall())
    print(results)

def get_page_of_variants_with_offset():
    sql = """
        WITH joint_table AS (
            SELECT variants.*, consequences.*
            FROM variants JOIN consequences USING(variant_id)
        ) SELECT * FROM joint_table WHERE variant_id IN (
            SELECT DISTINCT variant_id from joint_table
            LIMIT 100
            OFFSET 80000
        )
    """
    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.row_factory = sqlite3.Row
    cursor = db_connection.cursor()
    cursor.execute(sql)
    results = serialize_variants(cursor.fetchall())
    print(results)

def get_variants_with_one_filter():
    sql = """
        WITH joint_table AS (
            SELECT variants.*, consequences.*
            FROM variants JOIN consequences USING(variant_id)
        ) SELECT * FROM joint_table WHERE variant_id IN (
            SELECT DISTINCT variant_id from joint_table
            WHERE biotype="retained_intron"
            LIMIT 100
            OFFSET 20000
        )
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
