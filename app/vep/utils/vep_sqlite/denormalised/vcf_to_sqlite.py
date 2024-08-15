import sqlite3

# FIXME: fix the relative imports!!!
from parse_vcf import parse_vcf_data
from db_details import DATABASE_NAME


def load_db():
    db_connection = sqlite3.connect(DATABASE_NAME)
    db_connection.execute("PRAGMA foreign_keys = 1")
    create_tables(db_connection)

    count = 0

    for record in parse_vcf_data():
        count += 1
        if (count % 1000 == 0):
            print(f'{count} variants processed...')
        save_variant(record, db_connection)
    
    db_connection.commit()
    db_connection.close()


def create_tables(db_connection: sqlite3.Connection):
    variants_table_sql = """
        CREATE TABLE variants(
            variant_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name,
            region_name NOT NULL,
            start INTEGER NOT NULL,
            reference_allele NOT NULL
        )
    """
    consequences_table_sql = """
        CREATE TABLE consequences(
            consequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            alternative_allele NOT NULL,
            consequence NOT NULL,
            feature_type,
            feature_id,
            biotype,
            gene_id,
            gene_symbol,
            variant_id INTEGER,
            FOREIGN KEY (variant_id) REFERENCES variants(variant_id)
        )
    """
    
    cursor = db_connection.cursor()
    cursor.execute(variants_table_sql)
    cursor.execute(consequences_table_sql)


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
    variant_id = cursor.fetchone()[0]
    record['variant_id'] = variant_id
    save_variant_consequences(record, db_connection)

def save_variant_consequences(record: dict, db_connection: sqlite3.Connection):
    sql = """
        INSERT INTO consequences (
            alternative_allele,
            consequence,
            feature_type,
            feature_id,
            biotype,
            gene_id,
            gene_symbol,
            variant_id
        ) VALUES (
            :alternative_allele,
            :consequences,
            :feature_type,
            :feature_id,
            :biotype,
            :gene_id,
            :gene_symbol,
            :variant_id
        )
    """
    for cons in record["consequences"]:
        cons["variant_id"] = record["variant_id"]
        cons["consequences"] = "&".join(cons["consequences"])
        cursor = db_connection.cursor()
        cursor.execute(sql, cons)


load_db()


