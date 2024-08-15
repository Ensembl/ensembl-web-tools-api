import sqlite3

# FIXME: fix the relative imports!!!
from parse_vcf import parse_vcf_data
from db_details import DATABASE_NAME

# https://dba.stackexchange.com/questions/269453/limit-on-table-with-1-to-many


def load_db():
    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.execute("PRAGMA foreign_keys = 1")
    db_connection.row_factory = sqlite3.Row
    create_tables(db_connection)

    count = 0

    for record in parse_vcf_data():
        count += 1
        # if (count == 100):
        #     break

        if (count % 1000 == 0):
            print(f'{count} variants processed...')
        save_variant(record, db_connection)
    
    db_connection.commit()
    db_connection.close()


def create_tables(db_connection: sqlite3.Connection):
    variants_table_sql = """
        CREATE TABLE variants(
            variant_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            region_name TEXT NOT NULL,
            start INTEGER NOT NULL,
            reference_allele TEXT NOT NULL
        )
    """
    alternative_alleles_table_sql = """
        CREATE TABLE alternative_alleles(
            alternative_allele_id INTEGER PRIMARY KEY AUTOINCREMENT,
            alternative_allele TEXT NOT NULL,
            variant_id INTEGER NOT NULL,
            FOREIGN KEY (variant_id) REFERENCES variants(variant_id)
        )
    """
    consequences_table_sql = """
        CREATE TABLE consequences(
            consequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            consequence TEXT NOT NULL UNIQUE
        )
    """
    alternative_alleles_consequences_join_table_sql = """
        CREATE TABLE alternative_alleles_consequences(
            alternative_allele_id INTEGER,
            consequence_id INTEGER,
            FOREIGN KEY (alternative_allele_id) REFERENCES alternative_alleles(alternative_allele_id),
            FOREIGN KEY (consequence_id) REFERENCES consequences(consequence_id)
        )
    """
    features_table_sql = """
        CREATE TABLE features(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_type,
            feature_id,
            biotype,
            gene_id,
            gene_symbol
        )
    """
    alternative_alleles_features_join_table_sql = """
        CREATE TABLE alternative_alleles_features(
            alternative_allele_id INTEGER,
            feature_id INTEGER,
            FOREIGN KEY (alternative_allele_id) REFERENCES alternative_alleles(alternative_allele_id),
            FOREIGN KEY (feature_id) REFERENCES features(id)
        )
    """
    feature_id_index_sql = """
        CREATE INDEX feature_id_index
        ON features(feature_id)
    """

    cursor = db_connection.cursor()
    cursor.execute(variants_table_sql)
    cursor.execute(alternative_alleles_table_sql)
    cursor.execute(consequences_table_sql)
    cursor.execute(alternative_alleles_consequences_join_table_sql)
    cursor.execute(features_table_sql)
    cursor.execute(alternative_alleles_features_join_table_sql)
    cursor.execute(feature_id_index_sql)


def save_variant(record: dict, db_connection: sqlite3.Connection):
    sql = """
        INSERT INTO variants (
            name,
            region_name,
            start,
            reference_allele
        ) VALUES (
            :variant_name,
            :region_name,
            :start,
            :reference_allele
        ) RETURNING variant_id
    """
    cursor = db_connection.cursor()
    cursor.execute(sql, record)
    variant_id = cursor.fetchone()["variant_id"]
    record['variant_id'] = variant_id
    save_variant_consequences(record, db_connection)

def save_variant_consequences(record: dict, db_connection: sqlite3.Connection):
    alt_allele_insert_sql = """
        INSERT INTO alternative_alleles (
            alternative_allele,
            variant_id
        ) VALUES (
            :alternative_allele,
            :variant_id
        ) RETURNING alternative_allele_id
    """
    cursor = db_connection.cursor()

    for cons in record["consequences"]:
        cons["variant_id"] = record["variant_id"]
        cursor.execute(alt_allele_insert_sql, cons)
        query_result = cursor.fetchone()
        alternative_allele_id = query_result["alternative_allele_id"]

        if (cons["feature_id"]):
            feature_id = save_feature(cons, db_connection)
            save_alt_allele_feature_association(alternative_allele_id, feature_id, db_connection)

        for consequence in cons["consequences"]:
            consequence_id = save_consequence(consequence, db_connection)
            save_alt_allele_consequence_association(alternative_allele_id, consequence_id, db_connection)


def save_consequence(consequence: str, db_connection: sqlite3.Connection) -> int:
    consequence_query_sql = """
        SELECT consequence_id FROM consequences
        WHERE consequence = ?
    """
    consequence_insertion_sql = """
        INSERT INTO consequences (
            consequence
        ) VALUES (
            :consequence
        ) RETURNING consequence_id
    """
    cursor = db_connection.cursor()
    cursor.execute(consequence_query_sql, (consequence,))
    query_result = cursor.fetchone()

    if not query_result:
        cursor.execute(consequence_insertion_sql, { "consequence": consequence })
        query_result = cursor.fetchone()
    return query_result['consequence_id']


def save_feature(record: dict, db_connection: sqlite3.Connection):
    sql = """
        INSERT INTO features (
            feature_type,
            feature_id,
            biotype,
            gene_id,
            gene_symbol
        ) VALUES (
            :feature_type,
            :feature_id,
            :biotype,
            :gene_id,
            :gene_symbol
        ) RETURNING id
    """
    cursor = db_connection.cursor()
    cursor.execute(sql, record)
    query_result = cursor.fetchone()
    return query_result['id']

def save_alt_allele_feature_association(alt_allele_id: int, feature_id: int, db_connection: sqlite3.Connection):
    sql = """
        INSERT INTO alternative_alleles_features (
            alternative_allele_id,
            feature_id
        ) VALUES (
            :alternative_allele_id,
            :feature_id
        )
    """
    cursor = db_connection.cursor()
    cursor.execute(sql, {
        "alternative_allele_id": alt_allele_id,
        "feature_id": feature_id
    })

def save_alt_allele_consequence_association(alt_allele_id: int, consequence_id: int, db_connection: sqlite3.Connection):
    sql = """
        INSERT INTO alternative_alleles_consequences (
            alternative_allele_id,
            consequence_id
        ) VALUES (
            :alternative_allele_id,
            :consequence_id
        )
    """
    cursor = db_connection.cursor()
    cursor.execute(sql, {
        "alternative_allele_id": alt_allele_id,
        "consequence_id": consequence_id
    })


load_db()
