import sqlite3
import json

from db_details import DATABASE_NAME

def serialize_variants(rows):
    variants_map = {}
    for row in rows:
        variant_id = row["variant_id"]
        if variant_id in variants_map:
            variant = variants_map[variant_id]
        else:
            variant = {}
            variant["id"] = row["variant_id"]
            variant["name"] = row["name"]
            variant["region_name"] = row["region_name"]
            variant["start"] = row["start"]
            variant["alternative_alleles"] = []
            variants_map[variant_id] = variant

        alternative_allele = None

        for alt_allele in variant["alternative_alleles"]:
            if alt_allele['alternative_allele_id'] == row["alternative_allele_id"]:
                alternative_allele = alt_allele

        if not alternative_allele:
            alternative_allele = {
                "alternative_allele_id": row["alternative_allele_id"],
                "alternative_allele": row["alternative_allele"],
                "consequences": []
            }
            variant["alternative_alleles"].append(alternative_allele)

        # Add consequence to the list of alternative allele consequences if not already there
        consequence = row["consequence"] 
        if not consequence in alternative_allele["consequences"]:
            alternative_allele["consequences"].append(consequence)

    # Remove temporary ids from the json before returning
    variants = [ cleanup_variant(variant) for variant in variants_map.values() ]
    return json.dumps(variants, indent = 2)

def cleanup_variant(variant):
    """
    Remove unused fields, such as ids, from a variant before serialising
    """
    del variant["id"]
    for alt_allele in variant["alternative_alleles"]:
        del alt_allele["alternative_allele_id"]
    return variant


# takes about 40ms to run denormalized
def get_first_page_of_variants():
    sql = """
        WITH joint_table AS (
            SELECT variants.*, alternative_alleles.*, consequences.*, features.*
            FROM variants
            JOIN alternative_alleles USING(variant_id)
            JOIN alternative_alleles_consequences USING(alternative_allele_id)
            JOIN consequences USING(consequence_id)
            JOIN alternative_alleles_features USING(alternative_allele_id)
            JOIN features ON features.id = alternative_alleles_features.feature_id        
        )
        SELECT * FROM joint_table WHERE variant_id IN (
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


def try_json_group_object():
    sql = """
        WITH joint_table AS (
            SELECT variants.*, alternative_alleles.*, consequences.*, features.*
            FROM variants
            JOIN alternative_alleles USING(variant_id)
            JOIN alternative_alleles_consequences USING(alternative_allele_id)
            JOIN consequences USING(consequence_id)
            JOIN alternative_alleles_features USING(alternative_allele_id)
            JOIN features ON features.id = alternative_alleles_features.feature_id        
        )
        SELECT json_group_object(
            variant_id,
            json_object (
                "name", name,
                "region_name", region_name,
                "reference_allele", reference_allele
            )
        )  FROM joint_table  WHERE variant_id  IN (
            SELECT DISTINCT variant_id from joint_table
            LIMIT 100
        )
    """

    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.row_factory = sqlite3.Row
    cursor = db_connection.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    for result in results:
        print(result.keys())


# takes about 50ms to run
def get_page_of_variants_with_offset():
    sql = """
        WITH joint_table AS (
            SELECT variants.*, alternative_alleles.*, consequences.*, features.*
            FROM variants
            JOIN alternative_alleles USING(variant_id)
            JOIN alternative_alleles_consequences USING(alternative_allele_id)
            JOIN consequences USING(consequence_id)
            JOIN alternative_alleles_features USING(alternative_allele_id)
            JOIN features ON features.id = alternative_alleles_features.feature_id        
        )
        SELECT * FROM joint_table WHERE variant_id IN (
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

# takes about 150ms to run
def get_variants_with_one_filter():
    sql = """
        WITH joint_table AS (
            SELECT variants.*, alternative_alleles.*, consequences.*, features.*
            FROM variants
            JOIN alternative_alleles USING(variant_id)
            JOIN alternative_alleles_consequences USING(alternative_allele_id)
            JOIN consequences USING(consequence_id)
            JOIN alternative_alleles_features USING(alternative_allele_id)
            JOIN features ON features.id = alternative_alleles_features.feature_id        
        )
        SELECT * FROM joint_table WHERE variant_id IN (
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


def get_variant_at_start():
    sql = """
        WITH joint_table AS (
            SELECT variants.*, alternative_alleles.*, consequences.*, features.*
            FROM variants
            JOIN alternative_alleles USING(variant_id)
            JOIN alternative_alleles_consequences USING(alternative_allele_id)
            JOIN consequences USING(consequence_id)
            JOIN alternative_alleles_features USING(alternative_allele_id)
            JOIN features ON features.id = alternative_alleles_features.feature_id        
        )
        SELECT * FROM joint_table WHERE variant_id IN (
            SELECT DISTINCT variant_id from joint_table
            WHERE start = 243501
        )
    """
    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.row_factory = sqlite3.Row
    cursor = db_connection.cursor()
    cursor.execute(sql)
    results = serialize_variants(cursor.fetchall())
    print(results)


# get_first_page_of_variants()
# try_json_group_object()
# get_page_of_variants_with_offset()
# get_variants_with_one_filter()
get_variant_at_start()