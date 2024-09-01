import duckdb
import traceback

# FIXME: fix the relative imports!!!
from parse_vcf import parse_vcf_data
from db_details import DATABASE_NAME

def load_db():
    db_connection = duckdb.connect(DATABASE_NAME)
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


def create_tables(db_connection: duckdb.DuckDBPyConnection):
    variants_table_sql = """
        CREATE SEQUENCE variant_id_sequence START 1;
        CREATE TABLE variants(
            variant_id INTEGER PRIMARY KEY DEFAULT nextval('variant_id_sequence'),
            name TEXT,
            region_name TEXT NOT NULL,
            start INTEGER NOT NULL,
            reference_allele TEXT NOT NULL
        )
    """
    alternative_alleles_table_sql = """
        CREATE SEQUENCE alt_allele_id_sequence START 1;
        CREATE TABLE alternative_alleles(
            alternative_allele_id INTEGER PRIMARY KEY DEFAULT nextval('alt_allele_id_sequence'),
            alternative_allele TEXT NOT NULL,
            variant_id INTEGER NOT NULL,
            FOREIGN KEY (variant_id) REFERENCES variants(variant_id)
        )
    """
    consequences_table_sql = """
        CREATE SEQUENCE consequence_id_sequence START 1;
        CREATE TABLE consequences(
            consequence_id INTEGER PRIMARY KEY DEFAULT nextval('consequence_id_sequence'),
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
        CREATE SEQUENCE feature_id_sequence START 1;
        CREATE TABLE features (
            id INTEGER PRIMARY KEY DEFAULT nextval('feature_id_sequence'),
            feature_type VARCHAR,
            feature_id VARCHAR,
            biotype VARCHAR,
            gene_id VARCHAR,
            gene_symbol VARCHAR
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

    db_connection
    db_connection.sql(variants_table_sql)
    db_connection.sql(alternative_alleles_table_sql)
    db_connection.sql(consequences_table_sql)
    db_connection.sql(alternative_alleles_consequences_join_table_sql)
    db_connection.sql(features_table_sql)
    db_connection.sql(alternative_alleles_features_join_table_sql)
    db_connection.sql(feature_id_index_sql)


def save_variant(record: dict, db_connection: duckdb.DuckDBPyConnection):
    sql = """
        INSERT INTO variants (
            name,
            region_name,
            start,
            reference_allele
        ) VALUES (
            $variant_name,
            $region_name,
            $start,
            $reference_allele
        ) RETURNING variant_id
    """
    try:
        db_connection.execute(sql, {
            "variant_name": record["variant_name"],
            "region_name": record["region_name"],
            "start": record["start"],
            "reference_allele": record["reference_allele"],
        })
        query_result = db_connection.fetchone()
        variant_id = query_result[0]
        record['variant_id'] = variant_id
        save_variant_consequences(record, db_connection)
    except BaseException as err:
        print(''.join(traceback.TracebackException.from_exception(err).format()))

def save_variant_consequences(record: dict, db_connection: duckdb.DuckDBPyConnection):
    alt_allele_insert_sql = """
        INSERT INTO alternative_alleles (
            alternative_allele,
            variant_id
        ) VALUES (
            $alternative_allele,
            $variant_id
        ) RETURNING alternative_allele_id
    """

    for cons in record["consequences"]:
        cons["variant_id"] = record["variant_id"]
        db_connection.execute(alt_allele_insert_sql, {
            "variant_id": cons["variant_id"],
            "alternative_allele": cons["alternative_allele"]
        })
        query_result = db_connection.fetchone()
        alternative_allele_id = query_result[0]

        if (cons["feature_id"]):
            feature_id = save_feature(cons, db_connection)
            save_alt_allele_feature_association(alternative_allele_id, feature_id, db_connection)

        for consequence in cons["consequences"]:
            consequence_id = save_consequence(consequence, db_connection)
            save_alt_allele_consequence_association(alternative_allele_id, consequence_id, db_connection)


def save_consequence(consequence: str, db_connection: duckdb.DuckDBPyConnection) -> int:
    consequence_query_sql = """
        SELECT consequence_id FROM consequences
        WHERE consequence = ?
    """
    consequence_insertion_sql = """
        INSERT INTO consequences (
            consequence
        ) VALUES (
            $consequence
        ) RETURNING consequence_id
    """
    db_connection.execute(consequence_query_sql, [consequence])
    query_result = db_connection.fetchone()

    if not query_result:
        db_connection.execute(consequence_insertion_sql, { "consequence": consequence })
        query_result = db_connection.fetchone()
    return query_result[0]


def save_feature(record: dict, db_connection: duckdb.DuckDBPyConnection):
    feature_query_sql = """
        SELECT id FROM features
        WHERE feature_id = ?
    """
    feature_insert_sql = """
        INSERT INTO features (
            feature_type,
            feature_id,
            biotype,
            gene_id,
            gene_symbol
        ) VALUES (
            $feature_type,
            $feature_id,
            $biotype,
            $gene_id,
            $gene_symbol
        ) RETURNING id
    """
    db_connection.execute(feature_query_sql, [record['feature_id']])
    query_result = db_connection.fetchone()

    if not query_result:
        db_connection.execute(feature_insert_sql, {
            "feature_type": record["feature_type"],
            "feature_id": record["feature_id"],
            "biotype": record["biotype"],
            "gene_id": record["gene_id"],
            "gene_symbol": record["gene_symbol"]
        })
        query_result = db_connection.fetchone()
    return query_result[0]

def save_alt_allele_feature_association(alt_allele_id: int, feature_id: int, db_connection: duckdb.DuckDBPyConnection):
    sql = """
        INSERT INTO alternative_alleles_features (
            alternative_allele_id,
            feature_id
        ) VALUES (
            $alternative_allele_id,
            $feature_id
        )
    """
    db_connection.execute(sql, {
        "alternative_allele_id": alt_allele_id,
        "feature_id": feature_id
    })

def save_alt_allele_consequence_association(alt_allele_id: int, consequence_id: int, db_connection: duckdb.DuckDBPyConnection):
    sql = """
        INSERT INTO alternative_alleles_consequences (
            alternative_allele_id,
            consequence_id
        ) VALUES (
            $alternative_allele_id,
            $consequence_id
        )
    """
    db_connection.execute(sql, {
        "alternative_allele_id": alt_allele_id,
        "consequence_id": consequence_id
    })


load_db()
